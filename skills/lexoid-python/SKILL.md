---
name: lexoid-python
description: Parse and convert documents (PDFs, images, web pages, DOCX/XLSX/PPTX, audio) inside a Python program using the `lexoid` library. Use when the user is writing Python code that needs to extract markdown from documents, run schema-constrained extraction, convert files to LaTeX, get bounding boxes, recursively crawl URLs, or integrate document parsing into a larger pipeline. Triggers include `from lexoid` imports, "use lexoid in Python", "parse PDFs programmatically", "extract structured data with a Pydantic/dataclass schema", or any request to embed parsing into a Python app/notebook.
---

# Lexoid Python API

Lexoid's Python API is the right choice whenever the user is writing Python — notebooks, services, batch pipelines, or anything that needs the parsed result as a Python dict/list. For shell one-offs, use the `lexoid-cli` skill instead.

## When to use this skill

- The user is writing Python and wants to parse PDFs, images, URLs, DOCX/XLSX/PPTX, audio, or text-format files.
- The user needs per-page segments, token usage, parser metadata, or bounding boxes in code.
- The user wants schema-based structured extraction (`dict`, `dataclass`, or Pydantic `BaseModel`).
- The user is integrating parsing into a larger app (Streamlit, FastAPI, RAG pipeline, etc.).

## Setup checks

Before writing code, confirm:

1. `lexoid` is installed (`pip install lexoid`).
2. Required API key env vars are set for the chosen provider (see below).
3. For Linux DOCX → PDF conversion, LibreOffice (`lowriter`) is on PATH.
4. For `api_provider="ollama"`: an `ollama serve` process is running at `OLLAMA_BASE_URL` (default `http://localhost:11434`) and the target model has been pulled with `ollama pull <model>`.
5. For `api_provider="local"` (SmolDocling/granite-docling, PaddleOCR-VL): **no server needed** — these models run in-process via `transformers` / PaddleOCR. The first call downloads weights from Hugging Face, so the host needs network access (or pre-cached weights) and enough disk/RAM/GPU for the chosen model.

API keys by provider:

| Provider     | Env var                       |
|--------------|-------------------------------|
| `gemini`     | `GOOGLE_API_KEY`              |
| `openai`     | `OPENAI_API_KEY`              |
| `anthropic`  | `ANTHROPIC_API_KEY`           |
| `mistral`    | `MISTRAL_API_KEY`             |
| `huggingface`| `HUGGINGFACEHUB_API_TOKEN`    |
| `together`   | `TOGETHER_API_KEY`            |
| `openrouter` | `OPENROUTER_API_KEY`          |
| `fireworks`  | `FIREWORKS_API_KEY`           |
| `ollama`     | none (uses `OLLAMA_BASE_URL`) |
| `local`      | none                          |

### Loading API keys from `.env`

Lexoid reads API keys from the process environment; it does **not** load a `.env` file on its own. When keys live in a project `.env`, load them before calling any LLM-based API (`LLM_PARSE`, `parse_with_schema`, `parse_to_latex`, or `AUTO` when it routes to an LLM). `python-dotenv` ships as a Lexoid dependency, so it is already available:

```python
from dotenv import load_dotenv

# Loads .env from the current dir (or a parent) into os.environ if the file
# exists; a no-op that returns False when no .env is found. Existing env vars
# are not overwritten unless override=True is passed.
load_dotenv()

from lexoid.api import parse
result = parse("document.pdf", parser_type="LLM_PARSE", model="gpt-4o")
```

Call `load_dotenv()` once at program/notebook startup, before the first `parse(...)` call. If the keys are already exported in the environment, this step is unnecessary (and harmless).

## Public API

Four entry points in `lexoid.api`:

- `parse(path, parser_type="AUTO", pages_per_split=4, max_processes=4, **kwargs)` — main function. Returns a dict.
- `parse_with_schema(path, schema, api=None, model="gpt-4o-mini", **kwargs)` — structured JSON extraction. Returns a Python list whose shape depends on the mode and the model's output (see "Schema return shape" below).
- `parse_to_latex(path, api=None, model="gpt-4o-mini", **kwargs)` — returns a LaTeX string.
- `parse_chunk(path, parser_type, **kwargs)` — low-level single-chunk parser; users rarely need this.

`ParserType` enum: `LLM_PARSE`, `STATIC_PARSE`, `AUTO`.

## `parse()` return shape

```python
{
    "raw": str,                  # full markdown
    "segments": [                # one dict per page / section; may be empty
        # bboxes is included only when return_bboxes=True
        {"metadata": {"page": int}, "content": str, "bboxes": [(text, [x0, top, x1, bottom]), ...]},
        ...
    ],
    "title": str,
    "url": str,                  # input URL or "" if input was a local file
    "parent_title": str,         # parent doc title when recursive; "" otherwise
    "recursive_docs": [...],     # empty unless depth > 1
    # --- optional keys below ---
    "token_usage": {"input": int, "output": int, "total": int, "llm_page_count": int},
        # zeros under STATIC_PARSE-only; ABSENT on the HTML/recursive-URL path
        # (URL input that isn't a file-typed URL and as_pdf is not set)
    "parsers_used": [str, ...],  # ABSENT on the HTML/recursive-URL path (same condition)
    "token_cost": {...},         # only when api_cost_mapping is supplied
    "pdf_path": str,             # only when as_pdf=True; file is removed unless save_dir is also set
}
```

For URL inputs that resolve to HTML (no `.pdf`/image extension, and
`as_pdf=False`), `parse()` short-circuits to `recursive_read_html()`,
which returns only `raw`, `segments`, `title`, `url`, `parent_title`,
and `recursive_docs`. Code that always reads `result["token_usage"]` or
`result["parsers_used"]` will `KeyError` on that path — use `.get(...)`
or guard with `if "token_usage" in result`.

## Common recipes

### Basic parsing

```python
from lexoid.api import parse

result = parse("document.pdf")
markdown = result["raw"]
for seg in result["segments"]:
    print(seg["metadata"]["page"], seg["content"][:80])
```

### Choose a parser explicitly

```python
# Native-text PDFs — fastest, no API key
parse("document.pdf", parser_type="STATIC_PARSE", framework="pdfplumber")

# Scanned PDFs / images — local OCR, no API key
parse("scanned.pdf", parser_type="STATIC_PARSE", framework="paddleocr")

# LLM parsing
parse("document.pdf", parser_type="LLM_PARSE", model="gpt-4o")
parse("document.pdf", parser_type="LLM_PARSE", model="gemini-2.5-pro")
parse("document.pdf", parser_type="LLM_PARSE", model="claude-3-5-sonnet-20241022")
```

### AUTO routing with a priority

```python
# Speed (default): static if no images, LLM otherwise
parse("doc.pdf", parser_type="AUTO", router_priority="speed")

# Accuracy: prefers LLM, except PDFs with hidden hyperlinks
parse("doc.pdf", parser_type="AUTO", router_priority="accuracy")

# Cost: tries PaddleOCR first; LLM fallback if extracted text is too short
parse("doc.pdf", parser_type="AUTO", router_priority="cost", character_threshold=100)

# ML-based LLM auto-selection (uses lexoid/core/llm_selector.py)
parse("doc.pdf", parser_type="AUTO", autoselect_llm=True)
```

### Local inference (no API key)

```python
# Ollama — Lexoid forces max_processes=1 for Ollama
parse("doc.pdf", parser_type="LLM_PARSE",
      api_provider="ollama", model="gemma4:latest", max_processes=1)

# SmolDocling / granite-docling
parse("doc.pdf", parser_type="LLM_PARSE",
      api_provider="local", model="ds4sd/SmolDocling-256M-preview")

# PaddleOCR-VL
parse("doc.pdf", parser_type="LLM_PARSE",
      api_provider="local", model="PaddlePaddle/PaddleOCR-VL")
```

### Schema-based structured extraction

#### Schema return shape

`parse_with_schema` returns a Python `list`. The exact shape depends on
the mode and on what JSON the model emits:

- **Default (per-page) mode** — one entry per page. Each entry is the JSON
  the model returned for that page: a single `dict` for single-record
  schemas, or a `list` of `dict`s for multi-record schemas (e.g., a page
  of table rows). Index as `result[page_index]` for the page's value, and
  `result[page_index][record_index]` when each page has multiple records.
- **`fill_single_schema=True`** — a single-element list whose element is
  the JSON for the whole document (typically one `dict`).

If you need to support both single- and multi-record schemas in the same
code path, normalize the per-page entries yourself (e.g., wrap a `dict`
in `[dict]`).

```python
from lexoid.api import parse_with_schema
from pydantic import BaseModel

class Invoice(BaseModel):
    invoice_number: str
    total: float

# Per-page extraction. `pages` is a list with one entry per page;
# each entry is whatever JSON the model returned for that page.
pages = parse_with_schema("invoice.pdf", schema=Invoice, model="gpt-4o-mini")
# e.g., pages[0] -> {"invoice_number": "...", "total": ...}
#       pages[0][0] -> first record if the model returned a list per page

# Single instance for the whole document — returns a one-element list.
[full] = parse_with_schema("contract.pdf", schema=Invoice,
                           model="gpt-4o", fill_single_schema=True)

# Dict schema with example data + alternate keys (improves match)
pages = parse_with_schema(
    "invoice.pdf",
    schema={"invoice_number": "string", "total": "number"},
    example_schema={"invoice_number": "INV-001", "total": 199.95},
    alternate_keys={"invoice_number": ["Invoice #", "Invoice No."]},
)

# Dataclass schemas also work
from dataclasses import dataclass
@dataclass
class Receipt:
    merchant: str
    amount: float

parse_with_schema("receipt.pdf", schema=Receipt)
```

### LaTeX conversion

```python
from lexoid.api import parse_to_latex
latex_source = parse_to_latex("paper.pdf", model="gpt-4o")
```

### URLs and recursive crawling

```python
# Single page
parse("https://example.com")

# Crawl 2 levels deep
parse("https://example.com", depth=2)

# Render webpage → PDF first, then parse and keep the intermediate PDF
result = parse(
    "https://example.com",
    as_pdf=True,
    save_dir="output/",
    save_filename="example.pdf",
)
intermediate = result["pdf_path"]
```

### Bounding boxes

```python
result = parse("doc.pdf", return_bboxes=True, bbox_framework="auto")
for seg in result["segments"]:
    for text, bbox in seg.get("bboxes", []):
        # bbox = [x0, top, x1, bottom], normalized [0, 1]
        ...
```

### Audio

Audio inputs require a Gemini model (the only provider with audio support).

```python
result = parse("interview.mp3", model="gemini-2.5-flash")
print(result["raw"])
```

### Token cost tracking

```python
result = parse(
    "doc.pdf",
    model="gpt-4o",
    api_cost_mapping="tests/api_cost_mapping.json",
)
print(result["token_cost"])  # {"input": ..., "output": ..., "input-image": ..., "total": ...}
```

## Key kwargs reference

| kwarg                   | Purpose                                                                 |
|-------------------------|-------------------------------------------------------------------------|
| `model`                 | LLM model name (default from `DEFAULT_LLM`, falls back to `gemini-2.5-flash`). |
| `api_provider`          | Override inferred provider.                                             |
| `framework`             | `pdfplumber` / `pdfminer` / `paddleocr` for STATIC_PARSE.               |
| `temperature`           | LLM sampling temperature (default `0.0`).                               |
| `max_tokens`            | LLM output token limit (default `1024`, `4096` for Ollama).             |
| `pages_per_split`       | Pages per parallel chunk.                                               |
| `max_processes`         | Parallel workers (forced to 1 when `parser_type="LLM_PARSE"` and `api_provider="ollama"`). |
| `page_nums`             | Specific 1-indexed pages to parse (PDFs only).                          |
| `depth`                 | Recursive URL parsing depth.                                            |
| `as_pdf`                | Convert input to PDF before parsing.                                    |
| `save_dir`              | Where to keep the intermediate PDF if `as_pdf=True`.                    |
| `return_bboxes`         | Attach bounding boxes per segment.                                      |
| `bbox_framework`        | `auto` / `pdfplumber` / `paddleocr`.                                    |
| `router_priority`       | `speed` / `accuracy` / `cost` for AUTO mode.                            |
| `character_threshold`   | Min char count for STATIC accept under `cost` priority.                 |
| `autoselect_llm`        | ML-based LLM choice in AUTO mode.                                       |
| `retry_on_fail`         | Fall back to alternate parser on error (default `True`).                |
| `max_image_dimension`   | Max px to which images / page renders are downscaled.                   |
| `api_cost_mapping`      | Dict or JSON path with per-model cost — enables `token_cost` in output. |
| `system_prompt` / `user_prompt` | Override the default LLM prompts.                              |
| `verbose`               | Verbose logging during LLM parsing.                                     |

## Things to verify before reporting success

- The result dict has non-empty `raw`. Empty `raw` with an `error` key means a recoverable failure occurred and Lexoid returned a stub.
- For LLM_PARSE, `token_usage["total"]` is non-zero — zero suggests the API call silently failed.
- For multi-page PDFs, `len(result["segments"])` matches the expected page count (or `len(page_nums)` if used).
- For `parse_with_schema`, each per-page entry may be a `dict` or a `list` of `dict`s depending on the schema and the model. Check the type before indexing, and verify that the keys actually match the schema — the LLM can drift; pass `example_schema` to anchor it.

## See also

- API reference: `docs/api.rst`.
- CLI equivalent: `lexoid-cli` skill.
- Example notebooks: `examples/example_notebook.ipynb`, `examples/example_notebook_colab.ipynb`.
