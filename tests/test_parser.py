# python3 -m pytest tests/test_parser.py -v
# With logs: python3 -m pytest tests/test_parser.py -v -s

import os

import pytest
from dotenv import load_dotenv
from lexoid.api import parse
from lexoid.core.utils import calculate_similarity

load_dotenv()
output_dir = "tests/outputs"
os.makedirs(output_dir, exist_ok=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "models",
    ["gpt-4o", "gpt-4o-mini", "gemini-1.5-flash", "gemini-1.5-pro"],
)
async def test_llm_parse(models):
    input_data = "examples/inputs/test_1.pdf"
    expected_ouput_path = "examples/outputs/test_1.md"
    config = {"parser_type": "LLM_PARSE", "model": models, "verbose": True}
    result = parse(input_data, raw=True, **config)
    assert isinstance(result, str)

    # Compare the result with the expected output
    expected_ouput = open(expected_ouput_path, "r").read()
    # save the result to a file
    with open(f"{output_dir}/input_table_{models}.md", "w") as f:
        f.write(result)
    score = calculate_similarity(result, expected_ouput)
    assert round(score, 3) > 0.75


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "models",
    ["gpt-4o", "gpt-4o-mini", "gemini-1.5-flash", "gemini-1.5-pro"],
)
async def test_jpg_parse(models):
    input_data = "examples/inputs/test_4.jpg"
    expected_ouput_path = "examples/outputs/test_4.md"
    config = {"parser_type": "LLM_PARSE", "model": "gpt-4o"}
    result = parse(input_data, raw=True, **config)
    assert isinstance(result, str)

    # Compare the result with the expected output
    expected_ouput = open(expected_ouput_path, "r").read()
    # save the result to a file
    with open(f"{output_dir}/input_image_{models}.md", "w") as f:
        f.write(result)
    score = calculate_similarity(result, expected_ouput)
    assert round(score, 3) > 0.8


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sample",
    [
        "examples/inputs/test_explicit_hyperlink_n_img.pdf",
        "examples/inputs/test_hidden_link_with_image.pdf",  # currently fails
        "examples/inputs/test_with_hidden_links_no_img.pdf",
    ],
)
async def test_url_detection_auto_routing(sample):
    patterns = ["http", "https", "www"]
    model_type = "gemini-1.5-pro"
    config = {"parser_type": "AUTO", "model": model_type, "verbose": True}
    result = parse(sample, raw=True, **config)
    assert isinstance(result, str)
    found = [True if p in result else False for p in patterns]
    assert any(found)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sample",
    [
        "examples/inputs/test_explicit_hyperlink_n_img.pdf",
        "examples/inputs/test_hidden_link_with_image.pdf",
        "examples/inputs/test_with_hidden_links_no_img.pdf",
    ],
)
async def test_url_detection_pdfplumber(sample):
    patterns = ["http", "https", "www"]
    framework = "pdfplumber"
    config = {"parser_type": "STATIC_PARSE", "framework": framework}
    result = parse(sample, raw=True, **config)
    assert isinstance(result, str)
    found = [True if p in result else False for p in patterns]
    assert any(found)


@pytest.mark.parametrize(
    "model_type", ["gpt-4o", "gemini-1.5-pro", "gpt-4o-mini", "gemini-1.5-flash"]
)
@pytest.mark.asyncio
async def test_url_detection_multi_page_auto_routing(model_type):
    sample = "examples/inputs/sample_test_doc.pdf"
    patterns = ["http", "https", "www"]
    config = {"parser_type": "AUTO", "model": model_type, "verbose": True}
    results = parse(sample, pages_per_split=1, **config)

    assert len(results) == 6
    for res in results:
        content = res["content"]
        if res["metadata"]["page"] == 1:
            # Page 1: Fails to detect the URL
            found = [p in content for p in patterns]
            assert not any(found)
        elif res["metadata"]["page"] == 2:
            # Page 2: Detects the URL
            found = [p in content for p in patterns]
            assert any(found)
        elif res["metadata"]["page"] == 3:
            # Page 3: Does not contain any URL
            found = [p in content for p in patterns]
            assert not any(found)
        elif res["metadata"]["page"] == 4:
            # Page 4: Detects the URL
            found = [p in content for p in patterns]
            assert any(found)
        elif res["metadata"]["page"] == 5:
            # Page 5: Detects all the URLs
            found = [p in content for p in patterns]
            assert all(found)
        elif res["metadata"]["page"] == 6:
            # Page 6: Detects the URL
            found = "https://github" in content
            assert found


@pytest.mark.asyncio
@pytest.mark.parametrize("depth", [1, 2])
async def test_recursive_url_parsing(depth):
    results = parse("https://example.com/", depth=depth)
    assert len(results) == depth


@pytest.mark.asyncio
async def test_url_parsing_in_pdf():
    sample = "examples/inputs/sample_test_doc.pdf"
    parser_type = "AUTO"
    results = parse(sample, parser_type, pages_per_split=1, depth=2)
    assert len(results) > 10, results


@pytest.mark.asyncio
async def test_parsing_txt_type():
    sample = "examples/inputs/sample_test.txt"
    parser_type = "AUTO"
    results = parse(sample, parser_type)
    assert len(results) == 1
    assert results[0]["content"] is not None


@pytest.mark.asyncio
async def test_parsing_docx_type():
    sample = "examples/inputs/sample.docx"
    parser_type = "STATIC_PARSE"
    results = parse(sample, parser_type)
    assert len(results) == 1
    assert results[0]["content"] is not None

    parser_type = "LLM_PARSE"
    results = parse(sample, parser_type)
    assert len(results) > 1
    assert results[0]["content"] is not None


@pytest.mark.asyncio
async def test_dynamic_js_parsing():
    test_url = "https://go.contentsquare.com/ab-testing-playbook"
    results = parse(test_url, parser_type="AUTO", raw=True)
    # Check if the content contains the expected information
    should_contain_info = "6 Types of experimentation"
    assert should_contain_info.lower() in results.strip().lower()


@pytest.mark.asyncio
async def test_pdfplumber_table_parsing():
    sample = "examples/inputs/test_1.pdf"
    parser_type = "STATIC_PARSE"
    results = parse(sample, parser_type, raw=True, framework="pdfplumber")
    assert [token in results for token in ["|", "Results", "Accuracy"]]


@pytest.mark.asyncio
async def test_large_pdf_parsing():
    sample = "examples/inputs/test_large_doc.pdf"
    parser_type = "AUTO"
    results = parse(sample, parser_type, raw=False)
    assert len(results) > 1
    assert results[0]["content"] is not None
