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
     - AUTO
     - 0.906
     - 0.112
     - 9.56
     - 0.00068
   * - 2
     - gemini-2.0-flash
     - 0.897
     - 0.126
     - 9.91
     - 0.00078
   * - 3
     - gemini-2.5-flash
     - 0.895
     - 0.148
     - 54.10
     - 0.01051
   * - 4
     - gemini-1.5-pro
     - 0.868
     - 0.283
     - 15.03
     - 0.00637
   * - 5
     - gemini-1.5-flash
     - 0.864
     - 0.194
     - 15.47
     - 0.00044
   * - 6
     - claude-3-5-sonnet-20241022
     - 0.851
     - 0.209
     - 15.99
     - 0.01758
   * - 7
     - gemini-2.5-pro
     - 0.849
     - 0.298
     - 101.95
     - 0.01859
   * - 8
     - claude-sonnet-4-20250514
     - 0.804
     - 0.190
     - 19.27
     - 0.02071
   * - 9
     - claude-opus-4-20250514
     - 0.772
     - 0.238
     - 20.03
     - 0.09207
   * - 10
     - accounts/fireworks/models/llama4-maverick-instruct-basic
     - 0.768
     - 0.234
     - 12.12
     - 0.00150
   * - 11
     - gpt-4o
     - 0.748
     - 0.284
     - 26.80
     - 0.01478
   * - 12
     - gpt-4o-mini
     - 0.733
     - 0.231
     - 18.18
     - 0.00650
   * - 13
     - gpt-4.1-mini
     - 0.723
     - 0.269
     - 20.91
     - 0.00351
   * - 14
     - google/gemma-3-27b-it
     - 0.681
     - 0.334
     - 19.41
     - 0.00027
   * - 15
     - gpt-4.1
     - 0.650
     - 0.342
     - 33.72
     - 0.01443
   * - 16
     - claude-3-7-sonnet-20250219
     - 0.633
     - 0.369
     - 14.24
     - 0.01763
   * - 17
     - microsoft/phi-4-multimodal-instruct
     - 0.622
     - 0.320
     - 13.15
     - 0.00050
   * - 18
     - qwen/qwen-2.5-vl-7b-instruct
     - 0.559
     - 0.348
     - 17.71
     - 0.00086
   * - 19
     - meta-llama/Llama-3.2-90B-Vision-Instruct-Turbo
     - 0.546
     - 0.239
     - 29.26
     - 0.01103
    