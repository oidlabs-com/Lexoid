"""Basic CLI tests for Lexoid command-line interface."""

import json
import subprocess
import tempfile

import pytest


def run_lexoid(*args):
    """Helper to run lexoid CLI commands."""
    cmd = ["lexoid"] + list(args)
    return subprocess.run(cmd, capture_output=True, text=True)


@pytest.mark.parametrize(
    "command, expected",
    [
        ("--help", ["Lexoid", "Commands:", "parse", "schema", "latex"]),
        (
            "parse",
            ["Parse document", "--input", "--output", "--parser-type", "--model"],
        ),
        ("schema", ["Extract structured data", "--input", "--schema"]),
        ("latex", ["Convert document", "--input"]),
    ],
)
def test_help_commands(command, expected):
    """Test help text for CLI commands."""
    args = (command, "--help") if command != "--help" else ("--help",)
    result = run_lexoid(*args)
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
    assert "raw" in parsed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
