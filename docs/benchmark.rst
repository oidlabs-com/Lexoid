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
     - gemini-2.5-pro
     - 0.907 (±0.151)
     - 0.973 (±0.053)
     - 22.23
     - 0.02305
   * - 2
     - AUTO
     - 0.905 (±0.111)
     - 0.967 (±0.051)
     - 10.31
     - 0.00068
   * - 3
     - gemini-2.5-flash
     - 0.902 (±0.151)
     - 0.984 (±0.030)
     - 48.67
     - 0.01051
   * - 4
     - gemini-2.0-flash
     - 0.900 (±0.127)
     - 0.971 (±0.040)
     - 12.43
     - 0.00081
   * - 5
     - claude-3-5-sonnet-20241022
     - 0.873 (±0.195)
     - 0.937 (±0.095)
     - 16.86
     - 0.01779
   * - 6
     - gemini-1.5-flash
     - 0.868 (±0.198)
     - 0.965 (±0.041)
     - 17.19
     - 0.00044
   * - 7
     - claude-sonnet-4-20250514
     - 0.814 (±0.197)
     - 0.903 (±0.150)
     - 21.99
     - 0.02045
   * - 8
     - accounts/fireworks/models/llama4-scout-instruct-basic
     - 0.804 (±0.242)
     - 0.931 (±0.067)
     - 9.76
     - 0.00087
   * - 9
     - claude-opus-4-20250514
     - 0.798 (±0.230)
     - 0.878 (±0.159)
     - 21.01
     - 0.09233
   * - 10
     - gpt-4o
     - 0.796 (±0.264)
     - 0.898 (±0.117)
     - 28.23
     - 0.01473
   * - 11
     - accounts/fireworks/models/llama4-maverick-instruct-basic
     - 0.792 (±0.206)
     - 0.914 (±0.128)
     - 10.71
     - 0.00149
   * - 12
     - gemini-1.5-pro
     - 0.782 (±0.341)
     - 0.833 (±0.252)
     - 27.13
     - 0.01275
   * - 13
     - gpt-4.1-mini
     - 0.767 (±0.243)
     - 0.807 (±0.197)
     - 22.64
     - 0.00352
   * - 14
     - gpt-4o-mini
     - 0.727 (±0.245)
     - 0.832 (±0.136)
     - 17.20
     - 0.00650
   * - 15
     - meta-llama/Llama-Vision-Free
     - 0.682 (±0.223)
     - 0.847 (±0.135)
     - 12.31
     - 0.00000
   * - 16
     - meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo
     - 0.677 (±0.226)
     - 0.850 (±0.134)
     - 7.23
     - 0.00015
   * - 17
     - microsoft/phi-4-multimodal-instruct
     - 0.665 (±0.258)
     - 0.800 (±0.217)
     - 10.96
     - 0.00049
   * - 18
     - claude-3-7-sonnet-20250219
     - 0.634 (±0.395)
     - 0.752 (±0.298)
     - 70.10
     - 0.01775
   * - 19
     - google/gemma-3-27b-it
     - 0.624 (±0.357)
     - 0.750 (±0.327)
     - 24.51
     - 0.00020
   * - 20
     - gpt-4.1
     - 0.622 (±0.314)
     - 0.782 (±0.191)
     - 34.66
     - 0.01461
   * - 21
     - meta-llama/Llama-3.2-90B-Vision-Instruct-Turbo
     - 0.559 (±0.233)
     - 0.822 (±0.119)
     - 27.74
     - 0.01102
   * - 22
     - qwen/qwen-2.5-vl-7b-instruct
     - 0.469 (±0.364)
     - 0.617 (±0.441)
     - 13.23
     - 0.00060
    