import tempfile
import os
from enum import Enum
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor

from lexoid.core.parse_type.static_parser import parse_static_doc
from lexoid.core.parse_type.llm_parser import parse_llm_doc
from lexoid.core.utils import (
    split_pdf,
    is_supported_file_type,
    read_html_content,
    download_file,
    convert_to_pdf,
)


class ParserType(Enum):
    LLM_PARSE = "LLM_PARSE"
    STATIC_PARSE = "STATIC_PARSE"


def parse_chunk(
    path: str, parser_type: ParserType, raw: bool, **kwargs
) -> List[Dict] | str:
    """
    Parses a file using the specified parser type.

    Args:
        path (str): The file path or URL.
        parser_type (ParserType): The type of parser to use (LLM_PARSE or STATIC_PARSE).
        raw (bool): Whether to return raw text or structured data.
        **kwargs: Additional arguments for the parser.

    Returns:
        List[Dict] | str: Parsed document data as a list of dictionaries or raw text.
    """
    if parser_type == ParserType.STATIC_PARSE:
        return parse_static_doc(path, raw, **kwargs)
    else:
        return parse_llm_doc(path, raw, **kwargs)


def parse_chunk_list(
    file_paths: List[str], parser_type: ParserType, raw: bool, kwargs: Dict
) -> List[Dict | str]:
    """
    Parses a list of files using the specified parser type.

    Args:
        file_paths (list): List of file paths.
        parser_type (ParserType): The type of parser to use.
        raw (bool): Whether to return raw text or structured data.
        kwargs (dict): Additional arguments for the parser.

    Returns:
        List[Dict | str]: List of parsed documents with raw text and/or metadata.
    """
    local_docs = []
    for file_path in file_paths:
        result = parse_chunk(file_path, parser_type, raw, **kwargs)
        if isinstance(result, list):
            local_docs.extend(result)
        else:
            local_docs.append(result.replace("<page break>", "\n\n"))
    return local_docs


def parse(
    path: str,
    parser_type: str = "LLM_PARSE",
    raw: bool = False,
    pages_per_split: int = 4,
    max_threads: int = 4,
    **kwargs
) -> List[Dict] | str:
    """
    Parses a document or URL, optionally splitting it into chunks and using multithreading.

    Args:
        path (str): The file path or URL.
        parser_type (str, optional): The type of parser to use ("LLM_PARSE" or "STATIC_PARSE"). Defaults to "LLM_PARSE".
        raw (bool, optional): Whether to return raw text or structured data. Defaults to False.
        pages_per_split (int, optional): Number of pages per split for chunking. Defaults to 4.
        max_threads (int, optional): Maximum number of threads for parallel processing. Defaults to 4.
        **kwargs: Additional arguments for the parser.

    Returns:
        List[Dict] | str: Parsed document data as a list of dictionaries or raw text.
    """
    kwargs["title"] = os.path.basename(path)
    as_pdf = kwargs.pop("as_pdf", False)
    parser_type = ParserType[parser_type]

    with tempfile.TemporaryDirectory() as temp_dir:
        if path.startswith(("http://", "https://")):
            if is_supported_file_type(path):
                path = download_file(path, temp_dir)
            elif as_pdf:
                pdf_path = os.path.join(temp_dir, "webpage.pdf")
                path = convert_to_pdf(path, pdf_path)
            else:
                return read_html_content(path)

        if as_pdf and not path.lower().endswith(".pdf"):
            pdf_path = os.path.join(temp_dir, "converted.pdf")
            path = convert_to_pdf(path, pdf_path)

        if not path.lower().endswith(".pdf") or parser_type == ParserType.STATIC_PARSE:
            kwargs["split"] = False
            return parse_chunk(path, parser_type, raw, **kwargs)

        kwargs["split"] = True

        split_pdf(path, temp_dir, pages_per_split)
        split_files = [os.path.join(temp_dir, f) for f in sorted(os.listdir(temp_dir))]

        chunk_size = max(1, len(split_files) // max_threads)
        file_chunks = [
            split_files[i : i + chunk_size]
            for i in range(0, len(split_files), chunk_size)
        ]

        process_args = [(chunk, parser_type, raw, kwargs) for chunk in file_chunks]

        if max_threads == 1 or len(file_chunks) == 1:
            all_docs = [
                parse_chunk_list(chunk, parser_type, raw, kwargs)
                for chunk in file_chunks
            ]
        else:
            with ThreadPoolExecutor(max_workers=max_threads) as executor:
                all_docs = list(executor.map(parse_chunk_list, *zip(*process_args)))

        all_docs = [item for sublist in all_docs for item in sublist]

    return "\n".join(all_docs) if raw else all_docs
