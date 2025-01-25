Contributing to Lexoid
======================

Thank you for your interest in contributing to Lexoid! We welcome contributions from the community to make our document parsing library even better.

Getting Started
---------------

1. Fork the repository and clone your fork:

   .. code-block:: bash

       git clone https://github.com/YOUR_USERNAME/lexoid.git
       cd lexoid

2. Set up your development environment:

   .. code-block:: bash

       make dev

3. Activate the virtual environment:

   .. code-block:: bash

       source .venv/bin/activate

Development Setup
-----------------

Environment Variables
^^^^^^^^^^^^^^^^^^^^^

Create a ``.env`` file in the root directory with the following API keys (as needed):

.. code-block:: bash

    GOOGLE_API_KEY=your_google_api_key
    OPENAI_API_KEY=your_openai_api_key
    HUGGINGFACEHUB_API_TOKEN=your_huggingface_token
    TOGETHER_API_KEY=your_together_api_key

Running Tests
^^^^^^^^^^^^^

Run the test suite:

.. code-block:: bash

    python3 -m pytest tests/test_parser.py -v

To see test logs:

.. code-block:: bash

    python3 -m pytest tests/test_parser.py -v -s

Contributing Guidelines
-----------------------

Code Style
^^^^^^^^^^

* We use Python's `PEP 8 <https://www.python.org/dev/peps/pep-0008/>`_ style guide
* If using VS Code, install the `Black Formatter <https://marketplace.visualstudio.com/items?itemName=ms-python.black-formatter>`_ extension
* Use type hints for function parameters and return values

Pull Request Process
^^^^^^^^^^^^^^^^^^^^

1. Create a new branch for your feature or bugfix:

   .. code-block:: bash

       git checkout -b feature-name

2. Make your changes and commit them with clear, descriptive commit messages
3. Add tests for any new functionality
4. Update documentation as needed
5. Push your changes and create a pull request

Areas for Contribution
^^^^^^^^^^^^^^^^^^^^^^

* When starting out, check out the `Issues <https://github.com/oidlabs-com/Lexoid/issues>`_ page and look for tickets tagged with ``good first issue``
* However, don't let the above restrict you. Feel free to have a go at any ticket or suggest any new features!

Testing Your Changes
^^^^^^^^^^^^^^^^^^^^

1. Add test cases to ``tests/test_parser.py`` along with changes if appropriate
2. Test with different file formats and parsing strategies

Documentation
-------------

When adding new features, please:

1. Update the main ``README.md`` if needed
2. Add docstrings to new functions and classes
3. Include example usage in the documentation
4. Update type hints and function signatures in the docs

Reporting Issues
----------------

When reporting bugs, please include:

* A clear description of the problem
* Steps to reproduce
* Expected vs actual behavior
* Sample files (if possible)
* Environment information (Python version, OS, etc.)

Thank you for helping improve Lexoid!