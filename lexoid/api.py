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


def parse_chunk(path: str, parser_type: ParserType, **kwargs) -> Dict:
    """
    Parses a file using the specified parser type.

    Args:
        path (str): The file path or URL.
        parser_type (ParserType): The type of parser to use (LLM_PARSE, STATIC_PARSE, or AUTO).
        **kwargs: Additional arguments for the parser.

    Returns:
        Dict: Dictionary containing:
            - raw: Full markdown content as string
            - segments: List of dictionaries with metadata and content
            - title: Title of the document
            - url: URL if applicable
            - parent_title: Title of parent doc if recursively parsed
            - recursive_docs: List of dictionaries for recursively parsed documents
    """
    if parser_type == ParserType.AUTO:
        parser_type = ParserType[router(path)]
        logger.debug(f"Auto-detected parser type: {parser_type}")

    kwargs["start"] = (
        int(os.path.basename(path).split("_")[1]) - 1 if kwargs.get("split") else 0
    )
    if parser_type == ParserType.STATIC_PARSE:
        logger.debug("Using static parser")
        return parse_static_doc(path, **kwargs)
    else:
        logger.debug("Using LLM parser")
        return parse_llm_doc(path, **kwargs)


def parse_chunk_list(
    file_paths: List[str], parser_type: ParserType, kwargs: Dict
) -> Dict:
    """
    Parses a list of files using the specified parser type.

    Args:
        file_paths (list): List of file paths.
        parser_type (ParserType): The type of parser to use.
        kwargs (dict): Additional arguments for the parser.

    Returns:
        Dict: Dictionary containing parsed document data
    """
    combined_segments = []
    raw_texts = []

    for file_path in file_paths:
        result = parse_chunk(file_path, parser_type, **kwargs)
        combined_segments.extend(result["segments"])
        raw_texts.append(result["raw"])

    return {
        "raw": "\n\n".join(raw_texts),
        "segments": combined_segments,
        "title": kwargs.get("title", ""),
        "url": kwargs.get("url", ""),
        "parent_title": kwargs.get("parent_title", ""),
        "recursive_docs": [],
    }


def parse(
    path: str,
    parser_type: Union[str, ParserType] = "LLM_PARSE",
    pages_per_split: int = 4,
    max_processes: int = 4,
    **kwargs,
) -> Dict:
    """
    Parses a document or URL, optionally splitting it into chunks and using multiprocessing.

    Args:
        path (str): The file path or URL.
        parser_type (Union[str, ParserType], optional): Parser type ("LLM_PARSE", "STATIC_PARSE", or "AUTO").
        pages_per_split (int, optional): Number of pages per split for chunking.
        max_processes (int, optional): Maximum number of processes for parallel processing.
        **kwargs: Additional arguments for the parser.

    Returns:
        Dict: Dictionary containing:
            - raw: Full markdown content as string
            - segments: List of dictionaries with metadata and content
            - title: Title of the document
            - url: URL if applicable
            - parent_title: Title of parent doc if recursively parsed
            - recursive_docs: List of dictionaries for recursively parsed documents
    """
    kwargs["title"] = os.path.basename(path)
    kwargs["pages_per_split_"] = pages_per_split
    as_pdf = kwargs.get("as_pdf", False)
    depth = kwargs.get("depth", 1)

    if type(parser_type) == str:
        parser_type = ParserType[parser_type]

    with tempfile.TemporaryDirectory() as temp_dir:
        if (
            path.lower().endswith((".doc", ".docx"))
            and parser_type != ParserType.STATIC_PARSE
        ):
            as_pdf = True

        if path.startswith(("http://", "https://")):
            kwargs["url"] = path
            download_dir = os.path.join(temp_dir, "downloads/")
            os.makedirs(download_dir, exist_ok=True)
            if is_supported_url_file_type(path):
                path = download_file(path, download_dir)
            elif as_pdf:
                pdf_path = os.path.join(download_dir, f"webpage_{int(time())}.pdf")
                path = convert_to_pdf(path, pdf_path)
            else:
                return recursive_read_html(path, depth)

        assert is_supported_file_type(
            path
        ), f"Unsupported file type {os.path.splitext(path)[1]}"

        if as_pdf and not path.lower().endswith(".pdf"):
            pdf_path = os.path.join(temp_dir, "converted.pdf")
            path = convert_to_pdf(path, pdf_path)

        if not path.lower().endswith(".pdf") or parser_type == ParserType.STATIC_PARSE:
            kwargs["split"] = False
            result = parse_chunk(path, parser_type, **kwargs)
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

            process_args = [(chunk, parser_type, kwargs) for chunk in file_chunks]

            if max_processes == 1 or len(file_chunks) == 1:
                chunk_results = [parse_chunk_list(*args) for args in process_args]
            else:
                with ProcessPoolExecutor(max_workers=max_processes) as executor:
                    chunk_results = list(
                        executor.map(parse_chunk_list, *zip(*process_args))
                    )

            # Combine results from all chunks
            result = {
                "raw": "\n\n".join(r["raw"] for r in chunk_results),
                "segments": [seg for r in chunk_results for seg in r["segments"]],
                "title": kwargs["title"],
                "url": kwargs.get("url", ""),
                "parent_title": kwargs.get("parent_title", ""),
                "recursive_docs": [],
            }

    if depth > 1:
        recursive_docs = []
        for segment in result["segments"]:
            urls = re.findall(
                r'https?://[^\s<>"\']+|www\.[^\s<>"\']+(?:\.[^\s<>"\']+)*',
                segment["content"],
            )
            for url in urls:
                if "](" in url:
                    url = url.split("](")[-1]
                logger.debug(f"Reading content from {url}")
                if not url.startswith("http"):
                    url = "https://" + url

                kwargs_cp = kwargs.copy()
                kwargs_cp["depth"] = depth - 1
                kwargs_cp["parent_title"] = result["title"]
                sub_doc = parse(
                    url,
                    parser_type=parser_type,
                    pages_per_split=pages_per_split,
                    max_processes=max_processes,
                    **kwargs_cp,
                )
                recursive_docs.append(sub_doc)

        result["recursive_docs"] = recursive_docs

    return result
