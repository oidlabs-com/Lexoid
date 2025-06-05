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
   * ``save_dir`` (str): Directory to save intermediate PDFs
   * ``page_nums`` (List[int]): List of page numbers to parse
   * ``api_cost_mapping`` (Union[dict, str]): Dictionary containing API cost details or the string path to a JSON file containing
     the cost details. Sample file available at ``tests/api_cost_mapping.json``
   * ``router_priority`` (str): What the routing strategy should prioritize. Options are ``"speed"`` and ``"accuracy"``. The router directs a file to either ``"STATIC_PARSE"`` or ``"LLM_PARSE"`` based on its type and the selected priority. If priority is "accuracy", it prefers LLM_PARSE unless the PDF has no images but contains embedded/hidden hyperlinks, in which case it uses ``STATIC_PARSE`` (because LLMs currently fail to parse hidden hyperlinks). If priority is "speed", it uses ``STATIC_PARSE`` for documents without images and ``LLM_PARSE`` for documents with images.
   * ``api_provider`` (str): The API provider to use for LLM parsing. Options are ``openai``, ``huggingface``, ``together``, ``openrouter``, and ``fireworks``. This parameter is only relevant when using LLM parsing.

   Return value format:
   A dictionary containing a subset or all of the following keys:
   
   *  ``raw``: Full markdown content as string
   * ``segments``: List of dictionaries with metadata and content of each segment. For PDFs, a segment denotes a page. For webpages, a segment denotes a section (a heading and its content).
   * ``title``: Title of the document
   * ``url``: URL if applicable
   * ``parent_title``: Title of parent doc if recursively parsed
   * ``recursive_docs``: List of dictionaries for recursively parsed documents
   * ``token_usage``: Token usage statistics
   * ``pdf_path``: Path to the intermediate PDF generated when ``as_pdf`` is enabled and the kwarg ``save_dir`` is specified.


parse_with_schema
^^^^^^^^^^^^^^^^^

.. py:function:: lexoid.api.parse_with_schema(path: str, schema: Dict, api: str = "openai", model: str = "gpt-4o-mini", **kwargs) -> List[List[Dict]]

   Parses a PDF using an LLM to generate structured output conforming to a given JSON schema.

   :param path: Path to the PDF file.
   :param schema: JSON schema to which the parsed output should conform.
   :param api: LLM API provider to use (``"openai"``, ``"huggingface"``, ``"together"``, ``"openrouter"``, or ``"fireworks"``).
   :param model: LLM model name.
   :param kwargs: Additional keyword arguments passed to the LLM (e.g., ``temperature``, ``max_tokens``).
   :return: A list where each element represents a page, which in turn contains a list of dictionaries conforming to the provided schema.

   Additional keyword arguments:

   * ``temperature`` (float): Sampling temperature for LLM generation.
   * ``max_tokens`` (int): Maximum number of tokens to generate.

   Return value format:
   A list of pages, where each page is represented as a list of dictionaries. Each dictionary conforms to the structure defined by the input ``schema``.


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


Parse with Schema
^^^^^^^^^^^^^^^^^

.. code-block:: python

    from lexoid.api import parse_with_schema

    sample_schema = [
        {
            "Disability Category": "string",
            "Participants": "int",
            "Ballots Completed": "int",
            "Ballots Incomplete/Terminated": "int",
            "Accuracy": ["string"],
            "Time to complete": ["string"]
        }
    ]

    pdf_path = "inputs/test_1.pdf"
    result = parse_with_schema(path=pdf_path, schema=sample_schema, model="gpt-4o") 

Web Content
^^^^^^^^^^^

.. code-block:: python

    # Parse webpage
    result = parse("https://example.com")

    # Parse webpage and the pages linked within the page
    result = parse("https://example.com", depth=2)