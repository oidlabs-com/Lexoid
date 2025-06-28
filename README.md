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

Results aggregated across 5 iterations each for 5 documents.

_Note:_ Benchmarks are currently done in the zero-shot setting.

| Rank | Model | Mean Similarity | Std. Dev. | Time (s) | Cost ($) |
| --- | --- | --- | --- | --- | --- |
| 1 | AUTO | 0.906 | 0.112 | 9.56 | 0.00068 |
| 2 | gemini-2.0-flash | 0.897 | 0.126 | 9.91 | 0.00078 |
| 3 | gemini-2.5-flash | 0.895 | 0.148 | 54.10 | 0.01051 |
| 4 | gemini-1.5-pro | 0.868 | 0.283 | 15.03 | 0.00637 |
| 5 | gemini-1.5-flash | 0.864 | 0.194 | 15.47 | 0.00044 |
| 6 | claude-3-5-sonnet-20241022 | 0.851 | 0.209 | 15.99 | 0.01758 |
| 7 | gemini-2.5-pro | 0.849 | 0.298 | 101.95 | 0.01859 |
| 8 | claude-sonnet-4-20250514 | 0.804 | 0.190 | 19.27 | 0.02071 |
| 9 | claude-opus-4-20250514 | 0.772 | 0.238 | 20.03 | 0.09207 |
| 10 | accounts/fireworks/models/llama4-maverick-instruct-basic | 0.768 | 0.234 | 12.12 | 0.00150 |
| 11 | gpt-4o | 0.748 | 0.284 | 26.80 | 0.01478 |
| 12 | gpt-4o-mini | 0.733 | 0.231 | 18.18 | 0.00650 |
| 13 | gpt-4.1-mini | 0.723 | 0.269 | 20.91 | 0.00351 |
| 14 | google/gemma-3-27b-it | 0.681 | 0.334 | 19.41 | 0.00027 |
| 15 | gpt-4.1 | 0.650 | 0.342 | 33.72 | 0.01443 |
| 16 | claude-3-7-sonnet-20250219 | 0.633 | 0.369 | 14.24 | 0.01763 |
| 17 | microsoft/phi-4-multimodal-instruct | 0.622 | 0.320 | 13.15 | 0.00050 |
| 18 | qwen/qwen-2.5-vl-7b-instruct | 0.559 | 0.348 | 17.71 | 0.00086 |
| 19 | meta-llama/Llama-3.2-90B-Vision-Instruct-Turbo | 0.546 | 0.239 | 29.26 | 0.01103 |
