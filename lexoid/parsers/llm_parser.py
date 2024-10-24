import os
import base64
import requests
import mimetypes
from openai import OpenAI
from typing import List, Dict

from lexoid.prompt_templates import PARSER_PROMPT
from lexoid.utils import convert_image_to_pdf


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

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": PARSER_PROMPT},
                    {"inline_data": {"mime_type": mime_type, "data": base64_file}},
                ]
            }
        ]
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

    if raw:
        return raw_text

    return [
        {
            "metadata": {
                "title": kwargs["title"],
                "page": kwargs.get("start", 0) + page_no,
            },
            "content": page,
        }
        for page_no, page in enumerate(raw_text.split("<page break>"), start=1)
        if page.strip()
    ]


def parse_with_gpt(path: str, raw: bool, **kwargs) -> List[Dict] | str:
    client = OpenAI()
    pdf_assistant = client.beta.assistants.create(
        model=kwargs["model"],
        description="An assistant to extract the contents of documents.",
        tools=[{"type": "file_search"}],
        name="Document assistant",
    )
    thread = client.beta.threads.create()
    file = client.files.create(file=open(path, "rb"), purpose="assistants")

    client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        attachments=[
            {
                "file_id": file.id,
                "tools": [{"type": "file_search"}],
            }
        ],
        content=PARSER_PROMPT,
    )
    run = client.beta.threads.runs.create_and_poll(
        thread_id=thread.id, assistant_id=pdf_assistant.id, timeout=1000
    )

    if run.status != "completed":
        raise Exception("Run failed:", run.status)

    messages = list(client.beta.threads.messages.list(thread_id=thread.id))
    res_txt = messages[0].content[0].text.value

    if raw:
        return res_txt

    return [
        {
            "metadata": {
                "title": kwargs["title"],
                "page": kwargs.get("start", 0) + page_no,
            },
            "content": page,
        }
        for page_no, page in enumerate(res_txt.split("<page break>"), start=1)
        if page.strip()
    ]
