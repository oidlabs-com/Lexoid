import re
from importlib.util import find_spec

import pytest
from dotenv import load_dotenv
from lexoid.api import parse
from lexoid.core import conversion_utils

load_dotenv()
_TEST_URL = "https://jnhlifestyles.com/blog/top-5-reasons-to-add-a-full-spectrum-infrared-sauna-into-your-home/"

# Stable phrases that must survive rendering and PDF extraction.
_EXPECTED_PHRASES = [
    "which can run upwards up over $8,000",
    "collections are currently our full spectrum saunas",
    "24 February 2020",
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
@pytest.mark.asyncio
async def test_webpage_rendering(tmp_path, engine):
    output_path = tmp_path / f"test-preview-{engine}.pdf"
    print(f"Testing webpage rendering with engine '{engine}' to {output_path}")

    result = conversion_utils.save_webpage_as_pdf(
        _TEST_URL,
        str(output_path),
        engine=engine,
    )

    assert result == str(output_path)
    assert output_path.exists()
    assert output_path.stat().st_size > 0

    parsed = parse(str(output_path), parser_type="STATIC_PARSE")
    normalized = _normalize(parsed.get("raw", ""))

    missing = [p for p in _EXPECTED_PHRASES if p.lower() not in normalized]
    assert not missing, "Expected phrases missing from rendered PDF:\n" + "\n".join(
        f"  - {p!r}" for p in missing
    )
