import threading
import unittest
from unittest.mock import patch

from lib import pipeline
from lib import http
from lib import schema


class DepthSettingsOverrideTests(unittest.TestCase):
    def test_no_overrides_returns_depth_defaults(self):
        settings = pipeline._resolve_depth_settings("deep", {})
        self.assertEqual(pipeline.DEPTH_SETTINGS["deep"], settings)

    def test_overrides_raise_caps_and_do_not_mutate_module_defaults(self):
        before = dict(pipeline.DEPTH_SETTINGS["deep"])
        settings = pipeline._resolve_depth_settings(
            "deep", {"_max_per_source": 60, "_max_results": 200}
        )
        self.assertEqual(60, settings["per_stream_limit"])
        self.assertEqual(200, settings["pool_limit"])
        self.assertEqual(200, settings["rerank_limit"])
        # Module-level defaults must be untouched (issue #716 regression guard).
        self.assertEqual(before, pipeline.DEPTH_SETTINGS["deep"])

    def test_overrides_can_also_lower_caps(self):
        settings = pipeline._resolve_depth_settings("deep", {"_max_results": 10})
        self.assertEqual(10, settings["rerank_limit"])

    def test_zero_override_is_honored_not_swallowed(self):
        # 0 is a valid explicit value (e.g. disable a source), not "unset".
        settings = pipeline._resolve_depth_settings(
            "deep", {"_max_results": 0, "_max_per_source": 0}
        )
        self.assertEqual(0, settings["pool_limit"])
        self.assertEqual(0, settings["rerank_limit"])
        self.assertEqual(0, settings["per_stream_limit"])


class PipelineV3Tests(unittest.TestCase):
    def test_mock_pipeline_report_without_live_credentials(self):
        report = pipeline.run(
            topic="test topic",
            config={"LAST30DAYS_REASONING_PROVIDER": "gemini"},
            depth="quick",
            requested_sources=["reddit", "grounding"],
            mock=True,
        )
        self.assertEqual("test topic", report.topic)
        self.assertTrue(report.ranked_candidates)
        self.assertTrue(report.clusters)
        self.assertIn("reddit", report.items_by_source)
        # Grounding items now enter the ranked pool (web search backends produce real items)
        self.assertIn("grounding", report.items_by_source)
        self.assertEqual("gemini", report.provider_runtime.reasoning_provider)

    def test_planner_trace_always_fires_on_mock_run(self):
        """Unit 5: The unified planner trace emits one summary line plus one
        line per subquery on every run, regardless of --debug. 2026-04-19
        Hermes Agent Use Cases failure: retrieval-breadth issues were invisible
        because the internal planner path logged nothing.
        """
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            pipeline.run(
                topic="test topic",
                config={"LAST30DAYS_REASONING_PROVIDER": "gemini"},
                depth="quick",
                requested_sources=["reddit", "grounding"],
                mock=True,
            )
        output = buf.getvalue()
        self.assertIn("[Planner] Plan: intent=", output)
        self.assertIn("subqueries=", output)
        self.assertIn("source=", output)
        # At least one per-subquery line.
        self.assertIn("[Planner]   sq1 label=", output)

    def test_parallel_web_backend_enables_grounding_source(self):
        plan = {
            "intent": "news",
            "freshness_mode": "balanced_recent",
            "cluster_mode": "timeline",
            "subqueries": [
                {
                    "label": "primary",
                    "search_query": "test topic",
                    "ranking_query": "What happened with test topic?",
                    "sources": ["grounding"],
                }
            ],
            "source_weights": {"grounding": 1.0},
        }
        report = pipeline.run(
            topic="test topic",
            config={"LAST30DAYS_REASONING_PROVIDER": "auto"},
            depth="quick",
            requested_sources=["grounding"],
            web_backend="parallel",
            external_plan=plan,
        )
        # Anchor on the stable source key, not the exact wording of the
        # grounding.py error message. Phrasing can shift (e.g., when the
        # missing-key check moves or the message is reworded) without
        # changing the contract that the grounding source registers an
        # error when its required backend key is unset.
        self.assertIn("grounding", report.errors_by_source)

    def test_hiring_signals_mode_enables_jobs_source_in_mock_run(self):
        report = pipeline.run(
            topic="Listen Labs",
            config={"LAST30DAYS_REASONING_PROVIDER": "gemini"},
            depth="quick",
            requested_sources=["jobs"],
            mock=True,
            hiring_signals_mode=True,
        )
        self.assertIn("jobs", report.items_by_source)
        self.assertIn("hiring_signals", report.artifacts)
        self.assertTrue(report.artifacts["hiring_signals"]["include"])

    def test_hiring_signals_mode_defaults_to_jobs_source(self):
        report = pipeline.run(
            topic="Listen Labs",
            config={"LAST30DAYS_REASONING_PROVIDER": "gemini"},
            depth="quick",
            mock=True,
            hiring_signals_mode=True,
        )
        self.assertEqual(["jobs"], sorted(report.items_by_source))
        self.assertTrue(report.artifacts["hiring_signals"]["include"])

    def test_standard_company_run_fetches_jobs_for_signal_gate(self):
        report = pipeline.run(
            topic="Listen Labs",
            config={"LAST30DAYS_REASONING_PROVIDER": "gemini"},
            depth="quick",
            mock=True,
        )
        self.assertIn("jobs", report.items_by_source)
        self.assertIn("hiring_signals", report.artifacts)

    def test_standard_mock_run_does_not_add_jobs_for_generic_topic(self):
        report = pipeline.run(
            topic="how to deploy on Fly.io",
            config={"LAST30DAYS_REASONING_PROVIDER": "gemini"},
            depth="quick",
            mock=True,
        )
        self.assertNotIn("jobs", report.items_by_source)
        self.assertNotIn("hiring_signals", report.artifacts)

    def test_single_word_generic_topic_does_not_add_jobs(self):
        report = pipeline.run(
            topic="bitcoin",
            config={"LAST30DAYS_REASONING_PROVIDER": "gemini"},
            depth="quick",
            mock=True,
        )
        self.assertNotIn("jobs", report.items_by_source)
        self.assertNotIn("hiring_signals", report.artifacts)

    def test_question_comparison_topic_does_not_add_jobs(self):
        report = pipeline.run(
            topic="Python vs Ruby benchmark?",
            config={"LAST30DAYS_REASONING_PROVIDER": "gemini"},
            depth="quick",
            mock=True,
        )
        self.assertNotIn("jobs", report.items_by_source)
        self.assertNotIn("hiring_signals", report.artifacts)

    def test_bare_language_comparison_topics_do_not_add_jobs(self):
        for topic in ("python vs ruby", "Python vs Ruby"):
            with self.subTest(topic=topic):
                self.assertFalse(pipeline._company_topic_likely(topic))

    def test_company_comparison_topics_add_jobs(self):
        for topic in ("Stripe vs Brex", "OpenAI versus Anthropic"):
            with self.subTest(topic=topic):
                self.assertTrue(pipeline._company_topic_likely(topic))

    def test_standard_mode_omits_weak_large_company_jobs_signal(self):
        with patch("lib.pipeline._retrieve_stream") as mock_retrieve:
            def fake_retrieve(**kwargs):
                if kwargs["source"] == "jobs":
                    return (
                        [
                            {
                                "id": "J1",
                                "title": "Retail Associate",
                                "description": "Store operations",
                                "url": "https://example.com/jobs/1",
                                "department": "Retail",
                                "date": "2026-06-01",
                                "provider": "mock",
                            }
                        ],
                        {},
                    )
                return pipeline._mock_stream_results(kwargs["source"], kwargs["subquery"])

            mock_retrieve.side_effect = fake_retrieve
            report = pipeline.run(
                topic="Apple",
                config={"LAST30DAYS_REASONING_PROVIDER": "gemini"},
                depth="quick",
                requested_sources=["jobs"],
                mock=True,
            )
        self.assertNotIn("jobs", report.items_by_source)
        self.assertFalse(report.artifacts["hiring_signals"]["include"])


class TestSourceFetchCap(unittest.TestCase):
    """Expensive or duplicate sources must respect fetch caps."""

    def test_jobs_capped_in_max_source_fetches(self):
        self.assertIn("jobs", pipeline.MAX_SOURCE_FETCHES)
        self.assertEqual(pipeline.MAX_SOURCE_FETCHES["jobs"], 1)

    def test_cap_logic_limits_source_submissions(self):
        """Verify the cap logic skips submissions beyond the limit."""
        subquery_sources = [
            ["jobs", "reddit", "youtube"],
            ["jobs", "reddit", "youtube"],
            ["jobs", "reddit", "youtube"],
            ["jobs", "reddit", "youtube"],
        ]
        source_fetch_count: dict[str, int] = {}
        submitted: list[str] = []
        for sources in subquery_sources:
            for source in sources:
                source_cap = pipeline.MAX_SOURCE_FETCHES.get(source)
                if source_cap is not None:
                    current = source_fetch_count.get(source, 0)
                    if current >= source_cap:
                        continue
                    source_fetch_count[source] = current + 1
                submitted.append(source)

        jobs_count = submitted.count("jobs")
        reddit_count = submitted.count("reddit")
        self.assertEqual(jobs_count, 1, f"Jobs should be capped at 1, got {jobs_count}")
        self.assertEqual(reddit_count, 4, f"Reddit should be uncapped, got {reddit_count}")

class TestRateLimitSharing(unittest.TestCase):
    """429 signals should be shared across subqueries."""

    def test_is_rate_limit_error_detects_429_status(self):
        exc = http.HTTPError("HTTP 429: Too Many Requests", status_code=429)
        self.assertTrue(pipeline._is_rate_limit_error(exc))

    def test_is_rate_limit_error_ignores_non_429(self):
        exc = http.HTTPError("HTTP 400: Bad Request", status_code=400)
        self.assertFalse(pipeline._is_rate_limit_error(exc))

    def test_is_rate_limit_error_detects_429_in_string(self):
        exc = RuntimeError("xAI returned 429 rate limit")
        self.assertTrue(pipeline._is_rate_limit_error(exc))

    def test_is_rate_limit_error_rejects_unrelated_error(self):
        exc = RuntimeError("Connection refused")
        self.assertFalse(pipeline._is_rate_limit_error(exc))

    def test_retrieve_stream_skips_rate_limited_source(self):
        """_retrieve_stream should return empty when source is rate-limited."""
        from lib import schema
        rate_limited = {"bluesky"}
        lock = threading.Lock()
        subquery = schema.SubQuery(
            label="test",
            search_query="test query",
            ranking_query="test query",
            sources=["bluesky"],
        )
        items, artifact = pipeline._retrieve_stream(
            topic="test",
            subquery=subquery,
            source="bluesky",
            config={},
            depth="quick",
            date_range=("2026-02-15", "2026-03-17"),
            runtime=schema.ProviderRuntime(
                reasoning_provider="mock",
                planner_model="mock",
                rerank_model="mock",
            ),
            mock=True,
            rate_limited_sources=rate_limited,
            rate_limit_lock=lock,
        )
        self.assertEqual(items, [])
        self.assertEqual(artifact, {})


class TestThinSourceRetryPlannedSource(unittest.TestCase):
    @patch("lib.pipeline._retrieve_stream")
    def test_retry_includes_planned_source_with_zero_initial_items(self, mock_retrieve):
        mock_retrieve.return_value = (
            [
                {
                    "id": "BS100",
                    "text": "OpenClaw funding update from an investor",
                    "url": "https://bsky.app/profile/example/post/100",
                    "author": "example",
                    "date": "2026-03-15",
                    "engagement": {"likes": 25, "reposts": 4, "replies": 2},
                    "relevance": 0.8,
                    "why_relevant": "retry result",
                }
            ],
            {},
        )

        plan = schema.QueryPlan(
            intent="breaking_news",
            freshness_mode="strict_recent",
            cluster_mode="story",
            raw_topic="latest OpenClaw funding updates",
            subqueries=[
                schema.SubQuery(
                    label="primary",
                    search_query="latest OpenClaw funding updates",
                    ranking_query="What recent evidence matters for OpenClaw funding?",
                    sources=["bluesky", "reddit"],
                )
            ],
            source_weights={"bluesky": 1.0, "reddit": 1.0},
        )
        bundle = schema.RetrievalBundle(
            items_by_source={
                "reddit": [
                    _make_source_item("reddit", "r1", "https://reddit.com/1"),
                    _make_source_item("reddit", "r2", "https://reddit.com/2"),
                    _make_source_item("reddit", "r3", "https://reddit.com/3"),
                ]
            }
        )

        pipeline._retry_thin_sources(
            topic="latest OpenClaw funding updates",
            bundle=bundle,
            plan=plan,
            config={},
            depth="default",
            date_range=("2026-02-15", "2026-03-17"),
            runtime=_make_runtime(),
            mock=False,
            rate_limited_sources=set(),
            rate_limit_lock=threading.Lock(),
            settings=pipeline.DEPTH_SETTINGS["default"],
        )

        self.assertEqual(["bluesky"], [call.kwargs["source"] for call in mock_retrieve.call_args_list])
        self.assertIn("bluesky", bundle.items_by_source)
        self.assertEqual(
            "https://bsky.app/profile/example/post/100",
            bundle.items_by_source["bluesky"][0].url,
        )



class TestTrustpilotNeverRetriedAsThin(unittest.TestCase):
    @patch("lib.pipeline._retrieve_stream")
    def test_trustpilot_excluded_from_thin_source_retry(self, mock_retrieve):
        """Trustpilot returns at most one item by design, so the '<3 items'
        thinness rule must never re-fetch it: a retry would bypass
        MAX_SOURCE_FETCHES and re-resolve without the caller's
        --trustpilot-domain (a lookalike-misattribution path)."""
        mock_retrieve.return_value = ([], {})

        plan = schema.QueryPlan(
            intent="product",
            freshness_mode="balanced_recent",
            cluster_mode="none",
            raw_topic="ThriftBooks",
            subqueries=[
                schema.SubQuery(
                    label="primary",
                    search_query="thriftbooks",
                    ranking_query="What matters for ThriftBooks?",
                    sources=["trustpilot", "youtube"],
                )
            ],
            source_weights={"trustpilot": 1.0, "youtube": 1.0},
        )
        bundle = schema.RetrievalBundle(
            items_by_source={
                # one successful trustpilot item -- its normal success state,
                # yet still "<3" and thus retry-eligible without the exclusion
                "trustpilot": [
                    _make_source_item("trustpilot", "tp1", "https://www.trustpilot.com/review/x.com"),
                ],
            }
        )

        pipeline._retry_thin_sources(
            topic="ThriftBooks",
            bundle=bundle,
            plan=plan,
            config={},
            depth="default",
            date_range=("2026-06-04", "2026-07-04"),
            runtime=_make_runtime(),
            mock=False,
            rate_limited_sources=set(),
            rate_limit_lock=threading.Lock(),
            settings=pipeline.DEPTH_SETTINGS["default"],
        )

        retried = [call.kwargs["source"] for call in mock_retrieve.call_args_list]
        self.assertNotIn("trustpilot", retried)
        self.assertIn("youtube", retried)  # other thin sources still retry


def _make_runtime():
    return schema.ProviderRuntime(
        reasoning_provider="mock",
        planner_model="mock",
        rerank_model="mock",
    )


def _make_plan(topic="test topic"):
    return schema.QueryPlan(
        intent="exploration",
        freshness_mode="balanced_recent",
        cluster_mode="topic",
        raw_topic=topic,
        subqueries=[
            schema.SubQuery(
                label="primary",
                search_query=topic,
                ranking_query=f"What recent evidence matters for {topic}?",
                sources=["youtube", "reddit"],
            )
        ],
        source_weights={"youtube": 1.0, "reddit": 1.0},
    )


def _make_source_item(source, item_id, url, author=None, body="", container=None, metadata=None):
    return schema.SourceItem(
        item_id=item_id,
        source=source,
        title=f"Item {item_id}",
        body=body,
        url=url,
        author=author,
        container=container,
        metadata=metadata or {},
    )


class TestThinSourceRetry(unittest.TestCase):
    """R2: Dynamic query refinement on thin results."""

    def test_retry_thin_sources_exists(self):
        """_retry_thin_sources must be a callable in pipeline module."""
        self.assertTrue(
            hasattr(pipeline, "_retry_thin_sources"),
            "_retry_thin_sources function not found in pipeline module",
        )
        self.assertTrue(callable(pipeline._retry_thin_sources))

    @patch("lib.pipeline._retrieve_stream")
    def test_thin_source_retried_with_core_subject(self, mock_retrieve):
        """Sources with < 3 items and no errors should be retried."""
        mock_retrieve.return_value = (
            [
                {
                    "id": "retry1",
                    "title": "Retry result",
                    "url": "https://reddit.com/r/test/2",
                    "subreddit": "test",
                    "date": "2026-03-15",
                    "engagement": {"score": 10},
                    "selftext": "Retry content",
                    "relevance": 0.7,
                    "why_relevant": "retry",
                }
            ],
            {},
        )

        bundle = schema.RetrievalBundle()
        # Only 1 reddit item (thin)
        bundle.items_by_source["reddit"] = [
            _make_source_item("reddit", "R1", "https://reddit.com/r/test/1", container="test"),
        ]
        # 5 X items (not thin)
        bundle.items_by_source["youtube"] = [
            _make_source_item("youtube", f"Y{i}", f"https://youtube.com/watch?v={i}") for i in range(5)
        ]

        plan = _make_plan("advanced AI safety techniques")
        settings = pipeline.DEPTH_SETTINGS["default"]

        pipeline._retry_thin_sources(
            topic="advanced AI safety techniques",
            bundle=bundle,
            plan=plan,
            config={},
            depth="default",
            date_range=("2026-02-15", "2026-03-17"),
            runtime=_make_runtime(),
            mock=False,
            rate_limited_sources=set(),
            rate_limit_lock=threading.Lock(),
            settings=settings,
        )

        # _retrieve_stream should have been called for reddit (thin source)
        mock_retrieve.assert_called()
        call_sources = [c.kwargs.get("source") for c in mock_retrieve.call_args_list]
        self.assertIn("reddit", call_sources)
        # Errored sources should not have been retried.
        self.assertNotIn("youtube", call_sources)

    def test_sources_with_enough_items_not_retried(self):
        """Sources with >= 3 items should not be retried."""
        bundle = schema.RetrievalBundle()
        bundle.items_by_source["reddit"] = [
            _make_source_item("reddit", f"R{i}", f"https://reddit.com/r/test/{i}") for i in range(5)
        ]
        bundle.items_by_source["youtube"] = [
            _make_source_item("youtube", f"Y{i}", f"https://youtube.com/watch?v={i}") for i in range(5)
        ]

        plan = _make_plan("AI safety")
        settings = pipeline.DEPTH_SETTINGS["default"]

        with patch("lib.pipeline._retrieve_stream") as mock_retrieve:
            pipeline._retry_thin_sources(
                topic="AI safety",
                bundle=bundle,
                plan=plan,
                config={},
                depth="default",
                date_range=("2026-02-15", "2026-03-17"),
                runtime=_make_runtime(),
                mock=False,
                rate_limited_sources=set(),
                rate_limit_lock=threading.Lock(),
                settings=settings,
            )
            mock_retrieve.assert_not_called()

    def test_errored_sources_not_retried(self):
        """Sources in errors_by_source should not be retried even if thin.
        Non-errored thin sources SHOULD still be retried."""
        bundle = schema.RetrievalBundle()
        bundle.items_by_source["reddit"] = [
            _make_source_item("reddit", "R1", "https://reddit.com/r/test/1"),
        ]
        bundle.errors_by_source["reddit"] = "API error"

        plan = _make_plan("AI safety")
        settings = pipeline.DEPTH_SETTINGS["default"]

        mock_items = [{"id": "X1", "title": "test", "url": "https://x.com/1", "text": "test"}]
        with patch("lib.pipeline._retrieve_stream", return_value=(mock_items, {})) as mock_retrieve:
            pipeline._retry_thin_sources(
                topic="AI safety",
                bundle=bundle,
                plan=plan,
                config={},
                depth="default",
                date_range=("2026-02-15", "2026-03-17"),
                runtime=_make_runtime(),
                mock=False,
                rate_limited_sources=set(),
                rate_limit_lock=threading.Lock(),
                settings=settings,
            )
            # x (non-errored, thin) should be retried; reddit (errored) should not
            if mock_retrieve.call_count > 0:
                self.assertNotIn("reddit", [c.kwargs.get("source") for c in mock_retrieve.call_args_list])

    def test_retry_skipped_in_quick_mode(self):
        """_retry_thin_sources should return immediately in quick mode."""
        bundle = schema.RetrievalBundle()
        bundle.items_by_source["reddit"] = [
            _make_source_item("reddit", "R1", "https://reddit.com/r/test/1"),
        ]

        plan = _make_plan("AI safety")
        settings = pipeline.DEPTH_SETTINGS["quick"]

        with patch("lib.pipeline._retrieve_stream") as mock_retrieve:
            pipeline._retry_thin_sources(
                topic="AI safety",
                bundle=bundle,
                plan=plan,
                config={},
                depth="quick",
                date_range=("2026-02-15", "2026-03-17"),
                runtime=_make_runtime(),
                mock=False,
                rate_limited_sources=set(),
                rate_limit_lock=threading.Lock(),
                settings=settings,
            )
            mock_retrieve.assert_not_called()


class TestErrorCleanup(unittest.TestCase):
    """Source errors should be cleared when the source has items from other subqueries."""

    def test_error_cleared_when_source_has_items(self):
        """A source that 429'd on one subquery but succeeded on another is not errored."""
        bundle = schema.RetrievalBundle(artifacts={})
        item = schema.SourceItem(
            item_id="x1", source="x", title="A tweet", body="content",
            url="https://x.com/user/status/1",
        )
        bundle.items_by_source["x"] = [item]
        bundle.errors_by_source["x"] = "HTTP 429: Too Many Requests"

        # Simulate the cleanup logic from pipeline.run()
        for source in list(bundle.errors_by_source):
            if bundle.items_by_source.get(source):
                del bundle.errors_by_source[source]

        self.assertNotIn("x", bundle.errors_by_source,
                         "X should not be errored when it has items")

    def test_error_kept_when_source_has_no_items(self):
        """A source with zero items should remain in errors_by_source."""
        bundle = schema.RetrievalBundle(artifacts={})
        bundle.errors_by_source["x"] = "HTTP 429: Too Many Requests"

        for source in list(bundle.errors_by_source):
            if bundle.items_by_source.get(source):
                del bundle.errors_by_source[source]

        self.assertIn("x", bundle.errors_by_source,
                      "X should remain errored when it has no items")


class TestWarnings(unittest.TestCase):
    def _item(self, source="reddit"):
        return schema.SourceItem(item_id="1", source=source, title="t", body="b", url="u")

    def _candidate(self, source="reddit", score=50.0):
        c = schema.Candidate(
            candidate_id="c1", item_id="1", source=source, title="t", url="u",
            snippet="s", subquery_labels=["main"], native_ranks={"main:reddit": 1},
            local_relevance=0.5, freshness=50, engagement=10, source_quality=0.7,
            rrf_score=0.01, sources=[source],
        )
        c.final_score = score
        return c

    def test_no_candidates_warning(self):
        w = pipeline._warnings({"reddit": [self._item()]}, [], {})
        self.assertTrue(any("No candidates" in msg for msg in w))

    def test_thin_evidence_warning(self):
        candidates = [self._candidate() for _ in range(3)]
        w = pipeline._warnings({"reddit": [self._item()]}, candidates, {})
        self.assertTrue(any("thin" in msg.lower() for msg in w))

    def test_single_source_concentration(self):
        candidates = [self._candidate() for _ in range(5)]
        w = pipeline._warnings({"reddit": [self._item()]}, candidates, {})
        self.assertTrue(any("concentrated" in msg.lower() for msg in w))

    def test_source_errors_listed(self):
        w = pipeline._warnings({}, [self._candidate()], {"x": "timeout"})
        self.assertTrue(any("x" in msg for msg in w))

    def test_no_items_warning(self):
        w = pipeline._warnings({}, [], {})
        self.assertTrue(any("No source returned" in msg for msg in w))


class TestRetryThinSourcesCoreEqualsTopic(unittest.TestCase):
    """Test that _retry_thin_sources fires even when core == topic (the fix)."""

    @patch("lib.pipeline._retrieve_stream")
    def test_retry_fires_when_core_equals_topic(self, mock_retrieve):
        """Topic 'Kanye West' with 0 YouTube items should trigger retry.

        Previously this was skipped because core 'kanye west' == topic.
        The fix ensures retry still fires for short topics.
        """
        mock_retrieve.return_value = (
            [
                {
                    "id": "YT1",
                    "title": "Kanye West new album leak",
                    "url": "https://www.youtube.com/watch?v=abc123",
                    "date": "2026-03-15",
                    "engagement": {"views": 1000},
                    "relevance": 0.8,
                    "why_relevant": "retry result",
                }
            ],
            {},
        )

        plan = schema.QueryPlan(
            intent="breaking_news",
            freshness_mode="strict_recent",
            cluster_mode="story",
            raw_topic="Kanye West",
            subqueries=[
                schema.SubQuery(
                    label="primary",
                    search_query="Kanye West",
                    ranking_query="What recent evidence matters for Kanye West?",
                    sources=["youtube", "x"],
                )
            ],
            source_weights={"youtube": 1.0, "x": 1.0},
        )
        bundle = schema.RetrievalBundle()
        # YouTube has 0 items (thin), X has enough
        bundle.items_by_source["x"] = [
            _make_source_item("x", f"X{i}", f"https://x.com/a/{i}") for i in range(5)
        ]

        pipeline._retry_thin_sources(
            topic="Kanye West",
            bundle=bundle,
            plan=plan,
            config={},
            depth="default",
            date_range=("2026-02-15", "2026-03-17"),
            runtime=_make_runtime(),
            mock=False,
            rate_limited_sources=set(),
            rate_limit_lock=threading.Lock(),
            settings=pipeline.DEPTH_SETTINGS["default"],
        )

        # _retrieve_stream should have been called for youtube
        mock_retrieve.assert_called()
        retried_sources = [c.kwargs["source"] for c in mock_retrieve.call_args_list]
        self.assertIn("youtube", retried_sources)
        # YouTube should now have items in the bundle
        self.assertIn("youtube", bundle.items_by_source)


class TestZeroKeyPipelineRun(unittest.TestCase):
    """Pipeline should complete with local fallbacks when no reasoning keys are configured."""

    @patch("lib.pipeline._retrieve_stream")
    def test_zero_key_run_produces_report(self, mock_retrieve):
        mock_retrieve.side_effect = lambda **kwargs: pipeline._mock_stream_results(
            kwargs["source"], kwargs["subquery"]
        )
        config = {"LAST30DAYS_REASONING_PROVIDER": "auto"}
        report = pipeline.run(
            topic="test zero key topic",
            config=config,
            depth="quick",
            requested_sources=["hackernews"],
        )
        self.assertEqual("test zero key topic", report.topic)
        self.assertEqual("local", report.provider_runtime.reasoning_provider)
        self.assertEqual("deterministic", report.provider_runtime.planner_model)
        self.assertTrue(
            any("fallback" in note for note in report.query_plan.notes),
            f"Expected fallback plan, got notes: {report.query_plan.notes}",
        )
        for candidate in report.ranked_candidates:
            self.assertEqual("fallback-local-score", candidate.explanation)


class TestExcludeSources(unittest.TestCase):
    """EXCLUDE_SOURCES env var filters sources out of available_sources().

    The existing INCLUDE_SOURCES allowlist (used by Perplexity opt-in) does
    not cover this case — tiktok and instagram are added unconditionally
    when SCRAPECREATORS_API_KEY is set, with no way to opt out short of
    unsetting the key. EXCLUDE_SOURCES gives runs a per-invocation denylist.
    """

    def test_excludes_tiktok_and_instagram(self):
        config = {
            "SCRAPECREATORS_API_KEY": "test-key",
            "EXCLUDE_SOURCES": "tiktok,instagram",
        }
        sources = pipeline.available_sources(config)
        self.assertNotIn("tiktok", sources)
        self.assertNotIn("instagram", sources)
        self.assertIn("reddit", sources)
        self.assertIn("hackernews", sources)

    def test_no_exclusion_when_unset(self):
        config = {"SCRAPECREATORS_API_KEY": "test-key"}
        sources = pipeline.available_sources(config)
        self.assertIn("tiktok", sources)
        self.assertIn("instagram", sources)

    def test_empty_exclude_sources_is_noop(self):
        config = {
            "SCRAPECREATORS_API_KEY": "test-key",
            "EXCLUDE_SOURCES": "",
        }
        sources = pipeline.available_sources(config)
        self.assertIn("tiktok", sources)
        self.assertIn("instagram", sources)

    def test_whitespace_and_case_insensitive(self):
        config = {
            "SCRAPECREATORS_API_KEY": "test-key",
            "EXCLUDE_SOURCES": " TikTok , INSTAGRAM ",
        }
        sources = pipeline.available_sources(config)
        self.assertNotIn("tiktok", sources)
        self.assertNotIn("instagram", sources)

    def test_excludes_non_scrapecreators_source(self):
        """EXCLUDE_SOURCES applies to any source, not just SC-backed ones."""
        config = {"EXCLUDE_SOURCES": "hackernews"}
        sources = pipeline.available_sources(config)
        self.assertNotIn("hackernews", sources)
        self.assertIn("reddit", sources)


class TestPerplexityAvailability(unittest.TestCase):
    def test_perplexity_source_not_available_with_direct_key_without_opt_in(self):
        sources = pipeline.available_sources({"PERPLEXITY_API_KEY": "test-key"})
        self.assertNotIn("perplexity", sources)

    def test_perplexity_source_available_with_direct_key(self):
        sources = pipeline.available_sources(
            {"PERPLEXITY_API_KEY": "test-key", "INCLUDE_SOURCES": "perplexity"}
        )
        self.assertIn("perplexity", sources)

    def test_perplexity_diagnose_reports_direct_provider(self):
        diag = pipeline.diagnose({"PERPLEXITY_API_KEY": "test-key"})
        self.assertTrue(diag["providers"]["perplexity"])
        self.assertTrue(diag["local_mode"])


class TestLinkedinAvailability(unittest.TestCase):
    """LinkedIn is power-user opt-in (INCLUDE_SOURCES=linkedin), unlike
    tiktok/instagram which activate on SCRAPECREATORS_API_KEY alone. This
    keeps existing SCRAPECREATORS_API_KEY holders from silently picking up a
    new source — and spending new credits — on their next run."""

    def test_not_available_with_key_alone(self):
        sources = pipeline.available_sources({"SCRAPECREATORS_API_KEY": "test-key"})
        self.assertNotIn("linkedin", sources)
        # tiktok/instagram remain unconditional with just the key
        self.assertIn("tiktok", sources)
        self.assertIn("instagram", sources)

    def test_available_with_key_and_include_sources(self):
        sources = pipeline.available_sources(
            {"SCRAPECREATORS_API_KEY": "test-key", "INCLUDE_SOURCES": "linkedin"}
        )
        self.assertIn("linkedin", sources)

    def test_available_with_key_and_requested_sources(self):
        sources = pipeline.available_sources(
            {"SCRAPECREATORS_API_KEY": "test-key"}, requested_sources=["linkedin"]
        )
        self.assertIn("linkedin", sources)

    def test_not_available_with_include_sources_but_no_key(self):
        sources = pipeline.available_sources({"INCLUDE_SOURCES": "linkedin"})
        self.assertNotIn("linkedin", sources)


class TestKeylessGroundingAvailability(unittest.TestCase):
    """Grounding (general web) availability is host-aware.

    Non-native hosts get the keyless floor by default; native-search hosts leave
    general web to the model's own search unless a paid key is configured.
    """

    def test_grounding_available_without_key_on_non_native_host(self):
        sources = pipeline.available_sources({})
        self.assertIn("grounding", sources)

    def test_grounding_suppressed_without_key_on_native_host(self):
        config = {"LAST30DAYS_NATIVE_SEARCH": "1"}
        sources = pipeline.available_sources(config)
        self.assertNotIn("grounding", sources)

    def test_grounding_available_with_paid_key_even_on_native_host(self):
        config = {"LAST30DAYS_NATIVE_SEARCH": "1", "BRAVE_API_KEY": "k"}
        sources = pipeline.available_sources(config)
        self.assertIn("grounding", sources)


class TestExcludeSourcesEndToEnd(unittest.TestCase):
    """Wiring regression: EXCLUDE_SOURCES from the process environment must
    reach available_sources() via env.get_config(). The unit tests above
    construct config dicts directly; this one exercises the env-to-config
    path so a missing entry in env.py's keys list is caught immediately."""

    def test_exclude_sources_from_env_propagates_through_get_config(self):
        import os
        from unittest.mock import patch as _patch
        from lib import env as env_mod
        from importlib import reload
        with _patch.dict(os.environ, {
            "LAST30DAYS_CONFIG_DIR": "",
            "EXCLUDE_SOURCES": "tiktok,instagram",
            "SCRAPECREATORS_API_KEY": "fake",
        }, clear=False):
            reload(env_mod)
            cfg = env_mod.get_config()
        self.assertEqual(cfg.get("EXCLUDE_SOURCES"), "tiktok,instagram")
        sources = pipeline.available_sources(cfg)
        self.assertNotIn("tiktok", sources)
        self.assertNotIn("instagram", sources)


class TestInnerMaxWorkers(unittest.TestCase):
    """Cap inner ThreadPoolExecutor concurrency under competitor fanout.

    Without the cap, six competitor sub-runs each open their own
    ``ThreadPoolExecutor(max_workers=16)``, peaking around 96 worker threads
    that all hammer the same upstream APIs. ``internal_subrun=True`` should
    reduce the inner pool so the nested fanout stays bounded.
    """

    def test_normal_run_uses_full_ceiling(self):
        self.assertEqual(pipeline._inner_max_workers(20, internal_subrun=False), 16)
        self.assertEqual(pipeline._inner_max_workers(10, internal_subrun=False), 10)
        self.assertEqual(pipeline._inner_max_workers(1, internal_subrun=False), 4)

    def test_subrun_caps_at_four(self):
        self.assertEqual(pipeline._inner_max_workers(20, internal_subrun=True), 4)
        self.assertEqual(pipeline._inner_max_workers(10, internal_subrun=True), 4)
        self.assertEqual(pipeline._inner_max_workers(3, internal_subrun=True), 3)
        self.assertEqual(pipeline._inner_max_workers(1, internal_subrun=True), 2)

    def test_subrun_caps_total_concurrency_below_uncapped(self):
        # Derive the outer cap from fanout so this test stays meaningful if
        # MAX_PARALLEL_SUBRUNS is bumped. The contract under test is "subrun
        # mode meaningfully reduces total inner-thread count", not a magic
        # number tied to today's value of MAX_PARALLEL_SUBRUNS=6.
        from lib import fanout
        max_subruns = fanout.MAX_PARALLEL_SUBRUNS
        capped = pipeline._inner_max_workers(20, internal_subrun=True) * max_subruns
        uncapped = pipeline._inner_max_workers(20, internal_subrun=False) * max_subruns
        self.assertLess(capped, uncapped, f"capped={capped} not < uncapped={uncapped}")
        # The cap must cut total concurrency to at most half of the un-capped
        # value; otherwise the cap is doing real work.
        self.assertLessEqual(
            capped,
            uncapped // 2,
            f"capped {capped} should be at most half of uncapped {uncapped}",
        )


class TestScrapeCreatorsTierGating(unittest.TestCase):
    """The onboarding Recommended vs Everything tiers must be real.

    Recommended (key, no INCLUDE_SOURCES) = TikTok + Instagram only.
    Everything (INCLUDE_SOURCES lists them) = also Threads, Pinterest, ...
    """

    KEY = {"SCRAPECREATORS_API_KEY": "k"}

    def test_recommended_tier_runs_tiktok_instagram(self):
        avail = pipeline.available_sources(dict(self.KEY))
        self.assertIn("tiktok", avail)
        self.assertIn("instagram", avail)

    def test_threads_off_without_include_sources(self):
        self.assertNotIn("threads", pipeline.available_sources(dict(self.KEY)))

    def test_threads_on_with_include_sources(self):
        cfg = {**self.KEY, "INCLUDE_SOURCES": "threads"}
        self.assertIn("threads", pipeline.available_sources(cfg))

    def test_pinterest_off_without_include_sources(self):
        self.assertNotIn("pinterest", pipeline.available_sources(dict(self.KEY)))

    def test_pinterest_on_with_persisted_include_sources(self):
        # Regression: this failed before U6 because the pinterest gate read
        # requested_sources only and ignored a persisted INCLUDE_SOURCES.
        cfg = {**self.KEY, "INCLUDE_SOURCES": "pinterest"}
        self.assertIn("pinterest", pipeline.available_sources(cfg))

    def test_pinterest_on_via_requested_sources(self):
        # The per-run --sources path must still work.
        avail = pipeline.available_sources(dict(self.KEY), requested_sources=["pinterest"])
        self.assertIn("pinterest", avail)

    def test_everything_tier_enables_all(self):
        cfg = {
            **self.KEY,
            "INCLUDE_SOURCES": "tiktok,instagram,threads,pinterest,youtube_comments,tiktok_comments",
        }
        avail = pipeline.available_sources(cfg)
        self.assertIn("threads", avail)
        self.assertIn("pinterest", avail)


if __name__ == "__main__":
    unittest.main()
