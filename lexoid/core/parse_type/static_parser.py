import tempfile
import pandas as pd
import pdfplumber
from typing import List, Dict
from lexoid.core.utils import get_file_type, get_uri_rect, html_to_markdown, split_pdf
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer
from pdfplumber.utils import get_bbox_overlap, obj_to_bbox
from docx import Document


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
    elif file_type == "text/csv":
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

    # --- Updated helper functions for monospace detection and code block output ---

    def get_text_formatting(word):
        """
        Detect text formatting based on font properties.
        Returns a dict of formatting attributes.
        Now also detects monospace fonts.
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
        print(f"Formatting",formatting)
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
        If the preceding normal text contains a known language, use it as a language hint.
        """
        # List of known programming languages for hint extraction
        known_languages = {
            "python", "javascript", "java", "c++", "c", "ruby",
            "go", "php", "html", "css", "sql", "bash", "shell"
        }

        # Extract the preceding normal text to detect language hint
        detected_language = ""
        normal_texts = []
        code_elements = []

        for element in text_elements:
            text = element["text"]
            formatting = get_text_formatting(element)

            if formatting.get("monospace", False):
                code_elements.append(text)  # Collect monospace (code) elements
            else:
                normal_texts.append(text)  # Collect normal text elements

        # Try to detect language from normal text before the code block
        preceding_text = " ".join(normal_texts).lower()
        for lang in known_languages:
            if lang in preceding_text:
                detected_language = lang
                break  # Stop at the first match

        # If it's a monospace block, format it as code with language hint
        if code_elements:
            code_content = " ".join(code_elements)
            return f"```{detected_language}\n{code_content}\n```\n\n"

        # Otherwise, return normal text with proper markdown formatting
        formatted_words = [
            apply_markdown_formatting(element["text"], get_text_formatting(element))
            for element in text_elements
        ]
        return f"{' '.join(formatted_words)}\n\n"


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
    content_elements.extend(tables)

    for element_type, element in content_elements:
        # If there are any pending paragraphs or headings, add them first
        if element_type == "table":
            if current_heading:
                level = detect_heading_level(current_heading[0]["size"])
                heading_text = format_paragraph(current_heading)
                markdown_content.append(f"{'#' * level} {heading_text}")
                current_heading = []
            if current_paragraph:
                markdown_content.append(format_paragraph(current_paragraph))
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
                    heading_text = format_paragraph(current_heading)
                    markdown_content.append(f"{'#' * level} {heading_text}")
                    current_heading = []

                # If we were collecting a paragraph
                if current_paragraph:
                    markdown_content.append(format_paragraph(current_paragraph))
                    current_paragraph = []
            
            # Add word to appropriate collection
            if heading_level:
                if current_paragraph:  # Flush any pending paragraph
                    markdown_content.append(format_paragraph(current_paragraph))
                    current_paragraph = []
                current_heading.append(word)
            else:
                if current_heading:  # Flush any pending heading
                    level = detect_heading_level(current_heading[0]["size"])
                    heading_text = format_paragraph(current_heading)
                    markdown_content.append(f"{'#' * level} {heading_text}")
                    current_heading = []
                current_paragraph.append(word)

            last_y = word["top"]

    # Handle remaining content
    if current_heading:
        level = detect_heading_level(current_heading[0]["size"])
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

    # Remove redundant formatting
    content = content.replace("** **", " ").replace("* *", " ")
    
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
        "raw": "<page-break>".join(page_texts),
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
