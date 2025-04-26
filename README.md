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
[![GitHub license](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/oidlabs-com/Lexoid/blob/main/LICENSE)
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
| 1 | gemini-2.0-flash | 0.829 | 0.102 | 7.41 | 0.00048 |
| 2 | gemini-2.0-flash-001 | 0.814 | 0.176 | 6.85 | 0.000421 |
| 3 | gemini-1.5-flash | 0.797 | 0.143 | 9.54 | 0.000238 |
| 4 | gemini-2.0-pro-exp | 0.764 | 0.227 | 11.95 | TBA |
| 5 | AUTO | 0.76 | 0.184 | 5.14 | 0.000217 |
| 6 | gemini-2.0-flash-thinking-exp | 0.746 | 0.266 | 10.46 | TBA |
| 7 | gemini-1.5-pro | 0.732 | 0.265 | 11.44 | 0.003332 |
| 8 | accounts/fireworks/models/llama4-maverick-instruct-basic (via Fireworks) | 0.687 | 0.221 | 8.07 | 0.000419 |
| 9 | gpt-4o | 0.687 | 0.247 | 10.16 | 0.004736 |
| 10 | accounts/fireworks/models/llama4-scout-instruct-basic (via Fireworks) | 0.675 | 0.184 | 5.98 | 0.000226 |
| 11 | gpt-4o-mini | 0.642 | 0.213 | 9.71 | 0.000275 |
| 12 | gemma-3-27b-it (via OpenRouter) | 0.628 | 0.299 | 18.79 | 0.000096 |
| 13 | gemini-1.5-flash-8b | 0.551 | 0.223 | 3.91 | 0.000055 |
| 14 | Llama-Vision-Free (via Together AI) | 0.531 | 0.198 | 6.93 | 0 |
| 15 | Llama-3.2-11B-Vision-Instruct-Turbo (via Together AI) | 0.524 | 0.192 | 3.68 | 0.00006 |
| 16 | qwen/qwen-2.5-vl-7b-instruct (via OpenRouter) | 0.482 | 0.209 | 11.53 | 0.000052 |
| 17 | Llama-3.2-90B-Vision-Instruct-Turbo (via Together AI) | 0.461 | 0.306 | 19.26 | 0.000426 |
| 18 | Llama-3.2-11B-Vision-Instruct (via Hugging Face) | 0.451 | 0.257 | 4.54 | 0 |
| 19 | microsoft/phi-4-multimodal-instruct (via OpenRouter) | 0.366 | 0.287 | 10.8 | 0.000019 |
