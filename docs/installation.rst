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

* ``DEFAULT_LLM`` — overrides the default LLM model. Default: ``gemini-2.5-flash``.
* ``DEFAULT_LOCAL_LM`` — overrides the default local model used by ``parse_with_local_model``. Default: ``ds4sd/SmolDocling-256M-preview``.
* ``DEFAULT_STATIC_FRAMEWORK`` — overrides the default static-parsing framework. Default: ``pdfplumber``.
* ``DEFAULT_MAX_IMAGE_DIMENSION`` — maximum pixel dimension for resizing page/image inputs. Default: ``1000``.
* ``OLLAMA_BASE_URL`` — base URL of the Ollama server. Default: ``http://localhost:11434``.
* ``OLLAMA_TIMEOUT`` — request timeout (seconds) for Ollama. Default: ``120``.

Optional Dependencies
---------------------

Playwright (for web content retrieval)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

To use Playwright for retrieving web content (instead of the bare ``requests``
library), install its browser dependencies after ``pip install lexoid``:

.. code-block:: bash

    playwright install --with-deps --only-shell chromium

LibreOffice (for DOCX to PDF on Linux)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

On Linux, ``.doc``/``.docx`` to PDF conversion uses LibreOffice's
``lowriter`` binary (because ``docx2pdf`` is unsupported on Linux). Install
it from your distribution's package manager, e.g.:

.. code-block:: bash

    sudo apt-get install libreoffice

On macOS/Windows, ``docx2pdf`` is used automatically (requires Microsoft Word
or compatible installation).

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
