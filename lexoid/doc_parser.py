import tempfile
import os
from enum import Enum
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor

from lexoid.parsers.static_parser import parse_static_doc
from lexoid.parsers.llm_parser import parse_llm_doc
from lexoid.utils import split_pdf


class ParserType(Enum):
    LLM_PARSE = "llm-parse"
    STATIC_PARSE = "static-parse"


def parse_pdf_chunk(
    path: str, parser_type: ParserType, raw: bool, **kwargs
) -> List[Dict] | str:
    if parser_type == ParserType.STATIC_PARSE:
        return parse_static_doc(path, raw, **kwargs)
    else:
        return parse_llm_doc(path, raw, **kwargs)


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


def parse_doc(
    path,
    parser_type: ParserType,
    raw: bool = False,
    pages_per_split: int = 4,
    max_threads: int = 4,
    **kwargs
) -> List[Dict] | str:
    kwargs["title"] = os.path.basename(path)

    if not path.lower().endswith(".pdf") or parser_type == ParserType.STATIC_PARSE:
        kwargs["split"] = False
        return parse_pdf_chunk(path, parser_type, raw, **kwargs)

    kwargs["split"] = True

    with tempfile.TemporaryDirectory() as temp_dir:
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
                process_chunk((chunk, parser_type, raw, kwargs))
                for chunk in file_chunks
            ]
        else:
            with ThreadPoolExecutor(max_workers=max_threads) as executor:
                all_docs = list(executor.map(process_chunk, process_args))

        all_docs = [item for sublist in all_docs for item in sublist]

    return "\n".join(all_docs) if raw else all_docs
