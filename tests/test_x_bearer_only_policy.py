"""Last30Days must never acquire X through cookies, OAuth, or paid backends."""

from pathlib import Path

from lib import pipeline


ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "skills" / "last30days" / "scripts" / "lib"


def test_x_is_not_an_engine_source_even_when_legacy_credentials_are_present():
    legacy_config = {
        "AUTH_TOKEN": "legacy-cookie",
        "CT0": "legacy-csrf",
        "FROM_BROWSER": "true",
        "XAI_API_KEY": "legacy-xai-key",
        "XQUIK_API_KEY": "legacy-xquik-key",
        "LAST30DAYS_X_BACKEND": "bird",
    }

    assert "x" not in pipeline.available_sources(legacy_config)
    assert "x" not in pipeline.normalize_requested_sources(["x", "reddit"])


def test_legacy_x_backend_modules_are_absent():
    forbidden = [
        LIB / "bird_x.py",
        LIB / "xai_x.py",
        LIB / "xquik.py",
        LIB / "vendor" / "bird-search",
    ]
    assert not [path for path in forbidden if path.exists()]


def test_generic_cookie_api_fails_closed_for_x_domains(monkeypatch):
    from lib import cookie_extract

    called = False

    def unexpected(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"session": "must-not-be-read"}

    monkeypatch.setattr(cookie_extract, "extract_firefox_cookies", unexpected)

    assert cookie_extract.extract_cookies("firefox", "x.com", ["session"]) is None
    assert cookie_extract.extract_cookies("firefox", ".twitter.com", ["session"]) is None
    assert called is False


def test_active_skill_docs_never_offer_legacy_x_authentication():
    docs = [
        ROOT / "README.md",
        ROOT / "skills" / "last30days" / "SKILL.md",
    ]
    forbidden_phrases = (
        "AUTH_TOKEN",
        "CT0",
        "FROM_BROWSER",
        "XQUIK_API_KEY",
        "--x-handle",
        "--x-related",
        "xAI's API for X",
    )
    violations = {
        str(path.relative_to(ROOT)): phrase
        for path in docs
        for phrase in forbidden_phrases
        if phrase in path.read_text(encoding="utf-8")
    }
    assert violations == {}
