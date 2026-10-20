Installation
============

Installing with pip
-------------------

.. code-block:: bash

    pip install lexoid

This installs both the Python library and the ``lexoid`` command-line entry
point. See :doc:`cli` for CLI usage.

Environment Setup
-----------------

To use LLM-based parsing, define the environment variables for the providers
you intend to use (in a shell, ``.env`` file, or your container environment):

.. code-block:: bash

    GOOGLE_API_KEY=your_google_api_key            # Gemini
    OPENAI_API_KEY=your_openai_api_key            # OpenAI / GPT
    ANTHROPIC_API_KEY=your_anthropic_api_key      # Claude
    MISTRAL_API_KEY=your_mistral_api_key          # Mistral OCR
    HUGGINGFACEHUB_API_TOKEN=your_huggingface_token
    TOGETHER_API_KEY=your_together_api_key
    OPENROUTER_API_KEY=your_openrouter_api_key
    FIREWORKS_API_KEY=your_fireworks_api_key

Only the providers you actually use require keys. Local backends (Ollama,
SmolDocling/granite-docling, PaddleOCR-VL) do not require an API key.

Additional environment variables
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

* ``DEFAULT_LLM`` — overrides the default LLM model and thinking level. Defaults to ``gemini-3.5-flash-lite`` with ``medium`` thinking. Set a plain model name or a JSON object such as:

    .. code-block:: json

         {"model":"gemini-3.5-flash-lite","thinking_level":"medium"}
* ``DEFAULT_LOCAL_LM`` — overrides the default local model used by ``parse_with_local_model``. Default: ``ds4sd/SmolDocling-256M-preview``.
* ``DEFAULT_STATIC_FRAMEWORK`` — overrides the default static-parsing framework. Default: ``pdfplumber``.
* ``DEFAULT_MAX_IMAGE_DIMENSION`` — maximum pixel dimension for resizing page/image inputs. Default: ``1000``.
* ``OLLAMA_BASE_URL`` — base URL of the Ollama server. Default: ``http://localhost:11434``.
* ``OLLAMA_TIMEOUT`` — request timeout (seconds) for Ollama. Default: ``120``.

Optional Dependencies
---------------------

Parse web pages and render PDFs with ``parse()``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use ``parse(url)`` to retrieve and parse webpage content. To render a page to
PDF before parsing it, pass ``as_pdf=True``; set ``save_dir`` if you want to
keep the generated PDF after ``parse()`` returns. The Python package includes
Playwright, but Chromium's browser binaries must also be installed:

.. code-block:: bash

    playwright install --with-deps --only-shell chromium

Web Operator: for autonomous browser tasks
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Use the web operator agent ``browse()`` to navigate websites and complete
research tasks with evidence-backed results. This is separate from
``parse()``: ``browse()`` does not download a URL for PDF conversion. Install
the agent-framework extra and Patchright's browser binaries:

.. code-block:: bash

    pip install "lexoid[browse]"
    patchright install --with-deps chromium

LibreOffice (for DOCX to PDF)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Word-document to PDF conversion defaults to LibreOffice on all platforms.
Lexoid discovers ``soffice`` or ``lowriter`` on ``PATH``, then checks standard
macOS app-bundle and Windows Program Files locations. Install LibreOffice
separately; it is not installed by default outside of docker:

.. code-block:: bash

    sudo apt-get install libreoffice

On macOS:

.. code-block:: bash

    brew install --cask libreoffice

On Windows, install LibreOffice from https://www.libreoffice.org/.

For native Word rendering on macOS/Windows, explicitly pass
``docx_pdf_engine="word"`` to ``parse()``. This uses ``docx2pdf`` and requires
Microsoft Word installed in a standard location (or on ``PATH`` on Windows)
and permission to automate Word. Static DOCX parsing does not require either
application. Unlike earlier releases, Word is no longer selected automatically
on macOS/Windows. LibreOffice can change layout and pagination compared with
Word; engines never silently fall back to each other.

Ollama (for local LLM parsing)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Install `Ollama <https://ollama.com>`_, pull a vision-capable model, and
keep the server running:

.. code-block:: bash

    ollama pull gemma4
    ollama serve

Then call ``parse(..., api_provider="ollama", model="gemma4:latest", max_processes=1)``.
Lexoid forces ``max_processes=1`` for Ollama-backed parsing to avoid local
multiprocess contention.

Building from Source
--------------------

To build the ``.whl`` file:

.. code-block:: bash

    make build

Local Development Setup
-----------------------

To install dependencies:

.. code-block:: bash

    make install

Or, to install with dev-dependencies:

.. code-block:: bash

    make dev

To activate virtual environment:

.. code-block:: bash

    source .venv/bin/activate
