# python3 -m pytest tests/test_llm_parse.py -v
# With logs: python3 -m pytest tests/test_llm_parse.py -v -s

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
