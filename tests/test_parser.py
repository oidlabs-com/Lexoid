# python3 -m pytest tests/test_parser.py -v
# With logs: python3 -m pytest tests/test_parser.py -v -s

import os

import pytest
from dotenv import load_dotenv
from loguru import logger

from lexoid.api import parse
from lexoid.core.utils import calculate_similarity

load_dotenv()
output_dir = "tests/outputs"
os.makedirs(output_dir, exist_ok=True)
models = [
    # Google models
    "gemini-exp-1206",
    "gemini-2.0-flash-001",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    # OpenAI models
    "gpt-4o",
    "gpt-4o-mini",
    # Meta-LLAMA models through HF Hub
    "meta-llama/Llama-3.2-11B-Vision-Instruct",
    # Meta-LLAMA models through Together AI
    "meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo",
    "meta-llama/Llama-3.2-90B-Vision-Instruct-Turbo",
    "meta-llama/Llama-Vision-Free",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("model", models)
async def test_llm_parse(model):
    input_data = "examples/inputs/test_1.pdf"
    expected_ouput_path = "examples/outputs/test_1.md"
    config = {"parser_type": "LLM_PARSE", "model": model, "verbose": True}
    result = parse(input_data, **config)["raw"]
    assert isinstance(result, str)

    # Compare the result with the expected output
    expected_ouput = open(expected_ouput_path, "r").read()
    # save the result to a file
    with open(f"{output_dir}/input_table_{model.replace('/', '_')}.md", "w") as f:
        f.write(result)
    score = calculate_similarity(result, expected_ouput)
    assert round(score, 3) > 0.75


@pytest.mark.asyncio
@pytest.mark.parametrize("model", models)
async def test_jpg_parse(model):
    input_data = "examples/inputs/test_4.jpg"
    expected_ouput_path = "examples/outputs/test_4.md"
    config = {"parser_type": "LLM_PARSE", "model": model}
    result = parse(input_data, **config)["raw"]
    assert isinstance(result, str)

    # Compare the result with the expected output
    expected_ouput = open(expected_ouput_path, "r").read()
    # save the result to a file
    m_name = model.replace("/", "_")
    with open(f"{output_dir}/input_image_{m_name}.md", "w") as f:
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
    result = parse(sample, **config)["raw"]
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
    result = parse(sample, **config)["raw"]
    assert isinstance(result, str)
    found = [True if p in result else False for p in patterns]
    assert any(found)


@pytest.mark.parametrize("model", models)
@pytest.mark.asyncio
async def test_url_detection_multi_page_auto_routing(model):
    sample = "examples/inputs/sample_test_doc.pdf"
    patterns = ["http", "https", "www"]
    config = {"parser_type": "AUTO", "model": model, "verbose": True}
    results = parse(sample, pages_per_split=1, **config)["segments"]

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
    results = parse("https://example.com/", depth=depth)["segments"]

    # Not necessarily always the case. Just the case for "example.com".
    assert len(results) == depth


@pytest.mark.asyncio
async def test_recursive_url_parsing_in_pdf():
    sample = "examples/inputs/sample_test_doc.pdf"
    parser_type = "AUTO"
    results = parse(sample, parser_type, pages_per_split=1, depth=2)
    assert len(results["recursive_docs"]) >= 7, results


@pytest.mark.asyncio
async def test_parsing_txt_type():
    sample = "examples/inputs/sample_test.txt"
    parser_type = "AUTO"
    results = parse(sample, parser_type)["segments"]
    assert len(results) == 1
    assert results[0]["content"] is not None


@pytest.mark.asyncio
async def test_parsing_docx_type():
    sample = "examples/inputs/sample.docx"
    parser_type = "STATIC_PARSE"
    results = parse(sample, parser_type)["segments"]
    assert len(results) == 1
    assert results[0]["content"] is not None

    parser_type = "LLM_PARSE"
    results = parse(sample, parser_type)["segments"]
    assert len(results) > 1
    assert results[0]["content"] is not None


@pytest.mark.asyncio
async def test_dynamic_js_parsing():
    test_url = "https://go.contentsquare.com/ab-testing-playbook"
    results = parse(test_url, parser_type="AUTO")["raw"]
    # Check if the content contains the expected information
    should_contain_info = "6 Types of experimentation"
    assert should_contain_info.lower() in results.strip().lower()


@pytest.mark.asyncio
async def test_pdfplumber_table_parsing():
    sample = "examples/inputs/test_1.pdf"
    parser_type = "STATIC_PARSE"
    results = parse(sample, parser_type, framework="pdfplumber")["raw"]
    assert [token in results for token in ["|", "Results", "Accuracy"]]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sample",
    [
        ("examples/inputs/stress_test/large_doc_1.pdf", 527),
        ("examples/inputs/stress_test/large_doc_2.pdf", 117),
    ],
)
async def test_large_pdf_parsing(sample):
    parser_type = "AUTO"
    file_name = sample[0]
    n_pages = sample[1]
    results = parse(file_name, parser_type, pages_per_split=1)["segments"]
    assert len(results) == n_pages
    assert results[0]["content"] is not None


token_usage_models = [
    # Google models
    "gemini-2.0-flash-001",
    # OpenAI models
    "gpt-4o",
    # Meta-LLAMA models through HF Hub
    "meta-llama/Llama-3.2-11B-Vision-Instruct",
    # Meta-LLAMA models through Together AI
    "meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo",
]


@pytest.mark.parametrize("model", token_usage_models)
@pytest.mark.asyncio
async def test_token_usage_api(model):
    sample = "examples/inputs/test_1.pdf"
    parser_type = "LLM_PARSE"
    config = {"parser_type": parser_type, "model": model}
    token_usage = parse(sample, **config)["token_usage"]
    logger.info(f"Token usage: {token_usage}")
    assert token_usage["input"] > 0
    assert token_usage["output"] > 0
    assert token_usage["total"] > 0


@pytest.mark.asyncio
def test_pdf_save_path():
    sample = "https://example.com/"
    parser_type = "LLM_PARSE"
    result = parse(
        sample,
        parser_type,
        as_pdf=True,
        save_dir="tests/outputs/temp",
        save_filename="test_output.pdf",
    )
    assert "pdf_path" in result
    assert result["pdf_path"].endswith(".pdf")
    assert os.path.exists(result["pdf_path"])

    # Clean up
    os.remove(result["pdf_path"])
    os.rmdir("tests/outputs/temp")
