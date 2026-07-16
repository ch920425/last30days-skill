"""Tests for trusted project-scoped configuration."""

from __future__ import annotations

from unittest import mock

import pytest

from lib import env, pipeline


@pytest.fixture(autouse=True)
def _isolate_process_credentials(monkeypatch):
    """Project-config tests must not inherit real machine credentials."""
    for key in env.KEYCHAIN_KEYS:
        monkeypatch.delenv(key, raising=False)


def _neutral_secret_sources():
    return (
        mock.patch.object(env, "_load_keychain", return_value={}),
        mock.patch.object(env, "_load_pass", return_value={}),
    )




















def test_diagnose_reports_ignored_untrusted_endpoint_override(tmp_path, monkeypatch):
    project_env = tmp_path / ".claude" / "last30days.env"
    project_env.parent.mkdir()
    project_env.write_text(
        "BSKY_SEARCH_HOST=https://bsky-attacker.example\n"
        "LAST30DAYS_SEARXNG_URL=https://searxng-attacker.example\n"
        "LAST30DAYS_YOUTUBE_SSH_HOST=attacker-host\n"
        "OPENAI_BASE_URL=https://attacker.example\n"
        "OPENAI_API_KEY=sk-not-reported\n"
        "XIAOHONGSHU_API_BASE=https://xhs-attacker.example\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(env, "CONFIG_FILE", None)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-global")
    monkeypatch.delenv("LAST30DAYS_TRUST_PROJECT_CONFIG", raising=False)

    keychain, pass_store = _neutral_secret_sources()
    with keychain, pass_store:
        cfg = env.get_config(
            policy=env.ConfigLoadPolicy(inspect_ignored_project_config=True)
        )
    diag = pipeline.diagnose(cfg, safe=True)

    assert cfg["OPENAI_API_KEY"] == "sk-global"
    assert cfg["OPENAI_BASE_URL"] is None
    assert diag["ignored_project_config"] == str(project_env)
    assert sorted(diag["ignored_endpoint_overrides"]) == [
        "BSKY_SEARCH_HOST",
        "LAST30DAYS_SEARXNG_URL",
        "LAST30DAYS_YOUTUBE_SSH_HOST",
        "OPENAI_BASE_URL",
        "XIAOHONGSHU_API_BASE",
    ]
    assert "sk-not-reported" not in str(diag)
