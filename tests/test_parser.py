# python3 -m pytest tests/test_parser.py -v
# With logs: python3 -m pytest tests/test_parser.py -v -s

import os

import pytest
from benchmark_utils import calculate_similarities
from dotenv import load_dotenv
from loguru import logger

from lexoid.api import parse, parse_with_schema

load_dotenv()
output_dir = "tests/outputs"
os.makedirs(output_dir, exist_ok=True)
models = [
    # Google models
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    # OpenAI models
    "gpt-4o",
    "gpt-4o-mini",
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
    score = calculate_similarities(result, expected_ouput)["sequence_matcher"]
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
    score = calculate_similarities(result, expected_ouput)["sequence_matcher"]
    assert round(score, 3) > 0.8


@pytest.mark.asyncio
async def test_static_parse_images():
    input_data = "examples/inputs/cvs_coupon.jpg"
    result = parse(input_data, parser_type="STATIC_PARSE")["raw"]
    assert isinstance(result, str)


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


@pytest.mark.asyncio
async def test_url_detection_multi_page_auto_routing():
    sample = "examples/inputs/sample_test_doc.pdf"
    patterns = ["http", "https", "www"]
    config = {"parser_type": "AUTO", "verbose": True}
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
    results = parse("https://example.com/", depth=depth)

    n_total_segments = len(results["segments"]) + len(results["recursive_docs"])
    # Each depth level adds one more document to be parsed.
    # Not necessarily always the case. Just the case for "example.com".
    assert n_total_segments == depth, str(results)


@pytest.mark.asyncio
async def test_recursive_url_parsing_in_pdf():
    sample = "examples/inputs/sample_test_doc.pdf"
    parser_type = "AUTO"
    results = parse(sample, parser_type, pages_per_split=1, depth=2)
    assert len(results["recursive_docs"]) >= 7, results


@pytest.mark.asyncio
async def test_parsing_txt_type():
    # Contains invalid unicode characters that should be ignored
    sample = "examples/inputs/sample_test.txt"
    parser_type = "AUTO"
    results = parse(sample, parser_type)["segments"]
    assert len(results) == 1
    assert results[0]["content"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sample_url",
    [
        "https://www.justice.gov/archive/enron/exhibit/02-28/BBC-0001/OCR/EXH033-00243.TXT",
        "https://www.justice.gov/archive/enron/exhibit/03-28-p3/BBC-0001/OCR/EXH063-00292.TXT",
    ],
)
async def test_parsing_url_txt_type(sample_url):
    parser_type = "AUTO"
    results_1 = parse(
        sample_url, parser_type, page_nums=1, pages_per_split=1, as_pdf=False
    )["raw"]

    results_2 = parse(
        sample_url, parser_type, page_nums=1, pages_per_split=1, as_pdf=True
    )["raw"]
    assert len([results_1]) == 1
    assert len([results_2]) == 1

    if sample_url.endswith("EXH033-00243.TXT"):
        assert "David W Delainey" in results_1
        assert "David W Delainey" in results_2
    if sample_url.endswith("EXH063-00292.TXT"):
        # Contains invalid bytes that should be ignored
        assert "Please call Sherrie Gibson" in results_1
        assert "Please call Sherrie Gibson" in results_2


@pytest.mark.asyncio
async def test_parsing_arxiv_url():
    sample_url = "https://arxiv.org/pdf/2506.06576"
    parser_type = "AUTO"
    result = parse(sample_url, parser_type, page_nums=1, pages_per_split=1, as_pdf=True)
    assert result is not None
    assert "2506.06576" in result["raw"]
    assert "Future of Work with AI Agents" in result["raw"]


@pytest.mark.asyncio
async def test_parsing_docx_type():
    sample = "examples/inputs/sample.docx"
    parser_type = "STATIC_PARSE"
    results = parse(sample, parser_type)["segments"]
    assert len(results) >= 1
    assert results[0]["content"] is not None

    parser_type = "LLM_PARSE"
    results = parse(sample, parser_type)["segments"]
    assert len(results) > 1
    assert results[0]["content"] is not None


@pytest.mark.asyncio
async def test_parsing_xlsx_type():
    sample = "examples/inputs/sample.xlsx"
    parser_type = "STATIC_PARSE"
    results = parse(sample, parser_type)["segments"]
    assert len(results) >= 1
    assert results[0]["content"] is not None


@pytest.mark.asyncio
async def test_parsing_pptx_type():
    sample = "examples/inputs/sample.pptx"
    parser_type = "STATIC_PARSE"
    results = parse(sample, parser_type)["segments"]
    assert len(results) >= 1
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


@pytest.mark.parametrize("model", models)
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
async def test_pdf_save_path():
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


@pytest.mark.asyncio
async def test_page_nums():
    sample = "examples/inputs/sample_test_doc.pdf"
    result = parse(sample, "LLM_PARSE", page_nums=(3, 4), pages_per_split=1)
    assert len(result["segments"]) == 2
    assert all(keyword in result["raw"] for keyword in ["Table 24", "apple"])
    assert all(keyword not in result["raw"] for keyword in ["Aenean", "Lexoid"])

    result = parse(sample, "LLM_PARSE", page_nums=(3, 3), pages_per_split=1)
    assert len(result["segments"]) == 1
    assert "Table 24" in result["raw"]

    sample = "https://www.dca.ca.gov/acp/pdf_files/lemonlaw_qa.pdf"
    result = parse(sample, "STATIC_PARSE", page_nums=2, pages_per_split=1)
    assert len(result["segments"]) == 1
    assert "ATTEMPTS" in result["raw"]
    assert "acp@dca.ca.gov" not in result["raw"]


@pytest.mark.parametrize("model", models)
@pytest.mark.asyncio
async def test_token_cost(model):
    sample = "examples/inputs/test_1.pdf"
    parser_type = "LLM_PARSE"
    api_cost_path = os.path.join(os.path.dirname(__file__), "api_cost_mapping.json")
    config = {
        "parser_type": parser_type,
        "model": model,
        "api_cost_mapping": api_cost_path,
    }
    result = parse(sample, **config)
    assert "token_cost" in result
    assert result["token_cost"]["input"] > 0
    assert result["token_cost"]["output"] > 0
    assert result["token_cost"]["total"] > 0


@pytest.mark.asyncio
async def test_blockquote():
    sample = "examples/inputs/bench_md.pdf"
    parser_type = "STATIC_PARSE"
    results = parse(sample, parser_type, framework="pdfplumber")["raw"]
    # Assert that there is at least one fenced code block
    assert "&nbsp;" * 3 in results


@pytest.mark.asyncio
async def test_monospace_code_block():
    sample = "examples/inputs/bench_md.pdf"
    parser_type = "STATIC_PARSE"
    results = parse(sample, parser_type, framework="pdfplumber")["raw"]
    # Assert that there is at least one fenced code block
    assert "```" in results


@pytest.mark.asyncio
async def test_pdf_headings():
    sample_path = "examples/inputs/bench_md.pdf"
    parser_type = "STATIC_PARSE"
    results = parse(sample_path, parser_type, framework="pdfplumber")["raw"]

    # Test for h1 (should have # in markdown)
    assert "#" in results
    assert "##" in results


@pytest.mark.asyncio
async def test_email_address():
    sample = "examples/inputs/bench_md.pdf"
    parser_type = "STATIC_PARSE"
    results = parse(sample, parser_type, framework="pdfplumber")["raw"]
    assert "<mail@example.com>" in results


@pytest.mark.asyncio
async def test_horizontal_lines():
    sample = "examples/inputs/bench_md.pdf"
    parser_type = "STATIC_PARSE"
    results = parse(sample, parser_type, framework="pdfplumber")["raw"]
    assert "\n---\n" in results, "Markdown horizontal rule not found"


@pytest.mark.asyncio
async def test_strikethrough_words():
    sample = "examples/inputs/bench_md.pdf"
    parser_type = "STATIC_PARSE"
    results = parse(sample, parser_type, framework="pdfplumber")["raw"]
    assert "~~" in results, "Markdown strikethrough text not found"


@pytest.mark.parametrize(
    "sample",
    [
        "test$(mkdir -p path_injection_success).docx",
        "test; mkdir -p path_injection_success.docx",
        "test|mkdir -p path_injection_success.docx",
        "test&&mkdir -p path_injection_success.docx",
    ],
)
@pytest.mark.asyncio
async def test_docx_path_injection(sample):
    # Attempt to inject a directory creation command via the filename
    parser_type = "STATIC_PARSE"
    dir_name = "path_injection_success"
    try:
        parse(sample, parser_type, retry_on_fail=False)["raw"]
    except Exception as e:
        print(f"Parsing failed: {e}")
        assert "Package not found" in str(e)
    finally:
        if os.path.exists(dir_name):
            os.rmdir(dir_name)
            assert False, "Path injection detected"


@pytest.mark.asyncio
async def test_parse_with_schema():
    sample_schema = {
        "Disability Category": "string",
        "Participants": "int",
        "Ballots Completed": "int",
        "Ballots Incomplete/Terminated": "int",
        "Accuracy": ["string"],
        "Time to complete": ["string"],
    }
    pdf_path = "examples/inputs/test_1.pdf"
    result = parse_with_schema(path=pdf_path, schema=sample_schema)[0][0]
    assert isinstance(result, dict)
    assert all(key in result for key in sample_schema.keys())


@pytest.mark.parametrize("character_threshold", [160, 100])
@pytest.mark.asyncio
async def test_cost_priority_routing(character_threshold):
    sample = "examples/inputs/cvs_coupon.jpg"
    parser_type = "AUTO"
    router_priority = "cost"
    api_cost_path = os.path.join(os.path.dirname(__file__), "api_cost_mapping.json")
    config = {
        "parser_type": parser_type,
        "router_priority": router_priority,
        "page_nums": 1,
        "pages_per_split": 1,
        "character_threshold": character_threshold,
        "api_cost_mapping": api_cost_path,
    }
    result = parse(sample, **config)
    logger.debug(f"Token cost: {result['token_cost']}")
    if character_threshold > 150:
        assert "STATIC_PARSE" in result["parsers_used"]
        assert result["token_cost"]["total"] == 0
    else:
        assert "LLM_PARSE" in result["parsers_used"]
        assert result["token_cost"]["total"] > 0


@pytest.mark.asyncio
async def test_audio_parse():
    path = "examples/inputs/audio/harvard.wav"
    parsed_md = parse(path, parser_type="LLM_PARSE", model="gemini-2.5-flash")["raw"]
    assert "zestful food is the hot cross bun" in parsed_md
