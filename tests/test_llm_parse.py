# python3 -m pytest tests/test_llm_parse.py -v
# With logs: python3 -m pytest tests/test_llm_parse.py -v -s

import pytest
from dotenv import load_dotenv
import os
from lexoid.api import parse
from lexoid.core.utils import calculate_similarity

load_dotenv()
output_dir = "tests/outputs"
os.makedirs(output_dir, exist_ok=True)


@pytest.mark.parametrize(
    "models",
    ["gpt-4o", "gpt-4o-mini", "gemini-1.5-flash", "gemini-1.5-pro"],
)
def test_llm_parse(models):
    input_data = "examples/inputs/table.pdf"
    expected_ouput_path = "examples/outputs/table.md"
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
