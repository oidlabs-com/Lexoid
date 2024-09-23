import os
from enum import Enum
from typing import Dict, List
import pymupdf4llm
import google.generativeai as genai
from openai import OpenAI
from openai.types.beta.threads.message_create_params import (
    Attachment,
    AttachmentToolFileSearch,
)
from prompt_templates import PDF_PARSER_PROMPT


class ParserType(Enum):
    LLM_PARSE = "llm-parse"
    STATIC_PARSE = "static-parse"


def parse_pdf(path, parser_type: ParserType, **kwargs) -> List[Dict]:
    docs = []
    if parser_type == ParserType.STATIC_PARSE:
        if "framework" not in kwargs or kwargs["framework"] == "pymupdf":
            chunks = pymupdf4llm.to_markdown(path, page_chunks=True)
            for chunk in chunks:
                metadata = chunk["metadata"]
                docs.append(
                    {
                        "metadata": {
                            "title": os.path.basename(path),
                            "page": metadata["page"],
                        },
                        "content": chunk["text"],
                    }
                )
    elif parser_type == ParserType.LLM_PARSE:
        if "model" not in kwargs or kwargs["model"] == "gemini-1.5-flash":
            model = genai.GenerativeModel("gemini-1.5-flash")
            file = genai.upload_file(path)
            response = model.generate_content([PDF_PARSER_PROMPT, file])
            for part in response.parts:
                pages = part.text.split("<page break>")
                for page_no, page in enumerate(pages, start=1):
                    if page.strip() == "":
                        continue
                    docs.append(
                        {
                            "metadata": {
                                "title": os.path.basename(path),
                                "page": page_no,
                            },
                            "content": page,
                        }
                    )
        elif kwargs["model"].startswith("gpt"):
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
                    Attachment(
                        file_id=file.id,
                        tools=[AttachmentToolFileSearch(type="file_search")],
                    )
                ],
                content=PDF_PARSER_PROMPT,
            )
            run = client.beta.threads.runs.create_and_poll(
                thread_id=thread.id, assistant_id=pdf_assistant.id, timeout=1000
            )

            if run.status != "completed":
                raise Exception("Run failed:", run.status)

            messages_cursor = client.beta.threads.messages.list(thread_id=thread.id)
            messages = [message for message in messages_cursor]

            # Output text
            res_txt = messages[0].content[0].text.value
            print(res_txt)

    return docs


if __name__ == "__main__":
    path = "test_example_3.pdf"
    parse_pdf(path, ParserType.LLM_PARSE, model="gpt-4o")
