"""First-run contract after X acquisition was moved out of Last30Days."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "last30days" / "SKILL.md"


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_first_run_orders_welcome_preflight_then_setup():
    text = _text()
    welcome = text.index("**1. Welcome.**")
    preflight = text.index("**2. Permission preflight.**")
    setup = text.index("**3. Setup.**")

    assert welcome < preflight < setup


def test_setup_is_non_x_and_cookie_free_by_default():
    text = _text()

    assert "Do not read browser cookies" in text
    assert "X/Twitter is outside this engine" in text
    assert "setup --allow-browser-cookies" not in text
    assert "AUTH_TOKEN" not in text
    assert "CT0" not in text


def test_external_x_boundary_names_only_approved_routes():
    text = _text()

    assert "bearer-only X API v2 skill" in text
    assert "local Grok CLI" in text
    assert "xurl" not in text
    assert "Xquik" not in text
    assert "Bird" not in text


def test_first_run_still_installs_and_explains_supported_sources():
    text = _text()

    for required in ("yt-dlp", "Digg", "arXiv", "Techmeme", "ScrapeCreators"):
        assert required in text
