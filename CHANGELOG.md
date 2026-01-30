# Change Log

## [0.1.1] - 2024-10-28

### Added
- Support for URL parsing

### Changed

### Fixed

## [0.1.2] - 2024-11-04

### Added
- Initial testing code
- Benchmarking code

### Changed
- Improvements in OpenAI prompt
- Conversion of PDFs to images before parsing with OpenAI models

### Fixed


## [0.1.3] - 2024-11-12

### Added
- `AUTO` parse mode

### Changed
- Switch from multithreading to multiprocessing

### Fixed

## [0.1.4] - 2024-11-22

### Added
- Support for structured parsing of HTML pages
- Support for recursive URL parsing in websites and PDFs

### Changed
- URL extraction regex

### Fixed
- Bug in document appending logic
- Bug caused by split pdfs being in same dir as source pdf

## [0.1.5] - 2024-12-06

### Added

### Changed
- Improved pdfplumber parsing to format markdown and detect hyperlinks

### Fixed

## [0.1.6] - 2024-12-10

### Added
* Support for parsing .csv, .txt, and .html, and .docx files
* Support for parsing links to documents when recursive HTML parsing

### Changed

### Fixed

## [0.1.7] - 2025-01-08

### Added
* Colab example notebook
* Support for bold and italic formatting in PDFPlumber
* Support for Llama 3.2 models through HuggingFace and Together AI

### Changed
* Improved PDFPlumber table parsing

### Fixed
* PDFPlumber text detection bug

## [0.1.8] - 2025-01-23

### Added
* Retry and error handling for LLM_PARSE

### Changed
* Remove together Python client dependency and use REST API calls instead

## [0.1.8.post1] - 2025-01-28

### Added
* Documentation

### Changed
* Specify headers for Playwright web page retrieval

## [0.1.9] - 2025-02-17

### Added
- Parameters to specify intermediate PDF save path when `as_pdf=True`.
- Return `token_uage` and `pdf_path` with `parse()` output where applicable

### Changed
- Switched back to together Python client
- Improved `parse()` function return format to be a dictionary.


## [0.1.10] - 2025-02-23

### Added
- Parameter to specify page numbers for parsing

### Fixed
- Errors caused by empty token_usage

## [0.1.11] - 2025-02-27

### Added
- Priority setting to AUTO routing
- More models to benchmark

### Changed
- Set default parse_type to AUTO
- Set default LLM to Gemini 2.0 Flash
- Updated benchmark script to aggregate over multiple runs

### Fixed
- Incorrect title when `as_pdf=True`


## [0.1.11.post1] - 2025-03-05

### Added
- Code of Conduct

### Fixed
- Segmentation fault when PyQT app is reinitialized

## [0.1.12] - 2025-04-11

### Added
* Support for OpenRouter models
* Return token cost when cost mapping is provided
* Support for custom prompts
* Support for parsing Excel and PowerPoint files

### Changed
* Set default `router_priority` to `speed`

## [0.1.13] - 2025-04-20

### Added
* `STATIC_PARSE` improvements
    * Horizontal line detection
    * Strikethrough text detection
    * Email address formatting
    * Improved heading level detection
    * Monospace font detection
    * Indentation detection

## [0.1.14] - 2025-06-05

### Added
* Support for Fireworks API
* Support for matching data in document to pre-defined schema or template

## [0.1.15] - 2025-06-28

### Added
* Gemini support to `parse_with_schema`
* Support for Anthropic models
* Fallback to different parser in AUTO mode or STATIC mode

### Changed
* Update benchmark logic and benchmark

## [0.1.16]

### Added
* Support for SmolDocling
* Support for Mistral OCR models

### Changed
* Update benchmark code and add more metrics

### Fixed
* Set thinking budget to fix gemini-2.5-pro thinking for too long

## [0.1.17]

### Added
* Support for `dataclass` in parse_with_schema function

### Changed
* Upgrade Anthropic version

### Fixed
* Check for `title` attribute in web pages
* Fix arxiv URL parsing
* Handle invalid bytes when text parsing

## [0.1.18]

### Added
* Option for autoselecting the LLM based on clustering against benchmark documents (`autoselect_llm`)
* Support for returning bboxes and reference highlighting in `STATIC_PARSE`
* Function to parse documents into Latex
* Support for OCR via PaddleOCR and extraction of bboxes in `LLM_PARSE`

### Fixed
* Switch from `os.system()` to `subprocess.run()` to avoid injection via doc path

## [0.1.19]

### Added
* Support for granite docling
* Support for providing example values or alternate keys for `parse_with_schema` function
* Support for audio to markdown
* AUTO routing with cost priority

### Changed
* Improved PaddleOCR efficiency by skipping conversion to images

### Fixed
* STATIC_PARSE for images