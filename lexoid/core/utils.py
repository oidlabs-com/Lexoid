import asyncio
import io
import mimetypes
import os
import re
import sys
from difflib import SequenceMatcher
from typing import Dict, List, Union
from urllib.parse import urlparse

import nest_asyncio
import pikepdf
import pypdfium2
import requests
from bs4 import BeautifulSoup
from docx2pdf import convert
from loguru import logger
from markdown import markdown
from markdownify import markdownify as md
from PIL import Image
from PyQt5.QtCore import QMarginsF, QUrl
from PyQt5.QtGui import QPageLayout, QPageSize
from PyQt5.QtPrintSupport import QPrinter
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import QApplication

# Source: https://stackoverflow.com/a/12982689
HTML_TAG_PATTERN = re.compile("<.*?>|&([a-z0-9]+|#[0-9]{1,6}|#x[0-9a-f]{1,6});")


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


def convert_image_to_pdf(image_path: str) -> bytes:
    with Image.open(image_path) as img:
        img_rgb = img.convert("RGB")
        pdf_buffer = io.BytesIO()
        img_rgb.save(pdf_buffer, format="PDF")
        return pdf_buffer.getvalue()


def remove_html_tags(text: str):
    html = markdown(text, extensions=["tables"])
    return re.sub(HTML_TAG_PATTERN, "", html)


def calculate_similarity(text1: str, text2: str, ignore_html=True) -> float:
    """Calculate similarity ratio between two texts using SequenceMatcher."""
    if ignore_html:
        text1 = remove_html_tags(text1)
        text2 = remove_html_tags(text2)
    return SequenceMatcher(None, text1, text2).ratio()


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
    return mimetypes.guess_type(path)[0]


def is_supported_file_type(path: str) -> bool:
    """Check if the file type is supported for parsing."""
    file_type = get_file_type(path)
    if (
        file_type == "application/pdf"
        or "wordprocessing" in file_type
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
    response = requests.get(url)
    file_name = os.path.basename(urlparse(url).path)
    if not file_name:
        content_type = response.headers.get("Content-Type", "")
        ext = mimetypes.guess_extension(content_type)
        file_name = f"downloaded_file{ext}" if ext else "downloaded_file"

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


def split_md_by_headings(
    markdown_content: str, heading_pattern: str, title: str
) -> List[Dict]:
    """
    Splits markdown content by the specified heading pattern and structures it.

    Args:
        url (str): The URL of the HTML page
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
        sections = [section.strip() for section in sections if section.strip()]

        # Handle content before first heading if it exists
        if sections and not re.match(r"^[^\n]+\n-+$", sections[0], re.MULTILINE):
            structured_content.append(
                {
                    "metadata": {"title": title, "page": "Introduction"},
                    "content": sections.pop(0),
                }
            )

        # Process sections pairwise (heading, content)
        for i in range(0, len(sections), 2):
            if i + 1 < len(sections):
                structured_content.append(
                    {
                        "metadata": {"title": title, "page": sections[i]},
                        "content": sections[i + 1],
                    }
                )
    else:
        # Split by hash headings
        regex = f"^{heading_pattern} .*$"
        sections = re.split(regex, markdown_content, flags=re.MULTILINE)
        headings = re.findall(regex, markdown_content, flags=re.MULTILINE)

        # Remove empty sections and strip whitespace
        sections = [section.strip() for section in sections if section.strip()]

        # Handle content before first heading if it exists
        if len(sections) > len(headings):
            structured_content.append(
                {
                    "metadata": {"title": title, "page": "Introduction"},
                    "content": sections.pop(0),
                }
            )

        # Process remaining sections
        for heading, content in zip(headings, sections):
            clean_heading = heading.replace(heading_pattern, "").strip()
            structured_content.append(
                {
                    "metadata": {"title": title, "page": clean_heading},
                    "content": content,
                }
            )

    return structured_content


def html_to_markdown(html: str, raw: bool, title: str) -> str:
    """
    Converts HTML content to markdown.

    Args:
        html (str): The HTML content to convert.
        raw (bool): Whether to return raw markdown text or structured data.

    Returns:
        Union[str, List[Dict]]: Either raw markdown content or structured data with metadata and content sections.
    """
    markdown_content = md(html)

    if raw:
        return markdown_content

    # Find the dominant heading level
    heading_pattern = find_dominant_heading_level(markdown_content)

    # Split content by headings and structure it
    return split_md_by_headings(markdown_content, heading_pattern, title)


def read_html_content(url: str, raw: bool = False) -> Union[str, List[Dict]]:
    """
    Reads the content of an HTML page from the given URL and converts it to markdown or structured content.

    Args:
        url (str): The URL of the HTML page.
        raw (bool): Whether to return raw markdown text or structured data.

    Returns:
        Union[str, List[Dict]]: Either raw markdown content or structured data with metadata and content sections.
    """

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
                await page.wait_for_load_state("networkidle")

                # Additional wait for any dynamic content
                try:
                    await page.wait_for_selector("body", timeout=30000)
                except:
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
    return html_to_markdown(str(soup), raw, title=url)


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


def recursive_read_html(
    url: str, depth: int, raw: bool, visited_urls: set = None
) -> Union[str, List[Dict]]:
    """
    Recursively reads HTML content from URLs up to specified depth.

    Args:
        url (str): The URL to parse
        depth (int): How many levels deep to recursively parse
        raw (bool): Whether to return raw text or structured data
        visited_urls (set): Set of already visited URLs to prevent cycles

    Returns:
        Union[str, List[Dict]]: Combined content from all parsed URLs
    """
    if visited_urls is None:
        visited_urls = set()

    if url in visited_urls:
        return "" if raw else []

    visited_urls.add(url)

    try:
        content = read_html_content(url, raw)
    except Exception as e:
        print(f"Error processing URL {url}: {str(e)}")
        return "" if raw else []

    if depth <= 1:
        return content

    # Extract URLs from the content
    if raw:
        urls = extract_urls_from_markdown(content)
    else:
        # Extract URLs from all content sections
        urls = []
        for doc in content:
            urls.extend(extract_urls_from_markdown(doc["content"]))

    # Recursively process each URL
    for sub_url in urls:
        if sub_url not in visited_urls:
            sub_content = recursive_read_html(sub_url, depth - 1, raw, visited_urls)

            if raw:
                if sub_content:
                    content += f"\n\n--- Begin content from {sub_url} ---\n\n"
                    content += sub_content
                    content += f"\n\n--- End content from {sub_url} ---\n\n"
            else:
                if isinstance(sub_content, list):
                    content.extend(sub_content)

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
    app = QApplication(sys.argv)
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


def router(path: str):
    file_type = get_file_type(path)
    if file_type.startswith("text/"):
        return "STATIC_PARSE"
    # Naive routing strategy for now.
    # Current routing strategy,
    # 1. If the PDF has hidden hyperlinks (as alias) and no images: STATIC_PARSE
    # 2. Other scenarios: LLM_PARSE
    # If you have other needs, do reach out or create an issue.
    if (
        file_type == "application/pdf"
        and not has_image_in_pdf(path)
        and has_hyperlink_in_pdf(path)
    ):
        return "STATIC_PARSE"
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
