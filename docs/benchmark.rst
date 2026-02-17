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

3. Whitespace and Punctuation Normalization
   Extra whitespace and punctuation are removed from both the parsed and ground truth texts. Therefore, the comparison is purely based on the sequence of characters/words, ignoring any formatting differences.

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

We evaluate the performance of various models based on their parsing accuracy and efficiency. The results are summarized in the following table, which includes the SequenceMatcher similarity, TFIDF similarity, time taken for parsing, and cost associated with each model.

* **SequenceMatcher Similarity**: Indicates how closely the sequence of characters in the parsed content matches the ground truth. This mainly evaluates the text similarity with a penalty for structural differences.
* **TFIDF Similarity**: Measures the similarity based on frequency of terms in the parsed content compared to the ground truth. This purely evaluates text similarity.
* **Time (s)**: Average time to parse each document.
* **Cost ($)**: Average cost to parse each document, calculated based on the API usage of the model.

Here are the detailed parsing performance results for various models, sorted by SequenceMatcher similarity:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Rank
     - Model
     - SequenceMatcher Similarity
     - TFIDF Similarity.
     - Time (s)
     - Cost ($)
   * - 1
     - gemini-3-pro-preview
     - 0.917 (±0.127)
     - 0.943 (±0.159)
     - 46.92
     - 0.06288
   * - 2
     - AUTO (with auto-selected model)
     - 0.899 (±0.131)
     - 0.960 (±0.066)
     - 21.17
     - 0.00066
   * - 3
     - AUTO
     - 0.895 (±0.112)
     - 0.973 (±0.046)
     - 9.29
     - 0.00063
   * - 4
     - gpt-5.2
     - 0.890 (±0.193)
     - 0.975 (±0.036)
     - 33.32
     - 0.03959
   * - 5
     - gemini-2.5-flash
     - 0.886 (±0.164)
     - 0.986 (±0.027)
     - 52.55
     - 0.01226
   * - 6
     - mistral-ocr-latest
     - 0.882 (±0.106)
     - 0.932 (±0.091)
     - 5.75
     - 0.00121
   * - 7
     - gemini-2.5-pro
     - 0.876 (±0.195)
     - 0.976 (±0.049)
     - 22.65
     - 0.02408
   * - 8
     - gemini-2.0-flash
     - 0.875 (±0.148)
     - 0.977 (±0.037)
     - 11.96
     - 0.00079
   * - 9
     - claude-3-5-sonnet-20241022
     - 0.858 (±0.184)
     - 0.930 (±0.098)
     - 17.32
     - 0.01804
   * - 10
     - gemini-1.5-flash
     - 0.842 (±0.214)
     - 0.969 (±0.037)
     - 15.58
     - 0.00043
   * - 11
     - gpt-5-mini
     - 0.819 (±0.201)
     - 0.917 (±0.104)
     - 52.84
     - 0.00811
   * - 12
     - gpt-5
     - 0.807 (±0.215)
     - 0.919 (±0.088)
     - 98.12
     - 0.05505
   * - 13
     - claude-sonnet-4-20250514
     - 0.801 (±0.188)
     - 0.905 (±0.136)
     - 22.02
     - 0.02056
   * - 14
     - claude-opus-4-20250514
     - 0.789 (±0.220)
     - 0.886 (±0.148)
     - 29.55
     - 0.09513
   * - 15
     - accounts/fireworks/models/llama4-maverick-instruct-basic
     - 0.772 (±0.203)
     - 0.930 (±0.117)
     - 16.02
     - 0.00147
   * - 16
     - gemini-1.5-pro
     - 0.767 (±0.309)
     - 0.865 (±0.230)
     - 24.77
     - 0.01139
   * - 17
     - gemini-3-flash-preview
     - 0.766 (±0.293)
     - 0.858 (±0.210)
     - 39.38
     - 0.00969
   * - 18
     - gpt-4.1-mini
     - 0.754 (±0.249)
     - 0.803 (±0.193)
     - 23.28
     - 0.00347
   * - 19
     - accounts/fireworks/models/llama4-scout-instruct-basic
     - 0.754 (±0.243)
     - 0.942 (±0.063)
     - 13.36
     - 0.00087
   * - 20
     - gpt-4o
     - 0.752 (±0.269)
     - 0.896 (±0.123)
     - 28.87
     - 0.01469
   * - 21
     - gpt-4o-mini
     - 0.728 (±0.241)
     - 0.850 (±0.128)
     - 18.96
     - 0.00609
   * - 22
     - claude-3-7-sonnet-20250219
     - 0.646 (±0.397)
     - 0.758 (±0.297)
     - 57.96
     - 0.01730
   * - 23
     - gpt-4.1
     - 0.637 (±0.301)
     - 0.787 (±0.185)
     - 35.37
     - 0.01498
   * - 24
     - google/gemma-3-27b-it
     - 0.604 (±0.342)
     - 0.788 (±0.297)
     - 23.16
     - 0.00020
   * - 25
     - ds4sd/SmolDocling-256M-preview
     - 0.603 (±0.292)
     - 0.705 (±0.262)
     - 507.74
     - 0.00000
   * - 26
     - microsoft/phi-4-multimodal-instruct
     - 0.589 (±0.273)
     - 0.820 (±0.197)
     - 14.00
     - 0.00045
   * - 27
     - qwen/qwen-2.5-vl-7b-instruct
     - 0.498 (±0.378)
     - 0.630 (±0.445)
     - 14.73
     - 0.00056
    