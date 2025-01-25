Installation
============

Installing with pip
-------------------

.. code-block:: bash

    pip install lexoid

Environment Setup
-----------------

To use LLM-based parsing, define the following environment variables or create a ``.env`` file with the following definitions:

.. code-block:: bash

    GOOGLE_API_KEY=your_google_api_key
    OPENAI_API_KEY=your_openai_api_key
    HUGGINGFACEHUB_API_TOKEN=your_huggingface_token
    TOGETHER_API_KEY=your_together_api_key

Optional Dependencies
---------------------

To use ``Playwright`` for retrieving web content (instead of the ``requests`` library):

.. code-block:: bash

    playwright install --with-deps --only-shell chromium

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