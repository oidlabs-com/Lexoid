API Reference
=============

Parser Types
------------

Lexoid exposes three parser types via the ``lexoid.api.ParserType`` enum:

* ``LLM_PARSE`` — Sends document pages (rendered to images) to an LLM API.
* ``STATIC_PARSE`` — Non-LLM parsing via ``pdfplumber``, ``pdfminer``, or
  ``paddleocr`` for PDFs/images, plus dedicated handlers for HTML, plain
  text, CSV, spreadsheets, DOCX, and PPTX.
* ``AUTO`` — Routes to ``LLM_PARSE`` or ``STATIC_PARSE`` based on document
  characteristics and the configured routing priority. Falls back to the
  alternate parser type on failure.

Static parsing frameworks
^^^^^^^^^^^^^^^^^^^^^^^^^

For PDF inputs, the following ``framework`` values are supported:

* ``pdfplumber`` (default) — Text extraction with table/heading/hyperlink heuristics.
* ``pdfminer`` — Pure pdfminer-based text extraction.
* ``paddleocr`` — OCR-based extraction (used automatically for image inputs and as a fallback).

Core Function
-------------

parse
^^^^^

.. py:function:: lexoid.api.parse(path: str, parser_type: Union[str, ParserType] = "AUTO", pages_per_split: int = 4, max_processes: int = 4, **kwargs) -> Dict

   Parse a document, image, audio file, or URL.

   :param path: File path or URL to parse.
   :param parser_type: Parser type to use (``"LLM_PARSE"``, ``"STATIC_PARSE"``, or ``"AUTO"``). Default: ``"AUTO"``.
   :param pages_per_split: Number of pages per chunk for processing. Default: ``4``.
   :param max_processes: Maximum number of parallel processes. Default: ``4``. Automatically forced to ``1`` when ``parser_type="LLM_PARSE"`` and ``api_provider="ollama"``.
   :param kwargs: Additional keyword arguments (see below).

   Automatic input handling:

   * ``.doc`` / ``.docx`` inputs with any ``parser_type`` other than ``STATIC_PARSE`` are first converted to PDF (``as_pdf`` is forced to ``True``).
   * ``.xlsx`` and ``.pptx`` inputs with ``parser_type="LLM_PARSE"`` are silently switched to ``STATIC_PARSE`` (a warning is logged) because LLM parsing is not supported for these formats.

   Additional keyword arguments:

   * ``model`` (str): LLM model to use. Defaults to the ``DEFAULT_LLM`` environment variable, or ``"gemini-2.5-flash"``.
   * ``api_provider`` (str): API provider for LLM parsing. One of ``"gemini"``, ``"openai"``, ``"anthropic"``, ``"mistral"``, ``"huggingface"``, ``"together"``, ``"openrouter"``, ``"fireworks"``, ``"ollama"``, or ``"local"``. If not set, the provider is inferred from the model name.
   * ``framework`` (str): Static parsing framework — ``"pdfplumber"`` (default), ``"pdfminer"``, or ``"paddleocr"``.
   * ``temperature`` (float): Temperature for LLM generation. Default: ``0.0``.
   * ``max_tokens`` (int): Max output tokens per LLM call. Defaults to ``1024`` (``4096`` for Ollama).
   * ``system_prompt`` (str): Override the default parser system prompt.
   * ``user_prompt`` (str): Override the default user prompt.
   * ``depth`` (int): Depth for recursive URL parsing. Default: ``1``.
   * ``as_pdf`` (bool): Convert input (image / webpage / DOCX) to PDF before processing.
   * ``verbose`` (bool): Enable verbose logging during LLM parsing.
   * ``x_tolerance`` (int): X-axis tolerance for ``pdfplumber`` text extraction.
   * ``y_tolerance`` (int): Y-axis tolerance for ``pdfplumber`` text extraction.
   * ``save_dir`` (str): Directory to save intermediate PDFs when ``as_pdf=True``.
   * ``save_filename`` (str): Filename used when saving the intermediate PDF for a webpage. Defaults to ``webpage_<timestamp>.pdf``.
   * ``page_nums`` (List[int]): Specific 1-indexed page numbers to parse (PDFs only).
   * ``max_image_dimension`` (int): Maximum width/height (px) to which page images / input images are downscaled before parsing. Defaults to ``DEFAULT_MAX_IMAGE_DIMENSION`` (``1000``).
   * ``api_cost_mapping`` (Union[dict, str]): Cost-per-million-tokens dictionary, or path to a JSON file. Sample at ``tests/api_cost_mapping.json``. When provided, the ``token_cost`` key is added to the result.
   * ``router_priority`` (str): Routing priority for ``AUTO`` mode. One of:

     - ``"speed"`` (default): Uses ``STATIC_PARSE`` for PDFs without images, else ``LLM_PARSE``.
     - ``"accuracy"``: Prefers ``LLM_PARSE``, except for PDFs with no images but with embedded/hidden hyperlinks (uses ``STATIC_PARSE`` since LLMs miss hidden links).
     - ``"cost"``: For PDFs that contain images, tries PaddleOCR first; if the extracted character count is below ``character_threshold`` the PaddleOCR result is returned, otherwise the document is re-parsed with ``LLM_PARSE``. PDFs without images, and non-PDF inputs, fall back to the same routing as ``"speed"``.
   * ``character_threshold`` (int): Minimum character count for a ``router_priority="cost"`` STATIC_PARSE result to be accepted. Default: ``100``.
   * ``autoselect_llm`` (bool): When ``parser_type="AUTO"``, runs the ML-based ``DocumentRankedLLMSelector`` to choose the best LLM for the input document. Default: ``False``.
   * ``retry_on_fail`` (bool): When ``True`` (default), automatically retries with the alternate parser type / framework on failure.
   * ``return_bboxes`` (bool): If ``True``, attach per-segment bounding boxes (``bboxes`` key on each segment). Default: ``False``.
   * ``bbox_framework`` (str): Framework used for bounding box extraction when ``return_bboxes=True``. One of ``"auto"`` (default — chooses ``paddleocr`` or ``pdfplumber`` based on file content), ``"pdfplumber"``, or ``"paddleocr"``.

   Return value format:
   A dictionary with the following keys. Keys marked *(optional)* are only present in specific configurations; the others are present on the standard parsing path (and may hold an empty string / list / zeroed dict).

   * ``raw``: Full markdown content as a string.
   * ``segments``: List of dictionaries with per-segment ``metadata`` (e.g., ``page``) and ``content``. For PDFs, a segment is a page; for webpages, a segment is a section (heading and its content). When ``return_bboxes=True``, each segment additionally carries a ``bboxes`` key (a list of ``(text, [x0, top, x1, bottom])`` tuples normalized to ``[0, 1]``).
   * ``title``: Title of the document (defaults to the input file's basename).
   * ``url``: Original URL if the input was a URL, otherwise an empty string.
   * ``parent_title``: Title of the parent document when this result was produced by recursive crawling; otherwise an empty string.
   * ``recursive_docs``: List of recursively-parsed sub-documents. Empty unless ``depth > 1``.
   * ``token_usage`` *(optional)*: Dictionary with ``input``, ``output``, ``total``, and ``llm_page_count`` token statistics. Counts are zero when only ``STATIC_PARSE`` ran. **Absent on the HTML/recursive-URL path** — when ``path`` is a URL that is not a supported file-typed URL (e.g., ``.pdf``/image) and ``as_pdf`` is not set, ``parse()`` returns the output of ``recursive_read_html`` directly, which does not include this key.
   * ``parsers_used`` *(optional)*: List of parser names that actually ran, one entry per chunk (e.g., ``["LLM_PARSE", "STATIC_PARSE"]``). **Absent on the HTML/recursive-URL path** for the same reason as ``token_usage``.
   * ``token_cost`` *(optional)*: Estimated cost broken down by token category. Only present when ``api_cost_mapping`` is supplied and contains an entry for the resolved model.
   * ``pdf_path`` *(optional)*: Path to the intermediate PDF generated when ``as_pdf=True``. To keep the file readable after ``parse()`` returns, also pass ``save_dir`` — otherwise the PDF is written inside a temporary directory that is removed on return.


parse_with_schema
^^^^^^^^^^^^^^^^^

.. py:function:: lexoid.api.parse_with_schema(path: str, schema: Union[Dict, Type], api: Optional[str] = None, model: str = "gpt-4o-mini", example_schema: Optional[Dict] = None, alternate_keys: Optional[Dict] = None, fill_single_schema: bool = False, **kwargs) -> List

   Parse a document with an LLM to generate structured output conforming
   to a given schema. The schema can be a plain ``dict``, a Python
   ``dataclass``, or a Pydantic ``BaseModel`` (all are converted to JSON
   Schema internally).

   In the default per-page mode, only PDF and image inputs are accepted
   (each page is rendered to an image and sent to the LLM together with
   the schema prompt). When ``fill_single_schema=True``, the document is
   first parsed with :py:func:`parse` and the resulting markdown is sent
   to the LLM, so the broader set of file types supported by ``parse()``
   (DOCX, HTML, URLs, etc.) becomes available.

   :param path: Path to the file to parse.
   :param schema: ``dict``, ``dataclass``, or Pydantic ``BaseModel`` describing the desired output.
   :param api: LLM API provider. One of ``"gemini"``, ``"openai"``, ``"anthropic"``, ``"mistral"``, ``"huggingface"``, ``"together"``, ``"openrouter"``, ``"fireworks"``, or ``"ollama"``. If not specified, inferred from the model name.
   :param model: LLM model name. Default: ``"gpt-4o-mini"``.
   :param example_schema: Optional example data illustrating the desired filled schema (improves few-shot extraction).
   :param alternate_keys: Optional mapping of alternate key names that may appear in the document — helps the model match synonyms.
   :param fill_single_schema: When ``True``, the entire document is parsed once and the whole content is used to produce a single instance of the schema (rather than one instance per page).
   :param kwargs: Additional keyword arguments (e.g., ``temperature``, ``max_tokens``).

   Additional keyword arguments:

   * ``temperature`` (float): Sampling temperature for LLM generation. Default: ``0.0``.
   * ``max_tokens`` (int): Maximum number of tokens to generate. Default: ``1024``.

   Return value format:

   The function returns a Python list of the JSON values parsed from the model. The exact shape depends on the mode and on the schema:

   * **Default (per-page) mode** — one entry per page, in page order. Each entry is the JSON value the model produced for that page. If the schema describes a single record, expect one ``dict`` per page; if the schema describes multiple records per page (e.g., table rows), expect a ``list`` of ``dict``\s per page. Concretely, indexing follows ``result[page_index][record_index]`` when each page contains multiple records.
   * **``fill_single_schema=True``** — a single-element list whose lone element is the JSON value the model produced for the whole document (typically a single ``dict``).

   Because the shape is driven by the model's output, callers that need to support both single-record and multi-record schemas should normalize the per-page entries themselves (e.g., wrap ``dict`` entries in a one-element ``list``).


parse_to_latex
^^^^^^^^^^^^^^

.. py:function:: lexoid.api.parse_to_latex(path: str, api: Optional[str] = None, model: str = "gpt-4o-mini", **kwargs) -> str

   Convert a document (PDF or image) into a self-contained LaTeX string by
   feeding each rendered page to a vision-capable LLM. The first page emits
   the LaTeX preamble and ``\begin{document}``; the last page closes the
   document with ``\end{document}``.

   :param path: Path to the file to convert.
   :param api: LLM API provider. If not specified, inferred from the model name.
   :param model: LLM model name. Default: ``"gpt-4o-mini"``.
   :param kwargs: Additional keyword arguments forwarded to the LLM call (e.g., ``temperature``, ``max_tokens``).
   :return: The concatenated LaTeX source as a single string.


parse_chunk
^^^^^^^^^^^

.. py:function:: lexoid.api.parse_chunk(path: str, parser_type: ParserType, **kwargs) -> Dict

   Low-level entry point that parses a single file (or PDF chunk) with the
   given parser type. ``parse()`` orchestrates calls to ``parse_chunk`` over
   PDF splits; most users should call ``parse()``. ``parse_chunk`` is
   wrapped by the ``retry_with_different_parser_type`` decorator, which
   implements the ``AUTO`` routing and fallback logic.

   :param path: The file path or URL.
   :param parser_type: The :class:`ParserType` to use.
   :param kwargs: Same keyword arguments accepted by :py:func:`parse`.
   :return: Dictionary containing parsed document data, plus a ``parser_used`` key indicating which parser type actually ran.


Examples
--------

Basic Usage
^^^^^^^^^^^

.. code-block:: python

    from lexoid.api import parse

    # Basic parsing (AUTO is the default parser_type)
    result = parse("document.pdf")

    # Raw text output
    parsed_md = result["raw"]

    # Segmented output with metadata
    parsed_segments = result["segments"]

    # Explicitly select the parser type
    result = parse("document.pdf", parser_type="LLM_PARSE")

LLM-Based Parsing
^^^^^^^^^^^^^^^^^

.. code-block:: python

    # Parse using GPT-4o
    result = parse("document.pdf", parser_type="LLM_PARSE", model="gpt-4o")

    # Parse using Gemini 2.5 Pro
    result = parse("document.pdf", parser_type="LLM_PARSE", model="gemini-2.5-pro")

    # Parse using Claude
    result = parse("document.pdf", parser_type="LLM_PARSE", model="claude-3-5-sonnet-20241022")

    # Parse using Mistral OCR
    result = parse(
        "document.pdf",
        parser_type="LLM_PARSE",
        api_provider="mistral",
        model="mistral-ocr-latest",
    )

    # Parse using a local Ollama model
    result = parse(
        "document.pdf",
        parser_type="LLM_PARSE",
        api_provider="ollama",
        model="gemma4:latest",
        max_processes=1,
    )

    # Local SmolDocling / granite-docling
    result = parse(
        "document.pdf",
        parser_type="LLM_PARSE",
        api_provider="local",
        model="ds4sd/SmolDocling-256M-preview",
    )

    # Local PaddleOCR-VL
    result = parse(
        "document.pdf",
        parser_type="LLM_PARSE",
        api_provider="local",
        model="PaddlePaddle/PaddleOCR-VL",
    )


Static Parsing
^^^^^^^^^^^^^^

.. code-block:: python

    # Parse using pdfplumber (default static framework)
    result = parse("document.pdf", parser_type="STATIC_PARSE", framework="pdfplumber")

    # Parse using pdfminer
    result = parse("document.pdf", parser_type="STATIC_PARSE", framework="pdfminer")

    # OCR with PaddleOCR
    result = parse("scanned.pdf", parser_type="STATIC_PARSE", framework="paddleocr")


AUTO Mode and Routing
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    # Default AUTO with "speed" priority
    result = parse("document.pdf", parser_type="AUTO")

    # Accuracy-first routing (prefers LLM_PARSE)
    result = parse("document.pdf", parser_type="AUTO", router_priority="accuracy")

    # Cost-first routing (tries PaddleOCR before falling back to LLM)
    result = parse(
        "document.pdf",
        parser_type="AUTO",
        router_priority="cost",
        character_threshold=100,
    )

    # Auto-select the best LLM for this document
    result = parse("document.pdf", parser_type="AUTO", autoselect_llm=True)


Bounding Box Extraction
^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    result = parse(
        "document.pdf",
        return_bboxes=True,
        bbox_framework="auto",   # "auto", "pdfplumber", or "paddleocr"
    )
    for segment in result["segments"]:
        for text, bbox in segment.get("bboxes", []):
            print(text, bbox)  # bbox is [x0, top, x1, bottom] normalized to [0, 1]


Parse with Schema
^^^^^^^^^^^^^^^^^

.. code-block:: python

    from lexoid.api import parse_with_schema

    # Plain dict schema (one filled instance per page)
    schema = {
        "Disability Category": "string",
        "Participants": "int",
        "Ballots Completed": "int",
        "Accuracy": ["string"],
        "Time to complete": ["string"],
    }
    result = parse_with_schema(path="inputs/test_1.pdf", schema=schema, model="gpt-4o")

    # Single instance for the whole document
    result = parse_with_schema(
        path="inputs/test_1.pdf",
        schema=schema,
        model="gpt-4o",
        fill_single_schema=True,
    )

    # Pydantic schema with example data and alternate keys
    from pydantic import BaseModel

    class Invoice(BaseModel):
        invoice_number: str
        total: float

    result = parse_with_schema(
        path="inputs/invoice.pdf",
        schema=Invoice,
        model="gpt-4o-mini",
        example_schema={"invoice_number": "INV-001", "total": 199.95},
        alternate_keys={"invoice_number": ["Invoice #", "Invoice No."]},
    )

    # Dataclass schema
    from dataclasses import dataclass

    @dataclass
    class Receipt:
        merchant: str
        amount: float

    result = parse_with_schema(path="receipt.pdf", schema=Receipt)


Parse to LaTeX
^^^^^^^^^^^^^^

.. code-block:: python

    from lexoid.api import parse_to_latex

    latex_source = parse_to_latex("paper.pdf", model="gpt-4o")
    with open("paper.tex", "w") as f:
        f.write(latex_source)


Web Content
^^^^^^^^^^^

.. code-block:: python

    # Parse a webpage
    result = parse("https://example.com")

    # Parse a webpage and the pages linked within it
    result = parse("https://example.com", depth=2)

    # Render the webpage to PDF first, then parse
    result = parse(
        "https://example.com",
        as_pdf=True,
        save_dir="output/",
        save_filename="example.pdf",
    )


Audio Transcription
^^^^^^^^^^^^^^^^^^^

Audio inputs are routed to ``LLM_PARSE`` automatically and require a
Gemini model (currently the only provider supporting audio).

.. code-block:: python

    result = parse("interview.mp3", model="gemini-2.5-flash")
    print(result["raw"])
