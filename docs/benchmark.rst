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
   :widths: 10 40 20 20
   :header-rows: 1

   * - Rank
     - Model/Framework
     - Similarity
     - Time (s)
   * - 1
     - GPT-4o
     - 0.799
     - 21.77
   * - 2
     - Gemini 2.0 Flash (Experimental)
     - 0.797
     - 13.47
   * - 3
     - Gemini Experimental 1121
     - 0.779
     - 30.88
   * - 4
     - Gemini 1.5 Pro
     - 0.742
     - 15.77
   * - 5
     - GPT-4o Mini
     - 0.721
     - 14.86
   * - 6
     - Gemini 1.5 Flash
     - 0.702
     - 4.56
   * - 7
     - Llama 3.2 11B Vision Instruct
     - 0.582
     - 21.74
   * - 8
     - Llama 3.2 11B Vision Instruct Turbo
     - 0.556
     - 4.58
   * - 9
     - Llama 3.2 90B Vision Instruct Turbo
     - 0.527
     - 10.57
   * - 10
     - Llama Vision Free
     - 0.435
     - 8.42