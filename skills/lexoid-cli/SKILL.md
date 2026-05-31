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
   - Ollama needs no key, but needs `ollama serve` running at `OLLAMA_BASE_URL` (default `http://localhost:11434`) and the target model pulled (`ollama pull <model>`).
   - Local backends (SmolDocling/granite-docling, PaddleOCR-VL) need no key and no server — they run in-process; the first call downloads weights from Hugging Face.
3. For Linux DOCX → PDF, LibreOffice (`lowriter`) must be installed.

### Loading API keys from `.env`

API keys are commonly stored in a `.env` file at the project root rather than exported in the shell. The `lexoid` CLI does **not** auto-load `.env`, so for any LLM-based command (`LLM_PARSE`, `schema`, `latex`, or `AUTO` when it routes to an LLM) you must load it yourself.

**Always load `.env` in a subshell so the keys never leak into the surrounding environment** — the parentheses scope the `export`s to that one command, restoring the environment to its previous state automatically afterward. Guard the source with `[ -f .env ]` so the command still runs (using already-exported keys) when no `.env` is present:

```bash
# Load .env for this command only (if it exists); env is reset to its prior state on exit
( set -a; [ -f .env ] && . ./.env; set +a; lexoid parse --input document.pdf --parser-type LLM_PARSE --model gpt-4o )
```

Do **not** run a bare `set -a; . ./.env; set +a` in the parent shell — that persists secrets into the session.

**The examples in the rest of this skill are written as plain `lexoid …` for readability.** Apply the wrapper above to any LLM-based command (`LLM_PARSE`, `schema`, `latex`, or `AUTO` when it routes to an LLM). If your keys are already exported in the environment, run the commands as-is.

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

# Explicit LLM parsing (forces an LLM regardless of routing). LLM-based: load .env first.
lexoid parse --input document.pdf --parser-type LLM_PARSE --model gpt-4o
lexoid parse --input document.pdf --parser-type LLM_PARSE --model claude-3-5-sonnet-20241022
lexoid parse --input scanned.pdf --parser-type LLM_PARSE --model mistral-ocr-latest

# Force static parsing (no LLM, no API key needed for PDFs)
lexoid parse --input document.pdf --parser-type STATIC_PARSE --framework pdfplumber

# Parse a URL
lexoid parse --input https://example.com --output page.md

# Tune chunking / parallelism
lexoid parse --input big.pdf --pages-per-split 8 --max-processes 8
```

Key flags: `--parser-type` (`AUTO`/`LLM_PARSE`/`STATIC_PARSE`), `--model`, `--framework` (`pdfplumber`/`paddleocr`), `--api` (override provider), `--format` (`markdown`/`json`), `--pages-per-split`, `--max-processes`, `--verbose`.

### `lexoid schema` — Structured extraction

Extract data conforming to a JSON schema. Schema can be a file path or inline JSON.

All `schema` commands are LLM-based — load `.env` first (see "Loading API keys from .env") unless keys are already exported.

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

LaTeX conversion is LLM-based — load `.env` first (see "Loading API keys from .env") unless keys are already exported.

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

- **Default to `AUTO`**: with no `--parser-type`, the CLI uses `AUTO`, which inspects the document and routes to the best parser (often an LLM for scans, charts, or complex tables). This is the right choice unless the user asks otherwise.
- **`STATIC_PARSE` is opt-in, not the default**: choose it when the user explicitly wants no API calls / no cost, or you know the input is a clean native-text PDF. It returns empty output on scanned/image-only pages, so it is not a safe first guess for unknown documents.
- **`LLM_PARSE` for quality**: force it with `--parser-type LLM_PARSE --model <model>` for scans, chart/figure-heavy pages, or messy tables where layout fidelity matters.
- **Scanned PDFs / images**: use `--parser-type STATIC_PARSE --framework paddleocr` (no API key) or an LLM model with vision.
- **Batch**: drive the CLI from a shell loop (`for f in inputs/*.pdf; do lexoid parse -i "$f" -o "out/${f%.pdf}.md"; done`).
- **Debug**: add `--verbose` to surface loguru logs to stderr.

## Failure modes to watch for

- Missing API key → CLI raises a clean error naming the env var. The CLI does not auto-load `.env`; load it via the subshell wrapper (see "Loading API keys from .env") and retry.
- DOCX on Linux without LibreOffice installed → conversion to PDF fails. Install `libreoffice`.
- `--model` and `--api` mismatch → use `--api` only to override an auto-inferred provider (e.g., to send a model through OpenRouter).
- Ollama: must run `ollama serve` and `ollama pull <model>` first; the CLI does not start the server.

## See also

- Full reference: `docs/cli.rst` and `docs/api.rst` in this repo.
- Python equivalent: `lexoid-python` skill.
