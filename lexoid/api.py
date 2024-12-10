import os
import re
import tempfile
from concurrent.futures import ProcessPoolExecutor
from enum import Enum
from glob import glob
from time import time
from typing import Union, Dict, List

from loguru import logger

from lexoid.core.parse_type.llm_parser import parse_llm_doc
from lexoid.core.parse_type.static_parser import parse_static_doc
from lexoid.core.utils import (
    convert_to_pdf,
    download_file,
    is_supported_url_file_type,
    is_supported_file_type,
    recursive_read_html,
    router,
    split_pdf,
)


class ParserType(Enum):
    LLM_PARSE = "LLM_PARSE"
    STATIC_PARSE = "STATIC_PARSE"
    AUTO = "AUTO"


def parse_chunk(
    path: str, parser_type: ParserType, raw: bool, **kwargs
) -> List[Dict] | str:
    """
    Parses a file using the specified parser type.

    Args:
        path (str): The file path or URL.
        parser_type (ParserType): The type of parser to use (LLM_PARSE, STATIC_PARSE, or AUTO).
        raw (bool): Whether to return raw text or structured data.
        **kwargs: Additional arguments for the parser.

    Returns:
        List[Dict] | str: Parsed document data as a list of dictionaries or raw text.
    """
    if parser_type == ParserType.AUTO:
        parser_type = ParserType[router(path)]
        logger.debug(f"Auto-detected parser type: {parser_type}")

    kwargs["start"] = (
        int(os.path.basename(path).split("_")[1]) - 1 if kwargs.get("split") else 0
    )
    if parser_type == ParserType.STATIC_PARSE:
        logger.debug("Using static parser")
        return parse_static_doc(path, raw, **kwargs)
    else:
        logger.debug("Using LLM parser")
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
    max_processes: int = 4,
    **kwargs,
) -> Union[List[Dict], str]:
    """
    Parses a document or URL, optionally splitting it into chunks and using multiprocessing.

    Args:
        path (str): The file path or URL.
        parser_type (str, optional): The type of parser to use ("LLM_PARSE", "STATIC_PARSE", or "AUTO"). Defaults to "LLM_PARSE".
        raw (bool, optional): Whether to return raw text or structured data. Defaults to False.
        pages_per_split (int, optional): Number of pages per split for chunking. Defaults to 4.
        max_processes (int, optional): Maximum number of processes for parallel processing. Defaults to 4.
        **kwargs: Additional arguments for the parser.

    Returns:
        Union[List[Dict], str]: Parsed document data as a list of dictionaries or raw text.
    """
    kwargs["title"] = os.path.basename(path)
    kwargs["pages_per_split"] = pages_per_split
    as_pdf = kwargs.get("as_pdf", False)
    depth = kwargs.get("depth", 1)
    parser_type = ParserType[parser_type]

    with tempfile.TemporaryDirectory() as temp_dir:
        if (
            path.lower().endswith((".doc", ".docx"))
            and parser_type != ParserType.STATIC_PARSE
        ):
            as_pdf = True

        if path.startswith(("http://", "https://")):
            download_dir = os.path.join(temp_dir, "downloads/")
            os.makedirs(download_dir, exist_ok=True)
            if is_supported_url_file_type(path):
                path = download_file(path, download_dir)
            elif as_pdf:
                pdf_path = os.path.join(download_dir, f"webpage_{int(time())}.pdf")
                path = convert_to_pdf(path, pdf_path)
            else:
                return recursive_read_html(path, depth, raw)

        assert is_supported_file_type(
            path
        ), f"Unsupported file type {os.path.splitext(path)[1]}"

        if as_pdf and not path.lower().endswith(".pdf"):
            pdf_path = os.path.join(temp_dir, "converted.pdf")
            path = convert_to_pdf(path, pdf_path)

        if not path.lower().endswith(".pdf") or parser_type == ParserType.STATIC_PARSE:
            kwargs["split"] = False
            all_docs = parse_chunk(path, parser_type, raw, **kwargs)
            if raw:
                all_docs = [all_docs]
        else:
            kwargs["split"] = True
            split_dir = os.path.join(temp_dir, "splits/")
            os.makedirs(split_dir, exist_ok=True)
            split_pdf(path, split_dir, pages_per_split)
            split_files = sorted(glob(os.path.join(split_dir, "*.pdf")))

            chunk_size = max(1, len(split_files) // max_processes)
            file_chunks = [
                split_files[i : i + chunk_size]
                for i in range(0, len(split_files), chunk_size)
            ]

            process_args = [(chunk, parser_type, raw, kwargs) for chunk in file_chunks]

            if max_processes == 1 or len(file_chunks) == 1:
                all_docs = [parse_chunk_list(*args) for args in process_args]
            else:
                with ProcessPoolExecutor(max_workers=max_processes) as executor:
                    all_docs = list(executor.map(parse_chunk_list, *zip(*process_args)))

            all_docs = [item for sublist in all_docs for item in sublist]

    if depth > 1:
        new_docs = all_docs.copy()
        for doc in all_docs:
            urls = re.findall(
                r'https?://[^\s<>"\']+|www\.[^\s<>"\']+(?:\.[^\s<>"\']+)*',
                doc if raw else doc["content"],
            )
            for url in urls:
                if "](" in url:
                    url = url.split("](")[-1]
                logger.debug(f"Reading content from {url}")
                if not url.startswith("http"):
                    url = "https://" + url

                kwargs_cp = kwargs.copy()
                kwargs_cp["depth"] = depth - 1
                res = parse(
                    url,
                    parser_type=parser_type,
                    raw=raw,
                    pages_per_split=pages_per_split,
                    max_processes=max_processes,
                    **kwargs_cp,
                )

                if raw:
                    new_docs.append(res)
                else:
                    new_docs.extend(res)
        all_docs = new_docs

    return "\n".join(all_docs) if raw else all_docs
