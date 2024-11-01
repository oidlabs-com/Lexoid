import os
import io
import re
import pikepdf
import pypdfium2
import requests
from PIL import Image
from bs4 import BeautifulSoup
from difflib import SequenceMatcher
from urllib.parse import urlparse
from markdownify import markdownify as md
import mimetypes
import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QUrl, QMarginsF
from PyQt5.QtGui import QPageLayout, QPageSize
from PyQt5.QtPrintSupport import QPrinter
from PyQt5.QtWebEngineWidgets import QWebEngineView


HTML_TAG_PATTERN = re.compile("<.*?>|&([a-z0-9]+|#[0-9]{1,6}|#x[0-9a-f]{1,6});")


def split_pdf(input_path: str, output_dir: str, pages_per_split: int):
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


def convert_image_to_pdf(image_path: str) -> bytes:
    with Image.open(image_path) as img:
        img_rgb = img.convert("RGB")
        pdf_buffer = io.BytesIO()
        img_rgb.save(pdf_buffer, format="PDF")
        return pdf_buffer.getvalue()


def remove_html_tags(text: str):
    return re.sub(HTML_TAG_PATTERN, "", text)


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


def is_supported_file_type(url: str) -> bool:
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
    response = requests.head(url)
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


def read_html_content(url: str) -> str:
    """
    Reads the content of an HTML page from the given URL and converts it to markdown.

    Args:
        url (str): The URL of the HTML page.

    Returns:
        str: The markdown content of the HTML page.
    """
    response = requests.get(url)
    soup = BeautifulSoup(response.content, "html.parser")
    return md(str(soup))


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
    elif input_path.lower().endswith(
        (".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif")
    ):
        img_data = convert_image_to_pdf(input_path)
        with open(output_path, "wb") as f:
            f.write(img_data)
    else:
        # Assume it's already a PDF, just copy it
        with open(input_path, "rb") as src, open(output_path, "wb") as dst:
            dst.write(src.read())

    return output_path
