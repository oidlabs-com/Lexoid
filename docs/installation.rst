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

    OPENAI_API_KEY=""
    GOOGLE_API_KEY=""

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