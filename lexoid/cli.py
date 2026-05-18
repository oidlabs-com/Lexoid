#!/usr/bin/env python3
"""Command-line interface for Lexoid document parsing library."""

import json
import os
from pathlib import Path
from typing import Optional

import click
from loguru import logger

from lexoid.api import ParserType
from lexoid.api import parse as api_parse
from lexoid.api import parse_to_latex as api_parse_to_latex
from lexoid.api import parse_with_schema as api_parse_with_schema
from lexoid.core.utils import DEFAULT_LLM


API_KEY_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GOOGLE_API_KEY",  # Use 'gemini' as provider name, GOOGLE_API_KEY for credentials
    "anthropic": "ANTHROPIC_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "together": "TOGETHER_API_KEY",
    "huggingface": "HUGGINGFACEHUB_API_TOKEN",
    "openrouter": "OPENROUTER_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
    "ollama": None,
    "local": None,  # Local models don't require an API key
}
API_PROVIDER_CHOICES = [k for k in API_KEY_ENV_VARS.keys() if k != "local"]
DEFAULT_SCHEMA_LLM = "gpt-4o-mini"


def validate_input_file(path: str) -> str:
    """Validate that input is a file path or supported URL.

    Returns the path/URL as a string. URLs (http://, https://) are passed through.
    File paths are validated to exist and be readable.
    """
    if path.startswith(("http://", "https://")):
        return path  # Pass URLs through as-is; downstream handles them

    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        raise click.FileError(path, hint="File does not exist")
    if not file_path.is_file():
        raise click.UsageError(f"Path is not a file: {path}")
    return str(file_path)


def validate_output_path(path: Optional[str]) -> Optional[Path]:
    """Validate and prepare output path."""
    if path is None:
        return None
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def configure_logging(verbose: bool) -> None:
    """Enable or disable Lexoid logging."""
    if verbose:
        logger.enable("lexoid")
    else:
        logger.disable("lexoid")


def api_key_env_var(api_provider: str) -> Optional[str]:
    """Return the environment variable used for an API provider."""
    return API_KEY_ENV_VARS.get(api_provider.lower())


def check_api_key(api_provider: str) -> bool:
    """Check if required API key is set for provider."""
    key_name = api_key_env_var(api_provider)
    if key_name and not os.getenv(key_name):
        return False
    return True


def ensure_api_key(api_provider: str, *, required: bool) -> bool:
    """Validate the configured API key for a provider."""
    has_key = check_api_key(api_provider)
    if has_key:
        return True

    if required:
        key_name = api_key_env_var(api_provider) or f"{api_provider.upper()}_API_KEY"
        raise click.ClickException(
            f"API key required for {api_provider.upper()}. "
            f"Please set {key_name} environment variable."
        )

    return False


def infer_api_provider(model: str) -> str:
    """Infer API provider from model name.

    Provider names must match those used in lexoid.core.utils.get_api_provider_for_model().
    Raises ValueError if model is not recognized to match core library behavior.
    """
    model_lower = model.lower()

    # Match logic from lexoid.core.utils.get_api_provider_for_model
    if model_lower.startswith("gemini"):
        return "gemini"
    if model_lower.startswith("gpt"):
        return "openai"
    if model_lower.startswith("meta-llama"):
        if "turbo" in model_lower or model == "meta-llama/Llama-Vision-Free":
            return "together"
        return "huggingface"
    if any(
        model_lower.startswith(prefix) for prefix in ["microsoft", "google", "qwen"]
    ):
        return "openrouter"
    if model_lower.startswith("accounts/fireworks"):
        return "fireworks"
    if model_lower.startswith("claude"):
        return "anthropic"
    if model_lower.startswith("mistral"):
        return "mistral"
    if "docling" in model_lower:
        return "local"
    if model_lower.startswith("paddlepaddle/paddleocr-vl"):
        return "local"

    raise ValueError(f"Unsupported model: {model}")


def resolve_api_provider(model: str, api: Optional[str] = None) -> str:
    """Resolve the API provider from an explicit override or model name."""
    return api or infer_api_provider(model)


def load_schema_definition(schema: str) -> dict:
    """Load a schema from a path or inline JSON string."""
    schema_path = Path(schema).expanduser()
    if schema_path.exists() and schema_path.is_file():
        try:
            return json.loads(schema_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise click.ClickException(f"Invalid JSON in schema file: {error}")

    try:
        return json.loads(schema)
    except json.JSONDecodeError as error:
        raise click.ClickException(
            f"Schema must be valid JSON (file or inline string): {error}"
        )


def format_parse_output(result: dict, output_format: str) -> str:
    """Format parse output as markdown or JSON."""
    if output_format == "json":
        return json.dumps(result, indent=2, ensure_ascii=False)
    return result["raw"]


def write_output(
    output_path: Optional[Path], content: str, success_message: str
) -> None:
    """Write output to a file or stdout.

    When outputting to stdout, only the content is written to stdout (for clean piping).
    Status messages go to stderr.
    """
    if output_path:
        output_path.write_text(content, encoding="utf-8")
        click.secho(
            f"✅ {success_message} Output saved to: {output_path}", fg="green", err=True
        )
        return

    # Write only content to stdout for clean piping; status to stderr
    click.echo(content)


def show_parse_summary(result: dict, output_format: str, to_file: bool = False) -> None:
    """Display parse metadata for markdown output to stderr (for piping)."""
    if output_format != "markdown" or to_file:
        return

    if result.get("token_usage"):
        click.echo(f"\n📊 Token Usage: {result['token_usage']}", err=True)
    if "parsers_used" in result:
        click.echo(f"🔧 Parsers Used: {result['parsers_used']}", err=True)


def handle_cli_error(error: Exception, verbose: bool) -> None:
    """Convert unexpected exceptions to Click errors."""
    if verbose:
        import traceback

        traceback.print_exc()
    raise click.ClickException(str(error))


@click.group(invoke_without_command=False)
@click.version_option()
def app():
    """Lexoid: Convert PDFs, images, web pages, and documents into structured markdown."""
    pass


@app.command()
@click.option(
    "--input",
    "-i",
    required=True,
    type=str,
    help="Path to input file (PDF, image, HTML, DOCX, XLSX, PPTX) or URL (http://, https://)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Path to output markdown file (default: print to stdout)",
)
@click.option(
    "--parser-type",
    "-p",
    type=click.Choice(["AUTO", "LLM_PARSE", "STATIC_PARSE"], case_sensitive=False),
    default="AUTO",
    help="Parser type (default: AUTO)",
)
@click.option(
    "--model",
    "-m",
    default=DEFAULT_LLM,
    help=f"LLM model to use (default: {DEFAULT_LLM})",
)
@click.option(
    "--pages-per-split",
    type=click.IntRange(min=1),
    default=4,
    help="Number of pages per chunk for processing (default: 4)",
)
@click.option(
    "--max-processes",
    type=click.IntRange(min=1),
    default=4,
    help="Maximum parallel processes (default: 4)",
)
@click.option(
    "--framework",
    type=click.Choice(["pdfplumber", "paddleocr"]),
    default=None,
    help="Static parsing framework (auto-detected if not specified)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["markdown", "json"]),
    default="markdown",
    help="Output format: markdown (default, plain markdown text) or json (full result with metadata)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose logging",
)
@click.option(
    "--api",
    type=click.Choice(API_PROVIDER_CHOICES, case_sensitive=False),
    default=None,
    help="API provider override (auto-detected from model if not specified)",
)
def parse(
    input,
    output,
    parser_type,
    model,
    pages_per_split,
    max_processes,
    framework,
    output_format,
    verbose,
    api,
):
    """Parse document and extract markdown content."""
    configure_logging(verbose)

    try:
        input_path = validate_input_file(input)
        output_path = validate_output_path(output)

        parser_enum = ParserType[parser_type.upper()]

        api_provider = None
        if parser_enum == ParserType.LLM_PARSE:
            try:
                api_provider = resolve_api_provider(model, api)
            except ValueError as e:
                raise click.ClickException(str(e))

            if not ensure_api_key(api_provider, required=False):
                click.secho(
                    f"⚠️  Warning: API key for {api_provider.upper()} not found",
                    fg="yellow",
                    err=True,
                )
                key_name = (
                    api_key_env_var(api_provider) or f"{api_provider.upper()}_API_KEY"
                )
                raise click.ClickException(
                    f"API key required for {api_provider.upper()}. "
                    f"Please set {key_name} environment variable."
                )

        elif parser_enum == ParserType.AUTO:
            if api:
                api_provider = api
                # warn if API key missing but do not fail here; core may choose STATIC_PARSE
                if not ensure_api_key(api_provider, required=False):
                    click.secho(
                        f"⚠️  Warning: API key for {api_provider.upper()} not found",
                        fg="yellow",
                        err=True,
                    )

        click.echo("🔄 Parsing document...", err=True)
        kwargs = {
            "pages_per_split": pages_per_split,
            "max_processes": max_processes,
            "model": model,
        }
        if api_provider:
            kwargs["api_provider"] = api_provider
        if framework:
            kwargs["framework"] = framework

        try:
            result = api_parse(input_path, parser_enum, **kwargs)
        except ValueError as e:
            raise click.ClickException(str(e))
        except Exception as e:
            # Re-raise click exceptions as-is, convert others
            if isinstance(e, click.ClickException):
                raise
            raise click.ClickException(f"Parsing failed: {str(e)}")

        output_content = format_parse_output(result, output_format)

        write_output(output_path, output_content, "Successfully parsed!")

        show_parse_summary(result, output_format, to_file=output_path is not None)

    except click.ClickException:
        raise
    except Exception as e:
        handle_cli_error(e, verbose)


@app.command()
@click.option(
    "--input",
    "-i",
    required=True,
    type=str,
    help="Path to input file (PDF, image, HTML, DOCX, XLSX, PPTX) or URL (http://, https://)",
)
@click.option(
    "--schema",
    "-s",
    required=True,
    help="JSON schema for extraction (file path or inline JSON string)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Path to output JSON file (default: print to stdout)",
)
@click.option(
    "--model",
    "-m",
    default=DEFAULT_SCHEMA_LLM,
    help=f"LLM model to use (default: {DEFAULT_SCHEMA_LLM})",
)
@click.option(
    "--api",
    type=click.Choice(API_PROVIDER_CHOICES, case_sensitive=False),
    default=None,
    help="API provider (auto-detected from model if not specified)",
)
@click.option(
    "--example-schema",
    type=str,
    default=None,
    help="Example data conforming to schema (JSON string or file path); enables example-based extraction",
)
@click.option(
    "--fill-single-schema",
    is_flag=True,
    help="Fill single schema if multiple are provided",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose logging",
)
def schema(
    input,
    schema,
    output,
    model,
    api,
    example_schema,
    fill_single_schema,
    verbose,
):
    """Extract structured data from document using JSON schema."""
    configure_logging(verbose)

    try:
        input_path = validate_input_file(input)
        output_path = validate_output_path(output)
        schema_dict = load_schema_definition(schema)

        try:
            api = resolve_api_provider(model, api)
        except ValueError as e:
            raise click.ClickException(str(e))

        ensure_api_key(api, required=True)

        # Load example schema if provided
        example_data = None
        if example_schema:
            example_data = load_schema_definition(example_schema)

        click.echo("🔄 Extracting structured data...", err=True)
        try:
            result = api_parse_with_schema(
                input_path,
                schema_dict,
                api=api,
                model=model,
                example_schema=example_data,
                fill_single_schema=fill_single_schema,
            )
        except ValueError as e:
            raise click.ClickException(str(e))
        except Exception as e:
            if isinstance(e, click.ClickException):
                raise
            raise click.ClickException(f"Schema extraction failed: {str(e)}")

        output_json = json.dumps(result, indent=2, ensure_ascii=False)
        write_output(output_path, output_json, "Successfully extracted!")

    except click.ClickException:
        raise
    except Exception as e:
        handle_cli_error(e, verbose)


@app.command()
@click.option(
    "--input",
    "-i",
    required=True,
    type=str,
    help="Path to input file (PDF, image, HTML, DOCX, XLSX, PPTX) or URL (http://, https://)",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Path to output LaTeX file (default: print to stdout)",
)
@click.option(
    "--model",
    "-m",
    default=DEFAULT_SCHEMA_LLM,
    help=f"LLM model to use (default: {DEFAULT_SCHEMA_LLM})",
)
@click.option(
    "--api",
    type=click.Choice(API_PROVIDER_CHOICES, case_sensitive=False),
    default=None,
    help="API provider (auto-detected from model if not specified)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose logging",
)
def latex(input, output, model, api, verbose):
    """Convert document to LaTeX format."""
    configure_logging(verbose)

    try:
        input_path = validate_input_file(input)
        output_path = validate_output_path(output)

        try:
            api = resolve_api_provider(model, api)
        except ValueError as e:
            raise click.ClickException(str(e))

        ensure_api_key(api, required=True)

        click.echo("🔄 Converting to LaTeX...", err=True)
        try:
            result = api_parse_to_latex(input_path, api=api, model=model)
        except ValueError as e:
            raise click.ClickException(str(e))
        except Exception as e:
            if isinstance(e, click.ClickException):
                raise
            raise click.ClickException(f"LaTeX conversion failed: {str(e)}")

        write_output(output_path, result, "Successfully converted!")

    except click.ClickException:
        raise
    except Exception as e:
        handle_cli_error(e, verbose)


if __name__ == "__main__":
    app()
