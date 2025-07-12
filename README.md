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
| 1 | gemini-2.5-pro | 0.907 (±0.151) | 0.973 (±0.053) | 22.23 | 0.02305 |
| 2 | AUTO | 0.905 (±0.111) | 0.967 (±0.051) | 10.31 | 0.00068 |
| 3 | gemini-2.5-flash | 0.902 (±0.151) | 0.984 (±0.030) | 48.67 | 0.01051 |
| 4 | gemini-2.0-flash | 0.900 (±0.127) | 0.971 (±0.040) | 12.43 | 0.00081 |
| 5 | claude-3-5-sonnet-20241022 | 0.873 (±0.195) | 0.937 (±0.095) | 16.86 | 0.01779 |
| 6 | gemini-1.5-flash | 0.868 (±0.198) | 0.965 (±0.041) | 17.19 | 0.00044 |
| 7 | claude-sonnet-4-20250514 | 0.814 (±0.197) | 0.903 (±0.150) | 21.99 | 0.02045 |
| 8 | accounts/fireworks/models/llama4-scout-instruct-basic | 0.804 (±0.242) | 0.931 (±0.067) | 9.76 | 0.00087 |
| 9 | claude-opus-4-20250514 | 0.798 (±0.230) | 0.878 (±0.159) | 21.01 | 0.09233 |
| 10 | gpt-4o | 0.796 (±0.264) | 0.898 (±0.117) | 28.23 | 0.01473 |
| 11 | accounts/fireworks/models/llama4-maverick-instruct-basic | 0.792 (±0.206) | 0.914 (±0.128) | 10.71 | 0.00149 |
| 12 | gemini-1.5-pro | 0.782 (±0.341) | 0.833 (±0.252) | 27.13 | 0.01275 |
| 13 | gpt-4.1-mini | 0.767 (±0.243) | 0.807 (±0.197) | 22.64 | 0.00352 |
| 14 | gpt-4o-mini | 0.727 (±0.245) | 0.832 (±0.136) | 17.20 | 0.00650 |
| 15 | meta-llama/Llama-Vision-Free | 0.682 (±0.223) | 0.847 (±0.135) | 12.31 | 0.00000 |
| 16 | meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo | 0.677 (±0.226) | 0.850 (±0.134) | 7.23 | 0.00015 |
| 17 | microsoft/phi-4-multimodal-instruct | 0.665 (±0.258) | 0.800 (±0.217) | 10.96 | 0.00049 |
| 18 | claude-3-7-sonnet-20250219 | 0.634 (±0.395) | 0.752 (±0.298) | 70.10 | 0.01775 |
| 19 | google/gemma-3-27b-it | 0.624 (±0.357) | 0.750 (±0.327) | 24.51 | 0.00020 |
| 20 | gpt-4.1 | 0.622 (±0.314) | 0.782 (±0.191) | 34.66 | 0.01461 |
| 21 | meta-llama/Llama-3.2-90B-Vision-Instruct-Turbo | 0.559 (±0.233) | 0.822 (±0.119) | 27.74 | 0.01102 |
| 22 | ds4sd/SmolDocling-256M-preview | 0.486 (±0.378) | 0.583 (±0.355) | 108.91 | 0.00000 |
| 23 | qwen/qwen-2.5-vl-7b-instruct | 0.469 (±0.364) | 0.617 (±0.441) | 13.23 | 0.00060 |
