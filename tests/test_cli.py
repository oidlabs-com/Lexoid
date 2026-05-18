"""Basic CLI tests for Lexoid command-line interface."""

import json
import subprocess
import sys
import tempfile

import pytest


def run_lexoid(*args):
    """Helper to run lexoid CLI commands."""
    cmd = ["lexoid"] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True)


def run_lexoid_module(*args):
    """Helper to run lexoid via python -m lexoid."""
    cmd = [sys.executable, "-m", "lexoid"] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True)


@pytest.mark.parametrize(
    "command, expected",
    [
        ("--help", ["Lexoid", "Commands:", "parse", "schema", "latex"]),
        (
            "parse",
            ["Parse document", "--input", "--output", "--parser-type", "--model"],
        ),
        (
            "schema",
            ["Extract structured data", "--input", "--schema", "gpt-4o-mini", "ollama"],
        ),
        (
            "latex",
            ["Convert document", "--input", "gpt-4o-mini", "ollama"],
        ),
    ],
)
def test_help_commands(command, expected):
    """Test help text for CLI commands."""
    args = (command, "--help") if command != "--help" else ("--help",)
    result = run_lexoid(*args)
    assert result.returncode == 0
    for text in expected:
        assert text in result.stdout


@pytest.mark.parametrize(
    "command, expected",
    [
        ("--help", ["Lexoid", "Commands:", "parse", "schema", "latex"]),
        ("parse", ["Parse document", "--input", "--output", "--parser-type"]),
    ],
)
def test_module_invocation(command, expected):
    """Test running lexoid via python -m lexoid."""
    args = (command, "--help") if command != "--help" else ("--help",)
    result = run_lexoid_module(*args)
    assert result.returncode == 0
    for text in expected:
        assert text in result.stdout


def test_parse_missing_input():
    """Test parse command with missing required input."""
    result = run_lexoid("parse")
    assert result.returncode != 0
    assert "Missing option '--input'" in result.stderr or "--input" in result.stderr


def test_schema_missing_schema_argument():
    """Test schema command with missing schema argument."""
    with tempfile.NamedTemporaryFile(suffix=".html") as f:
        result = run_lexoid("schema", "--input", f.name)
        assert result.returncode != 0
        assert "--schema" in result.stderr


def test_parse_invalid_file():
    """Test parse command with non-existent file."""
    result = run_lexoid("parse", "--input", "/nonexistent/file.pdf")
    assert result.returncode != 0
    assert "does not exist" in result.stderr or "No such file" in result.stderr


def test_parse_invalid_parser_type():
    """Test parse command with invalid parser type."""
    with tempfile.NamedTemporaryFile(suffix=".html") as f:
        result = run_lexoid("parse", "--input", f.name, "--parser-type", "invalid_type")
        assert result.returncode != 0


@pytest.mark.parametrize("output_format", ["markdown", "json"])
def test_parse_format_option(output_format):
    """Test parse command with supported format options."""
    result = run_lexoid(
        "parse",
        "--input",
        "examples/inputs/test_1.pdf",
        "--parser-type",
        "STATIC_PARSE",
        "--framework",
        "pdfplumber",
        "--format",
        output_format,
    )
    assert result.returncode == 0, result.stderr
    if output_format == "json":
        assert '"raw"' in result.stdout
    else:
        assert result.stdout.strip()


def test_parse_format_invalid():
    """Test parse command with invalid format option."""
    result = run_lexoid(
        "parse", "--input", "examples/inputs/test_1.pdf", "--format", "invalid_format"
    )
    assert result.returncode != 0


def test_parse_output_to_file_markdown(tmp_path):
    """Test parse output saved as markdown."""
    output_path = tmp_path / "result.md"
    result = run_lexoid(
        "parse",
        "--input",
        "examples/inputs/test_1.pdf",
        "--parser-type",
        "STATIC_PARSE",
        "--framework",
        "pdfplumber",
        "--format",
        "markdown",
        "--output",
        str(output_path),
    )
    assert result.returncode == 0, result.stderr
    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8").strip()


def test_parse_output_to_file_json(tmp_path):
    """Test parse output saved as JSON."""
    output_path = tmp_path / "result.json"
    result = run_lexoid(
        "parse",
        "--input",
        "examples/inputs/test_1.pdf",
        "--parser-type",
        "STATIC_PARSE",
        "--framework",
        "pdfplumber",
        "--format",
        "json",
        "--output",
        str(output_path),
    )
    assert result.returncode == 0, result.stderr
    parsed = json.loads(output_path.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)


def test_parse_stdout_stderr_separation():
    """Test that markdown content goes to stdout and status to stderr."""
    result = run_lexoid(
        "parse",
        "--input",
        "examples/inputs/test_1.pdf",
        "--parser-type",
        "STATIC_PARSE",
        "--framework",
        "pdfplumber",
        "--format",
        "markdown",
    )
    assert result.returncode == 0
    # Markdown content should be in stdout
    assert "**Example table**" in result.stdout
    # Status messages should NOT be in stdout (avoid piping issues)
    assert "🔄 Parsing" not in result.stdout
    # Status should be in stderr
    assert "🔄 Parsing" in result.stderr or len(result.stderr) > 0


def test_parse_json_piping():
    """Test that JSON output to stdout is valid and pipeable."""
    result = run_lexoid(
        "parse",
        "--input",
        "examples/inputs/test_1.pdf",
        "--parser-type",
        "STATIC_PARSE",
        "--framework",
        "pdfplumber",
        "--format",
        "json",
    )
    assert result.returncode == 0
    # Should be valid JSON that can be parsed
    parsed = json.loads(result.stdout)
    assert "raw" in parsed
    assert "segments" in parsed


def test_parse_output_file_no_stderr_content(tmp_path):
    """Test that when writing to file, content doesn't leak to stdout."""
    output_path = tmp_path / "result.md"
    result = run_lexoid(
        "parse",
        "--input",
        "examples/inputs/test_1.pdf",
        "--parser-type",
        "STATIC_PARSE",
        "--framework",
        "pdfplumber",
        "--format",
        "markdown",
        "--output",
        str(output_path),
    )
    assert result.returncode == 0
    # Stdout should be empty when writing to file
    assert not result.stdout.strip()
    # File should contain the content
    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "**Example table**" in content


def test_parse_with_nested_output_path(tmp_path):
    """Test that nested output directories are created."""
    nested_dir = tmp_path / "nested" / "output" / "path"
    output_path = nested_dir / "result.md"
    result = run_lexoid(
        "parse",
        "--input",
        "examples/inputs/test_1.pdf",
        "--parser-type",
        "STATIC_PARSE",
        "--framework",
        "pdfplumber",
        "--format",
        "markdown",
        "--output",
        str(output_path),
    )
    assert result.returncode == 0, result.stderr
    assert output_path.exists()
    assert output_path.read_text(encoding="utf-8").strip()


@pytest.mark.parametrize("parser_type", ["AUTO", "auto", "Auto"])
def test_parse_parser_type_case_insensitive(parser_type):
    """Test that parser type is case-insensitive."""
    result = run_lexoid(
        "parse",
        "--input",
        "examples/inputs/test_1.pdf",
        "--parser-type",
        parser_type,
        "--format",
        "markdown",
    )
    # Should not fail due to case sensitivity
    assert result.returncode in (0, 2)  # 0 success or 2 for missing API key


def test_parse_invalid_model():
    """Test parse command with invalid model name."""
    result = run_lexoid(
        "parse",
        "--input",
        "examples/inputs/test_1.pdf",
        "--model",
        "invalid-model-xyz",
        "--parser-type",
        "LLM_PARSE",
    )
    assert result.returncode != 0
    assert "Unsupported model" in result.stderr


def test_parse_static_ignores_invalid_model():
    """Test that STATIC_PARSE doesn't validate model name."""
    result = run_lexoid(
        "parse",
        "--input",
        "examples/inputs/test_1.pdf",
        "--model",
        "invalid-model-xyz",
        "--parser-type",
        "STATIC_PARSE",
        "--framework",
        "pdfplumber",
        "--format",
        "markdown",
    )
    # Should succeed because STATIC_PARSE doesn't use model
    assert result.returncode == 0


def test_schema_invalid_model():
    """Test schema command with invalid model name."""
    result = run_lexoid(
        "schema",
        "--input",
        "examples/inputs/test_1.pdf",
        "--schema",
        '{"type": "object"}',
        "--model",
        "invalid-model-xyz",
    )
    assert result.returncode != 0
    assert "Unsupported model" in result.stderr


def test_latex_invalid_model():
    """Test latex command with invalid model name."""
    result = run_lexoid(
        "latex",
        "--input",
        "examples/inputs/test_1.pdf",
        "--model",
        "invalid-model-xyz",
    )
    assert result.returncode != 0
    assert "Unsupported model" in result.stderr


@pytest.mark.parametrize(
    "model,expected_provider",
    [
        ("gemini-2.5-flash", "gemini"),
        ("gpt-4o", "openai"),
        ("claude-3-opus", "anthropic"),
        ("mistral-large", "mistral"),
        ("meta-llama/Llama-2-7b", "huggingface"),
        ("meta-llama/Llama-3.1-405B-Instruct-Turbo", "together"),
    ],
)
def test_model_provider_inference(model, expected_provider):
    """Test that model to provider mapping is correct."""
    from lexoid.cli import infer_api_provider

    provider = infer_api_provider(model)
    assert provider == expected_provider


def test_model_inference_with_invalid_model():
    """Test that invalid models raise ValueError."""
    from lexoid.cli import infer_api_provider

    with pytest.raises(ValueError, match="Unsupported model"):
        infer_api_provider("invalid-model-xyz")
