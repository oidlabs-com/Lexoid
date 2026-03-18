import base64
import dataclasses
import io
import mimetypes
import os
import subprocess
import sys
from typing import Any, Dict, List, Tuple, Type, Union, get_args, get_origin

import cv2
import docx2pdf
import numpy as np
import pypdfium2 as pdfium
from loguru import logger
from PIL import Image
from pydantic import BaseModel
from PyQt5.QtCore import QMarginsF, QUrl
from PyQt5.QtGui import QPageLayout, QPageSize
from PyQt5.QtPrintSupport import QPrinter
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtWidgets import QApplication


def convert_pdf_page_to_base64(
    pdf_document: pdfium.PdfDocument, page_number: int, max_dimension: int = 1500
) -> str:
    """Convert a PDF page to a base64-encoded PNG string."""
    page = pdf_document[page_number]
    pil_image = page.render(scale=1).to_pil()

    # Resize image if too large
    if pil_image.width > max_dimension or pil_image.height > max_dimension:
        scaling_factor = min(
            max_dimension / pil_image.width, max_dimension / pil_image.height
        )
        new_size = (
            int(pil_image.width * scaling_factor),
            int(pil_image.height * scaling_factor),
        )
        pil_image = pil_image.resize(new_size, Image.Resampling.LANCZOS)
        logger.debug(f"Resized page {page_number} to {new_size} for base64 conversion.")

    # Convert to base64
    img_byte_arr = io.BytesIO()
    pil_image.save(img_byte_arr, format="PNG")
    img_byte_arr.seek(0)
    return base64.b64encode(img_byte_arr.getvalue()).decode("utf-8")


def convert_doc_to_base64_images(
    path: str, max_dimension: int = 1500
) -> List[Tuple[int, str]]:
    """
    Converts a document (PDF or image) to a base64 encoded string.

    Args:
        path (str): Path to the document.
        max_dimension (int): Maximum dimension (width or height) for the output images. Default is 1500.

    Returns:
        List[Tuple[int, str]]: A list of tuples where each tuple contains the page number
                               and the base64 encoded image string.
    """
    if path.endswith(".pdf"):
        pdf_document = pdfium.PdfDocument(path)
        images = [
            (
                page_num,
                f"data:image/png;base64,{convert_pdf_page_to_base64(pdf_document, page_num, max_dimension)}",
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


def base64_to_np_array(b64_string: str, gray_scale: bool = True) -> np.ndarray:
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
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
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
        subprocess.run(
            [
                "lowriter",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                temp_dir,
                input_path,
            ],
            check=True,
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
        logger.debug(f"Converting webpage {input_path} to PDF...")
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
    Convert a dict, dataclass, or Pydantic BaseModel into JSON schema.
    """
    if isinstance(schema, dict):
        return schema

    if dataclasses.is_dataclass(schema):
        return _dataclass_to_json_schema(schema)

    if BaseModel and isinstance(schema, type) and issubclass(schema, BaseModel):
        return _pydantic_to_json_schema(schema)

    raise TypeError("Schema must be dict, dataclass, or Pydantic BaseModel")


def _pydantic_to_json_schema(model: Type) -> Dict:
    properties = {}
    required = []

    for name, field in model.model_fields.items():
        field_schema = _python_type_to_schema(field.annotation)

        if field.description:
            field_schema["description"] = field.description

        properties[name] = field_schema

        if field.is_required():
            required.append(name)

    schema = {"type": "object", "properties": properties}

    if required:
        schema["required"] = required

    return schema


def _dataclass_to_json_schema(cls: Type) -> Dict:
    properties = {}
    required = []

    for field in dataclasses.fields(cls):
        field_schema = _python_type_to_schema(field.type)

        # description from metadata
        description = field.metadata.get("description") if field.metadata else None
        if description:
            field_schema["description"] = description

        properties[field.name] = field_schema

        if (
            field.default is dataclasses.MISSING
            and field.default_factory is dataclasses.MISSING
        ):
            required.append(field.name)

    schema = {"type": "object", "properties": properties}

    if required:
        schema["required"] = required

    return schema


def _python_type_to_schema(tp: Any) -> Dict:
    """
    Convert arbitrary Python typing annotations to JSON schema.
    Handles recursion for dataclasses and Pydantic models.
    """

    origin = get_origin(tp)
    args = get_args(tp)

    # Primitive types
    primitive_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        dict: "object",
        list: "array",
    }

    if tp in primitive_map:
        return {"type": primitive_map[tp]}

    # Optional / Union
    if origin is Union:
        non_none = [a for a in args if a is not type(None)]

        if len(non_none) == 1:
            return _python_type_to_schema(non_none[0])

        return {"anyOf": [_python_type_to_schema(a) for a in non_none]}

    # List
    if origin in (list, List):
        item_type = args[0] if args else str
        return {"type": "array", "items": _python_type_to_schema(item_type)}

    # Dict
    if origin in (dict, Dict):
        return {"type": "object"}

    # Nested dataclass
    if dataclasses.is_dataclass(tp):
        return _dataclass_to_json_schema(tp)

    # Nested Pydantic model
    if BaseModel and isinstance(tp, type) and issubclass(tp, BaseModel):
        return _pydantic_to_json_schema(tp)

    # Fallback
    return {"type": "string"}
