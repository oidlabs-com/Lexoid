Welcome to Lexoid's Documentation
=================================

Lexoid is an efficient document parsing library that supports both LLM-based and non-LLM-based (static) parsing of PDFs, images, web pages, office documents, and audio files.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   installation
   api
   cli
   contributing
   benchmark

Key Features
------------

* Multiple parsing strategies (LLM-based and static parsing)
* Automatic parsing strategy selection (``AUTO`` mode) with optional ML-based LLM auto-selection
* Routing priorities: ``speed``, ``accuracy``, and ``cost``
* Support for many LLM providers (OpenAI, Google Gemini, Anthropic, Mistral, Hugging Face, Together AI, OpenRouter, Fireworks)
* Local LLM inference via Ollama, SmolDocling/granite-docling, and PaddleOCR-VL (no API key required)
* Schema-constrained extraction (``parse_with_schema``) accepting ``dict``, ``dataclass``, or Pydantic ``BaseModel``
* LaTeX conversion (``parse_to_latex``)
* Audio transcription to markdown (via Gemini)
* Multi-format input: PDF, images (PNG/JPG/TIFF/BMP/GIF), HTML, DOCX, XLSX, PPTX, CSV, TXT, audio, and URLs
* Recursive URL parsing
* Table detection and markdown conversion
* Hyperlink detection and preservation
* Reference highlighting and bounding box extraction (``return_bboxes``)
* Parallel processing via multiprocessing
* Command-line interface (``lexoid`` / ``python -m lexoid``)
* Permissive Apache 2.0 license

Supported API Providers
-----------------------

* Google (Gemini)
* OpenAI
* Anthropic (Claude)
* Mistral (OCR models)
* Hugging Face
* Together AI
* OpenRouter
* Fireworks
* Ollama (local inference)
* Local models (SmolDocling/granite-docling, PaddleOCR-VL)

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
