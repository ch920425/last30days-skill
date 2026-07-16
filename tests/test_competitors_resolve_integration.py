"""Production-shaped competitor targeting tests without an X acquisition lane."""

from __future__ import annotations

import json

import last30days as cli


def test_competitor_plan_threads_supported_targets_per_entity():
    plan = cli.parse_competitors_plan(
        json.dumps(
            {
                "Anthropic": {
                    "subreddits": ["ClaudeAI", "ClaudeCode"],
                    "github_user": "anthropics",
                    "github_repos": ["anthropics/claude-code"],
                    "trustpilot_domain": "anthropic.com",
                    "context": "Current product and company context",
                }
            }
        )
    )

    kwargs = cli.subrun_kwargs_for(
        "Anthropic",
        plan["anthropic"],
        resolved={
            "subreddits": ["wrong"],
            "github_user": "wrong",
            "github_repos": ["wrong/repo"],
            "trustpilot_domain": "wrong.example",
            "context": "stale",
        },
    )

    assert kwargs["subreddits"] == ["ClaudeAI", "ClaudeCode"]
    assert kwargs["github_user"] == "anthropics"
    assert kwargs["github_repos"] == ["anthropics/claude-code"]
    assert kwargs["trustpilot_domain"] == "anthropic.com"
    assert kwargs["_trustpilot_domain_is_hint"] is False
    assert kwargs["_context"] == "Current product and company context"


def test_auto_resolved_targets_fill_only_missing_plan_fields():
    kwargs = cli.subrun_kwargs_for(
        "OpenAI",
        {"subreddits": ["OpenAI"]},
        resolved={
            "subreddits": ["wrong"],
            "github_user": "openai",
            "github_repos": ["openai/codex"],
            "trustpilot_domain": "openai.com",
            "context": "Current context",
        },
    )

    assert kwargs["subreddits"] == ["OpenAI"]
    assert kwargs["github_user"] == "openai"
    assert kwargs["github_repos"] == ["openai/codex"]
    assert kwargs["trustpilot_domain"] == "openai.com"
    assert kwargs["_trustpilot_domain_is_hint"] is True
    assert kwargs["_context"] == "Current context"


def test_legacy_x_targeting_fields_are_ignored_fail_closed(capsys):
    plan = cli.parse_competitors_plan(
        '{"OpenAI":{"x_handle":"OpenAI","x_related":["sama"],'
        '"subreddits":["OpenAI"]}}'
    )

    assert plan == {"openai": {"subreddits": ["OpenAI"]}}
    assert "Unknown fields" in capsys.readouterr().err
