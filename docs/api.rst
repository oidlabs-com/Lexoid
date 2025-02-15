API Reference
=============

Core Function
-------------

parse
^^^^^

.. py:function:: lexoid.api.parse(path: str, parser_type: Union[str, ParserType] = "LLM_PARSE", pages_per_split: int = 4, max_processes: int = 4, **kwargs) -> Dict

   Parse a document using specified strategy.

   :param path: File path or URL to parse
   :param parser_type: Parser type to use ("LLM_PARSE", "STATIC_PARSE", or "AUTO")
   :param pages_per_split: Number of pages per chunk for processing
   :param max_processes: Maximum number of parallel processes
   :param kwargs: Additional keyword arguments
   :return: List of dictionaries containing page metadata and content, or raw text string

   Additional keyword arguments:

   * ``model`` (str): LLM model to use
   * ``framework`` (str): Static parsing framework
   * ``temperature`` (float): Temperature for LLM generation
   * ``depth`` (int): Depth for recursive URL parsing
   * ``as_pdf`` (bool): Convert input to PDF before processing
   * ``verbose`` (bool): Enable verbose logging
   * ``x_tolerance`` (int): X-axis tolerance for text extraction
   * ``y_tolerance`` (int): Y-axis tolerance for text extraction

   Return value format:
   A dictionary containing a subset or all of the following keys:
   *  ``raw``: Full markdown content as string
   * ``segments``: List of dictionaries with metadata and content
   * ``title``: Title of the document
   * ``url``: URL if applicable
   * ``parent_title``: Title of parent doc if recursively parsed
   * ``recursive_docs``: List of dictionaries for recursively parsed documents
   * ``token_usage``: Token usage statistics
   * ``pdf_path``: Path to the intermediate PDF generated when ``as_pdf`` is enabled and the kwarg ``save_dir`` is specified.

Examples
--------

Basic Usage
^^^^^^^^^^^

.. code-block:: python

    from lexoid.api import parse

    # Basic parsing
    result = parse("document.pdf")

    # Raw text output
    parsed_md = result["raw"]

    # Segmented output with metadata
    parsed_segments = result["segments"]

    # Automatic parser selection
    result = parse("document.pdf", parser_type="AUTO")

LLM-Based Parsing
^^^^^^^^^^^^^^^^^

.. code-block:: python

    # Parse using GPT-4o
    result = parse("document.pdf", parser_type="LLM_PARSE", model="gpt-4o")

    # Parse using Gemini 1.5 Pro
    result = parse("document.pdf", parser_type="LLM_PARSE", model="gemini-1.5-pro")


Static Parsing
^^^^^^^^^^^^^^

.. code-block:: python

    # Parse using PDFPlumber
    result = parse("document.pdf", parser_type="STATIC_PARSE", model="pdfplumber")

    # Parse using PDFMiner
    result = parse("document.pdf", parser_type="STATIC_PARSE", model="pdfminer")

Web Content
^^^^^^^^^^^

.. code-block:: python

    # Parse webpage
    result = parse("https://example.com")

    # Parse webpage and the pages linked within the page
    result = parse("https://example.com", depth=2)