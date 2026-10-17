from unittest.mock import patch

import pytest
from lexoid.api import (
    ParserType,
    _set_default_llm_defaults,
    retry_with_different_parser_type,
)


@pytest.mark.parametrize(
    "env_value,expected_model,expected_level",
    [
        (None, "gemini-3.5-flash-lite", "medium"),
        ("gemini-3.8-flash", "gemini-3.8-flash", "medium"),
        (
            '{"model":"gemini-3.5-flash-lite","thinking_level":"medium"}',
            "gemini-3.5-flash-lite",
            "medium",
        ),
        ('{"model":"gemini-3.8-flash"}', "gemini-3.8-flash", "medium"),
    ],
)
@pytest.mark.asyncio
async def test_default_llm_defaults_and_overrides(
    monkeypatch: pytest.MonkeyPatch,
    env_value: str | None,
    expected_model: str,
    expected_level: str,
) -> None:
    if env_value is None:
        monkeypatch.delenv("DEFAULT_LLM", raising=False)
    else:
        monkeypatch.setenv("DEFAULT_LLM", env_value)

    def capture_kwargs(**kwargs: object) -> dict[str, object]:
        return kwargs

    parse_with_routing = retry_with_different_parser_type(capture_kwargs)
    with patch("lexoid.api.router", return_value=("LLM_PARSE", None)):
        defaults = parse_with_routing("sample.pdf", ParserType.AUTO)
        assert defaults["model"] == expected_model
        assert defaults["thinking_level"] == expected_level

        keyword_defaults = parse_with_routing("sample.pdf", parser_type="AUTO")
        assert keyword_defaults["model"] == expected_model
        assert keyword_defaults["thinking_level"] == expected_level

        thinking_override = parse_with_routing(
            "sample.pdf", ParserType.AUTO, thinking_level="high"
        )
        assert thinking_override["model"] == expected_model
        assert thinking_override["thinking_level"] == "high"

        overrides = parse_with_routing(
            "sample.pdf",
            ParserType.AUTO,
            model="gemini-3.8-flash",
            thinking_level="low",
        )
        assert overrides["model"] == "gemini-3.8-flash"
        assert overrides["thinking_level"] == "low"


@pytest.mark.asyncio
async def test_direct_llm_parse_uses_default_llm_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DEFAULT_LLM",
        '{"model":"gemini-3.5-flash-lite","thinking_level":"medium"}',
    )

    def capture_kwargs(**kwargs: object) -> dict[str, object]:
        return kwargs

    parse_with_routing = retry_with_different_parser_type(capture_kwargs)
    defaults = parse_with_routing("sample.pdf", ParserType.LLM_PARSE)

    assert defaults["model"] == "gemini-3.5-flash-lite"
    assert defaults["thinking_level"] == "medium"


@pytest.mark.asyncio
async def test_auto_selector_model_is_not_replaced_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEFAULT_LLM", "gemini-3.5-flash-lite")

    def capture_kwargs(**kwargs: object) -> dict[str, object]:
        return kwargs

    parse_with_routing = retry_with_different_parser_type(capture_kwargs)
    with patch("lexoid.api.router", return_value=("LLM_PARSE", "gemini-3.8-flash")):
        result = parse_with_routing("sample.pdf", ParserType.AUTO, autoselect_llm=True)
        explicit_result = parse_with_routing(
            "sample.pdf",
            ParserType.AUTO,
            autoselect_llm=True,
            model="gemini-3.7-flash",
        )

    assert result["model"] == "gemini-3.8-flash"
    assert explicit_result["model"] == "gemini-3.7-flash"


@pytest.mark.parametrize(
    "env_value",
    [
        "",
        "{invalid",
        "[]",
        '"gemini-3.8-flash"',
        "{}",
        '{"model":null}',
        '{"model":" "}',
        '{"model":"gemini-3.8-flash","unknown":true}',
        '{"model":"gemini-3.8-flash","thinking_level":"invalid"}',
    ],
)
@pytest.mark.asyncio
async def test_default_llm_invalid_environment(
    monkeypatch: pytest.MonkeyPatch, env_value: str
) -> None:
    monkeypatch.setenv("DEFAULT_LLM", env_value)
    with pytest.raises(ValueError, match="DEFAULT_LLM"):
        _set_default_llm_defaults({})
    explicit = {"model": "gemini-3.8-flash"}
    _set_default_llm_defaults(explicit)
    assert explicit == {"model": "gemini-3.8-flash"}
