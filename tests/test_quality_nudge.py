"""Quality-nudge tests for engine-owned sources only."""

from unittest import mock

from lib import quality_nudge


def _compute(*, ytdlp: bool, config=None, results=None):
    with mock.patch("lib.quality_nudge._has_ytdlp", return_value=ytdlp):
        return quality_nudge.compute_quality_score(config or {}, results or {})


def test_all_engine_owned_core_sources_healthy_scores_100():
    result = _compute(ytdlp=True)

    assert result["score_pct"] == 100
    assert result["core_active"] == ["hn", "polymarket", "reddit", "youtube"]
    assert result["core_missing"] == []
    assert result["nudge_text"] is None


def test_missing_youtube_scores_75_and_has_actionable_nudge():
    result = _compute(ytdlp=False)

    assert result["score_pct"] == 75
    assert result["core_missing"] == ["youtube"]
    assert "YouTube" in result["nudge_text"]
    assert "yt-dlp" in result["nudge_text"]
    assert "X/Twitter" not in result["nudge_text"]


def test_provider_youtube_data_counts_present_but_degraded_without_ytdlp():
    result = _compute(
        ytdlp=False,
        results={"youtube_videos_count": 3, "youtube_transcripts_count": 2},
    )

    assert result["score_pct"] == 100
    assert result["core_missing"] == []
    assert result["core_degraded"] == ["youtube"]


def test_all_caption_disabled_videos_do_not_create_false_degradation():
    result = _compute(
        ytdlp=True,
        results={
            "youtube_videos_count": 3,
            "youtube_transcripts_count": 0,
            "youtube_captions_disabled_count": 3,
        },
    )

    assert result["core_degraded"] == []
    assert result["nudge_text"] is None


def test_successful_fetch_telemetry_overrides_post_pruning_ratio():
    result = _compute(
        ytdlp=True,
        results={
            "youtube_videos_count": 3,
            "youtube_transcripts_count": 0,
            "youtube_transcript_fetch_attempts": 3,
            "youtube_transcript_fetch_failures": 0,
        },
    )

    assert result["core_degraded"] == []


def test_configured_instagram_zero_results_is_visible_unless_excluded():
    failed = _compute(
        ytdlp=True,
        config={"SCRAPECREATORS_API_KEY": "configured"},
        results={"instagram_items_count": 0},
    )
    excluded = _compute(
        ytdlp=True,
        config={
            "SCRAPECREATORS_API_KEY": "configured",
            "EXCLUDE_SOURCES": "instagram",
        },
        results={"instagram_items_count": 0},
    )

    assert failed["bonus_errored"] == ["instagram"]
    assert excluded["bonus_errored"] == []
