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
     - AUTO (with auto-selected model)
     - 0.893 (±0.135)
     - 0.957 (±0.068)
     - 22.25
     - 0.00066
   * - 2
     - AUTO
     - 0.889 (±0.115)
     - 0.971 (±0.048)
     - 9.29
     - 0.00062
   * - 3
     - mistral-ocr-latest
     - 0.882 (±0.111)
     - 0.927 (±0.094)
     - 5.64
     - 0.00123
   * - 4
     - gemini-2.5-flash
     - 0.877 (±0.169)
     - 0.986 (±0.028)
     - 52.28
     - 0.01056
   * - 5
     - gemini-2.5-pro
     - 0.876 (±0.195)
     - 0.976 (±0.049)
     - 22.65
     - 0.02408
   * - 6
     - gemini-2.0-flash
     - 0.867 (±0.152)
     - 0.975 (±0.038)
     - 11.97
     - 0.00079
   * - 7
     - claude-3-5-sonnet-20241022
     - 0.851 (±0.191)
     - 0.927 (±0.102)
     - 16.68
     - 0.01777
   * - 8
     - gemini-1.5-flash
     - 0.843 (±0.223)
     - 0.969 (±0.039)
     - 15.98
     - 0.00043
   * - 9
     - gpt-5-mini
     - 0.816 (±0.210)
     - 0.920 (±0.108)
     - 52.99
     - 0.00818
   * - 10
     - gpt-5
     - 0.806 (±0.224)
     - 0.919 (±0.092)
     - 97.62
     - 0.05421
   * - 11
     - claude-sonnet-4-20250514
     - 0.789 (±0.192)
     - 0.898 (±0.140)
     - 21.31
     - 0.02053
   * - 12
     - gpt-4o
     - 0.774 (±0.271)
     - 0.889 (±0.126)
     - 28.51
     - 0.01438
   * - 13
     - claude-opus-4-20250514
     - 0.774 (±0.224)
     - 0.877 (±0.151)
     - 28.56
     - 0.09425
   * - 14
     - accounts/fireworks/models/llama4-scout-instruct-basic
     - 0.769 (±0.248)
     - 0.938 (±0.064)
     - 13.48
     - 0.00086
   * - 15
     - accounts/fireworks/models/llama4-maverick-instruct-basic
     - 0.767 (±0.211)
     - 0.927 (±0.122)
     - 16.22
     - 0.00147
   * - 16
     - gemini-1.5-pro
     - 0.766 (±0.323)
     - 0.858 (±0.239)
     - 25.25
     - 0.01173
   * - 17
     - gpt-4.1-mini
     - 0.735 (±0.251)
     - 0.786 (±0.193)
     - 22.39
     - 0.00344
   * - 18
     - gpt-4o-mini
     - 0.718 (±0.249)
     - 0.842 (±0.131)
     - 18.11
     - 0.00619
   * - 19
     - meta-llama/Llama-Vision-Free
     - 0.677 (±0.247)
     - 0.865 (±0.132)
     - 11.34
     - 0.00000
   * - 20
     - meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo
     - 0.674 (±0.240)
     - 0.857 (±0.128)
     - 7.33
     - 0.00015
   * - 21
     - microsoft/phi-4-multimodal-instruct
     - 0.623 (±0.260)
     - 0.821 (±0.206)
     - 12.79
     - 0.00046
   * - 22
     - claude-3-7-sonnet-20250219
     - 0.621 (±0.405)
     - 0.740 (±0.304)
     - 61.06
     - 0.01696
   * - 23
     - google/gemma-3-27b-it
     - 0.614 (±0.356)
     - 0.779 (±0.309)
     - 22.97
     - 0.00020
   * - 24
     - gpt-4.1
     - 0.613 (±0.303)
     - 0.769 (±0.183)
     - 34.47
     - 0.01415
   * - 25
     - meta-llama/Llama-3.2-90B-Vision-Instruct-Turbo
     - 0.562 (±0.242)
     - 0.815 (±0.140)
     - 27.10
     - 0.01067
   * - 26
     - ds4sd/SmolDocling-256M-preview
     - 0.468 (±0.378)
     - 0.554 (±0.361)
     - 103.86
     - 0.00000
   * - 27
     - qwen/qwen-2.5-vl-7b-instruct
     - 0.460 (±0.372)
     - 0.599 (±0.452)
     - 12.83
     - 0.00057
    