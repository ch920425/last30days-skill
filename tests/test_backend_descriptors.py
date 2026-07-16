"""U2: backend-chain descriptors with predicted selection (lib/backends.py).

Chained sources declare their routing once — imported from the definitions
lib/env.py already owns — and ``backends.resolve`` produces a truthful
"will use" prediction for alternative chains (X, YouTube, web search) plus
honest conditional wording for Reddit.

Covers the plan's U2 scenarios:
  1. X uses the local bearer-only wrapper.
  2. Paid lanes probe key presence ONLY — no network, no subprocess.
  3. Reddit renders conditional wording (default + backfill), never a
     computed winner; a scrapecreators pin renders as pinned.
"""

from unittest import mock

import pytest

from lib import backends, env, health


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _probe_dep(status_map=None, default_status=health.OK):
    """Build a fake health.probe_dependency honoring a per-name status map."""
    status_map = status_map or {}

    def fake(name, timeout=health.PROBE_TIMEOUT):
        status = status_map.get(name, default_status)
        if status == health.OK:
            return health.DependencyProbe(name=name, status=health.OK, detail=f"{name} 1.0.0")
        return health.DependencyProbe(
            name=name,
            status=status,
            detail=f"{name} probe simulated {status}",
            prescription=f"reinstall {name}" if status != health.MISSING else f"install {name}",
            owner_pkg_manager="brew",
        )

    return fake




# ---------------------------------------------------------------------------
# Descriptor registry: routing declared once, imported from env.py (KTD 6)
# ---------------------------------------------------------------------------

class TestDescriptorRegistry:

    def test_env_exposes_reddit_pin_constants(self):
        assert env.REDDIT_BACKEND_PIN_VAR == "LAST30DAYS_REDDIT_BACKEND"
        assert env.REDDIT_SC_MIN_ITEMS_VAR == "LAST30DAYS_REDDIT_SC_MIN_ITEMS"

    def test_youtube_and_web_chains_declared_in_order(self):
        yt = backends.get_descriptor("youtube")
        assert tuple(s.name for s in yt.backends) == ("yt-dlp", "scrapecreators")
        web = backends.get_descriptor("web")
        assert tuple(s.name for s in web.backends) == (
            "brave", "exa", "serper", "parallel", "keyless",
        )
        assert web.pin_flag == "--web-backend"

    def test_reddit_is_conditional_and_lanes_are_not_chain_entries(self):
        d = backends.get_descriptor("reddit")
        assert d.mode == backends.MODE_CONDITIONAL
        names = [s.name for s in d.backends]
        # Internal keyless lanes are sub-probe detail, never chain entries.
        for lane in ("rss", "listing", "arctic", "shreddit"):
            assert lane not in names
        assert names == ["public", "scrapecreators"]

    def test_unknown_source_raises(self):
        with pytest.raises(KeyError):
            backends.get_descriptor("nope")
        with pytest.raises(KeyError):
            backends.resolve("nope", {})


# ---------------------------------------------------------------------------
# X bearer-only prediction
# ---------------------------------------------------------------------------

class TestXBearerPrediction:
    def test_x_chain_contains_only_xurl(self):
        descriptor = backends.get_descriptor("x")
        assert tuple(spec.name for spec in descriptor.backends) == ("xurl",)

    def test_bearer_and_wrapper_enable_xurl(self):
        with mock.patch("lib.backends.which", return_value="/usr/local/bin/xurl"):
            result = backends.resolve("x", {"X_BEARER_TOKEN": "test-token"})
        assert result.active_backend == "xurl"
        assert result.tier == backends.TIER_OK

    def test_missing_bearer_disables_x(self):
        with mock.patch("lib.backends.which", return_value="/usr/local/bin/xurl"):
            result = backends.resolve("x", {})
        assert result.active_backend is None
        assert result.tier == backends.TIER_ERROR


# ---------------------------------------------------------------------------
# Scenario 5: paid lanes probe key presence only — never network/subprocess
# ---------------------------------------------------------------------------

def _forbid_io():
    def boom(*a, **k):
        raise AssertionError("paid-lane probe attempted I/O")

    return (
        mock.patch("socket.socket", boom),
        mock.patch("socket.create_connection", boom),
        mock.patch("urllib.request.urlopen", boom),
        mock.patch("subprocess.run", boom),
        mock.patch("subprocess.Popen", boom),
    )


class TestPaidLaneProbes:
    PAID = [
        ("web", "serper", "SERPER_API_KEY"),
        ("youtube", "scrapecreators", "SCRAPECREATORS_API_KEY"),
        ("reddit", "scrapecreators", "SCRAPECREATORS_API_KEY"),
    ]

    def test_paid_lanes_are_flagged_paid(self):
        for source, name, _key in self.PAID:
            spec = next(
                s for s in backends.get_descriptor(source).backends if s.name == name
            )
            assert spec.paid is True, f"{source}/{name} must be a paid (key-only) lane"

    def test_key_presence_probe_makes_no_network_or_subprocess_calls(self):
        ctxs = _forbid_io()
        with ctxs[0], ctxs[1], ctxs[2], ctxs[3], ctxs[4]:
            for source, name, key in self.PAID:
                spec = next(
                    s for s in backends.get_descriptor(source).backends if s.name == name
                )
                present = spec.probe({key: "dummy-key"})
                assert present.status == health.OK
                absent = spec.probe({})
                assert absent.status == health.MISSING
                assert key in absent.prescription


# ---------------------------------------------------------------------------
# F1 + F10: the doctor-path xurl probe is LOCAL-ONLY (stored-token evidence,
# never a live `xurl whoami` — doctor's no-network guarantee) and typed.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Scenario 6: Reddit conditional wording, never a computed winner
# ---------------------------------------------------------------------------

class TestRedditConditional:
    def test_sc_key_present_renders_default_plus_backfill_no_winner(self):
        res = backends.resolve("reddit", {"SCRAPECREATORS_API_KEY": "dummy-key"})
        assert res.mode == backends.MODE_CONDITIONAL
        assert res.active_backend is None  # never a single computed winner
        assert "will use" not in res.summary
        low = res.conditional.lower()
        assert "public keyless" in low
        assert "default" in low
        assert "scrapecreators backfill" in low
        assert res.tier == backends.TIER_OK

    def test_thinness_floor_appears_in_wording(self):
        res = backends.resolve(
            "reddit",
            {"SCRAPECREATORS_API_KEY": "dummy-key", "LAST30DAYS_REDDIT_SC_MIN_ITEMS": "5"},
        )
        assert "5" in res.conditional
        assert "floor" in res.conditional.lower()

    def test_default_floor_zero_means_empty_only_wording(self):
        res = backends.resolve("reddit", {"SCRAPECREATORS_API_KEY": "dummy-key"})
        assert "nothing" in res.conditional.lower()

    def test_malformed_floor_treated_as_default(self):
        res = backends.resolve(
            "reddit",
            {"SCRAPECREATORS_API_KEY": "dummy-key", "LAST30DAYS_REDDIT_SC_MIN_ITEMS": "lots"},
        )
        assert "nothing" in res.conditional.lower()

    def test_pinned_scrapecreators_renders_pin(self):
        res = backends.resolve(
            "reddit",
            {
                "SCRAPECREATORS_API_KEY": "dummy-key",
                "LAST30DAYS_REDDIT_BACKEND": "scrapecreators",
            },
        )
        assert res.pinned is True
        assert res.pin == "scrapecreators"
        low = res.conditional.lower()
        assert "pinned" in low
        assert "primary" in low
        assert res.active_backend is None  # still conditional, not a winner

    def test_no_key_means_no_backfill_wording(self):
        res = backends.resolve("reddit", {})
        low = res.conditional.lower()
        assert "public keyless" in low
        assert "backfill" not in low or "no scrapecreators" in low
        assert res.tier == backends.TIER_OK  # public composite always reachable

    def test_pin_without_key_is_ignored_like_the_pipeline(self):
        # pipeline gates sc_first on has_sc_key; the pin alone changes nothing.
        res = backends.resolve(
            "reddit", {"LAST30DAYS_REDDIT_BACKEND": "scrapecreators"},
        )
        assert res.pinned is False
        assert "primary" not in res.conditional.lower().split("pin ignored")[0]

    def test_keyless_lanes_are_sub_probe_detail(self):
        res = backends.resolve("reddit", {})
        public = next(f for f in res.findings if f.name == "public")
        for lane in ("rss", "listing", "arctic", "shreddit"):
            assert lane in public.detail


# ---------------------------------------------------------------------------
# Scenario 7: parity with the pipeline's pre-failover X selection
# ---------------------------------------------------------------------------

 # ---------------------------------------------------------------------------
# YouTube chain: yt-dlp -> ScrapeCreators
# ---------------------------------------------------------------------------

class TestYouTubeChain:
    def test_ytdlp_healthy_wins(self):
        with mock.patch("lib.health.probe_dependency", _probe_dep()):
            res = backends.resolve("youtube", {"SCRAPECREATORS_API_KEY": "dummy-key"})
        assert res.active_backend == "yt-dlp"
        assert res.tier == backends.TIER_OK

    def test_missing_ytdlp_falls_back_to_sc_key(self):
        with mock.patch(
            "lib.health.probe_dependency", _probe_dep({"yt-dlp": health.MISSING}),
        ):
            res = backends.resolve("youtube", {"SCRAPECREATORS_API_KEY": "dummy-key"})
        assert res.active_backend == "scrapecreators"
        assert res.tier == backends.TIER_OK

    def test_neither_available_error_carries_ytdlp_prescription(self):
        with mock.patch(
            "lib.health.probe_dependency", _probe_dep({"yt-dlp": health.MISSING}),
        ):
            res = backends.resolve("youtube", {})
        assert res.active_backend is None
        assert res.tier == backends.TIER_ERROR
        assert "yt-dlp" in res.prescription


# ---------------------------------------------------------------------------
# Web search chain: brave -> exa -> serper -> parallel -> keyless floor
# ---------------------------------------------------------------------------

class TestWebChain:
    def test_brave_key_predicted_first(self):
        res = backends.resolve(
            "web", {"BRAVE_API_KEY": "dummy-key", "EXA_API_KEY": "dummy-key"},
        )
        assert res.active_backend == "brave"
        assert res.tier == backends.TIER_OK

    def test_keyless_floor_is_degraded_warn(self):
        res = backends.resolve("web", {})
        assert res.active_backend == "keyless"
        assert res.tier == backends.TIER_WARN

    def test_native_search_suppresses_keyless_floor(self):
        res = backends.resolve("web", {"LAST30DAYS_NATIVE_SEARCH": "1"})
        keyless = next(f for f in res.findings if f.name == "keyless")
        assert not keyless.usable
        assert res.active_backend is None

    def test_pin_via_web_backend_flag(self):
        res = backends.resolve(
            "web", {"BRAVE_API_KEY": "dummy-key", "EXA_API_KEY": "dummy-key"}, pin="exa",
        )
        assert res.active_backend == "exa"
        assert res.pinned is True
        assert "pinned" in res.summary

    def test_parity_with_grounding_auto_dispatch(self):
        """resolve('web').active_backend must match the backend grounding's
        auto branch actually dispatches to, per config permutation."""
        from lib import grounding

        def _auto_pick(config):
            picked = {}

            def rec(label):
                def f(query, date_range, key, count=5):
                    picked["backend"] = label
                    return [], {"label": label}
                return f

            with mock.patch.object(grounding, "brave_search", rec("brave")), \
                 mock.patch.object(grounding, "exa_search", rec("exa")), \
                 mock.patch.object(grounding, "serper_search", rec("serper")), \
                 mock.patch.object(grounding, "parallel_search", rec("parallel")), \
                 mock.patch(
                     "lib.web_search_keyless.keyless_search",
                     lambda q, dr, cfg: (picked.__setitem__("backend", "keyless") or ([], {})),
                 ):
                grounding.web_search("q", ("2026-06-04", "2026-07-04"), config, backend="auto")
            return picked.get("backend")

        for config in (
            {"BRAVE_API_KEY": "dummy-key"},
            {"SERPER_API_KEY": "dummy-key"},
            {},
        ):
            assert backends.resolve("web", config).active_backend == _auto_pick(config)


# ---------------------------------------------------------------------------
# Rendering: prediction reads as will-use, never as past observation
# ---------------------------------------------------------------------------

class TestSummaryWording:
    def test_alternative_summary_is_will_use(self):
        res = backends.resolve("web", {"BRAVE_API_KEY": "dummy-key"})
        assert res.summary.startswith("will use: brave")
        assert "used" not in res.summary.split("will use")[1]

    def test_error_summary_names_no_backend(self):
        with mock.patch(
            "lib.health.probe_dependency", _probe_dep({"yt-dlp": health.MISSING}),
        ):
            res = backends.resolve("youtube", {})
        assert "will use" not in res.summary
        assert "no usable backend" in res.summary.lower()

    def test_conditional_summary_is_the_conditional_wording(self):
        res = backends.resolve("reddit", {"SCRAPECREATORS_API_KEY": "dummy-key"})
        assert res.summary == res.conditional
