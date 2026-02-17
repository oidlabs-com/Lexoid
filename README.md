<div align="center">
  
<img src="assets/logo.png">
  
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

>[!NOTE]
>Installing the package from within the virtual environment could cause unexpected behavior, 
>as Lexoid creates and activates its own environment in order to build the wheel.

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

parsed_md = parse("https://www.justice.gov/eoir/immigration-law-advisor", parser_type="AUTO")["raw"]
# or
pdf_path = "path/to/immigration-law-advisor.pdf"
parsed_md = parse(pdf_path, parser_type="LLM_PARSE")["raw"]
# or
pdf_path = "path/to/immigration-law-advisor.pdf"
parsed_md = parse(pdf_path, parser_type="STATIC_PARSE")["raw"]

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

Results aggregated across 14 documents.

_Note:_ Benchmarks are currently done in the zero-shot setting.

| Rank | Model | SequenceMatcher Similarity | TFIDF Similarity | Time (s) | Cost ($) |
| --- | --- | --- | --- | --- | --- |
| 1 | gemini-3-pro-preview | 0.917 (±0.127) | 0.943 (±0.159) | 46.92 | 0.06288 |
| 2 | AUTO (with auto-selected model) | 0.899 (±0.131) | 0.960 (±0.066) | 21.17 | 0.00066 |
| 3 | AUTO | 0.895 (±0.112) | 0.973 (±0.046) | 9.29 | 0.00063 |
| 4 | gpt-5.2 | 0.890 (±0.193) | 0.975 (±0.036) | 33.32 | 0.03959 |
| 5 | gemini-2.5-flash | 0.886 (±0.164) | 0.986 (±0.027) | 52.55 | 0.01226 |
| 6 | mistral-ocr-latest | 0.882 (±0.106) | 0.932 (±0.091) | 5.75 | 0.00121 |
| 7 | gemini-2.5-pro | 0.876 (±0.195) | 0.976 (±0.049) | 22.65 | 0.02408 |
| 8 | gemini-2.0-flash | 0.875 (±0.148) | 0.977 (±0.037) | 11.96 | 0.00079 |
| 9 | claude-3-5-sonnet-20241022 | 0.858 (±0.184) | 0.930 (±0.098) | 17.32 | 0.01804 |
| 10 | gemini-1.5-flash | 0.842 (±0.214) | 0.969 (±0.037) | 15.58 | 0.00043 |
| 11 | gpt-5-mini | 0.819 (±0.201) | 0.917 (±0.104) | 52.84 | 0.00811 |
| 12 | gpt-5 | 0.807 (±0.215) | 0.919 (±0.088) | 98.12 | 0.05505 |
| 13 | claude-sonnet-4-20250514 | 0.801 (±0.188) | 0.905 (±0.136) | 22.02 | 0.02056 |
| 14 | claude-opus-4-20250514 | 0.789 (±0.220) | 0.886 (±0.148) | 29.55 | 0.09513 |
| 15 | accounts/fireworks/models/llama4-maverick-instruct-basic | 0.772 (±0.203) | 0.930 (±0.117) | 16.02 | 0.00147 |
| 16 | gemini-1.5-pro | 0.767 (±0.309) | 0.865 (±0.230) | 24.77 | 0.01139 |
| 17 | gemini-3-flash-preview | 0.766 (±0.293) | 0.858 (±0.210) | 39.38 | 0.00969 |
| 18 | gpt-4.1-mini | 0.754 (±0.249) | 0.803 (±0.193) | 23.28 | 0.00347 |
| 19 | accounts/fireworks/models/llama4-scout-instruct-basic | 0.754 (±0.243) | 0.942 (±0.063) | 13.36 | 0.00087 |
| 20 | gpt-4o | 0.752 (±0.269) | 0.896 (±0.123) | 28.87 | 0.01469 |
| 21 | gpt-4o-mini | 0.728 (±0.241) | 0.850 (±0.128) | 18.96 | 0.00609 |
| 22 | claude-3-7-sonnet-20250219 | 0.646 (±0.397) | 0.758 (±0.297) | 57.96 | 0.01730 |
| 23 | gpt-4.1 | 0.637 (±0.301) | 0.787 (±0.185) | 35.37 | 0.01498 |
| 24 | google/gemma-3-27b-it | 0.604 (±0.342) | 0.788 (±0.297) | 23.16 | 0.00020 |
| 25 | ds4sd/SmolDocling-256M-preview | 0.603 (±0.292) | 0.705 (±0.262) | 507.74 | 0.00000 |
| 26 | microsoft/phi-4-multimodal-instruct | 0.589 (±0.273) | 0.820 (±0.197) | 14.00 | 0.00045 |
| 27 | qwen/qwen-2.5-vl-7b-instruct | 0.498 (±0.378) | 0.630 (±0.445) | 14.73 | 0.00056 |

## Citation
If you use Lexoid in production or publications, please cite accordingly and acknowledge usage. We appreciate the support 🙏
