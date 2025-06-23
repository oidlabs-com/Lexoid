import os
import re
import tempfile
from functools import wraps
from time import time
from typing import Dict, List

import pandas as pd
import pdfplumber
from docx import Document
from loguru import logger
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer
from pdfplumber.utils import get_bbox_overlap, obj_to_bbox
from pptx2md import ConversionConfig, convert


from lexoid.core.utils import (
    get_file_type,
    get_uri_rect,
    html_to_markdown,
    split_md_by_headings,
    split_pdf,
)


def retry_with_different_parser(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if "pdfplumber" in kwargs.get("framework", "pdfplumber") and not kwargs.get(
                "routed", False
            ):
                kwargs["framework"] = "pdfminer"
                logger.warning(
                    f"Retrying with pdfminer due to error: {e}. Original framework: {kwargs['framework']}"
                )
                return func(*args, **kwargs)
            elif "pdfminer" in kwargs.get("framework", "pdfplumber") and not kwargs.get(
                "routed", False
            ):
                kwargs["framework"] = "pdfplumber"
                logger.warning(
                    f"Retrying with pdfplumber due to error: {e}. Original framework: {kwargs['framework']}"
                )
                return func(*args, **kwargs)
            else:
                logger.error(
                    f"Failed to parse document with both pdfplumber and pdfminer: {e}"
                )
                raise e

    return wrapper


@retry_with_different_parser
def parse_static_doc(path: str, **kwargs) -> Dict:
    """
    Parses a document using static parsing methods.

    Args:
        path (str): The file path.
        **kwargs: Additional arguments for parsing.

    Returns:
        Dict: Dictionary containing parsed document data
    """
    framework = kwargs.get("framework", "pdfplumber")

    file_type = get_file_type(path)
    if file_type == "application/pdf":
        if framework == "pdfplumber":
            return parse_with_pdfplumber(path, **kwargs)
        elif framework == "pdfminer":
            return parse_with_pdfminer(path, **kwargs)
        else:
            raise ValueError(f"Unsupported framework: {framework}")
    elif "wordprocessing" in file_type:
        return parse_with_docx(path, **kwargs)
    elif file_type == "text/html":
        with open(path, "r") as f:
            html_content = f.read()
            return html_to_markdown(html_content, kwargs["title"])
    elif file_type == "text/plain":
        with open(path, "r") as f:
            content = f.read()
            return {
                "raw": content,
                "segments": [{"metadata": {"page": 1}, "content": content}],
                "title": kwargs["title"],
                "url": kwargs.get("url", ""),
                "parent_title": kwargs.get("parent_title", ""),
                "recursive_docs": [],
            }
    elif file_type == "text/csv" or "spreadsheet" in file_type:
        if "spreadsheet" in file_type:
            df = pd.read_excel(path)
        else:
            df = pd.read_csv(path)
        content = df.to_markdown(index=False)
        return {
            "raw": content,
            "segments": [{"metadata": {"page": 1}, "content": content}],
            "title": kwargs["title"],
            "url": kwargs.get("url", ""),
            "parent_title": kwargs.get("parent_title", ""),
            "recursive_docs": [],
        }
    elif "presentation" in file_type:
        md_path = os.path.join(kwargs["temp_dir"], f"{int(time())}.md")
        convert(
            ConversionConfig(
                pptx_path=path,
                output_path=md_path,
                image_dir=None,
                disable_image=True,
                disable_notes=True,
            )
        )
        with open(md_path, "r") as f:
            content = f.read()
        return {
            "raw": content,
            "segments": split_md_by_headings(content, "#"),
            "title": kwargs["title"],
            "url": kwargs.get("url", ""),
            "parent_title": kwargs.get("parent_title", ""),
            "recursive_docs": [],
        }
    else:
        raise ValueError(f"Unsupported file type: {file_type}")


def parse_with_pdfminer(path: str, **kwargs) -> Dict:
    """
    Parse PDF using pdfminer.

    Returns:
        Dict: Dictionary containing parsed document data
    """
    pages = list(extract_pages(path))
    segments = []
    raw_texts = []

    for page_num, page_layout in enumerate(pages, start=1):
        page_text = "".join(
            element.get_text()
            for element in page_layout
            if isinstance(element, LTTextContainer)
        )
        raw_texts.append(page_text)
        segments.append(
            {"metadata": {"page": kwargs["start"] + page_num}, "content": page_text}
        )

    return {
        "raw": "\n".join(raw_texts),
        "segments": segments,
        "title": kwargs["title"],
        "url": kwargs.get("url", ""),
        "parent_title": kwargs.get("parent_title", ""),
        "recursive_docs": [],
    }


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
    df.replace("", pd.NA, inplace=True)
    df = df.dropna(how="all", axis=0)
    df = df.dropna(how="all", axis=1)
    df = df.fillna("")
    if len(df) == 0:
        return ""

    # Use first row as header and clean it up
    df.columns = df.iloc[0]
    df = df.drop(df.index[0])
    df.replace(r"\n", "<br>", regex=True, inplace=True)

    # Convert to markdown with some formatting options
    markdown_table = df.to_markdown(index=False, tablefmt="pipe")
    return f"\n{markdown_table}\n\n"


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


def detect_indentation_level(word, base_left_position):
    """Determine indentation level based on left position difference."""
    left_diff = word["x0"] - base_left_position
    if left_diff < 5:
        return 0
    return int(left_diff // 25) + 1


def embed_email_links(text: str) -> str:
    """
    Detect email addresses in text and wrap them in angle brackets.
    For example, 'mail@example.com' becomes '<mail@example.com>'.
    """
    email_pattern = re.compile(
        r"(?<![<\[])(?P<email>\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b)(?![>\]])"
    )
    return email_pattern.sub(lambda match: f"<{match.group('email')}>", text)


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
    next_h_line_idx = 0

    # First detect horizontal lines that could be markdown rules
    horizontal_lines = []
    if hasattr(page, "lines"):
        for line in page.lines:
            # Check if line is approximately horizontal (within 5 degrees)
            if (
                abs(line["height"]) < 0.1
                or abs(line["width"]) > abs(line["height"]) * 20
            ):
                # Consider it a horizontal rule candidate
                horizontal_lines.append(
                    {
                        "top": line["top"],
                        "bottom": line["bottom"],
                        "x0": line["x0"],
                        "x1": line["x1"],
                    }
                )
    # Table settings
    vertical_strategy = kwargs.get("vertical_strategy", "lines")
    horizontal_strategy = kwargs.get("horizontal_strategy", "lines")
    snap_x_tolerance = kwargs.get("snap_x_tolerance", 10)
    snap_y_tolerance = kwargs.get("snap_y_tolerance", 0)

    tables = page.find_tables(
        table_settings={
            "vertical_strategy": vertical_strategy,
            "horizontal_strategy": horizontal_strategy,
            "snap_x_tolerance": snap_x_tolerance,
            "snap_y_tolerance": snap_y_tolerance,
        }
    )
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
        extra_attrs=["size", "top", "bottom", "fontname"],
    )

    if words:
        font_sizes = [w.get("size", 12) for w in words]
        body_font_size = max(set(font_sizes), key=font_sizes.count)
    else:
        body_font_size = 12

    left_positions = []
    prev_bottom = None

    for word in words:
        # Check if this is likely a new line (first word in line)
        if prev_bottom is None or abs(word["top"] - prev_bottom) > y_tolerance:
            left_positions.append(word["x0"])
        prev_bottom = word["top"]

    # Find the most common minimum left position (mode)
    if left_positions:
        base_left = max(set(left_positions), key=left_positions.count)
    else:
        base_left = 0

    for line in horizontal_lines:
        # Check each word to see if it overlaps with this line
        for word in words:
            # Get word bounding box coordinates
            word_left = word["x0"]
            word_right = word["x1"]
            word_top = word["top"]
            word_bottom = word["bottom"]

            # Check if word overlaps with line in both x and y dimensions
            x_overlap = (word_left <= line["x1"]) and (word_right >= line["x0"])
            y_overlap = (word_top <= line["bottom"]) and (word_bottom >= line["top"])

            if x_overlap and y_overlap:
                word["text"] = f"~~{word['text']}~~"
                break

    def get_text_formatting(word):
        """
        Detect text formatting based on font properties
        Returns a dict of formatting attributes
        """
        formatting = {
            "bold": False,
            "italic": False,
            "monospace": False,
        }
        # Check font name for common bold/italic indicators
        font_name = word.get("fontname", "").lower()
        if any(style in font_name for style in ["bold", "heavy", "black"]):
            formatting["bold"] = True
        if any(style in font_name for style in ["italic", "oblique"]):
            formatting["italic"] = True
        if "mono" in font_name:  # Detect monospace fonts
            formatting["monospace"] = True
        return formatting

    def apply_markdown_formatting(text, formatting):
        """Apply markdown formatting to text based on detected styles"""
        if formatting["monospace"]:
            text = f"`{text}`"
        if formatting["bold"] and formatting["italic"]:
            text = f"***{text}***"
        elif formatting["bold"]:
            text = f"**{text}**"
        elif formatting["italic"]:
            text = f"*{text}*"
        return text

    def format_paragraph(text_elements):
        """
        Format a paragraph with styling applied to individual words.
        If all words are monospace, treat the paragraph as a code block.
        Otherwise, wrap monospace words with backticks (`).
        """

        all_monospace = True
        formatted_words = []

        for element in text_elements:
            if isinstance(element, tuple) and element[0] == "indent":
                indent = "&nbsp;" * element[1] * 3
                formatted_words.append(indent)
                continue

            text = element["text"]
            formatting = get_text_formatting(element)

            if formatting.get("monospace", False):
                # Wrap monospace words with backticks
                formatted_words.append(f"`{text}`")
            else:
                all_monospace = False
                # Apply other markdown formatting
                formatted_words.append(apply_markdown_formatting(text, formatting))

        # If all words are monospace, format as a code block
        if all_monospace:
            if isinstance(text_elements[0], tuple):
                indent_str = " " * text_elements[0][1]
                if len(text_elements) > 1:
                    text_elements = text_elements[1:]
                    text_elements[0]["text"] = indent_str + text_elements[0]["text"]
                else:
                    return indent_str
            code_content = " ".join([element["text"] for element in text_elements])
            return f"```\n{code_content}\n```\n\n"

        # Otherwise, return the formatted paragraph
        return f"{' '.join(formatted_words)}\n\n"

    def detect_heading_level(font_size, body_font_size):
        """Determine heading level based on font size ratio.

        Args:
            font_size: The font size to evaluate
            body_font_size: The base body font size for comparison

        Returns:
            int: The heading level (1-3) or None if not a heading
        """
        size_ratio = font_size / body_font_size
        if size_ratio >= 2:
            return 1
        elif size_ratio >= 1.4:
            return 2
        elif size_ratio >= 1.2:
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
    for line in horizontal_lines:
        content_elements.append(
            (
                "horizontal_line",
                {
                    "top": line["top"],
                    "bottom": line["bottom"],
                    "x0": line["x0"],
                    "x1": line["x1"],
                },
            )
        )

    for i, word in enumerate(words):
        while tables and word["bottom"] > tables[0][1]["bottom"]:
            content_elements.append(tables.pop(0))

        # Equate position of words on the same line
        if i > 0 and abs(word["top"] - words[i - 1]["top"]) < 3:
            word["top"] = words[i - 1]["top"]

        content_elements.append(("word", word))
    content_elements.extend(tables)

    content_elements.sort(
        key=lambda x: x[1]["top"] if isinstance(x[1], dict) and "top" in x[1] else 0
    )

    for element_type, element in content_elements:
        # If there are any pending paragraphs or headings, add them first
        if element_type == "table":
            if current_heading:
                level = detect_heading_level(current_heading[0]["size"], body_font_size)
                heading_text = format_paragraph(current_heading)
                markdown_content.append(f"{'#' * level} {heading_text}")
                current_heading = []
            if current_paragraph:
                markdown_content.append(format_paragraph(current_paragraph))
                current_paragraph = []
            # Add the table
            markdown_content.append(element["content"])
            last_y = element["bottom"]
        elif element_type == "horizontal_line":
            while (next_h_line_idx < len(horizontal_lines)) and (
                last_y is not None
                and horizontal_lines[next_h_line_idx]["top"] <= last_y
            ):
                # Insert the horizontal rule *after* the preceding text
                if current_paragraph:  # Flush any pending paragraph
                    markdown_content.append(format_paragraph(current_paragraph))
                    current_paragraph = []
                markdown_content.append("\n---\n\n")  # Add the rule
                next_h_line_idx += 1
        else:
            # Process word
            word = element
            # Check if this might be a heading
            heading_level = detect_heading_level(word["size"], body_font_size)

            # Detect new line based on vertical position
            is_new_line = last_y is not None and abs(word["top"] - last_y) > y_tolerance

            if is_new_line:
                # If we were collecting a heading
                if current_heading:
                    level = detect_heading_level(
                        current_heading[0]["size"], body_font_size
                    )
                    heading_text = format_paragraph(current_heading)
                    markdown_content.append(f"{'#' * level} {heading_text}")
                    current_heading = []

                # If we were collecting a paragraph
                if current_paragraph:
                    markdown_content.append(format_paragraph(current_paragraph))
                    current_paragraph = []

                indent_level = detect_indentation_level(word, base_left)
                current_paragraph.append(("indent", indent_level))

            # Add word to appropriate collection
            if heading_level:
                if current_paragraph:  # Flush any pending paragraph
                    markdown_content.append(format_paragraph(current_paragraph))
                    current_paragraph = []
                current_heading.append(word)
            else:
                if current_heading:  # Flush any pending heading
                    level = detect_heading_level(
                        current_heading[0]["size"], body_font_size
                    )
                    heading_text = format_paragraph(current_heading)
                    markdown_content.append(f"{'#' * level} {heading_text}")
                    current_heading = []
                current_paragraph.append(word)

            last_y = word["top"]

    # Handle remaining content
    if current_heading:
        level = detect_heading_level(current_heading[0]["size"], body_font_size)
        heading_text = format_paragraph(current_heading)
        markdown_content.append(f"{'#' * level} {heading_text}")

    if current_paragraph:
        markdown_content.append(format_paragraph(current_paragraph))

    # Process links for the page
    content = "".join(markdown_content)
    if page.annots:
        links = []
        for annot in page.annots:
            uri = annot.get("uri")
            if uri and uri_rects.get(uri):
                links.append((uri_rects[uri], uri))

        if links:
            content = embed_links_in_text(page, content, links)

    content = embed_email_links(content)

    # Remove redundant formatting
    content = (
        content.replace("** **", " ")
        .replace("* *", " ")
        .replace("` `", " ")
        .replace("\n```\n\n```", "")
    )

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


def parse_with_pdfplumber(path: str, **kwargs) -> Dict:
    """
    Parse PDF using pdfplumber.

    Returns:
        Dict: Dictionary containing parsed document data
    """
    page_texts = process_pdf_with_pdfplumber(path)
    segments = [
        {"metadata": {"page": kwargs["start"] + page_num}, "content": page_text}
        for page_num, page_text in enumerate(page_texts, start=1)
    ]

    return {
        "raw": "\n\n".join(page_texts),
        "segments": segments,
        "title": kwargs["title"],
        "url": kwargs.get("url", ""),
        "parent_title": kwargs.get("parent_title", ""),
        "recursive_docs": [],
    }


def parse_with_docx(path: str, **kwargs) -> Dict:
    """
    Parse DOCX document.

    Returns:
        Dict: Dictionary containing parsed document data
    """
    doc = Document(path)
    full_text = "\n".join([paragraph.text for paragraph in doc.paragraphs])

    return {
        "raw": full_text,
        "segments": [{"metadata": {"page": kwargs["start"] + 1}, "content": full_text}],
        "title": kwargs["title"],
        "url": kwargs.get("url", ""),
        "parent_title": kwargs.get("parent_title", ""),
        "recursive_docs": [],
    }
