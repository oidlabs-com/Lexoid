import base64
import dataclasses
import io
import mimetypes
import os
import sys
from typing import Dict, List, Tuple, Type, Union

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


def base64_to_bytesio(b64_string: str) -> io.BytesIO:
    image_data = base64.b64decode(b64_string.split(",")[1])
    return io.BytesIO(image_data)


def base64_to_pil_image(b64_string: str) -> Image.Image:
    return Image.open(base64_to_bytesio(b64_string))


def base64_to_cv2_image(b64_string: str, gray_scale: bool = True) -> np.ndarray:
    pil_image = base64_to_pil_image(b64_string)
    if gray_scale:
        image = pil_image.convert("L")
        return np.array(image)
    else:
        return np.array(pil_image)


def cv2_to_pil(cv2_image: np.ndarray) -> Image.Image:
    """Convert OpenCV image (BGR or grayscale) to PIL (RGB or L)."""
    if cv2_image.ndim == 2 or (cv2_image.ndim == 3 and cv2_image.shape[2] == 1):
        # Grayscale image
        return Image.fromarray(cv2_image)
    else:
        # Color image (BGR)
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

    for field in dataclasses.fields(dataclass_type):
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

    if dataclasses.is_dataclass(field_type):
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
    elif dataclasses.is_dataclass(python_type):  # Add this check
        return _dataclass_to_json_schema(python_type)
    else:
        return {"type": "string"}  # Default fallback
