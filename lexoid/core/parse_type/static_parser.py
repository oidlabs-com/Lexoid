from typing import Dict, List

import pandas as pd
import pdfplumber
import pymupdf4llm
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer
from pdfplumber.utils import extract_text, get_bbox_overlap, obj_to_bbox


def parse_static_doc(path: str, raw: bool, **kwargs) -> List[Dict] | str:
    framework = kwargs.get("framework", "pymupdf")

    if framework == "pymupdf":
        return parse_with_pymupdf(path, raw, **kwargs)
    elif framework == "pdfminer":
        return parse_with_pdfminer(path, raw, **kwargs)
    elif framework == "pdfplumber":
        return parse_with_pdfplumber(path, raw, **kwargs)
    else:
        raise ValueError(f"Unsupported framework: {framework}")


def parse_with_pymupdf(path: str, raw: bool, **kwargs) -> List[Dict] | str:
    if raw:
        return pymupdf4llm.to_markdown(path)
    chunks = pymupdf4llm.to_markdown(path, page_chunks=True)
    return [
        {
            "metadata": {
                "title": kwargs["title"],
                "page": kwargs["start"] + chunk["metadata"]["page"],
            },
            "content": chunk["text"],
        }
        for chunk in chunks
    ]


def parse_with_pdfminer(path: str, raw: bool, **kwargs) -> List[Dict] | str:
    pages = list(extract_pages(path))
    docs = []
    for page_num, page_layout in enumerate(pages, start=1):
        page_text = "".join(
            element.get_text()
            for element in page_layout
            if isinstance(element, LTTextContainer)
        )
        if raw:
            docs.append(page_text)
        else:
            docs.append(
                {
                    "metadata": {
                        "title": kwargs["title"],
                        "page": kwargs["start"] + page_num,
                    },
                    "content": page_text,
                }
            )
    return "\n".join(docs) if raw else docs


def parse_with_pdfplumber(path: str, raw: bool, **kwargs) -> List[Dict] | str:
    page_texts = process_pdf_with_pdfplumber(path)
    if raw:
        return "<page-break>".join(page_texts)
    return [
        {
            "metadata": {"title": kwargs["title"], "page": kwargs["start"] + page_num},
            "content": page_text,
        }
        for page_num, page_text in enumerate(page_texts, start=1)
    ]


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
