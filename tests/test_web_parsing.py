import re
from importlib.util import find_spec

import pytest
from lexoid.api import parse
from lexoid.core import conversion_utils

_TEST_URL = "https://jnhlifestyles.com/blog/top-5-reasons-to-add-a-full-spectrum-infrared-sauna-into-your-home/"

# Stable phrases that must survive rendering and PDF extraction.
_EXPECTED_PHRASES = [
    "$8,000",
    "Tosi",
    "ProSeries",
    "the carbon fiber heaters",
    "24 February 2020",
    "https://www.ncbi.nlm.nih.gov/pubmed/18685882",
]


def _normalize(text: str) -> str:
    """Collapse whitespace and non-breaking spaces for robust phrase matching."""
    text = text.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


_HAS_PLAYWRIGHT = find_spec("playwright") is not None
_HAS_PYQT5 = find_spec("PyQt5") is not None


@pytest.mark.parametrize(
    "engine",
    [
        pytest.param(
            "chromium",
            marks=pytest.mark.skipif(
                not _HAS_PLAYWRIGHT,
                reason="Playwright is required for chromium engine test",
            ),
        ),
        pytest.param(
            "qt",
            marks=pytest.mark.skipif(
                not _HAS_PYQT5,
                reason="PyQt5 is required for qt engine test",
            ),
        ),
    ],
)
@pytest.mark.parametrize(
    "parser_type, parser_kwargs",
    [
        pytest.param("STATIC_PARSE", {}, id="static_parse"),
        pytest.param("AUTO", {"model": "gemini-3.6-flash"}, id="auto_gemini_3_6_flash"),
        pytest.param("AUTO", {"model": "claude-opus-4-8"}, id="auto_claude_opus_4_8"),
    ],
)
@pytest.mark.asyncio
async def test_webpage_rendering(tmp_path, engine, parser_type, parser_kwargs):
    import os

    if not os.getenv("RUN_WEB_RENDER_TESTS"):
        pytest.skip("RUN_WEB_RENDER_TESTS is not enabled")

    output_path = tmp_path / f"test-preview-{engine}.pdf"

    result = conversion_utils.save_webpage_as_pdf(
        _TEST_URL,
        str(output_path),
        engine=engine,
    )

    assert result == str(output_path)
    assert output_path.exists()
    assert output_path.stat().st_size > 0

    parsed = parse(
        str(output_path),
        parser_type=parser_type,
        router_priority="accuracy",  # or speed
        pages_per_split=1,
        depth=1,
        max_image_dimension=1024,
        **parser_kwargs,
    )
    normalized = _normalize(parsed.get("raw", ""))

    missing = [p for p in _EXPECTED_PHRASES if _normalize(p) not in normalized]
    assert not missing, "Expected phrases missing from rendered PDF:\n" + "\n".join(
        f"  - {p!r}" for p in missing
    )
