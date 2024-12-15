import base64
import io
import mimetypes
import os
from typing import Dict, List

import pypdfium2 as pdfium
import requests
from lexoid.core.prompt_templates import (
    INSTRUCTIONS_ADD_PG_BREAK,
    OPENAI_USER_PROMPT,
    PARSER_PROMPT,
)
from lexoid.core.utils import convert_image_to_pdf
from loguru import logger
from openai import OpenAI


def parse_llm_doc(path: str, raw: bool, **kwargs) -> List[Dict] | str:
    if "model" not in kwargs:
        kwargs["model"] = "gemini-1.5-flash"
    model = kwargs.get("model")
    if model.startswith("gemini"):
        return parse_with_gemini(path, raw, **kwargs)
    elif model.startswith("gpt"):
        return parse_with_gpt(path, raw, **kwargs)
    else:
        raise ValueError(f"Unsupported model: {model}")


def parse_with_gemini(path: str, raw: bool, **kwargs) -> List[Dict] | str:
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

    # Ideally, we do this ourselves. But, for now this might be a good enough.
    custom_instruction = f"""- Total number of pages: {kwargs["pages_per_split_"]}. {INSTRUCTIONS_ADD_PG_BREAK}"""
    if kwargs["pages_per_split_"] == 1:
        custom_instruction = ""

    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": PARSER_PROMPT.format(
                            custom_instructions=custom_instruction
                        )
                    },
                    {"inline_data": {"mime_type": mime_type, "data": base64_file}},
                ]
            }
        ],
        "generationConfig": {
            "temperature": kwargs.get("temperature", 0.7),
        },
    }

    headers = {"Content-Type": "application/json"}

    response = requests.post(url, json=payload, headers=headers)
    response.raise_for_status()

    result = response.json()

    raw_text = "".join(
        part["text"]
        for candidate in result.get("candidates", [])
        for part in candidate.get("content", {}).get("parts", [])
        if "text" in part
    )

    result = ""
    if "<output>" in raw_text:
        result = raw_text.split("<output>")[1].strip()
    if "</output>" in result:
        result = result.split("</output>")[0].strip()

    if raw:
        return result

    return [
        {
            "metadata": {
                "title": kwargs["title"],
                "page": kwargs.get("start", 0) + page_no,
            },
            "content": page,
        }
        for page_no, page in enumerate(result.split("<page-break>"), start=1)
        if page.strip()
    ]


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


def parse_with_gpt(path: str, raw: bool, **kwargs) -> List[Dict] | str:
    client = OpenAI()

    # Handle different input types
    mime_type, _ = mimetypes.guess_type(path)
    if mime_type and mime_type.startswith("image"):
        # Single image processing
        with open(path, "rb") as img_file:
            image_base64 = base64.b64encode(img_file.read()).decode("utf-8")
            images = [(0, image_base64)]
    else:
        # PDF processing
        pdf_document = pdfium.PdfDocument(path)
        images = [
            (page_num, convert_pdf_page_to_base64(pdf_document, page_num))
            for page_num in range(len(pdf_document))
        ]

    # Process each page/image
    all_results = []
    for page_num, image_base64 in images:
        messages = [
            {
                "role": "system",
                "content": PARSER_PROMPT,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"{OPENAI_USER_PROMPT} (Page {page_num + 1})",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_base64}"},
                    },
                ],
            },
        ]

        # Get completion from GPT-4 Vision
        response = client.chat.completions.create(
            model=kwargs["model"],
            temperature=kwargs.get("temperature", 0.7),
            messages=messages,
        )

        # Extract the response text
        page_text = response.choices[0].message.content
        if kwargs.get("verbose", None):
            logger.debug(f"Page {page_num + 1} response: {page_text}")
        result = ""
        if "<output>" in page_text:
            result = page_text.split("<output>")[1].strip()
        if "</output>" in result:
            result = result.split("</output>")[0].strip()
        all_results.append((page_num, result))

    # Sort results by page number and combine
    all_results.sort(key=lambda x: x[0])
    all_texts = [text for _, text in all_results]
    combined_text = "<page-break>".join(all_texts)

    if raw:
        return combined_text

    return [
        {
            "metadata": {
                "title": kwargs["title"],
                "page": kwargs.get("start", 0) + page_no,
            },
            "content": page,
        }
        for page_no, page in enumerate(all_texts, start=1)
        if page.strip()
    ]
