import base64
import io
import mimetypes
import os
import sys
from typing import List, Tuple

import cv2
import docx2pdf
import numpy as np
import pypdfium2 as pdfium
from PIL import Image
from PyQt5.QtCore import QMarginsF, QUrl
from PyQt5.QtGui import QPageLayout, QPageSize
from PyQt5.QtPrintSupport import QPrinter
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import QApplication


def convert_pdf_page_to_base64(
    pdf_document: pdfium.PdfDocument, page_number: int
) -> str:
    """Convert a PDF page to a base64-encoded PNG string."""
    page = pdf_document[page_number]
    # Render with 4x scaling for better quality
    pil_image = page.render(scale=4).to_pil()

    # Convert to base64
    img_byte_arr = io.BytesIO()
    pil_image.save(img_byte_arr, format="PNG")
    img_byte_arr.seek(0)
    return base64.b64encode(img_byte_arr.getvalue()).decode("utf-8")


def convert_doc_to_base64_images(path: str) -> List[Tuple[int, str]]:
    """
    Converts a document (PDF or image) to a base64 encoded string.

    Args:
        path (str): Path to the document.

    Returns:
        List[Tuple[int, str]]: A list of tuples where each tuple contains the page number
                               and the base64 encoded image string.
    """
    if path.endswith(".pdf"):
        pdf_document = pdfium.PdfDocument(path)
        images = [
            (
                page_num,
                f"data:image/png;base64,{convert_pdf_page_to_base64(pdf_document, page_num)}",
            )
            for page_num in range(len(pdf_document))
        ]
        pdf_document.close()
        return images
    elif mimetypes.guess_type(path)[0].startswith("image"):
        with open(path, "rb") as img_file:
            image_base64 = base64.b64encode(img_file.read()).decode("utf-8")
            return [(0, f"data:image/png;base64,{image_base64}")]


def base64_to_cv2_image(b64_string: str) -> np.ndarray:
    image_data = base64.b64decode(b64_string.split(",")[1])
    image = Image.open(io.BytesIO(image_data)).convert("L")  # grayscale
    return np.array(image)


def cv2_to_pil(cv2_image: np.ndarray) -> Image.Image:
    """Convert OpenCV image (BGR) to PIL (RGB)."""
    rgb = cv2.cvtColor(cv2_image, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def convert_image_to_pdf(image_path: str) -> bytes:
    with Image.open(image_path) as img:
        img_rgb = img.convert("RGB")
        pdf_buffer = io.BytesIO()
        img_rgb.save(pdf_buffer, format="PDF")
        return pdf_buffer.getvalue()


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
        docx2pdf.convert(input_path, temp_path)

    # Return the path of the converted PDF
    return temp_path


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
    file_type = mimetypes.guess_type(input_path)[0]
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
