import base64
import io
import mimetypes
import os
import time
from functools import wraps
from typing import Dict, List, Optional, Tuple

import pypdfium2 as pdfium
import requests
from huggingface_hub import InferenceClient
from loguru import logger
from mistralai import Mistral
from openai import OpenAI
from requests.exceptions import HTTPError
from together import Together

from lexoid.core.prompt_templates import (
    INSTRUCTIONS_ADD_PG_BREAK,
    LLAMA_PARSER_PROMPT,
    OPENAI_USER_PROMPT,
    PARSER_PROMPT,
)
from lexoid.core.utils import convert_image_to_pdf


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
    if "api_provider" in kwargs and kwargs["api_provider"]:
        return parse_with_api(path, api=kwargs["api_provider"], **kwargs)
    if "model" not in kwargs:
        kwargs["model"] = "gemini-2.0-flash"
    model = kwargs.get("model")
    if model.startswith("gemini"):
        return parse_with_gemini(path, **kwargs)
    if model.startswith("gpt"):
        return parse_with_api(path, api="openai", **kwargs)
    if model.startswith("meta-llama"):
        if "Turbo" in model or model == "meta-llama/Llama-Vision-Free":
            return parse_with_api(path, api="together", **kwargs)
        return parse_with_api(path, api="huggingface", **kwargs)
    if any(model.startswith(prefix) for prefix in ["microsoft", "google", "qwen"]):
        return parse_with_api(path, api="openrouter", **kwargs)
    if model.startswith("accounts/fireworks"):
        return parse_with_api(path, api="fireworks", **kwargs)
    if model.startswith("mistral"):
        return parse_with_api(path, api="mistral", **kwargs)
    raise ValueError(f"Unsupported model: {model}")


def parse_with_gemini(path: str, **kwargs) -> List[Dict] | str:
    logger.debug(f"Parsing with Gemini API and model {kwargs['model']}")
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY environment variable is not set")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{kwargs['model']}:generateContent?key={api_key}"

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

    if "system_prompt" in kwargs:
        prompt = kwargs["system_prompt"]
    else:
        # Ideally, we do this ourselves. But, for now this might be a good enough.
        custom_instruction = f"""- Total number of pages: {kwargs["pages_per_split_"]}. {INSTRUCTIONS_ADD_PG_BREAK}"""
        if kwargs["pages_per_split_"] == 1:
            custom_instruction = ""
        prompt = PARSER_PROMPT.format(custom_instructions=custom_instruction)

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": base64_file}},
                ]
            }
        ],
        "generationConfig": {
            "temperature": kwargs.get("temperature", 0.2),
        },
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

    combined_text = ""
    if "<output>" in raw_text:
        combined_text = raw_text.split("<output>")[-1].strip()
    if "</output>" in result:
        combined_text = result.split("</output>")[0].strip()

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
        "title": kwargs["title"],
        "url": kwargs.get("url", ""),
        "parent_title": kwargs.get("parent_title", ""),
        "recursive_docs": [],
        "token_usage": {
            "input": input_tokens,
            "output": output_tokens,
            "total": total_tokens,
        },
    }


def convert_pdf_page_to_base64(
    pdf_document: pdfium.PdfDocument, page_number: int
) -> str:
    """Convert a PDF page to a base64-encoded PNG string."""
    page = pdf_document[page_number]
    # Render with 4x scaling for better quality
    pil_image = page.render(scale=4).to_pil()

    # Convert to base64
    img_byte_arr = io.BytesIO()
    pil_image.save(img_byte_arr, format="PNG")
    img_byte_arr.seek(0)
    return base64.b64encode(img_byte_arr.getvalue()).decode("utf-8")


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
    temperature: float = 0.2,
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
    }
    assert api in clients, f"Unsupported API: {api}"
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

        token_usage = TokenUsage(0, 0, 0)  # Mistral does not provide token usage

        return {
            "response": response.pages[0].markdown,
            "usage": token_usage,
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
        "usage": token_usage,
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
            temperature=kwargs.get("temperature", 0.2),
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
                token_usage.prompt_tokens,
                token_usage.completion_tokens,
                token_usage.total_tokens,
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


def convert_doc_to_base64_images(path: str) -> List[Tuple[int, str]]:
    """
    Converts a document (PDF or image) to a base64 encoded string.

    Args:
        path (str): Path to the PDF file.

    Returns:
        str: Base64 encoded string of the PDF content.
    """
    if path.endswith(".pdf"):
        pdf_document = pdfium.PdfDocument(path)
        return [
            (
                page_num,
                f"data:image/png;base64,{convert_pdf_page_to_base64(pdf_document, page_num)}",
            )
            for page_num in range(len(pdf_document))
        ]
    elif mimetypes.guess_type(path)[0].startswith("image"):
        with open(path, "rb") as img_file:
            image_base64 = base64.b64encode(img_file.read()).decode("utf-8")
            return [(0, f"data:image/png;base64,{image_base64}")]
