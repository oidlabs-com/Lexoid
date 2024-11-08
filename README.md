# Lexoid

Lexoid is an efficient document parsing library that supports both LLM-based and non-LLM-based (static) PDF document parsing.

## Dev
```
1. make setup
2. source .venv/bin/activate
3. To build .whl for testing: poetry build
```

## Usage
[Example Notebook](https://github.com/oidlabs-com/Lexoid/blob/main/examples/example_notebook.ipynb)

Here's a quick example to parse documents using Lexoid:
``` python
from lexoid.api import parse
from lexoid.api import ParserType

parsed_md = parse("https://www.justice.gov/eoir/immigration-law-advisor", parser_type="LLM_PARSE", raw=True)
# or
pdf_path = "path/to/immigration-law-advisor.pdf"
parsed_md = parse(pdf_path, parser_type="LLM_PARSE", raw=True)

print(parsed_md)
```

### Parameters
- path (str): The file path or URL.
- parser_type (str, optional): The type of parser to use ("LLM_PARSE" or "STATIC_PARSE"). Defaults to "LLM_PARSE".
- raw (bool, optional): Whether to return raw text or structured data. Defaults to False.
- pages_per_split (int, optional): Number of pages per split for chunking. Defaults to 4.
- max_threads (int, optional): Maximum number of threads for parallel processing. Defaults to 4.
- **kwargs: Additional arguments for the parser.

## Benchmark

| Rank | Model/Framework | Similarity | Time (s) |
|------|-----------|------------|----------|
| 1 | gpt-4o | 0.799 | 21.77|
| 2 | gemini-1.5-pro | 0.742 | 15.77 |
| 3 | gpt-4o-mini | 0.721 | 14.86 |
| 4 | gemini-1.5-flash | 0.702 | 4.56 |
