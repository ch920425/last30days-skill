"""Backend descriptor tests for the supported Last30Days source chains."""

from unittest import mock

import pytest

from lib import backends, env, health


def _dependency(status: str):
    return health.DependencyProbe(
        name="yt-dlp",
        status=status,
        detail=f"simulated {status}",
        prescription="install yt-dlp",
        owner_pkg_manager="brew",
    )


def test_registry_contains_only_supported_chained_sources():
    assert set(backends.DESCRIPTORS) == {"youtube", "web", "reddit"}
    with pytest.raises(KeyError):
        backends.resolve("x", {})


def test_youtube_prefers_healthy_ytdlp_over_paid_fallback():
    with mock.patch("lib.health.probe_dependency", return_value=_dependency(health.OK)):
        result = backends.resolve("youtube", {"SCRAPECREATORS_API_KEY": "configured"})

    assert result.active_backend == "yt-dlp"
    assert result.tier == backends.TIER_OK
    assert result.chain == ["yt-dlp", "scrapecreators"]


def test_youtube_falls_back_when_ytdlp_is_missing():
    with mock.patch("lib.health.probe_dependency", return_value=_dependency(health.MISSING)):
        result = backends.resolve("youtube", {"SCRAPECREATORS_API_KEY": "configured"})

    assert result.active_backend == "scrapecreators"
    assert result.tier == backends.TIER_OK


def test_web_pin_is_honored_without_probing_network():
    result = backends.resolve(
        "web",
        {"BRAVE_API_KEY": "b", "EXA_API_KEY": "e"},
        pin="exa",
    )

    assert result.active_backend == "exa"
    assert result.pinned is True
    assert result.pin == "exa"
    assert result.tier == backends.TIER_OK


def test_reddit_routing_is_conditional_not_a_false_single_winner():
    result = backends.resolve("reddit", {})

    assert result.mode == backends.MODE_CONDITIONAL
    assert result.active_backend is None
    assert "public" in result.conditional
    assert env.REDDIT_BACKEND_PIN_VAR == "LAST30DAYS_REDDIT_BACKEND"
    assert env.REDDIT_SC_MIN_ITEMS_VAR == "LAST30DAYS_REDDIT_SC_MIN_ITEMS"
