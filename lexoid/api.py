import json
import os
import re
import tempfile
from concurrent.futures import ProcessPoolExecutor
from enum import Enum
from functools import wraps
from glob import glob
from time import time
from typing import Dict, List, Optional, Type, Union

from loguru import logger

from lexoid.core.parse_type.llm_parser import (
    convert_doc_to_base64_images,
    create_response,
    get_api_provider_for_model,
    parse_llm_doc,
)
from lexoid.core.parse_type.static_parser import parse_static_doc
from lexoid.core.utils import (
    convert_schema_to_dict,
    convert_to_pdf,
    create_sub_pdf,
    download_file,
    get_webpage_soup,
    is_supported_file_type,
    is_supported_url_file_type,
    recursive_read_html,
    router,
    split_pdf,
)


class ParserType(Enum):
    LLM_PARSE = "LLM_PARSE"
    STATIC_PARSE = "STATIC_PARSE"
    AUTO = "AUTO"


def retry_with_different_parser_type(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            if len(args) > 0:
                kwargs["path"] = args[0]
            if len(args) > 1:
                router_priority = kwargs.get("router_priority", "speed")
                if args[1] == ParserType.AUTO:
                    parser_type = ParserType[router(kwargs["path"], router_priority)]
                    logger.debug(f"Auto-detected parser type: {parser_type}")
                    kwargs["routed"] = True
                else:
                    parser_type = args[1]
                kwargs["parser_type"] = parser_type
            return func(**kwargs)
        except Exception as e:
            if kwargs.get("parser_type") == ParserType.LLM_PARSE and kwargs.get(
                "routed", False
            ):
                logger.warning(
                    f"LLM_PARSE failed with error: {e}. Retrying with STATIC_PARSE."
                )
                kwargs["parser_type"] = ParserType.STATIC_PARSE
                kwargs["routed"] = False
                return func(**kwargs)
            elif kwargs.get("parser_type") == ParserType.STATIC_PARSE and kwargs.get(
                "routed", False
            ):
                logger.warning(
                    f"STATIC_PARSE failed with error: {e}. Retrying with LLM_PARSE."
                )
                kwargs["parser_type"] = ParserType.LLM_PARSE
                kwargs["routed"] = False
                return func(**kwargs)
            else:
                logger.error(
                    f"Parsing failed with error: {e}. No fallback parser available."
                )
                raise e

    return wrapper


@retry_with_different_parser_type
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
            - token_usage: Dictionary containing token usage statistics
            - parser_used: Which parser was actually used
    """
    kwargs["start"] = (
        int(os.path.basename(path).split("_")[1]) - 1 if kwargs.get("split") else 0
    )
    if parser_type == ParserType.STATIC_PARSE:
        logger.debug("Using static parser")
        result = parse_static_doc(path, **kwargs)
    else:
        logger.debug("Using LLM parser")
        result = parse_llm_doc(path, **kwargs)

    result["parser_used"] = parser_type
    return result


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
    token_usage = {"input": 0, "output": 0, "llm_page_count": 0}
    for file_path in file_paths:
        result = parse_chunk(file_path, parser_type, **kwargs)
        combined_segments.extend(result["segments"])
        raw_texts.append(result["raw"])
        if (
            result.get("parser_used") == ParserType.LLM_PARSE
            and "token_usage" in result
        ):
            token_usage["input"] += result["token_usage"]["input"]
            token_usage["output"] += result["token_usage"]["output"]
            token_usage["llm_page_count"] += len(result["segments"])
    token_usage["total"] = token_usage["input"] + token_usage["output"]

    return {
        "raw": "\n\n".join(raw_texts),
        "segments": combined_segments,
        "title": kwargs.get("title", ""),
        "url": kwargs.get("url", ""),
        "parent_title": kwargs.get("parent_title", ""),
        "recursive_docs": [],
        "token_usage": token_usage,
    }


def parse(
    path: str,
    parser_type: Union[str, ParserType] = "AUTO",
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
            - token_usage: Dictionary containing token usage statistics
    """
    kwargs["title"] = os.path.basename(path)
    kwargs["pages_per_split_"] = pages_per_split
    as_pdf = kwargs.get("as_pdf", False)
    depth = kwargs.get("depth", 1)

    if type(parser_type) is str:
        parser_type = ParserType[parser_type]
    if (
        path.lower().endswith((".doc", ".docx"))
        and parser_type != ParserType.STATIC_PARSE
    ):
        as_pdf = True
    if path.lower().endswith(".xlsx") and parser_type == ParserType.LLM_PARSE:
        logger.warning("LLM_PARSE does not support .xlsx files. Using STATIC_PARSE.")
        parser_type = ParserType.STATIC_PARSE
    if path.lower().endswith(".pptx") and parser_type == ParserType.LLM_PARSE:
        logger.warning("LLM_PARSE does not support .pptx files. Using STATIC_PARSE.")
        parser_type = ParserType.STATIC_PARSE

    with tempfile.TemporaryDirectory() as temp_dir:
        kwargs["temp_dir"] = temp_dir
        if path.startswith(("http://", "https://")):
            kwargs["url"] = path
            download_dir = kwargs.get("save_dir", os.path.join(temp_dir, "downloads/"))
            os.makedirs(download_dir, exist_ok=True)
            if is_supported_url_file_type(path):
                path = download_file(path, download_dir)
            elif as_pdf:
                soup = get_webpage_soup(path)
                kwargs["title"] = str(soup.title).strip() if soup.title else "Untitled"
                pdf_filename = kwargs.get("save_filename", f"webpage_{int(time())}.pdf")
                if not pdf_filename.endswith(".pdf"):
                    pdf_filename += ".pdf"
                pdf_path = os.path.join(download_dir, pdf_filename)
                logger.debug("Converting webpage to PDF...")
                path = convert_to_pdf(path, pdf_path)
            else:
                return recursive_read_html(path, depth)

        assert is_supported_file_type(path), (
            f"Unsupported file type {os.path.splitext(path)[1]}"
        )

        if as_pdf and not path.lower().endswith(".pdf"):
            pdf_path = os.path.join(temp_dir, "converted.pdf")
            logger.debug("Converting file to PDF")
            path = convert_to_pdf(path, pdf_path)

        if "page_nums" in kwargs and path.lower().endswith(".pdf"):
            sub_pdf_dir = os.path.join(temp_dir, "sub_pdfs")
            os.makedirs(sub_pdf_dir, exist_ok=True)
            sub_pdf_path = os.path.join(sub_pdf_dir, f"{os.path.basename(path)}")
            path = create_sub_pdf(path, sub_pdf_path, kwargs["page_nums"])

        if not path.lower().endswith(".pdf"):
            kwargs["split"] = False
            result = parse_chunk_list([path], parser_type, kwargs)
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
                "token_usage": {
                    "input": sum(r["token_usage"]["input"] for r in chunk_results),
                    "output": sum(r["token_usage"]["output"] for r in chunk_results),
                    "llm_page_count": sum(
                        r["token_usage"]["llm_page_count"] for r in chunk_results
                    ),
                    "total": sum(r["token_usage"]["total"] for r in chunk_results),
                },
            }

        if "api_cost_mapping" in kwargs and "token_usage" in result:
            api_cost_mapping = kwargs["api_cost_mapping"]
            if isinstance(api_cost_mapping, dict):
                api_cost_mapping = api_cost_mapping
            elif isinstance(api_cost_mapping, str) and os.path.exists(api_cost_mapping):
                with open(api_cost_mapping, "r") as f:
                    api_cost_mapping = json.load(f)
            else:
                raise ValueError(f"Unsupported API cost value: {api_cost_mapping}.")

            api_cost = api_cost_mapping.get(
                kwargs.get("model", "gemini-2.0-flash"), None
            )
            if api_cost:
                token_usage = result["token_usage"]
                token_cost = {
                    "input": token_usage["input"] * api_cost["input"] / 1_000_000,
                    "input-image": api_cost.get("input-image", 0)
                    * token_usage.get("llm_page_count", 0),
                    "output": token_usage["output"] * api_cost["output"] / 1_000_000,
                }
                token_cost["total"] = (
                    token_cost["input"]
                    + token_cost["input-image"]
                    + token_cost["output"]
                )
                result["token_cost"] = token_cost

        if as_pdf:
            result["pdf_path"] = path

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


def parse_with_schema(
    path: str,
    schema: Union[Dict, Type],
    api: Optional[str] = None,
    model: str = "gpt-4o-mini",
    **kwargs,
) -> List[List[Dict]]:
    """
    Parses a PDF using an LLM to generate structured output conforming to a given JSON schema.

    Args:
        path (str): Path to the PDF file.
        schema (Dict): JSON schema to which the parsed output should conform.
        api (str, optional): LLM API provider (One of "openai", "huggingface", "together", "openrouter", and "fireworks").
        model (str, optional): LLM model name.
        **kwargs: Additional arguments for the parser (e.g.: temperature, max_tokens).

    Returns:
        List[List[Dict]]: List of dictionaries for each page, each conforming to the provided schema.
    """
    if not api:
        api = get_api_provider_for_model(model)
        logger.debug(f"Using API provider: {api}")

    json_schema = convert_schema_to_dict(schema)

    system_prompt = f"""
        The output should be formatted as a JSON instance that conforms to the JSON schema below.

        As an example, for the schema {{
        "properties": {{
            "foo": {{
            "title": "Foo",
            "description": "a list of strings",
            "type": "array",
            "items": {{"type": "string"}}
            }}
        }},
        "required": ["foo"]
        }}, the object {{"foo": ["bar", "baz"]}} is valid. The object {{"properties": {{"foo": ["bar", "baz"]}}}} is not.

        Here is the output schema:
        {json.dumps(json_schema, indent=2)}

        """

    user_prompt = "You are an AI agent that parses documents and returns them in the specified JSON format. Please parse the document and return it in the required format."

    responses = []
    images = convert_doc_to_base64_images(path)
    for i, (page_num, image) in enumerate(images):
        resp_dict = create_response(
            api=api,
            model=model,
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            image_url=image,
            temperature=kwargs.get("temperature", 0.0),
            max_tokens=kwargs.get("max_tokens", 1024),
        )

        response = resp_dict.get("response", "")
        response = response.split("```json")[-1].split("```")[0].strip()
        logger.debug(f"Processing page {page_num + 1} with response: {response}")
        new_dict = json.loads(response)
        responses.append(new_dict)

    return responses


def parse_to_latex(
    path: str,
    api: Optional[str] = None,
    model: str = "gpt-4o-mini",
    **kwargs,
) -> str:
    if not api:
        api = get_api_provider_for_model(model)
        logger.debug(f"Using API provider: {api}")

    first_page_prompt = """
    You are an AI agent tasked with converting the **first page** of a PDF document into LaTeX format.

    Begin the LaTeX document with:
    documentclass{article}
    usepackage{amsmath, graphicx, geometry}
    geometry{margin=1in}  % Ensure content stays within page bounds
    begin{document}

    If the first page contains title and abstract, use:
    title{}
    author{}
    date{}
    maketitle
    begin{abstract}...end{abstract}

    Then begin converting the content with structured LaTeX formatting with the necessary tags:
    - Use section{}, subsection{}, subsubsection{} for headings
    - Use begin{itemize}, begin{enumerate} for lists
    - Use textbf{}, textit{}, underline{} for text styling
    - Use inline math ($...$) or begin{equation} for equations
    - Use begin{tabular} and includegraphics[]{} for tables and figures

    **Important:** Only include content visible on the current page. Do not include content from other pages. Keep the LaTeX output strictly limited to the information available on this page.

    """

    middle_page_prompt = """
    Convert this page into valid LaTeX **content only**, assuming the document is already open.
    Do not repeat the document preamble.
    Continue using:
    - section{}, subsection{}, etc. for headings
    - textbf{}, textit{}, underline{} for formatting
    - $...$ and begin{equation} for math
    - begin{itemize}, begin{enumerate} for lists
    - begin{tabular}, includegraphics[]{} for tables/figures
    - footnote{}, bibitem{} where needed
    Do not add begin{document} or end{document}.
    """

    last_page_prompt = """
    This is the **final page** of the PDF.
    Continue converting content as usual using LaTeX formatting, and then **end the document** with:
    end{document}
    Ensure no section is left open. If the document ends with a reference section, use begin{thebibliography}...end{thebibliography} if appropriate.
    Add % TODO comments where structure or content is uncertain.
    """

    user_prompt = "You are an AI agent that parses documents and returns them in the Latex format. Please parse the document and return Latex for a document."

    responses = []
    images = convert_doc_to_base64_images(path)
    total_pages = len(images)

    for i, (page_num, image) in enumerate(images):
        if i == 0:
            system_prompt = first_page_prompt
        elif i == total_pages - 1:
            system_prompt = last_page_prompt
        else:
            system_prompt = middle_page_prompt

        resp_dict = create_response(
            api=api,
            model=model,
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            image_url=image,
            temperature=kwargs.get("temperature", 0.0),
            max_tokens=kwargs.get("max_tokens", 1024),
        )
        response = resp_dict.get("response", "").strip()
        response = response.split("```latex")[-1].split("```")[0].strip()
        logger.debug(f"Processing page {page_num + 1} with response:\n{response}")
        responses.append(response)

    return "\n\n".join(responses)
