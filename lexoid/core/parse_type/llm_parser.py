from PIL import Image
import base64
import io
import mimetypes
import os
import time
from functools import wraps
from typing import Dict, List, Optional

import pypdfium2 as pdfium
import requests
from anthropic import Anthropic
from huggingface_hub import InferenceClient
from loguru import logger
from mistralai import Mistral
from openai import OpenAI
from requests.exceptions import HTTPError
from together import Together
import torch
from transformers import AutoProcessor, AutoModelForImageTextToText

from lexoid.core.prompt_templates import (
    INSTRUCTIONS_ADD_PG_BREAK,
    LLAMA_PARSER_PROMPT,
    OPENAI_USER_PROMPT,
    PARSER_PROMPT,
)
from lexoid.core.utils import get_api_provider_for_model
from lexoid.core.conversion_utils import (
    convert_image_to_pdf,
    convert_pdf_page_to_base64,
)


def retry_on_http_error(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except HTTPError as e:
            logger.error(f"HTTPError encountered: {e}. Retrying in 10 seconds...")
            time.sleep(10)
            try:
                logger.debug(f"Retry {func.__name__}")
                return func(*args, **kwargs)
            except HTTPError as e:
                logger.error(f"Retry failed: {e}")
                return {
                    "raw": "",
                    "segments": [],
                    "title": kwargs["title"],
                    "url": kwargs.get("url", ""),
                    "parent_title": kwargs.get("parent_title", ""),
                    "recursive_docs": [],
                    "error": f"HTTPError encountered on page {kwargs.get('start', 0)}: {e}",
                }

    return wrapper


@retry_on_http_error
def parse_llm_doc(path: str, **kwargs) -> List[Dict] | str:
    if "api_provider" in kwargs:
        if kwargs["api_provider"] == "local":
            return parse_with_local_model(path, **kwargs)
        elif kwargs["api_provider"]:
            return parse_with_api(path, api=kwargs["api_provider"], **kwargs)

    model = kwargs.get("model", "gemini-2.0-flash")
    kwargs["model"] = model

    api_provider = get_api_provider_for_model(model)

    if api_provider == "gemini":
        return parse_with_gemini(path, **kwargs)
    elif api_provider == "local":
        return parse_with_local_model(path, **kwargs)
    return parse_with_api(path, api=api_provider, **kwargs)


def parse_with_local_model(path: str, **kwargs) -> List[Dict] | str:
    # Reference: https://huggingface.co/spaces/aabdullah27/SmolDocling-OCR-App/blob/main/app.py
    model_name = kwargs.get("model", "ds4sd/SmolDocling-256M-preview")
    if not model_name.startswith("ds4sd/SmolDocling"):
        raise ValueError(
            f"Local model parsing is only supported for 'ds4sd/SmolDocling*', got {model_name}"
        )
    processor = AutoProcessor.from_pretrained(model_name)
    model = AutoModelForImageTextToText.from_pretrained(model_name)
    images = convert_path_to_images(path)
    pil_images = [
        Image.open(io.BytesIO(base64.b64decode(image.split(",")[1])))
        for _, image in images
    ]
    intruction = kwargs.get("docling_command", "Convert this page to docling.")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image"},
                {"type": "text", "text": intruction},
            ],
        },
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "<output>\n"},
            ],
        },
    ]
    prompt = processor.apply_chat_template(messages, add_generation_prompt=True)
    inputs = processor(text=prompt, images=pil_images, return_tensors="pt")
    with torch.no_grad():
        generated_ids = model.generate(
            **inputs, max_new_tokens=1500, do_sample=False, num_beams=1, temperature=1.0
        )

    prompt_length = inputs.input_ids.shape[1]
    trimmed_generated_ids = generated_ids[:, prompt_length:]
    output = (
        processor.batch_decode(
            trimmed_generated_ids,
            skip_special_tokens=False,
        )[0]
        .strip()
        .replace("<end_of_utterance>", "")
    )
    return {
        "raw": output,
        "segments": [
            {
                "metadata": {"page": kwargs.get("start", 0) + 1},
                "content": output,
            }
        ],
        "title": kwargs["title"],
        "url": kwargs.get("url", ""),
        "parent_title": kwargs.get("parent_title", ""),
    }


def parse_with_gemini(path: str, **kwargs) -> List[Dict] | str:
    # Check if the file is an image and convert to PDF if necessary
    mime_type, _ = mimetypes.guess_type(path)
    if mime_type and mime_type.startswith("image"):
        pdf_content = convert_image_to_pdf(path)
        mime_type = "application/pdf"
        base64_file = base64.b64encode(pdf_content).decode("utf-8")
    else:
        with open(path, "rb") as file:
            file_content = file.read()
        base64_file = base64.b64encode(file_content).decode("utf-8")

    return parse_image_with_gemini(
        base64_file=base64_file, mime_type=mime_type, **kwargs
    )


def parse_image_with_gemini(
    base64_file: str, mime_type: str = "image/png", **kwargs
) -> List[Dict] | str:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY environment variable is not set")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{kwargs['model']}:generateContent?key={api_key}"

    if "system_prompt" in kwargs:
        prompt = kwargs["system_prompt"]
    else:
        # Ideally, we do this ourselves. But, for now this might be a good enough.
        custom_instruction = f"""- Total number of pages: {kwargs["pages_per_split_"]}. {INSTRUCTIONS_ADD_PG_BREAK}"""
        if kwargs["pages_per_split_"] == 1:
            custom_instruction = ""
        prompt = PARSER_PROMPT.format(custom_instructions=custom_instruction)

    generation_config = {
        "temperature": kwargs.get("temperature", 0),
    }
    if kwargs["model"] == "gemini-2.5-pro":
        generation_config["thinkingConfig"] = {"thinkingBudget": 128}

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": base64_file}},
                ]
            }
        ],
        "generationConfig": generation_config,
    }

    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=120)
        response.raise_for_status()
    except requests.Timeout as e:
        raise HTTPError(f"Timeout error occurred: {e}")

    result = response.json()

    raw_text = "".join(
        part["text"]
        for candidate in result.get("candidates", [])
        for part in candidate.get("content", {}).get("parts", [])
        if "text" in part
    )

    combined_text = raw_text
    if "<output>" in raw_text:
        combined_text = raw_text.split("<output>")[-1].strip()
    if "</output>" in combined_text:
        combined_text = combined_text.split("</output>")[0].strip()

    token_usage = result["usageMetadata"]
    input_tokens = token_usage.get("promptTokenCount", 0)
    output_tokens = token_usage.get("candidatesTokenCount", 0)
    total_tokens = input_tokens + output_tokens
    return {
        "raw": combined_text.replace("<page-break>", "\n\n"),
        "segments": [
            {"metadata": {"page": kwargs.get("start", 0) + page_no}, "content": page}
            for page_no, page in enumerate(combined_text.split("<page-break>"), start=1)
        ],
        "title": kwargs.get("title", ""),
        "url": kwargs.get("url", ""),
        "parent_title": kwargs.get("parent_title", ""),
        "recursive_docs": [],
        "token_usage": {
            "input": input_tokens,
            "output": output_tokens,
            "total": total_tokens,
        },
    }


def convert_path_to_images(path):
    mime_type, _ = mimetypes.guess_type(path)
    if mime_type and mime_type.startswith("image"):
        # Single image processing
        with open(path, "rb") as img_file:
            image_base64 = base64.b64encode(img_file.read()).decode("utf-8")
            return [(0, f"data:{mime_type};base64,{image_base64}")]
    elif mime_type and mime_type.startswith("application/pdf"):
        # PDF processing
        pdf_document = pdfium.PdfDocument(path)
        return [
            (
                page_num,
                f"data:image/png;base64,{convert_pdf_page_to_base64(pdf_document, page_num)}",
            )
            for page_num in range(len(pdf_document))
        ]
    else:
        raise ValueError(f"Unsupported file type: {mime_type}")


def get_messages(
    system_prompt: Optional[str], user_prompt: Optional[str], image_url: Optional[str]
) -> List[Dict]:
    messages = []
    if system_prompt:
        messages.append(
            {
                "role": "system",
                "content": system_prompt,
            }
        )
    base_message = (
        [
            {"type": "text", "text": user_prompt},
        ]
        if user_prompt
        else []
    )
    image_message = (
        [
            {
                "type": "image_url",
                "image_url": {"url": image_url},
            }
        ]
        if image_url
        else []
    )

    messages.append(
        {
            "role": "user",
            "content": base_message + image_message,
        }
    )

    return messages


def create_response(
    api: str,
    model: str,
    system_prompt: Optional[str] = None,
    user_prompt: Optional[str] = None,
    image_url: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: int = 1024,
) -> Dict:
    # Initialize appropriate client
    clients = {
        "openai": lambda: OpenAI(),
        "huggingface": lambda: InferenceClient(
            token=os.environ["HUGGINGFACEHUB_API_TOKEN"]
        ),
        "together": lambda: Together(),
        "openrouter": lambda: OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
        ),
        "fireworks": lambda: OpenAI(
            base_url="https://api.fireworks.ai/inference/v1",
            api_key=os.environ["FIREWORKS_API_KEY"],
        ),
        "mistral": lambda: Mistral(
            api_key=os.environ["MISTRAL_API_KEY"],
        ),
        "anthropic": lambda: Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
        ),
        "gemini": lambda: None,  # Gemini is handled separately
    }
    assert api in clients, f"Unsupported API: {api}"

    if api == "gemini":
        image_url = image_url.split("data:image/png;base64,")[1]
        response = parse_image_with_gemini(
            base64_file=image_url,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )
        return {
            "response": response["raw"],
            "usage": response["token_usage"],
        }

    client = clients[api]()

    if api == "mistral":
        if "ocr" not in model:
            raise ValueError("Only OCR models are currently supported for Mistral")
        response = client.ocr.process(
            model=model,
            document={
                "type": "image_url",
                "image_url": image_url,
            },
            include_image_base64=True,
        )

        class TokenUsage:
            def __init__(self, prompt_tokens, completion_tokens, total_tokens):
                self.prompt_tokens = prompt_tokens
                self.completion_tokens = completion_tokens
                self.total_tokens = total_tokens

        return {
            "response": response.pages[0].markdown,
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,  # Mistral does not provide token usage
            },
        }
    if api == "anthropic":
        image_media_type = image_url.split(";")[0].split(":")[1]
        image_data = image_url.split(",")[1]
        response = client.messages.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": image_media_type,
                                "data": image_data,
                            },
                        },
                        {"type": "text", "text": user_prompt},
                    ],
                }
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )

        return {
            "response": response.content[0].text,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens
                + response.usage.output_tokens,
            },
        }

    # Prepare messages for the API call
    messages = get_messages(system_prompt, user_prompt, image_url)

    # Common completion parameters
    completion_params = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    # Get completion from selected API
    response = client.chat.completions.create(**completion_params)
    token_usage = response.usage

    # Extract the response text
    page_text = response.choices[0].message.content

    return {
        "response": page_text,
        "usage": {
            "input_tokens": getattr(token_usage, "prompt_tokens", 0),
            "output_tokens": getattr(token_usage, "completion_tokens", 0),
            "total_tokens": getattr(token_usage, "total_tokens", 0),
        },
    }


def parse_with_api(path: str, api: str, **kwargs) -> List[Dict] | str:
    """
    Parse documents (PDFs or images) using various vision model APIs.

    Args:
        path (str): Path to the document to parse
        api (str): Which API to use ("openai", "huggingface", or "together")
        **kwargs: Additional arguments including model, temperature, title, etc.

    Returns:
        Dict: Dictionary containing parsed document data
    """
    logger.debug(f"Parsing with {api} API and model {kwargs['model']}")

    # Handle different input types
    mime_type, _ = mimetypes.guess_type(path)
    if mime_type and mime_type.startswith("image"):
        # Single image processing
        with open(path, "rb") as img_file:
            image_base64 = base64.b64encode(img_file.read()).decode("utf-8")
            images = [(0, f"data:{mime_type};base64,{image_base64}")]
    else:
        # PDF processing
        pdf_document = pdfium.PdfDocument(path)
        images = [
            (
                page_num,
                f"data:image/png;base64,{convert_pdf_page_to_base64(pdf_document, page_num)}",
            )
            for page_num in range(len(pdf_document))
        ]
    images = convert_path_to_images(path)

    # Process each page/image
    all_results = []
    for page_num, image_url in images:
        if api == "openai":
            system_prompt = kwargs.get(
                "system_prompt", PARSER_PROMPT.format(custom_instructions="")
            )
            user_prompt = kwargs.get("user_prompt", OPENAI_USER_PROMPT)
        else:
            system_prompt = kwargs.get("system_prompt", None)
            user_prompt = kwargs.get("user_prompt", LLAMA_PARSER_PROMPT)

        response = create_response(
            api=api,
            model=kwargs["model"],
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            image_url=image_url,
            temperature=kwargs.get("temperature", 0.0),
            max_tokens=kwargs.get("max_tokens", 1024),
        )

        # Get completion from selected API
        page_text = response["response"]
        token_usage = response["usage"]

        if kwargs.get("verbose", None):
            logger.debug(f"Page {page_num + 1} response: {page_text}")

        # Extract content between output tags if present
        result = page_text
        if "<output>" in page_text:
            result = page_text.split("<output>")[-1].strip()
        if "</output>" in result:
            result = result.split("</output>")[0].strip()
        all_results.append(
            (
                page_num,
                result,
                token_usage["input_tokens"],
                token_usage["output_tokens"],
                token_usage["total_tokens"],
            )
        )

    # Sort results by page number and combine
    all_results.sort(key=lambda x: x[0])
    all_texts = [text for _, text, _, _, _ in all_results]
    combined_text = "\n\n".join(all_texts)

    return {
        "raw": combined_text,
        "segments": [
            {
                "metadata": {
                    "page": kwargs.get("start", 0) + page_no + 1,
                    "token_usage": {
                        "input": input_tokens,
                        "output": output_tokens,
                        "total": total_tokens,
                    },
                },
                "content": page,
            }
            for page_no, page, input_tokens, output_tokens, total_tokens in all_results
        ],
        "title": kwargs["title"],
        "url": kwargs.get("url", ""),
        "parent_title": kwargs.get("parent_title", ""),
        "recursive_docs": [],
        "token_usage": {
            "input": sum(input_tokens for _, _, input_tokens, _, _ in all_results),
            "output": sum(output_tokens for _, _, _, output_tokens, _ in all_results),
            "total": sum(total_tokens for _, _, _, _, total_tokens in all_results),
        },
    }
