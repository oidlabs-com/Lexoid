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
        ("--help", ["Lexoid", "Commands:", "parse", "schema", "latex", "browse"]),
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
        (
            "browse",
            [
                "web-operator",
                "--model",
                "--model-config",
                "--headless",
                "--headed",
                "--cdp-url",
                "--max-steps",
                "--max-pages",
                "--format",
            ],
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
        ("--help", ["Lexoid", "Commands:", "parse", "schema", "latex", "browse"]),
        ("parse", ["Parse document", "--input", "--output", "--parser-type"]),
        ("browse", ["web-operator", "--model", "--headless"]),
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
        ("gemini-3.8-flash", "gemini"),
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


def test_browse_missing_query():
    """Test browse command fails when no query is provided."""
    result = run_lexoid("browse")
    assert result.returncode != 0
    assert "Missing argument 'QUERY'" in result.stderr or "QUERY" in result.stderr


def test_browse_conflicting_model_options(tmp_path):
    """Test browse command rejects both --model and --model-config."""
    from click.testing import CliRunner

    from lexoid import cli

    config_file = tmp_path / "roles.json"
    config_file.write_text('{"default": "gpt-6.2-sol"}', encoding="utf-8")

    result = CliRunner().invoke(
        cli.app,
        [
            "browse",
            "Find pricing on https://example.com/",
            "--model",
            "gpt-6.2-sol",
            "--model-config",
            str(config_file),
        ],
    )

    assert result.exit_code != 0
    assert "not both" in result.output


def test_browse_options_markdown(monkeypatch):
    """Test browse CLI forwards options to api.browse and formats markdown output."""
    from click.testing import CliRunner

    from lexoid import cli
    from lexoid.core.browse.schemas import (
        BrowseLimits,
        BrowseResult,
        BrowseTask,
        BrowseTaskResult,
        BrowseTerminalState,
        BrowseUsage,
    )

    captured: dict[str, object] = {}

    async def fake_browse(query, **kwargs):
        captured["query"] = query
        captured["kwargs"] = kwargs
        return BrowseResult(
            answer="Grounded answer from example.com",
            task_results=[
                BrowseTaskResult(
                    task=BrowseTask(
                        seed_urls=["https://example.com/"],
                        subject="Find pricing",
                        allowed_domains=["example.com"],
                    ),
                    status=BrowseTerminalState.COMPLETED,
                )
            ],
            warnings=["Sample warning"],
            usage=BrowseUsage(input=10, output=5, total=15),
        )

    monkeypatch.setattr(cli, "api_browse", fake_browse)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "browse",
            "Find pricing on https://example.com/",
            "--model",
            "gpt-6.2-sol",
            "--headed",
            "--no-mute-audio",
            "--cdp-url",
            "http://localhost:9222",
            "--channel",
            "chrome",
            "--max-steps",
            "25",
            "--max-pages",
            "3",
            "--timeout-ms",
            "30000",
            "--default-search-url",
            "https://www.bing.com/",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Grounded answer from example.com" in result.output
    assert captured["query"] == "Find pricing on https://example.com/"
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["model_config"] == "gpt-6.2-sol"
    assert kwargs["headless"] is False
    assert kwargs["mute_audio"] is False
    assert kwargs["cdp_url"] == "http://localhost:9222"
    assert kwargs["channel"] == "chrome"
    assert kwargs["default_search_url"] == "https://www.bing.com/"
    assert kwargs["limits"] == BrowseLimits(max_steps=25, max_pages=3, timeout_ms=30000)


def test_browse_model_config_json(monkeypatch, tmp_path):
    """Test browse CLI loads a --model-config file and writes JSON output."""
    from click.testing import CliRunner

    from lexoid import cli
    from lexoid.core.browse.schemas import BrowseModelConfig, BrowseResult

    config_file = tmp_path / "roles.json"
    config_file.write_text(
        json.dumps(
            {
                "default": "gpt-6.2-sol",
                "planner": {
                    "model": "gpt-6-luna",
                    "reasoning": {"effort": "high", "summary": "detailed"},
                    "options": {"verbosity": "high"},
                },
            }
        ),
        encoding="utf-8",
    )
    output_file = tmp_path / "browse_result.json"
    captured: dict[str, object] = {}

    async def fake_browse(query, **kwargs):
        captured["query"] = query
        captured["kwargs"] = kwargs
        return BrowseResult(answer="All systems operational.")

    monkeypatch.setattr(cli, "api_browse", fake_browse)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "browse",
            "Check the status at https://example.com/",
            "--model-config",
            str(config_file),
            "--format",
            "json",
            "--output",
            str(output_file),
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["query"] == "Check the status at https://example.com/"
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["model_config"] == BrowseModelConfig(
        default="gpt-6.2-sol",
        planner={
            "model": "gpt-6-luna",
            "reasoning": {"effort": "high", "summary": "detailed"},
            "options": {"verbosity": "high"},
        },
    )
    assert kwargs["headless"] is True
    assert kwargs["mute_audio"] is True
    assert kwargs["limits"] is None
    saved = json.loads(output_file.read_text(encoding="utf-8"))
    assert saved["answer"] == "All systems operational."


def test_browse_model_config_unknown_keys(tmp_path):
    """Test Pydantic rejects unknown keys in a model config file."""
    from click.testing import CliRunner

    from lexoid import cli

    config_file = tmp_path / "roles.json"
    config_file.write_text('{"planner": "gpt-6-luna", "typo": true}', encoding="utf-8")

    result = CliRunner().invoke(
        cli.app,
        ["browse", "Find recent filings", "--model-config", str(config_file)],
    )

    assert result.exit_code != 0
    assert str(config_file) in result.output
    assert "Extra inputs are not permitted" in result.output
