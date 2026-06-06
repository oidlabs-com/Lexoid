Command-Line Interface
======================

Lexoid ships with a ``lexoid`` command (installed as a console script) for
parsing documents without writing Python code. You can also invoke it via
the module form ``python -m lexoid``.

.. code-block:: bash

    lexoid --help
    python -m lexoid --help

Commands
--------

The CLI exposes three sub-commands:

* ``lexoid parse`` — Convert a document into markdown (or JSON with metadata).
* ``lexoid schema`` — Extract structured data conforming to a JSON schema.
* ``lexoid latex`` — Convert a document into LaTeX.

Common options
^^^^^^^^^^^^^^

Available across all sub-commands:

* ``--input, -i`` (required): Path to an input file (PDF, image, HTML, DOCX, XLSX, PPTX, CSV, TXT, audio) or a URL (``http://``, ``https://``).
* ``--output, -o``: Path to an output file. If omitted, output goes to stdout (clean — status messages are written to stderr so output can be piped).
* ``--verbose, -v``: Enable detailed logging.

``lexoid parse``
^^^^^^^^^^^^^^^^

.. code-block:: bash

    lexoid parse --input document.pdf
    lexoid parse --input document.pdf --output output.md
    lexoid parse --input document.pdf --format json --output result.json
    lexoid parse --input document.pdf --parser-type STATIC_PARSE
    lexoid parse --input document.pdf --model gpt-4o

Options:

* ``--parser-type, -p``: ``AUTO`` (default), ``LLM_PARSE``, or ``STATIC_PARSE``.
* ``--model, -m``: LLM model name. Default: ``gemini-2.5-flash``.
* ``--pages-per-split``: Pages per chunk. Default: ``4``.
* ``--max-processes``: Parallel processes. Default: ``4``.
* ``--framework``: Static parsing framework — ``pdfplumber`` or ``paddleocr``.
* ``--format``: ``markdown`` (default; raw markdown text) or ``json`` (full result with segments, metadata, and token usage).
* ``--api``: API provider override. One of ``openai``, ``gemini``, ``anthropic``, ``mistral``, ``together``, ``huggingface``, ``openrouter``, ``fireworks``, ``ollama``. If omitted, inferred from the model name.

``lexoid schema``
^^^^^^^^^^^^^^^^^

Extract structured data using a JSON schema. The schema can be passed as a
file path or as an inline JSON string.

.. code-block:: bash

    # Inline schema
    lexoid schema \
      --input document.pdf \
      --schema '{"type": "object", "properties": {"title": {"type": "string"}}}' \
      --output result.json

    # Schema from file
    lexoid schema --input document.pdf --schema schema.json --output result.json

    # Specify model and API explicitly
    lexoid schema --input document.pdf --schema schema.json --api openai --model gpt-4o

Options:

* ``--schema, -s`` (required): JSON schema — file path or inline JSON.
* ``--model, -m``: LLM model. Default: ``gpt-4o-mini``.
* ``--api``: API provider (auto-detected from model name if omitted).
* ``--example-schema``: Example data (JSON string or file path) illustrating a filled schema.
* ``--fill-single-schema``: Produce a single schema instance for the whole document instead of one per page.

``lexoid latex``
^^^^^^^^^^^^^^^^

.. code-block:: bash

    lexoid latex --input document.pdf
    lexoid latex --input document.pdf --output output.tex
    lexoid latex --input document.pdf --model gpt-4o

Options:

* ``--model, -m``: LLM model. Default: ``gpt-4o-mini``.
* ``--api``: API provider (auto-detected from model name if omitted).

API keys
--------

LLM commands require the relevant environment variable to be set
(see :doc:`installation`). The CLI checks for the required key based on
the resolved provider and raises a clear error if it is missing.
