# Lexoid

Lexoid is an efficient document parsing library with support for both LLM-based and non-LLM based (static) parsing of PDF documents.

## Usage

To parse a PDF document using Lexoid, you can use the `parse_doc` function from the `lexoid.doc_parser` module. Here's a basic example:

```python
from lexoid.doc_parser import parse_doc, ParserType

pdf_path = "path/to/document.pdf"
parsed_md = parse_doc(pdf_path, ParserType.LLM_PARSE, raw=True)
print(parsed_md)
```

### Parameters

- `path`: The file path to the PDF document.
- `parser_type`: The type of parser to use (`ParserType.STATIC_PARSE` or `ParserType.LLM_PARSE`).
- `raw`: If `True`, returns raw text; otherwise, returns structured data.
- `pages_per_split`: Number of pages per split when processing large documents.
- `max_threads`: Maximum number of threads to use for processing.
