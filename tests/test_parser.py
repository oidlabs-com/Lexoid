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
    assert round(score, 3) > 0.8


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
async def test_url_detection_multi_page_auto_routing():
    sample = "examples/inputs/sample_test_doc.pdf"
    patterns = ["http", "https", "www"]
    model_type = "gemini-1.5-pro"
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
