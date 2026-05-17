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
    "google": "GOOGLE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "together": "TOGETHER_API_KEY",
    "huggingface": "HUGGINGFACEHUB_API_TOKEN",
    "openrouter": "OPENROUTER_API_KEY",
    "fireworks": "FIREWORKS_API_KEY",
}
API_PROVIDER_CHOICES = list(API_KEY_ENV_VARS.keys())

OUTPUT_SEPARATOR = "\n" + "=" * 80


def validate_input_file(path: str) -> Path:
    """Validate that input file exists and is readable."""
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        raise click.FileError(path, hint="File does not exist")
    if not file_path.is_file():
        raise click.UsageError(f"Path is not a file: {path}")
    return file_path


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
    """Infer API provider from model name."""
    model_lower = model.lower()
    if "gemini" in model_lower:
        return "google"
    elif "gpt" in model_lower:
        return "openai"
    elif "claude" in model_lower:
        return "anthropic"
    elif "mistral" in model_lower:
        return "mistral"
    elif "llama" in model_lower or "firefunction" in model_lower:
        return "fireworks"
    return "unknown"


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
    """Write output to a file or stdout."""
    if output_path:
        output_path.write_text(content, encoding="utf-8")
        click.secho(f"✅ {success_message} Output saved to: {output_path}", fg="green")
        return

    click.echo(OUTPUT_SEPARATOR)
    click.echo(content)
    click.echo("=" * 80)


def show_parse_summary(result: dict, output_format: str) -> None:
    """Display parse metadata for markdown output."""
    if output_format != "markdown":
        return

    if result.get("token_usage"):
        click.echo(f"\n📊 Token Usage: {result['token_usage']}")
    if "parsers_used" in result:
        click.echo(f"🔧 Parsers Used: {result['parsers_used']}")


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
    type=click.Path(exists=True, file_okay=True, dir_okay=False),
    help="Path to input file (PDF, image, HTML, DOCX, XLSX, PPTX, or URL)",
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
    type=int,
    default=4,
    help="Number of pages per chunk for processing (default: 4)",
)
@click.option(
    "--max-processes",
    type=int,
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
    help="Output format: markdown (default) or full JSON with metadata",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose logging",
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
):
    """Parse document and extract markdown content."""
    configure_logging(verbose)

    try:
        input_path = validate_input_file(input)
        output_path = validate_output_path(output)

        parser_enum = ParserType[parser_type.upper()]

        if parser_enum in (ParserType.LLM_PARSE, ParserType.AUTO):
            api_provider = resolve_api_provider(model)
            if not ensure_api_key(api_provider, required=False):
                click.secho(
                    f"⚠️  Warning: API key for {api_provider.upper()} not found",
                    fg="yellow",
                    err=True,
                )
                if parser_enum == ParserType.LLM_PARSE:
                    key_name = (
                        api_key_env_var(api_provider)
                        or f"{api_provider.upper()}_API_KEY"
                    )
                    raise click.ClickException(
                        f"API key required for {api_provider.upper()}. "
                        f"Please set {key_name} environment variable."
                    )

        click.echo("🔄 Parsing document...")
        kwargs = {
            "pages_per_split": pages_per_split,
            "max_processes": max_processes,
            "model": model,
        }
        if framework:
            kwargs["framework"] = framework

        result = api_parse(str(input_path), parser_enum, **kwargs)

        output_content = format_parse_output(result, output_format)

        write_output(output_path, output_content, "Successfully parsed!")

        show_parse_summary(result, output_format)

    except click.ClickException:
        raise
    except Exception as e:
        handle_cli_error(e, verbose)


@app.command()
@click.option(
    "--input",
    "-i",
    required=True,
    type=click.Path(exists=True, file_okay=True, dir_okay=False),
    help="Path to input file (PDF, image, HTML, DOCX, XLSX, PPTX, or URL)",
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
    default="gpt-4o-mini",
    help="LLM model to use (default: gpt-4o-mini)",
)
@click.option(
    "--api",
    type=click.Choice(API_PROVIDER_CHOICES),
    default=None,
    help="API provider (auto-detected from model if not specified)",
)
@click.option(
    "--example-schema",
    is_flag=True,
    help="Provide example data conforming to schema",
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

        api = resolve_api_provider(model, api)
        ensure_api_key(api, required=True)

        click.echo("🔄 Extracting structured data...")
        result = api_parse_with_schema(
            str(input_path),
            schema_dict,
            api=api,
            model=model,
            example_schema=example_schema,
            fill_single_schema=fill_single_schema,
        )

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
    type=click.Path(exists=True, file_okay=True, dir_okay=False),
    help="Path to input file (PDF, image, HTML, DOCX, XLSX, PPTX, or URL)",
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
    default="gpt-4o-mini",
    help="LLM model to use (default: gpt-4o-mini)",
)
@click.option(
    "--api",
    type=click.Choice(API_PROVIDER_CHOICES),
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

        api = resolve_api_provider(model, api)
        ensure_api_key(api, required=True)

        click.echo("🔄 Converting to LaTeX...")
        result = api_parse_to_latex(str(input_path), api=api, model=model)

        write_output(output_path, result, "Successfully converted!")

    except click.ClickException:
        raise
    except Exception as e:
        handle_cli_error(e, verbose)


if __name__ == "__main__":
    app()
