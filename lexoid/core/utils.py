import asyncio
import dataclasses
import io
import mimetypes
import os
import re
import sys
from dataclasses import fields, is_dataclass
from hashlib import md5
from typing import Dict, List, Optional, Type, Union
from urllib.parse import urlparse

import nest_asyncio
import pikepdf
import pypdfium2
import requests
from bs4 import BeautifulSoup
from docx2pdf import convert
from loguru import logger
from markdownify import markdownify as md
from PIL import Image
from PyQt5.QtCore import QMarginsF, QUrl
from PyQt5.QtGui import QPageLayout, QPageSize
from PyQt5.QtPrintSupport import QPrinter
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import QApplication


def split_pdf(input_path: str, output_dir: str, pages_per_split: int):
    paths = []
    with pikepdf.open(input_path) as pdf:
        total_pages = len(pdf.pages)
        for start in range(0, total_pages, pages_per_split):
            end = min(start + pages_per_split, total_pages)
            output_path = os.path.join(
                output_dir, f"split_{str(start + 1).zfill(4)}_{end}.pdf"
            )
            with pikepdf.new() as new_pdf:
                new_pdf.pages.extend(pdf.pages[start:end])
                new_pdf.save(output_path)
                paths.append(output_path)
    return paths


def create_sub_pdf(
    input_path: str, output_path: str, page_nums: Optional[tuple[int, ...] | int] = None
) -> str:
    if isinstance(page_nums, int):
        page_nums = (page_nums,)
    page_nums = tuple(sorted(set(page_nums)))
    with pikepdf.open(input_path) as pdf:
        indices = page_nums if page_nums else range(len(pdf.pages))
        with pikepdf.new() as new_pdf:
            new_pdf.pages.extend([pdf.pages[i - 1] for i in indices])
            new_pdf.save(output_path)
    return output_path


def convert_image_to_pdf(image_path: str) -> bytes:
    with Image.open(image_path) as img:
        img_rgb = img.convert("RGB")
        pdf_buffer = io.BytesIO()
        img_rgb.save(pdf_buffer, format="PDF")
        return pdf_buffer.getvalue()


def convert_pdf_page_to_image(
    pdf_document: pypdfium2.PdfDocument, page_number: int
) -> bytes:
    """Convert a PDF page to an image."""
    page = pdf_document[page_number]
    # Render with 4x scaling for better quality
    pil_image = page.render(scale=4).to_pil()

    # Convert to bytes
    img_byte_arr = io.BytesIO()
    pil_image.save(img_byte_arr, format="PNG")
    img_byte_arr.seek(0)
    return img_byte_arr.getvalue()


def get_file_type(path: str) -> str:
    """Get the file type of a file based on its extension."""
    return mimetypes.guess_type(path)[0] or ""


def is_supported_file_type(path: str) -> bool:
    """Check if the file type is supported for parsing."""
    file_type = get_file_type(path)
    logger.debug(f"File type: {file_type}")
    if (
        file_type == "application/pdf"
        or "wordprocessing" in file_type
        or "spreadsheet" in file_type
        or "presentation" in file_type
        or file_type.startswith("image/")
        or file_type.startswith("text")
    ):
        return True
    return False


def is_supported_url_file_type(url: str) -> bool:
    """
    Check if the file type from the URL is supported.

    Args:
        url (str): The URL of the file.

    Returns:
        bool: True if the file type is supported, False otherwise.
    """
    supported_extensions = [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif"]
    parsed_url = urlparse(url)
    ext = os.path.splitext(parsed_url.path)[1].lower()

    if ext in supported_extensions:
        return True

    # If no extension in URL, try to get content type from headers
    try:
        response = requests.head(url)
    except requests.exceptions.ConnectionError:
        return False
    content_type = response.headers.get("Content-Type", "")
    ext = mimetypes.guess_extension(content_type)

    return ext in supported_extensions


def download_file(url: str, temp_dir: str) -> str:
    """
    Downloads a file from the given URL and saves it to a temporary directory.

    Args:
        url (str): The URL of the file to download.
        temp_dir (str): The temporary directory to save the file.

    Returns:
        str: The path to the downloaded file.
    """
    supported_extensions = [".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif"]
    response = requests.get(url)
    file_name = os.path.basename(urlparse(url).path)
    ext = os.path.splitext(file_name)[1].lower()
    if ext not in supported_extensions:
        ext = None

    if not file_name or not ext:
        content_type = response.headers.get("Content-Type", "")
        ext = mimetypes.guess_extension(content_type)
        if not file_name:
            file_name = f"downloaded_file{ext}" if ext else "downloaded_file"
        else:
            file_name = f"{file_name}{ext}" if ext else file_name

    file_path = os.path.join(temp_dir, file_name)
    with open(file_path, "wb") as f:
        f.write(response.content)
    return file_path


def find_dominant_heading_level(markdown_content: str) -> str:
    """
    Finds the most common heading level that occurs more than once.
    Also checks for underline style headings (---).

    Args:
        markdown_content (str): The markdown content to analyze

    Returns:
        str: The dominant heading pattern (e.g., '##' or 'underline')
    """
    # Check for underline style headings first
    underline_pattern = r"^[^\n]+\n-+$"
    underline_matches = re.findall(underline_pattern, markdown_content, re.MULTILINE)
    if len(underline_matches) > 1:
        return "underline"

    # Find all hash-style headings in the markdown content
    heading_patterns = ["#####", "####", "###", "##", "#"]
    heading_counts = {}

    for pattern in heading_patterns:
        # Look for headings at the start of a line
        regex = f"^{pattern} .*$"
        matches = re.findall(regex, markdown_content, re.MULTILINE)
        if len(matches) > 1:  # Only consider headings that appear more than once
            heading_counts[pattern] = len(matches)

    if not heading_counts:
        return "#"  # Default to h1 if no repeated headings found

    return min(heading_counts.keys(), key=len)


def split_md_by_headings(markdown_content: str, heading_pattern: str) -> List[Dict]:
    """
    Splits markdown content by the specified heading pattern and structures it.

    Args:
        markdown_content (str): The markdown content to split
        heading_pattern (str): The heading pattern to split on (e.g., '##' or 'underline')

    Returns:
        List[Dict]: List of dictionaries containing metadata and content
    """
    structured_content = []

    if heading_pattern == "underline":
        # Split by underline headings
        pattern = r"^([^\n]+)\n-+$"
        sections = re.split(pattern, markdown_content, flags=re.MULTILINE)
        # Remove empty sections and strip whitespace
        sections = [section.strip() for section in sections]

        # Handle content before first heading if it exists
        if sections and not re.match(r"^[^\n]+\n-+$", sections[0], re.MULTILINE):
            structured_content.append(
                {
                    "metadata": {"page": "Introduction"},
                    "content": sections.pop(0),
                }
            )

        # Process sections pairwise (heading, content)
        for i in range(0, len(sections), 2):
            if i + 1 < len(sections):
                structured_content.append(
                    {
                        "metadata": {"page": sections[i]},
                        "content": sections[i + 1],
                    }
                )
    else:
        # Split by hash headings
        regex = f"^{heading_pattern} .*$"
        sections = re.split(regex, markdown_content, flags=re.MULTILINE)
        headings = re.findall(regex, markdown_content, flags=re.MULTILINE)

        # Remove empty sections and strip whitespace
        sections = [section.strip() for section in sections]

        # Handle content before first heading if it exists
        if len(sections) > len(headings):
            structured_content.append(
                {
                    "metadata": {"page": "Introduction"},
                    "content": sections.pop(0),
                }
            )

        # Process remaining sections
        for heading, content in zip(headings, sections):
            clean_heading = heading.replace(heading_pattern, "").strip()
            structured_content.append(
                {
                    "metadata": {"page": clean_heading},
                    "content": content,
                }
            )

    return structured_content


def html_to_markdown(html: str, title: str, url: str) -> str:
    """
    Converts HTML content to markdown.

    Args:
        html (str): The HTML content to convert.
        title (str): The title of the HTML page
        url (str): The URL of the HTML page

    Returns:
        Dict: Dictionary containing parsed document data
    """
    markdown_content = md(html)

    # Find the dominant heading level
    heading_pattern = find_dominant_heading_level(markdown_content)

    # Split content by headings and structure it
    split_md = split_md_by_headings(markdown_content, heading_pattern)

    content = {
        "raw": markdown_content,
        "segments": split_md,
        "title": title,
        "url": url,
        "parent_title": "",
        "recursive_docs": [],
    }

    return content


def get_webpage_soup(url: str) -> BeautifulSoup:
    try:
        from playwright.async_api import async_playwright

        nest_asyncio.apply()

        async def fetch_page():
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--window-size=1920,1080",
                    ],
                )
                context = await browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    bypass_csp=True,
                )
                page = await context.new_page()

                # Add headers to appear more like a real browser
                await page.set_extra_http_headers(
                    {
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.5",
                        "Sec-Fetch-Dest": "document",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-Site": "none",
                        "Sec-Fetch-User": "?1",
                    }
                )

                await page.goto(url)

                # Wait for Cloudflare check to complete
                await page.wait_for_load_state("domcontentloaded")

                # Additional wait for any dynamic content
                try:
                    await page.wait_for_selector("body", timeout=30000)
                except Exception:
                    pass

                html = await page.content()
                await browser.close()
                return html

        loop = asyncio.get_event_loop()
        html = loop.run_until_complete(fetch_page())
        soup = BeautifulSoup(html, "html.parser")
    except Exception as e:
        logger.debug(
            f"Error reading HTML content from URL, attempting with default https request: {str(e)}"
        )
        response = requests.get(url)
        soup = BeautifulSoup(
            response.content, "html.parser", from_encoding="iso-8859-1"
        )
    return soup


def read_html_content(url: str) -> Dict:
    """
    Reads the content of an HTML page from the given URL and converts it to markdown or structured content.

    Args:
        url (str): The URL of the HTML page.

    Returns:
        Dict: Dictionary containing parsed document data
    """

    soup = get_webpage_soup(url)
    title = soup.title.string.strip() if soup.title else "No title"
    url_hash = md5(url.encode("utf-8")).hexdigest()[:8]
    full_title = f"{title} - {url_hash}"
    return html_to_markdown(str(soup), title=full_title, url=url)


def extract_urls_from_markdown(content: str) -> List[str]:
    """
    Extracts URLs from markdown content using regex.
    Matches both [text](url) and bare http(s):// URLs.

    Args:
        content (str): Markdown content to search for URLs

    Returns:
        List[str]: List of unique URLs found
    """
    # Match markdown links [text](url) and bare URLs
    markdown_pattern = r"\[([^\]]+)\]\((https?://[^\s\)]+)\)"
    bare_url_pattern = r"(?<!\()(https?://[^\s\)]+)"

    urls = []
    # Extract URLs from markdown links
    urls.extend(match.group(2) for match in re.finditer(markdown_pattern, content))
    # Extract bare URLs
    urls.extend(match.group(0) for match in re.finditer(bare_url_pattern, content))

    return list(set(urls))  # Remove duplicates


def recursive_read_html(url: str, depth: int, visited_urls: set = None) -> Dict:
    """
    Recursively reads HTML content from URLs up to specified depth.

    Args:
        url (str): The URL to parse
        depth (int): How many levels deep to recursively parse
        visited_urls (set): Set of already visited URLs to prevent cycles

    Returns:
        Dict: Dictionary containing parsed document data
    """
    if visited_urls is None:
        visited_urls = set()

    if url in visited_urls:
        return {
            "raw": "",
            "segments": [],
            "title": "",
            "url": url,
            "parent_title": "",
            "recursive_docs": [],
        }

    visited_urls.add(url)

    try:
        content = read_html_content(url)
    except Exception as e:
        print(f"Error processing URL {url}: {str(e)}")
        return {
            "raw": "",
            "segments": [],
            "title": "",
            "url": url,
            "parent_title": "",
            "recursive_docs": [],
        }

    if depth <= 1:
        return content

    # Extract URLs from all content sections
    urls = extract_urls_from_markdown(content["raw"])

    # Recursively process each URL
    recursive_docs = []
    for sub_url in urls:
        if sub_url not in visited_urls:
            sub_content = recursive_read_html(sub_url, depth - 1, visited_urls)
            recursive_docs.append(sub_content)

    content["recursive_docs"] = recursive_docs
    return content


def save_webpage_as_pdf(url: str, output_path: str) -> str:
    """
    Saves a webpage as a PDF file using PyQt5.

    Args:
        url (str): The URL of the webpage.
        output_path (str): The path to save the PDF file.

    Returns:
        str: The path to the saved PDF file.
    """
    if not QApplication.instance():
        app = QApplication(sys.argv)
    else:
        app = QApplication.instance()
    web = QWebEngineView()
    web.load(QUrl(url))

    def handle_print_finished(filename, status):
        print(f"PDF saved to: {filename}")
        app.quit()

    def handle_load_finished(status):
        if status:
            printer = QPrinter(QPrinter.HighResolution)
            printer.setOutputFormat(QPrinter.PdfFormat)
            printer.setOutputFileName(output_path)

            page_layout = QPageLayout(
                QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(15, 15, 15, 15)
            )
            printer.setPageLayout(page_layout)

            web.page().printToPdf(output_path)
            web.page().pdfPrintingFinished.connect(handle_print_finished)

    web.loadFinished.connect(handle_load_finished)
    app.exec_()

    return output_path


def convert_to_pdf(input_path: str, output_path: str) -> str:
    """
    Converts a file or webpage to PDF.

    Args:
        input_path (str): The path to the input file or URL.
        output_path (str): The path to save the output PDF file.

    Returns:
        str: The path to the saved PDF file.
    """
    if input_path.startswith(("http://", "https://")):
        return save_webpage_as_pdf(input_path, output_path)
    file_type = get_file_type(input_path)
    if file_type.startswith("image/"):
        img_data = convert_image_to_pdf(input_path)
        with open(output_path, "wb") as f:
            f.write(img_data)
    elif "word" in file_type:
        return convert_doc_to_pdf(input_path, os.path.dirname(output_path))
    else:
        # Assume it's already a PDF, just copy it
        with open(input_path, "rb") as src, open(output_path, "wb") as dst:
            dst.write(src.read())

    return output_path


def has_image_in_pdf(path: str):
    with open(path, "rb") as fp:
        content = fp.read()
    return "Image".lower() in list(
        map(lambda x: x.strip(), (str(content).lower().split("/")))
    )


def has_hyperlink_in_pdf(path: str):
    with open(path, "rb") as fp:
        content = fp.read()
    # URI tag is used if Links are hidden.
    return "URI".lower() in list(
        map(lambda x: x.strip(), (str(content).lower().split("/")))
    )


def router(path: str, priority: str = "speed") -> str:
    """
    Routes the file path to the appropriate parser based on the file type.

    Args:
        path (str): The file path to route.
        priority (str): The priority for routing: "accuracy" (preference to LLM_PARSE) or "speed" (preference to STATIC_PARSE).
    """
    file_type = get_file_type(path)
    if (
        file_type.startswith("text/")
        or "spreadsheet" in file_type
        or "presentation" in file_type
    ):
        return "STATIC_PARSE"

    if priority == "accuracy":
        # If the file is a PDF without images but has hyperlinks, use STATIC_PARSE
        # Otherwise, use LLM_PARSE
        has_image = has_image_in_pdf(path)
        has_hyperlink = has_hyperlink_in_pdf(path)
        if file_type == "application/pdf" and not has_image and has_hyperlink:
            logger.debug("Using STATIC_PARSE for PDF with hyperlinks and no images.")
            return "STATIC_PARSE"
        logger.debug(
            f"Using LLM_PARSE because PDF has image ({has_image}) or has no hyperlink ({has_hyperlink})."
        )
        return "LLM_PARSE"
    else:
        # If the file is a PDF without images, use STATIC_PARSE
        # Otherwise, use LLM_PARSE
        if file_type == "application/pdf" and not has_image_in_pdf(path):
            logger.debug("Using STATIC_PARSE for PDF without images.")
            return "STATIC_PARSE"
        logger.debug("Using LLM_PARSE because PDF has images")
        return "LLM_PARSE"


def convert_doc_to_pdf(input_path: str, temp_dir: str) -> str:
    temp_path = os.path.join(
        temp_dir, os.path.splitext(os.path.basename(input_path))[0] + ".pdf"
    )

    # Convert the document to PDF
    # docx2pdf is not supported in linux. Use LibreOffice in linux instead.
    # May need to install LibreOffice if not already installed.
    if "linux" in sys.platform.lower():
        os.system(
            f'lowriter --headless --convert-to pdf --outdir {temp_dir} "{input_path}"'
        )
    else:
        convert(input_path, temp_path)

    # Return the path of the converted PDF
    return temp_path


def get_uri_rect(path):
    with open(path, "rb") as fp:
        byte_str = str(fp.read())
    pattern = r"\((https?://[^\s)]+)\)"
    uris = re.findall(pattern, byte_str)
    rect_splits = byte_str.split("/Rect [")[1:]
    rects = [
        list(map(float, rect_split.split("]")[0].split())) for rect_split in rect_splits
    ]
    return {uri: rect for uri, rect in zip(uris, rects)}


def convert_schema_to_dict(schema: Union[Dict, Type]) -> Dict:
    """
    Convert a dataclass type or existing dict schema to a JSON schema dictionary.

    Args:
        schema: Either a dictionary (JSON schema) or a dataclass type

    Returns:
        Dict: JSON schema dictionary
    """
    if isinstance(schema, dict):
        return schema

    # Handle dataclass types
    if hasattr(schema, "__dataclass_fields__"):
        return _dataclass_to_json_schema(schema)

    raise ValueError(f"Unsupported schema type: {type(schema)}")


def _dataclass_to_json_schema(dataclass_type: Type) -> Dict:
    """
    Convert a dataclass type to a JSON schema dictionary.

    Args:
        dataclass_type: A dataclass type

    Returns:
        Dict: JSON schema representation
    """
    properties = {}
    required_fields = []

    for field in fields(dataclass_type):
        field_schema = _get_field_json_schema(field)
        properties[field.name] = field_schema

        # Check if field is required (no default value)
        # Fixed: Use dataclasses.MISSING instead of dataclass.MISSING
        if field.default == field.default_factory == dataclasses.MISSING:
            required_fields.append(field.name)

    schema = {"type": "object", "properties": properties}

    if required_fields:
        schema["required"] = required_fields

    return schema


def _get_field_json_schema(field) -> Dict:
    """
    Convert a dataclass field to JSON schema property definition.
    """
    field_type = field.type

    # Handle basic types
    if field_type is str:
        return {"type": "string"}
    elif field_type is int:
        return {"type": "integer"}
    elif field_type is float:
        return {"type": "number"}
    elif field_type is bool:
        return {"type": "boolean"}
    elif field_type is list:
        return {"type": "array"}
    elif field_type is dict:
        return {"type": "object"}

    if is_dataclass(field_type):
        return _dataclass_to_json_schema(field_type)

    # Handle typing module types
    origin = getattr(field_type, "__origin__", None)
    args = getattr(field_type, "__args__", ())

    if origin is Union:
        if len(args) == 2 and type(None) in args:
            non_none_type = next(arg for arg in args if arg is not type(None))
            base_schema = _type_to_json_schema(non_none_type)
            return base_schema
        return {"anyOf": [_type_to_json_schema(arg) for arg in args]}
    elif origin is list:
        item_type = args[0] if args else str
        return {"type": "array", "items": _type_to_json_schema(item_type)}
    elif origin is dict:
        return {"type": "object"}

    # Fallback
    return {"type": "string"}


def _type_to_json_schema(python_type) -> Dict:
    """Convert a Python type to JSON schema type definition."""
    if python_type is str:
        return {"type": "string"}
    elif python_type is int:
        return {"type": "integer"}
    elif python_type is float:
        return {"type": "number"}
    elif python_type is bool:
        return {"type": "boolean"}
    elif python_type is list:
        return {"type": "array"}
    elif python_type is dict:
        return {"type": "object"}
    elif is_dataclass(python_type):  # Add this check
        return _dataclass_to_json_schema(python_type)
    else:
        return {"type": "string"}  # Default fallback
