Benchmark Report
================

Overview
--------

This benchmark evaluates the performance of various Large Language Models (LLMs) and parsing strategies in extracting and parsing document content using Lexoid.

Each approach is evaluated based on a comparison between the parsed content and the manually created ground truths of several documents, with a similarity metric indicating the accuracy of the parsing process.

Similarity Metric
^^^^^^^^^^^^^^^^^

The similarity metric is calculated using the following steps (see `calculate_similarity()` in `lexoid/core/utils.py` for the implementation).

1. Markdown Conversion
   Both parsed and ground truth documents are converted to HTML, standardizing their format across structural elements like tables and lists.

2. HTML Tag Removal
   All HTML markup is stripped away, leaving only the pure textual content. This ensures the comparison focuses on the actual text rather than formatting.

3. Sequence Matching
   Python's ``SequenceMatcher`` compares the extracted text sequences, calculating a similarity ratio between 0 and 1 that reflects content preservation and accuracy.

Running the Benchmarks
----------------------

Setup Environment Variables
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Create a ``.env`` file with the necessary API keys:

.. code-block:: bash

    OPENAI_API_KEY=your_openai_key
    GOOGLE_API_KEY=your_google_key
    HUGGINGFACEHUB_API_TOKEN=your_huggingface_token
    TOGETHER_API_KEY=your_together_api_key

Running the Benchmark Script
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: bash

    # Clone the repository
    git clone https://github.com/oidlabs-com/lexoid.git
    cd lexoid

    # Install dependencies
    pip install -r requirements.txt

    # Run benchmarks
    python tests/benchmark.py

Customizing Benchmarks
^^^^^^^^^^^^^^^^^^^^^^

You can modify the ``test_attributes`` list in the ``main()`` function to test different configurations:

* ``parser_type``: Switch between LLM and static parsing
* ``model``: Test different LLM models
* ``framework``: Test different static parsing frameworks
* ``pages_per_split``: Adjust document chunking
* ``max_threads``: Control parallel processing

Benchmark Results
-----------------

Here are the detailed parsing performance results for various models:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Rank
     - Model
     - Mean Similarity
     - Std. Dev.
     - Time (s)
     - Cost ($)
   * - 1
     - gemini-2.0-flash
     - 0.829
     - 0.102
     - 7.41
     - 0.000480
   * - 2
     - gemini-2.0-flash-001
     - 0.814
     - 0.176
     - 6.85
     - 0.000421
   * - 3
     - gemini-1.5-flash
     - 0.797
     - 0.143
     - 9.54
     - 0.000238
   * - 4
     - gemini-2.0-pro-exp
     - 0.764
     - 0.227
     - 11.95
     - TBA
   * - 5
     - gemini-2.0-flash-thinking-exp
     - 0.746
     - 0.266
     - 10.46
     - TBA
   * - 6
     - gemini-1.5-pro
     - 0.732
     - 0.265
     - 11.44
     - 0.003332
   * - 7
     - gpt-4o
     - 0.687
     - 0.247
     - 10.16
     - 0.004736
   * - 8
     - gpt-4o-mini
     - 0.642
     - 0.213
     - 9.71
     - 0.000275
   * - 9
     - google/gemma-3-27b-it
     - 0.628
     - 0.299
     - 18.79
     - 0.000096
   * - 10
     - gemini-1.5-flash-8b
     - 0.551
     - 0.223
     - 3.91
     - 0.000055
   * - 11
     - Llama-Vision-Free (via Together AI)
     - 0.531
     - 0.198
     - 6.93
     - 0
   * - 12
     - Llama-3.2-11B-Vision-Instruct-Turbo (via Together AI)
     - 0.524
     - 0.192
     - 3.68
     - 0.000060
   * - 13
     - qwen/qwen-2.5-vl-7b-instruct
     - 0.482
     - 0.209
     - 11.53
     - 0.000052
   * - 14
     - Llama-3.2-90B-Vision-Instruct-Turbo (via Together AI)
     - 0.461
     - 0.306
     - 19.26
     - 0.000426
   * - 15
     - Llama-3.2-11B-Vision-Instruct (via Hugging Face)
     - 0.451
     - 0.257
     - 4.54
     - 0