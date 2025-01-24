API Reference
=============

Core Functions
--------------

parse
^^^^^

.. py:function:: lexoid.api.parse(path: str, parser_type: Union[str, ParserType] = "LLM_PARSE", raw: bool = False, pages_per_split: int = 4, max_processes: int = 4, **kwargs) -> Union[List[Dict], str]

   Parse a document using specified strategy.

   :param path: File path or URL to parse
   :param parser_type: Parser type to use ("LLM_PARSE", "STATIC_PARSE", or "AUTO")
   :param raw: If True, returns raw text; if False, returns structured data
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

Examples
--------

Basic Usage
^^^^^^^^^^^

.. code-block:: python

    from lexoid.api import parse

    # Basic parsing
    result = parse("document.pdf")

    # Raw text output
    text = parse("document.pdf", raw=True)

    # Automatic parser selection
    result = parse("document.pdf", parser_type="AUTO")

LLM-Based Parsing
^^^^^^^^^^^^^^^^^

.. code-block:: python

    # Parse using GPT-4
    result = parse("document.pdf", parser_type="LLM_PARSE", model="gpt-4o")

    # Parse using Gemini
    result = parse("document.pdf", model="gemini-1.5-pro")

Web Content
^^^^^^^^^^^

.. code-block:: python

    # Parse webpage
    result = parse("https://example.com")

    # Parse webpage recursively
    result = parse("https://example.com", depth=2)

Return Value Format
-------------------

When ``raw=True``, the function returns a raw text string.

When ``raw=False``, the function returns a list of dictionaries:

.. code-block:: python

    [
        {
            "metadata": {
                "title": "filename",
                "page": page_number
            },
            "content": "parsed_content"
        },
        # ... one dict per page
    ]