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

The CLI exposes four sub-commands:

* ``lexoid parse`` — Convert a document into markdown (or JSON with metadata).
* ``lexoid schema`` — Extract structured data conforming to a JSON schema.
* ``lexoid latex`` — Convert a document into LaTeX.
* ``lexoid browse`` — Run an evidence-grounded web-operator task.

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
* ``--model, -m``: LLM model name. Default: ``gemini-3.5-flash-lite`` (thinking: medium).
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

``lexoid browse``
^^^^^^^^^^^^^^^^^

Run an evidence-grounded web-operator task from a natural-language query.

.. code-block:: bash

    lexoid browse "Go to https://example.com/ and summarize the pricing page" --model gpt-6.2-sol
    lexoid browse "Find recent filings" --model-config roles.json --format json --output result.json
    lexoid browse "Find recent filings" --headed --cdp-url http://localhost:9222

The model config file accepts the same role mapping as the Python API. A ``default``
entry applies to every role; a role-specific entry overrides it. If ``assessor`` is
omitted, it uses the ``extractor`` configuration when present, otherwise ``default``.
Reasoning settings and model options are provider- and model-specific; consult the
provider documentation for supported fields and values. For OpenAI, see the
`reasoning guide <https://developers.openai.com/api/docs/guides/reasoning>`_ and
`Responses API reference <https://developers.openai.com/api/reference/resources/responses/methods/create>`_.
For example:

.. code-block:: json

        {
            "planner": {
                "model": "gpt-6-luna",
                "reasoning": {"effort": "high", "summary": "detailed"},
                "options": {"verbosity": "high"}
            },
            "navigator": {
                "model": "gpt-6.2-sol",
                "reasoning": {"effort": "medium"},
                "options": {"verbosity": "high"}
            },
            "assessor": {
                "model": "gpt-6.2-sol",
                "reasoning": {"effort": "medium"}
            },
            "extractor": {
                "model": "gpt-6-luna",
                "reasoning": {"effort": "high"}
            },
            "synthesizer": {
                "model": "gpt-6-luna",
                "reasoning": {"effort": "medium"}
            }
        }

Options:

* ``QUERY`` (required): Natural-language web-operator query.
* ``--output, -o``: Path to output file (default: stdout).
* ``--format``: ``markdown`` (default; grounded answer) or ``json`` (full ``BrowseResult``).
* ``--model, -m``: Default LLM model for all browse roles.
* ``--model-config``: Path to a JSON file with per-role models, reasoning, and options (see example above). Unknown keys are rejected. Cannot be combined with ``--model``.
* ``--cdp-url``: Attach to an existing browser over Chrome DevTools Protocol.
* ``--user-data-dir``: Dedicated persistent browser profile directory.
* ``--channel``: Browser distribution channel (e.g. ``chrome``, ``chromium``).
* ``--headless / --headed``: Run headless (default) or visible browser.
* ``--mute-audio / --no-mute-audio``: Mute audio in locally launched browsers (default: muted).
* ``--max-steps``: Maximum total browser actions (default: ``50``).
* ``--max-pages``: Maximum pages to capture (default: ``5``).
* ``--timeout-ms``: Per-operation timeout in milliseconds (default: ``60000``).
* ``--verification-timeout-ms``: Maximum wait for a person to complete a verification challenge (default: ``120000``; range: ``1000``–``300000``). On timeout, the navigator may use a permitted alternative or report the site as blocked.
* ``--default-search-url``: Starting search provider URL for open-ended queries.
* ``--verbose, -v``: Enable detailed logging.

API keys
--------

LLM commands require the relevant environment variable to be set
(see :doc:`installation`). The CLI checks for the required key based on
the resolved provider and raises a clear error if it is missing.
