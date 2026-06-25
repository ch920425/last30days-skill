"""Host-contract tests for non-modal agent runtimes."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_MD = ROOT / "skills" / "last30days" / "SKILL.md"


def _prose_flow() -> str:
    text = SKILL_MD.read_text(encoding="utf-8")
    start_marker = "### Non-Modal Prose Flow"
    end_marker = "### Manual Setup Guide"
    start = text.find(start_marker)
    assert start != -1, f"missing section marker: {start_marker}"
    end = text.find(end_marker, start)
    assert end != -1, f"missing section marker: {end_marker}"
    return text[start:end]


def test_non_modal_hosts_are_named():
    prose = _prose_flow()
    for host in ("Codex", "Cursor", "Gemini CLI", "raw CLI"):
        assert host in prose


def test_non_modal_cookie_consent_uses_engine_allow_flag():
    prose = _prose_flow()
    consent = prose.index("Cookie consent")
    allow = prose.index("setup --allow-browser-cookies")
    decline = prose.index("FROM_BROWSER=off")
    assert consent < allow
    assert consent < decline


def test_non_modal_completion_mentions_safe_diagnose_and_project_trust():
    prose = _prose_flow()
    assert "safe `--diagnose`" in prose
    assert "LAST30DAYS_TRUST_PROJECT_CONFIG=1" in prose
    assert "Codex desktop" in prose


def _step0_search_contract() -> str:
    text = SKILL_MD.read_text(encoding="utf-8")
    start_marker = "**STEP 0 - RESOLVE HOST WEB SEARCH FIRST.**"
    end_marker = "**FIRST-RUN GATE"
    start = text.find(start_marker)
    assert start != -1, f"missing section marker: {start_marker}"
    end = text.find(end_marker, start)
    assert end != -1, f"missing section marker: {end_marker}"
    return text[start:end]


def test_host_web_search_uses_available_capability_not_specific_tool_name():
    step0 = _step0_search_contract()
    assert "usable web-search tool" in step0
    assert "built in, exposed as a deferred tool, or provided by an installed connector" in step0
    assert "Brave, Firecrawl, Exa, Serper" in step0
    assert "If your host requires loading, selecting, or enabling the web-search tool" in step0
    assert "Do not fail the skill just because one particular schema lookup or tool name is unavailable" in step0


def test_no_host_search_uses_auto_resolve_and_leaves_native_signal_unset():
    step0 = _step0_search_contract()
    assert "If no web-search tool is available in the agent session" in step0
    assert "--auto-resolve" in step0
    assert "LAST30DAYS_NATIVE_SEARCH=1" in step0
    assert "Leave it unset when the agent session has no web-search tool" in step0
