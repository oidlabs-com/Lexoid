# Lexoid

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

[Example Colab Notebook](https://drive.google.com/file/d/1v9R6VOUp9CEGalgZGeg5G57XzHqh_tB6/view?usp=sharing)

Here's a quick example to parse documents using Lexoid:
``` python
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
- **kwargs: Additional arguments for the parser.

## Benchmark
Initial results (_more updates soon_)

_Note:_ Benchmarks are currently done in the zero-shot setting.

| Rank | Model/Framework | Similarity | Time (s) |
|------|-----------|------------|----------|
| 1 | gpt-4o | 0.799 | 21.77|
| 2 | gemini-2.0-flash-exp | 0.797 | 13.47 |
| 3 | gemini-exp-1121 | 0.779 | 30.88 |
| 4 | gemini-1.5-pro | 0.742 | 15.77 |
| 5 | gpt-4o-mini | 0.721 | 14.86 |
| 6 | gemini-1.5-flash | 0.702 | 4.56 |
| 7 | Llama-3.2-11B-Vision-Instruct (via HF) | 0.582 | 21.74 |
| 8 | Llama-3.2-11B-Vision-Instruct-Turbo (via Together AI) | 0.556 | 4.58 |
| 9 | Llama-3.2-90B-Vision-Instruct-Turbo (via Together AI) | 0.527 | 10.57 |
| 10 | Llama-Vision-Free (via Together AI) | 0.435 | 8.42 |
