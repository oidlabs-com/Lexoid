import ast
import base64
import io
import mimetypes
import os
import re
import time
from functools import wraps
from typing import Dict, List, Optional, Tuple

import requests
import torch
from anthropic import Anthropic
from google import genai
from huggingface_hub import InferenceClient
from loguru import logger
from mistralai import Mistral
from openai import OpenAI
from PIL import Image
from requests.exceptions import HTTPError

from transformers import AutoModelForVision2Seq, AutoProcessor

from lexoid.core.conversion_utils import (
    convert_doc_to_base64_images,
    convert_image_to_pdf,
)
from lexoid.core.prompt_templates import (
    AUDIO_TO_MARKDOWN_PROMPT,
    INSTRUCTIONS_ADD_PG_BREAK,
    LLAMA_PARSER_PROMPT,
    OPENAI_USER_PROMPT,
    PARSER_PROMPT,
)
from lexoid.core.utils import (
    DEFAULT_LLM,
    DEFAULT_LOCAL_LM,
    get_api_provider_for_model,
    get_file_type,
)

# Till Together new API is stable
os.environ.setdefault("TOGETHER_NO_BANNER", "1")
from together import Together


def retry_on_error(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return_dict = {
            "raw": "",
            "segments": [],
            "title": kwargs["title"],
            "url": kwargs.get("url", ""),
            "parent_title": kwargs.get("parent_title", ""),
            "recursive_docs": [],
        }
        try:
            return func(*args, **kwargs)
        except HTTPError as e:
            logger.error(f"HTTPError encountered: {e}. Retrying in 10 seconds...")
            if not kwargs.get("retry_on_fail", True):
                return_dict["error"] = (
                    f"HTTPError encountered on page {kwargs.get('start', 0)}: {e}"
                )
                return return_dict
            time.sleep(10)
            try:
                logger.debug(f"Retry {func.__name__}")
                return func(*args, **kwargs)
            except HTTPError as e:
                logger.error(f"Retry failed: {e}")
                return_dict["error"] = (
                    f"HTTPError encountered on page {kwargs.get('start', 0)}: {e}"
                )
                return return_dict
        except ValueError as e:
            logger.error(f"ValueError encountered: {e}")
            if not kwargs.get("retry_on_fail", True):
                return_dict["error"] = (
                    f"ValueError encountered on page {kwargs.get('start', 0)}: {e}"
                )
                return return_dict
            time.sleep(10)
            try:
                logger.debug(f"Retry {func.__name__}")
                return func(*args, **kwargs)
            except ValueError as e:
                logger.error(f"Retry failed: {e}")
                return_dict["error"] = (
                    f"ValueError encountered on page {kwargs.get('start', 0)}: {e}"
                )
                return return_dict

    return wrapper


@retry_on_error
def parse_llm_doc(path: str, **kwargs) -> List[Dict] | str:
    mime_type = get_file_type(path)
    if not ("image" in mime_type or "pdf" in mime_type or "audio" in mime_type):
        raise ValueError(
            f"Unsupported file type: {mime_type}. Only PDF, image, and audio files are supported for LLM_PARSE."
        )
    if "api_provider" in kwargs:
        if kwargs["api_provider"] == "local":
            return parse_with_local_model(path, **kwargs)
        elif kwargs["api_provider"]:
            return parse_with_api(path, api=kwargs["api_provider"], **kwargs)

    model = kwargs.get("model", DEFAULT_LLM)
    kwargs["model"] = model

    api_provider = get_api_provider_for_model(model)

    if mime_type.startswith("audio") and api_provider != "gemini":
        raise ValueError(
            f"Audio files are only supported with the Gemini API provider. The model '{model}' is not compatible."
        )

    if api_provider == "gemini":
        return parse_with_gemini(path, **kwargs)
    elif api_provider == "local":
        return parse_with_local_model(path, **kwargs)
    return parse_with_api(path, api=api_provider, **kwargs)


def doctags_to_markdown_and_bboxes(
    doctags: str,
) -> Tuple[str, List[Tuple[str, List[float]]]]:
    """
    # Reference: https://huggingface.co/ibm-granite/granite-docling-258M

    Parse a subset of DocTags/OTSL:
      - <section_header_level_N>Title</section_header_level_N> -> Markdown #... heading
      - <text>Paragraph</text> -> Markdown paragraph
      - <otsl> with <ched>, <fcel>, <nl> -> Markdown table
    Bboxes: when 4 successive <loc_*> appear before a textual atom, assign that bbox
    normalized to [0,1] via 500-scale reported by the model.
    """
    # Tokenize into tags and text
    tokens = re.split(r"(<[^>]+>)", doctags)
    md_lines: List[str] = []
    bboxes: List[Tuple[str, List[float]]] = []

    # State for capturing bounding boxes
    loc_buffer: List[int] = []
    pending_bbox: List[float] = None

    def update_bbox_from_tag(tag: str):
        nonlocal loc_buffer, pending_bbox
        m = re.fullmatch(r"<loc_(\d+)>", tag)
        if m:
            loc_buffer.append(int(m.group(1)))
            if len(loc_buffer) >= 4:
                vals = loc_buffer[-4:]
                pending_bbox = [
                    vals[0] / 500,
                    vals[1] / 500,
                    vals[2] / 500,
                    vals[3] / 500,
                ]

    def take_bbox_for(text_value: str):
        nonlocal pending_bbox
        if text_value and pending_bbox is not None:
            bboxes.append((text_value, pending_bbox))
            pending_bbox = None  # consume per atom

    def finalize_text(s: str) -> str:
        # Collapse spaces and non-breaking spaces left by tag splits
        return re.sub(r"\s+", " ", s).strip()

    i = 0
    L = len(tokens)
    while i < L:
        tok = tokens[i]

        # Track loc tags regardless of context
        if tok.startswith("<loc_"):
            update_bbox_from_tag(tok)
            i += 1
            continue

        # Section headers
        m_hdr_open = re.fullmatch(r"<section_header_level_(\d+)>", tok)
        if m_hdr_open:
            level = max(1, min(6, int(m_hdr_open.group(1))))
            # accumulate inner text until closing tag
            j = i + 1
            inner = []
            while j < L:
                if tokens[j].startswith("</section_header_level_"):
                    break
                if tokens[j].startswith("<"):
                    # allow loc tags inside
                    if tokens[j].startswith("<loc_"):
                        update_bbox_from_tag(tokens[j])
                else:
                    inner.append(tokens[j])
                j += 1
            title = finalize_text("".join(inner))
            if title:
                md_lines.append(("#" * level) + " " + title)
                take_bbox_for(title)
            i = j + 1
            continue

        # Paragraph text
        if tok == "<text>":
            j = i + 1
            inner = []
            while j < L and tokens[j] != "</text>":
                if tokens[j].startswith("<"):
                    if tokens[j].startswith("<loc_"):
                        update_bbox_from_tag(tokens[j])
                    # ignore other tags inside <text> block
                else:
                    inner.append(tokens[j])
                j += 1
            paragraph = finalize_text("".join(inner))
            if paragraph:
                md_lines.append(paragraph)
                take_bbox_for(paragraph)
            i = j + 1
            continue

        # OTSL table
        if tok == "<otsl>":
            j = i + 1
            headers: List[str] = []
            rows: List[List[str]] = []
            current_row: List[str] = []

            def flush_row():
                nonlocal current_row, rows
                if any(cell.strip() for cell in current_row):
                    rows.append(current_row)
                current_row = []

            while j < L and tokens[j] != "</otsl>":
                t = tokens[j]

                if t.startswith("<loc_"):
                    update_bbox_from_tag(t)
                    j += 1
                    continue

                if t == "<ched>":
                    # header cell up to next tag
                    k = j + 1
                    cell = []
                    while k < L and not tokens[k].startswith("<"):
                        cell.append(tokens[k])
                        k += 1
                    text_cell = finalize_text("".join(cell))
                    if text_cell:
                        headers.append(text_cell)
                        take_bbox_for(text_cell)
                    j = k
                    continue

                if t == "<fcel>":
                    k = j + 1
                    cell = []
                    while k < L and not tokens[k].startswith("<"):
                        cell.append(tokens[k])
                        k += 1
                    text_cell = finalize_text("".join(cell))
                    if text_cell:
                        current_row.append(text_cell)
                        take_bbox_for(text_cell)
                    j = k
                    continue

                if t == "<nl>":
                    flush_row()
                    j += 1
                    continue

                # skip other tags (including formatting)
                j += 1

            # flush any trailing row
            if current_row:
                flush_row()

            md_lines.append("")  # blank line before table

            # Render Markdown table
            if headers:
                md_lines.append("| " + " | ".join(headers) + " |")
                md_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
            for i, r in enumerate(rows):
                if i == 1 and not headers:
                    # if no headers, add a separator after first row
                    md_lines.append("| " + " | ".join(["---"] * len(r)) + " |")
                if r:
                    md_lines.append("| " + " | ".join(r) + " |")

            i = j + 1
            continue

        # Ignore other tags and plain text outside known blocks
        i += 1

    markdown = "\n".join([ln for ln in md_lines])
    return markdown, bboxes


def parse_with_local_model(path: str, **kwargs) -> Dict:
    # Source: https://huggingface.co/ibm-granite/granite-docling-258M
    model_name = kwargs.get("model", DEFAULT_LOCAL_LM)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    processor = AutoProcessor.from_pretrained(model_name)
    model = AutoModelForVision2Seq.from_pretrained(
        model_name,
        torch_dtype=torch.bfloat16 if device == "cuda" else torch.float32,
    ).to(device)

    max_dimension = kwargs.get("max_image_dimension", 1500)
    images = convert_doc_to_base64_images(path, max_dimension=max_dimension)
    proc_images = [
        Image.open(io.BytesIO(base64.b64decode(image_b64.split(",")[1]))).convert("RGB")
        for _, image_b64 in images
    ]

    instruction = kwargs.get("docling_command", "Convert this page to docling.")

    # Normalize bbox prompts for certain instruction types (parity)
    if (
        ("OCR text at" in instruction)
        or ("Identify element" in instruction)
        or ("formula" in instruction)
    ):

        def normalize_list(values):
            max_value = max(values) if values else 1
            return [round((v / max_value) * 500) for v in values]

        def process_match(match):
            num_list = ast.literal_eval(match.group(0))
            normalized = normalize_list(num_list)
            return "".join([f"<loc_{num}>" for num in normalized])

        pattern = r"\[([\d\.\s,]+)\]"
        instruction = re.sub(pattern, process_match, instruction)

    segments = []
    all_md_pages: List[str] = []

    start_page = kwargs.get("start", 0)

    # Run per page for clean segments
    for idx, img in enumerate(proc_images):
        # Build messages and prompt mirroring the Space
        messages = [
            {
                "role": "user",
                "content": [{"type": "image"}, {"type": "text", "text": instruction}],
            }
        ]
        prompt = processor.apply_chat_template(messages, add_generation_prompt=True)
        inputs = processor(text=prompt, images=[[img]], return_tensors="pt").to(device)
        with torch.no_grad():
            generated_ids = model.generate(
                **inputs,
                max_new_tokens=8192,
                do_sample=False,
                num_beams=1,
                temperature=1.0,
            )
        prompt_len = inputs.input_ids.shape[1]
        trimmed = generated_ids[:, prompt_len:]
        doctag_output = processor.batch_decode(trimmed, skip_special_tokens=False)[0]
        doctag_output = doctag_output.replace("<end_of_utterance>", "").strip()

        # DocTags cleanup and chart remapping
        if "<chart>" in doctag_output:
            doctag_output = doctag_output.replace("<chart>", "<otsl>").replace(
                "</chart>", "</otsl>"
            )
            doctag_output = re.sub(
                r"(<loc_500>)(?!.*<loc_500>)<[^>]+>", r"\1", doctag_output
            )

        markdown, bboxes = doctags_to_markdown_and_bboxes(doctag_output)

        all_md_pages.append(markdown)
        segments.append(
            {
                "metadata": {"page": start_page + idx + 1},
                "content": markdown,
                "bboxes": bboxes,  # list of (text, [x0, top, x1, bottom]) normalized to 0–1
            }
        )

    return {
        "raw": "\n\n---\n\n".join(all_md_pages),  # full Markdown for the document
        "segments": segments,
        "title": kwargs.get("title", ""),
        "url": kwargs.get("url", ""),
        "parent_title": kwargs.get("parent_title", ""),
        "recursive_docs": [],
    }


def parse_with_gemini(path: str, **kwargs) -> List[Dict] | str:
    # Check if the file is an image and convert to PDF if necessary
    mime_type, _ = mimetypes.guess_type(path)

    if mime_type and mime_type.startswith("audio"):
        return parse_audio_with_gemini(path, **kwargs)

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
    elif kwargs["model"].startswith("gemini-3"):
        generation_config["thinkingConfig"] = {"thinkingLevel": "low"}

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
    }

    if api == "openai":
        # Unsupported in some models
        del completion_params["max_tokens"]
        del completion_params["temperature"]

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
    max_dimension = kwargs.get("max_image_dimension", 1500)
    images = convert_doc_to_base64_images(path, max_dimension=max_dimension)

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


def parse_audio_with_gemini(path: str, **kwargs) -> Dict:
    client = genai.Client()
    audio_file = client.files.upload(file=path)
    system_prompt = kwargs.get("system_prompt", None)
    if system_prompt == "" or system_prompt is None:
        system_prompt = AUDIO_TO_MARKDOWN_PROMPT + f"Audio file name is: {path}\n"

    response = client.models.generate_content(
        model=kwargs["model"], contents=[system_prompt, audio_file]
    )

    return {
        "raw": response.text,
        "segments": [
            {
                "metadata": {"page": 0},
                "content": response.text,
            }
        ],
        "title": kwargs.get("title", ""),
        "url": kwargs.get("url", ""),
        "parent_title": kwargs.get("parent_title", ""),
        "recursive_docs": [],
        "token_usage": {
            "input": response.usage_metadata.prompt_token_count,
            "output": response.usage_metadata.candidates_token_count,
            "total": (
                response.usage_metadata.prompt_token_count
                + response.usage_metadata.candidates_token_count
            ),
        },
    }
