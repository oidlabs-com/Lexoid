import tempfile
import pandas as pd
import pdfplumber
from typing import List, Dict
from lexoid.core.utils import get_file_type, get_uri_rect, html_to_markdown, split_pdf
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer
from pdfplumber.utils import extract_text, get_bbox_overlap, obj_to_bbox
from docx import Document


def parse_static_doc(path: str, raw: bool, **kwargs) -> List[Dict] | str:
    framework = kwargs.get("framework", "pdfplumber")

    file_type = get_file_type(path)
    if file_type == "application/pdf":
        if framework == "pdfplumber":
            return parse_with_pdfplumber(path, raw, **kwargs)
        elif framework == "pdfminer":
            return parse_with_pdfminer(path, raw, **kwargs)
        else:
            raise ValueError(f"Unsupported framework: {framework}")
    elif file_type == "application/word":
        return parse_with_docx(path, raw, **kwargs)
    elif file_type == "text/html":
        with open(path, "r") as f:
            html_content = f.read()
            return html_to_markdown(html_content, raw, kwargs["title"])
    elif file_type == "text/plain":
        with open(path, "r") as f:
            content = f.read()
            if raw:
                return content
            else:
                return [
                    {
                        "metadata": {"title": kwargs["title"], "page": 1},
                        "content": content,
                    }
                ]
    elif file_type == "text/csv":
        df = pd.read_csv(path)
        content = df.to_markdown(index=False)
        if raw:
            return content
        else:
            return [
                {
                    "metadata": {"title": kwargs["title"], "page": 1},
                    "content": content,
                }
            ]
    else:
        raise ValueError(f"Unsupported file type: {file_type}")


def parse_with_pdfminer(path: str, raw: bool, **kwargs) -> List[Dict] | str:
    pages = list(extract_pages(path))
    docs = []
    for page_num, page_layout in enumerate(pages, start=1):
        page_text = "".join(
            element.get_text()
            for element in page_layout
            if isinstance(element, LTTextContainer)
        )
        if raw:
            docs.append(page_text)
        else:
            docs.append(
                {
                    "metadata": {
                        "title": kwargs["title"],
                        "page": kwargs["start"] + page_num,
                    },
                    "content": page_text,
                }
            )
    return "\n".join(docs) if raw else docs


def process_table(table) -> str:
    """
    Convert a table to markdown format.
    """
    # Extract table data
    table_data = table.extract()
    if not table_data or not table_data[0]:  # Check if table is empty
        return ""

    # Convert to DataFrame and handle empty cells
    df = pd.DataFrame(table_data)
    df = df.fillna("")

    # Use first row as header and clean it up
    df.columns = df.iloc[0]
    df = df.drop(0)

    # Convert to markdown with some formatting options
    markdown_table = df.to_markdown(index=False, tablefmt="pipe")
    return f"\n{markdown_table}\n\n"  # Add newlines for proper markdown rendering


def embed_links_in_text(page, text, links):
    """
    Embed hyperlinks inline within the text, matching their position based on rectangles.

    Args:
        page (pdfplumber.page.Page): The page containing the links.
        text (str): The full text extracted from the page.
        links (list of tuples): List of (rect, uri) pairs.

    Returns:
        str: The text with hyperlinks embedded inline.
    """
    words = page.extract_words(x_tolerance=1)

    words_with_positions = []
    cur_position = 0
    for word in words:
        try:
            word_pos = text[cur_position:].index(word["text"])
        except ValueError:
            continue
        words_with_positions.append(
            (word["text"], word["x0"], page.mediabox[-1] - word["top"], word_pos)
        )
        cur_position = cur_position + word_pos + len(word["text"])

    for rect, uri in links:
        rect_left, rect_top, rect_right, rect_bottom = rect
        text_span = []
        start_pos = None

        for word, x0, word_top, word_pos in words_with_positions:
            if rect_left <= x0 <= rect_right and rect_top <= word_top <= rect_bottom:
                if not start_pos:
                    start_pos = word_pos
                text_span.append(word)

        if text_span:
            original_text = " ".join(text_span)
            text = text[:start_pos] + text[start_pos:].replace(
                original_text, f"[{original_text}]({uri})"
            )

    return text


def process_pdf_page_with_pdfplumber(page, uri_rects, **kwargs):
    """
    Process a single page's content and return formatted markdown text.
    """
    markdown_content = []
    current_paragraph = []
    current_heading = []
    last_y = None
    x_tolerance = kwargs.get("x_tolerance", 1)
    y_tolerance = kwargs.get("y_tolerance", 5)

    # First, identify tables and their positions
    tables = page.find_tables()
    table_zones = [(table.bbox, process_table(table)) for table in tables]

    # Create a filtered page excluding table areas
    filtered_page = page
    for table_bbox, _ in table_zones:
        filtered_page = filtered_page.filter(
            lambda obj: get_bbox_overlap(obj_to_bbox(obj), table_bbox) is None
        )

    words = filtered_page.extract_words(
        x_tolerance=x_tolerance,
        y_tolerance=y_tolerance,
        extra_attrs=["size", "top", "bottom"],
    )

    def format_paragraph(text):
        text = " ".join(text.split())
        return f"{text}\n\n"

    def detect_heading_level(font_size):
        if font_size >= 24:
            return 1
        elif font_size >= 20:
            return 2
        elif font_size >= 16:
            return 3
        return None

    tables = []
    for bbox, table_md in table_zones:
        tables.append(
            (
                "table",
                {
                    "top": bbox[1],
                    "bottom": bbox[3],
                    "content": table_md,
                },
            )
        )
    tables.sort(key=lambda x: x[1]["bottom"])
    content_elements = []
    for word in words:
        while tables and word["bottom"] > tables[0][1]["bottom"]:
            content_elements.append(tables.pop(0))
        content_elements.append(("word", word))

    for element_type, element in content_elements:
        if element_type == "table":
            # If there are any pending paragraphs or headings, add them first
            if current_heading:
                level = detect_heading_level(current_heading[0]["size"])
                heading_text = " ".join(word["text"] for word in current_heading)
                markdown_content.append(f"{'#' * level} {heading_text}\n\n")
                current_heading = []
            if current_paragraph:
                markdown_content.append(format_paragraph(" ".join(current_paragraph)))
                current_paragraph = []
            # Add the table
            markdown_content.append(element["content"])
            last_y = element["bottom"]
        else:
            # Process word
            word = element
            # Check if this might be a heading
            heading_level = detect_heading_level(word["size"])

            # Detect new line based on vertical position
            is_new_line = last_y is not None and abs(word["top"] - last_y) > y_tolerance

            if is_new_line:
                # If we were collecting a heading
                if current_heading:
                    level = detect_heading_level(current_heading[0]["size"])
                    heading_text = " ".join(word["text"] for word in current_heading)
                    markdown_content.append(f"{'#' * level} {heading_text}\n\n")
                    current_heading = []

                # If we were collecting a paragraph
                if current_paragraph:
                    markdown_content.append(
                        format_paragraph(" ".join(current_paragraph))
                    )
                    current_paragraph = []

            # Add word to appropriate collection
            if heading_level:
                if current_paragraph:  # Flush any pending paragraph
                    markdown_content.append(
                        format_paragraph(" ".join(current_paragraph))
                    )
                    current_paragraph = []
                current_heading.append({"text": word["text"], "size": word["size"]})
            else:
                if current_heading:  # Flush any pending heading
                    level = detect_heading_level(current_heading[0]["size"])
                    heading_text = " ".join(word["text"] for word in current_heading)
                    markdown_content.append(f"{'#' * level} {heading_text}\n\n")
                    current_heading = []
                current_paragraph.append(word["text"])

            last_y = word["top"]

    # Handle remaining content
    if current_heading:
        level = detect_heading_level(current_heading[0]["size"])
        heading_text = " ".join(word["text"] for word in current_heading)
        markdown_content.append(f"{'#' * level} {heading_text}\n\n")

    if current_paragraph:
        markdown_content.append(format_paragraph(" ".join(current_paragraph)))

    # Process links for the page
    content = "".join(markdown_content)  # Process links using the new function
    if page.annots:
        links = []
        for annot in page.annots:
            uri = annot.get("uri")
            if uri and uri_rects.get(uri):
                links.append((uri_rects[uri], uri))

        if links:
            content = embed_links_in_text(page, content, links)

    return content


def process_pdf_with_pdfplumber(path: str, **kwargs) -> List[str]:
    """
    Process PDF and return a list of markdown-formatted strings, one per page.
    """
    page_texts = []

    with tempfile.TemporaryDirectory() as temp_dir:
        paths = split_pdf(path, temp_dir, pages_per_split=1)

        for split_path in paths:
            uri_rects = get_uri_rect(split_path)
            with pdfplumber.open(split_path) as pdf:
                for page in pdf.pages:
                    page_content = process_pdf_page_with_pdfplumber(
                        page, uri_rects, **kwargs
                    )
                    page_texts.append(page_content.strip())

    return page_texts


def parse_with_pdfplumber(path: str, raw: bool, **kwargs) -> List[Dict] | str:
    """
    Parse PDF and return either raw text or structured data.

    Args:
        path (str): Path to the PDF file
        raw (bool): If True, return raw text with page breaks; if False, return structured data
        **kwargs: Additional arguments including 'title' and 'start' page number

    Returns:
        Union[List[Dict], str]: Either a list of dictionaries containing page metadata and content,
                               or a string of raw text with page breaks
    """
    page_texts = process_pdf_with_pdfplumber(path, **kwargs)
    if raw:
        return "<page-break>".join(page_texts)
    return [
        {
            "metadata": {"title": kwargs["title"], "page": kwargs["start"] + page_num},
            "content": page_text,
        }
        for page_num, page_text in enumerate(page_texts, start=1)
    ]


def process_pdf_with_pdfplumber(path: str) -> List[str]:
    with pdfplumber.open(path) as pdf:
        all_text = []
        for page in pdf.pages:
            filtered_page = page
            chars = filtered_page.chars
            for table in page.find_tables():
                first_table_char = page.crop(table.bbox).chars[0]
                filtered_page = filtered_page.filter(
                    lambda obj: get_bbox_overlap(obj_to_bbox(obj), table.bbox) is None
                )
                chars = filtered_page.chars
                df = pd.DataFrame(table.extract())
                df.columns = df.iloc[0]
                markdown = df.drop(0).to_markdown(index=False)
                chars.append(first_table_char | {"text": markdown})
            page_text = extract_text(chars, layout=True)
            all_text.append(page_text)
    return all_text


def parse_with_docx(path: str, raw: bool, **kwargs) -> List[Dict] | str:
    doc = Document(path)
    full_text = "\n".join([paragraph.text for paragraph in doc.paragraphs])

    if raw:
        return full_text

    return [
        {
            "metadata": {
                "title": kwargs["title"],
                "page": kwargs["start"] + 1,
            },
            "content": full_text,
        }
    ]
