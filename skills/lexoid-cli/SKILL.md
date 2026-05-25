---
name: lexoid-cli
description: Parse and convert documents (PDFs, images, web pages, DOCX/XLSX/PPTX, audio) from the terminal using the `lexoid` CLI. Use when the user wants to extract markdown / JSON / LaTeX from a file or URL without writing Python, run schema-based structured extraction, or batch-parse from shell scripts. Triggers include "parse this PDF", "convert document to markdown", "extract JSON from PDF", "convert PDF to LaTeX", "use lexoid CLI", or any pipe/shell-style document-processing request.
---

# Lexoid CLI

Lexoid ships a `lexoid` console script (also runnable as `python -m lexoid`) for document parsing without writing Python. There are three sub-commands: `parse`, `schema`, and `latex`.

## When to use this skill

- The user has a document (PDF, image, HTML, DOCX, XLSX, PPTX, CSV, TXT, audio) or a URL and wants it converted to markdown/JSON/LaTeX.
- The user wants structured extraction (JSON conforming to a schema) from the shell.
- The task is one-off or scripted — no need to build a Python integration.

If the user wants to embed parsing into a Python application or library, use the `lexoid-python` skill instead.

## Setup checks

Before invoking, confirm:

1. `lexoid` is installed (`lexoid --help` or `python -m lexoid --help`). If not, run `pip install lexoid`.
2. For LLM-based commands, the relevant API key env var is set:
   - `GOOGLE_API_KEY` (Gemini, default), `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `MISTRAL_API_KEY`, `HUGGINGFACEHUB_API_TOKEN`, `TOGETHER_API_KEY`, `OPENROUTER_API_KEY`, `FIREWORKS_API_KEY`.
   - Ollama / local backends need no key but need a running server / pulled model.
3. For Linux DOCX → PDF, LibreOffice (`lowriter`) must be installed.

## Commands

### `lexoid parse` — Markdown / JSON output

Convert a document to markdown (default) or JSON (with segments, token usage, parser info).

```bash
# Default: AUTO routing, markdown to stdout
lexoid parse --input document.pdf

# Save to file
lexoid parse --input document.pdf --output output.md

# Full result as JSON (includes per-page segments, token usage, parsers_used)
lexoid parse --input document.pdf --format json --output result.json

# Force static parsing (no LLM, no API key needed for PDFs)
lexoid parse --input document.pdf --parser-type STATIC_PARSE --framework pdfplumber

# LLM parsing with a specific model
lexoid parse --input document.pdf --model gpt-4o
lexoid parse --input document.pdf --model claude-3-5-sonnet-20241022
lexoid parse --input scanned.pdf --model mistral-ocr-latest

# Parse a URL
lexoid parse --input https://example.com --output page.md

# Tune chunking / parallelism
lexoid parse --input big.pdf --pages-per-split 8 --max-processes 8
```

Key flags: `--parser-type` (`AUTO`/`LLM_PARSE`/`STATIC_PARSE`), `--model`, `--framework` (`pdfplumber`/`paddleocr`), `--api` (override provider), `--format` (`markdown`/`json`), `--pages-per-split`, `--max-processes`, `--verbose`.

### `lexoid schema` — Structured extraction

Extract data conforming to a JSON schema. Schema can be a file path or inline JSON.

```bash
# Inline schema
lexoid schema \
  --input invoice.pdf \
  --schema '{"type":"object","properties":{"invoice_number":{"type":"string"},"total":{"type":"number"}}}' \
  --output invoice.json

# Schema from file, explicit provider
lexoid schema --input invoice.pdf --schema schema.json --api openai --model gpt-4o

# Example-guided extraction (improves accuracy)
lexoid schema --input invoice.pdf --schema schema.json \
  --example-schema example.json

# Treat the whole doc as one instance (vs. one per page)
lexoid schema --input contract.pdf --schema schema.json --fill-single-schema
```

Defaults: model `gpt-4o-mini`. The provider is auto-detected from the model name unless `--api` is given.

### `lexoid latex` — LaTeX conversion

Convert a document to a self-contained LaTeX source.

```bash
lexoid latex --input paper.pdf --output paper.tex
lexoid latex --input paper.pdf --model gpt-4o
```

## Output piping

When no `--output` is given, only the parsed content is written to stdout; status messages, token usage, and parser info go to stderr. This means standard piping works:

```bash
lexoid parse --input report.pdf | grep -i "revenue"
lexoid parse --input report.pdf --format json | jq '.token_usage'
```

## Common patterns

- **Cheap path first**: try `--parser-type STATIC_PARSE --framework pdfplumber` for native-text PDFs. Fall back to `--parser-type LLM_PARSE` for scans, tables-heavy pages, or hand-written content.
- **Scanned PDFs / images**: use `--framework paddleocr` (no API key) or an LLM model with vision.
- **Batch**: drive the CLI from a shell loop (`for f in inputs/*.pdf; do lexoid parse -i "$f" -o "out/${f%.pdf}.md"; done`).
- **Debug**: add `--verbose` to surface loguru logs to stderr.

## Failure modes to watch for

- Missing API key → CLI raises a clean error naming the env var. Set it and retry.
- DOCX on Linux without LibreOffice installed → conversion to PDF fails. Install `libreoffice`.
- `--model` and `--api` mismatch → use `--api` only to override an auto-inferred provider (e.g., to send a model through OpenRouter).
- Ollama: must run `ollama serve` and `ollama pull <model>` first; the CLI does not start the server.

## See also

- Full reference: `docs/cli.rst` and `docs/api.rst` in this repo.
- Python equivalent: `lexoid-python` skill.
