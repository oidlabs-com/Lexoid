import os
import tempfile
import multiprocessing
import pymupdf4llm
import google.generativeai as genai
import pikepdf
import pdfplumber
import pandas as pd
from enum import Enum
from typing import Dict, List
from openai import OpenAI
from openai.types.beta.threads.message_create_params import (
    Attachment,
    AttachmentToolFileSearch,
)
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer
from pdfplumber.utils import extract_text, get_bbox_overlap, obj_to_bbox

from pdf_parser.prompt_templates import PDF_PARSER_PROMPT


class ParserType(Enum):
    LLM_PARSE = "llm-parse"
    STATIC_PARSE = "static-parse"


def split_pdf(input_path: str, output_dir: str, pages_per_split: int):
    with pikepdf.open(input_path) as pdf:
        total_pages = len(pdf.pages)
        for start in range(0, total_pages, pages_per_split):
            end = min(start + pages_per_split, total_pages)
            output_path = os.path.join(
                output_dir, f"split_{str(start + 1).zfill(4)}_{end}.pdf"
            )

            with pikepdf.new() as new_pdf:
                new_pdf.pages.extend(pdf.pages[start:end])
                new_pdf.save(output_path)


def process_pdf_with_pdfplumber(path: str) -> List[str]:
    with pdfplumber.open(path) as pdf:
        all_text = []

        for page in pdf.pages:
            filtered_page = page
            chars = filtered_page.chars

            for table in page.find_tables():
                first_table_char = page.crop(table.bbox).chars[0]
                filtered_page = filtered_page.filter(
                    lambda obj: get_bbox_overlap(obj_to_bbox(obj), table.bbox) is None
                )
                chars = filtered_page.chars

                df = pd.DataFrame(table.extract())
                df.columns = df.iloc[0]
                markdown = df.drop(0).to_markdown(index=False)

                chars.append(first_table_char | {"text": markdown})

            page_text = extract_text(chars, layout=True)
            all_text.append(page_text)

    return all_text


def parse_pdf_chunk(
    path: str, parser_type: ParserType, raw: bool, **kwargs
) -> List[Dict] | str:
    assert os.path.exists(path)

    if kwargs["split"]:
        start = int(os.path.basename(path).split("_")[1])
    else:
        start = 0

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
                            "title": kwargs["title"],
                            "page": start + metadata["page"],
                        },
                        "content": chunk["text"],
                    }
                )
        elif kwargs["framework"] == "pdfminer":
            pages = list(extract_pages(path))
            for page_num, page_layout in enumerate(pages, start=1):
                page_text = ""
                for element in page_layout:
                    if isinstance(element, LTTextContainer):
                        page_text += element.get_text()

                if raw:
                    docs.append(page_text)
                else:
                    docs.append(
                        {
                            "metadata": {
                                "title": kwargs["title"],
                                "page": start + page_num,
                            },
                            "content": page_text,
                        }
                    )
            if raw:
                return "\n".join(docs)
        elif kwargs["framework"] == "pdfplumber":
            page_texts = process_pdf_with_pdfplumber(path)
            if raw:
                return "<page break>".join(page_texts)
            else:
                for page_num, page_text in enumerate(page_texts, start=1):
                    docs.append(
                        {
                            "metadata": {
                                "title": kwargs["title"],
                                "page": start + page_num,
                            },
                            "content": page_text,
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
                                "title": kwargs["title"],
                                "page": start + page_no,
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
                            "title": kwargs["title"],
                            "page": start + page_no,
                        },
                        "content": page,
                    }
                )

    return docs


def process_chunk(args):
    file_paths, parser_type, raw, kwargs = args
    local_docs = []
    for file_path in file_paths:
        result = parse_pdf_chunk(file_path, parser_type, raw, **kwargs)
        if isinstance(result, list):
            local_docs.extend(result)
        else:
            local_docs.append(result)
    return local_docs


def parse_pdf(
    path,
    parser_type: ParserType,
    raw: bool = False,
    pages_per_split: int = 4,
    max_processes: int = 4,
    **kwargs,
) -> List[Dict] | str:
    kwargs["title"] = os.path.basename(path)

    if not path.lower().endswith(".pdf") or parser_type == ParserType.STATIC_PARSE:
        kwargs["split"] = False
        return parse_pdf_chunk(path, parser_type, raw, **kwargs)

    kwargs["split"] = True

    with tempfile.TemporaryDirectory() as temp_dir:
        split_pdf(path, temp_dir, pages_per_split)
        split_files = [os.path.join(temp_dir, f) for f in sorted(os.listdir(temp_dir))]

        chunk_size = max(1, len(split_files) // max_processes)
        file_chunks = [
            split_files[i : i + chunk_size]
            for i in range(0, len(split_files), chunk_size)
        ]

        # Prepare arguments for each process
        process_args = [(chunk, parser_type, raw, kwargs) for chunk in file_chunks]

        if max_processes == 1 or len(file_chunks) == 1:
            # Process sequentially if max_processes is 1 or there's only one chunk
            all_docs = [
                process_chunk((chunk, parser_type, raw, kwargs))
                for chunk in file_chunks
            ]
        else:
            # Use multiprocessing for multiple chunks
            with multiprocessing.Pool(processes=max_processes) as pool:
                all_docs = pool.map(process_chunk, process_args)

        # Flatten the list of lists
        all_docs = [item for sublist in all_docs for item in sublist]

    if raw:
        return "\n".join(all_docs)
    return all_docs


if __name__ == "__main__":
    path = "table.pdf"
    docs = parse_pdf(
        path, ParserType.STATIC_PARSE, pages_per_split=5, framework="pdfplumber"
    )
    print(f"Parsed {len(docs)} chunks from the PDF.")
    print("Sample of parsed content:")
    print(docs[0]["content"][:500] if docs else "No content parsed.")