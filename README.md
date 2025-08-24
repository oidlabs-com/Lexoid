<div align="center">
  
```
 ___      _______  __   __  _______  ___   ______  
|   |    |       ||  |_|  ||       ||   | |      | 
|   |    |    ___||       ||   _   ||   | |  _    |
|   |    |   |___ |       ||  | |  ||   | | | |   |
|   |___ |    ___| |     | |  |_|  ||   | | |_|   |
|       ||   |___ |   _   ||       ||   | |       |
|_______||_______||__| |__||_______||___| |______| 
                                                                                                    
```
  
</div>

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/oidlabs-com/Lexoid/blob/main/examples/example_notebook_colab.ipynb)
[![Hugging Face](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Spaces-yellow)](https://huggingface.co/spaces/oidlabs/Lexoid)
[![GitHub license](https://img.shields.io/badge/License-Apache_2.0-turquoise.svg)](https://github.com/oidlabs-com/Lexoid/blob/main/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/lexoid)](https://pypi.org/project/lexoid/)
[![Docs](https://github.com/oidlabs-com/Lexoid/actions/workflows/deploy_docs.yml/badge.svg)](https://oidlabs-com.github.io/Lexoid/)

Lexoid is an efficient document parsing library that supports both LLM-based and non-LLM-based (static) PDF document parsing.

[Documentation](https://oidlabs-com.github.io/Lexoid/)

## Motivation:

- Use the multi-modal advancement of LLMs
- Enable convenience for users
- Collaborate with a permissive license

## Installation

### Installing with pip

```
pip install lexoid
```

To use LLM-based parsing, define the following environment variables or create a `.env` file with the following definitions

```
OPENAI_API_KEY=""
GOOGLE_API_KEY=""
```

Optionally, to use `Playwright` for retrieving web content (instead of the `requests` library):

```
playwright install --with-deps --only-shell chromium
```

### Building `.whl` from source

```
make build
```

### Creating a local installation

To install dependencies:

```
make install
```

or, to install with dev-dependencies:

```
make dev
```

To activate virtual environment:

```
source .venv/bin/activate
```

## Usage

[Example Notebook](https://github.com/oidlabs-com/Lexoid/blob/main/examples/example_notebook.ipynb)

[Example Colab Notebook](https://colab.research.google.com/github/oidlabs-com/Lexoid/blob/main/examples/example_notebook_colab.ipynb)

Here's a quick example to parse documents using Lexoid:

```python
from lexoid.api import parse
from lexoid.api import ParserType

parsed_md = parse("https://www.justice.gov/eoir/immigration-law-advisor", parser_type="LLM_PARSE")["raw"]
# or
pdf_path = "path/to/immigration-law-advisor.pdf"
parsed_md = parse(pdf_path, parser_type="LLM_PARSE")["raw"]

print(parsed_md)
```

### Parameters

- path (str): The file path or URL.
- parser_type (str, optional): The type of parser to use ("LLM_PARSE" or "STATIC_PARSE"). Defaults to "AUTO".
- pages_per_split (int, optional): Number of pages per split for chunking. Defaults to 4.
- max_threads (int, optional): Maximum number of threads for parallel processing. Defaults to 4.
- \*\*kwargs: Additional arguments for the parser.

## Supported API Providers
* Google
* OpenAI
* Hugging Face
* Together AI
* OpenRouter
* Fireworks

## Benchmark

Results aggregated across 11 documents.

_Note:_ Benchmarks are currently done in the zero-shot setting.

| Rank | Model | SequenceMatcher Similarity | TFIDF Similarity | Time (s) | Cost ($) |
| --- | --- | --- | --- | --- | --- |
| 1 | AUTO (with auto-selected model) | 0.893 (±0.135) | 0.957 (±0.068) | 22.25 | 0.00066 |
| 2 | AUTO | 0.889 (±0.115) | 0.971 (±0.048) | 9.29 | 0.00062 |
| 3 | mistral-ocr-latest | 0.882 (±0.111) | 0.927 (±0.094) | 5.64 | 0.00123 |
| 4 | gemini-2.5-flash | 0.877 (±0.169) | 0.986 (±0.028) | 52.28 | 0.01056 |
| 5 | gemini-2.5-pro | 0.876 (±0.195) | 0.976 (±0.049) | 22.65 | 0.02408 |
| 6 | gemini-2.0-flash | 0.867 (±0.152) | 0.975 (±0.038) | 11.97 | 0.00079 |
| 7 | claude-3-5-sonnet-20241022 | 0.851 (±0.191) | 0.927 (±0.102) | 16.68 | 0.01777 |
| 8 | gemini-1.5-flash | 0.843 (±0.223) | 0.969 (±0.039) | 15.98 | 0.00043 |
| 9 | gpt-5-mini | 0.816 (±0.210) | 0.920 (±0.108) | 52.99 | 0.00818 |
| 10 | gpt-5 | 0.806 (±0.224) | 0.919 (±0.092) | 97.62 | 0.05421 |
| 11 | claude-sonnet-4-20250514 | 0.789 (±0.192) | 0.898 (±0.140) | 21.31 | 0.02053 |
| 12 | gpt-4o | 0.774 (±0.271) | 0.889 (±0.126) | 28.51 | 0.01438 |
| 13 | claude-opus-4-20250514 | 0.774 (±0.224) | 0.877 (±0.151) | 28.56 | 0.09425 |
| 14 | accounts/fireworks/models/llama4-scout-instruct-basic | 0.769 (±0.248) | 0.938 (±0.064) | 13.48 | 0.00086 |
| 15 | accounts/fireworks/models/llama4-maverick-instruct-basic | 0.767 (±0.211) | 0.927 (±0.122) | 16.22 | 0.00147 |
| 16 | gemini-1.5-pro | 0.766 (±0.323) | 0.858 (±0.239) | 25.25 | 0.01173 |
| 17 | gpt-4.1-mini | 0.735 (±0.251) | 0.786 (±0.193) | 22.39 | 0.00344 |
| 18 | gpt-4o-mini | 0.718 (±0.249) | 0.842 (±0.131) | 18.11 | 0.00619 |
| 19 | meta-llama/Llama-Vision-Free | 0.677 (±0.247) | 0.865 (±0.132) | 11.34 | 0.00000 |
| 20 | meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo | 0.674 (±0.240) | 0.857 (±0.128) | 7.33 | 0.00015 |
| 21 | microsoft/phi-4-multimodal-instruct | 0.623 (±0.260) | 0.821 (±0.206) | 12.79 | 0.00046 |
| 22 | claude-3-7-sonnet-20250219 | 0.621 (±0.405) | 0.740 (±0.304) | 61.06 | 0.01696 |
| 23 | google/gemma-3-27b-it | 0.614 (±0.356) | 0.779 (±0.309) | 22.97 | 0.00020 |
| 24 | gpt-4.1 | 0.613 (±0.303) | 0.769 (±0.183) | 34.47 | 0.01415 |
| 25 | meta-llama/Llama-3.2-90B-Vision-Instruct-Turbo | 0.562 (±0.242) | 0.815 (±0.140) | 27.10 | 0.01067 |
| 26 | ds4sd/SmolDocling-256M-preview | 0.468 (±0.378) | 0.554 (±0.361) | 103.86 | 0.00000 |
| 27 | qwen/qwen-2.5-vl-7b-instruct | 0.460 (±0.372) | 0.599 (±0.452) | 12.83 | 0.00057 |
