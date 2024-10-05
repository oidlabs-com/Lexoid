import os
import tempfile
import threading
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
import pikepdf


class ParserType(Enum):
    LLM_PARSE = "llm-parse"
    STATIC_PARSE = "static-parse"


def split_pdf(input_path: str, output_dir: str, pages_per_split: int):
    with pikepdf.open(input_path) as pdf:
        total_pages = len(pdf.pages)
        for start in range(0, total_pages, pages_per_split):
            end = min(start + pages_per_split, total_pages)
            output_path = os.path.join(output_dir, f"split_{start+1}_{end}.pdf")

            with pikepdf.new() as new_pdf:
                new_pdf.pages.extend(pdf.pages[start:end])
                new_pdf.save(output_path)


def parse_pdf_chunk(
    path: str, parser_type: ParserType, raw: bool, **kwargs
) -> List[Dict] | str:
    assert os.path.exists(path)

    docs = []
    if parser_type == ParserType.STATIC_PARSE:
        if "framework" not in kwargs or kwargs["framework"] == "pymupdf":
            if raw:
                return pymupdf4llm.to_markdown(path)
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
    else:  # parser_type == ParserType.LLM_PARSE:
        if "model" not in kwargs:
            kwargs["model"] = "gemini-1.5-flash"
        if kwargs["model"].startswith("gemini"):
            model = genai.GenerativeModel(kwargs["model"])
            file = genai.upload_file(path)
            response = model.generate_content([PDF_PARSER_PROMPT, file])
            raw_text = ""
            for part in response.parts:
                raw_text += part.text
                if raw:
                    continue
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
            if raw:
                return raw_text
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
            if raw:
                return res_txt
            pages = res_txt.text.split("<page break>")
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

    return docs


def parse_pdf(
    path,
    parser_type: ParserType,
    raw: bool = False,
    pages_per_split: int = 4,
    **kwargs,
) -> List[Dict] | str:
    if not path.lower().endswith(".pdf") or parser_type == ParserType.STATIC_PARSE:
        return parse_pdf_chunk(path, parser_type, raw, **kwargs)

    with tempfile.TemporaryDirectory() as temp_dir:
        split_pdf(path, temp_dir, pages_per_split)
        split_files = [os.path.join(temp_dir, f) for f in sorted(os.listdir(temp_dir))]

        all_docs = []
        threads = []

        def thread_parse(file_path, thread_idx):
            result = parse_pdf_chunk(file_path, parser_type, raw, **kwargs)
            all_docs.extend(
                [(res, thread_idx) for res in result]
                if isinstance(result, list)
                else [(result, thread_idx)]
            )

        for idx, split_file in enumerate(split_files):
            thread = threading.Thread(target=thread_parse, args=(split_file, idx))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

    all_docs = sorted(all_docs, key=lambda x: x[1])
    all_docs = [doc for doc, _ in all_docs]
    if raw:
        return "\n".join(all_docs)
    return all_docs


if __name__ == "__main__":
    path = "table.pdf"
    docs = parse_pdf(path, ParserType.LLM_PARSE, pages_per_split=5)
    print(f"Parsed {len(docs)} chunks from the PDF.")
