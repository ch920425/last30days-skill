import os
import unittest
from pathlib import Path
from unittest import mock

from lib import env


class EnvV3Tests(unittest.TestCase):





    def test_file_permission_check_skips_windows_posix_mode_bits(self):
        path = mock.Mock(spec=Path)
        with mock.patch.object(env.os, "name", "nt"), mock.patch.object(env.sys.stderr, "write") as write:
            env._check_file_permissions(path)

        path.stat.assert_not_called()
        write.assert_not_called()

    def test_get_config_includes_perplexity_knobs(self):
        overrides = {
            "LAST30DAYS_PERPLEXITY_MODE": "search",
            "LAST30DAYS_PERPLEXITY_MODEL": "sonar-reasoning-pro",
            "LAST30DAYS_PERPLEXITY_MAX_RESULTS": "3",
            "LAST30DAYS_PERPLEXITY_SEARCH_CONTEXT_SIZE": "low",
            "LAST30DAYS_PERPLEXITY_SEARCH_MODE": "academic",
            "LAST30DAYS_PERPLEXITY_DOMAIN_FILTER": "example.com",
            "LAST30DAYS_PERPLEXITY_LANGUAGE_FILTER": "en",
            "LAST30DAYS_PERPLEXITY_COUNTRY": "US",
            "LAST30DAYS_PERPLEXITY_RECENCY_FILTER": "week",
            "LAST30DAYS_PERPLEXITY_REASONING_EFFORT": "high",
            "LAST30DAYS_PERPLEXITY_DEEP_TIMEOUT_SECONDS": "600",
        }
        with mock.patch.object(env, "CONFIG_FILE", None), \
             mock.patch.object(env, "_find_project_env", return_value=None), \
             mock.patch("lib.env._load_keychain", return_value={}), \
             mock.patch("lib.env._load_pass", return_value={}), \
             mock.patch.dict(os.environ, overrides, clear=False):
            config = env.get_config()

        for key, value in overrides.items():
            self.assertEqual(value, config[key])


class ThreadsAvailabilityTests(unittest.TestCase):
    """Threads is in the SC default-on family: same key, same per-call cost
    shape as TikTok / Instagram, so the same default-on rule applies.
    Suppression goes through EXCLUDE_SOURCES, not gated opt-in."""

    def test_threads_available_with_sc_key_only(self):
        self.assertTrue(env.is_threads_available({"SCRAPECREATORS_API_KEY": "k"}))

    def test_threads_unavailable_without_sc_key(self):
        self.assertFalse(env.is_threads_available({}))
        self.assertFalse(env.is_threads_available({"INCLUDE_SOURCES": "threads"}))

    def test_threads_availability_predicate_is_key_only(self):
        """is_threads_available is availability-only (key present).

        Scheduling is gated separately by INCLUDE_SOURCES in the pipeline's
        available_sources (see TestScrapeCreatorsTierGating) — the predicate
        itself only reports whether the credential exists.
        """
        self.assertTrue(env.is_threads_available({
            "SCRAPECREATORS_API_KEY": "k",
            "INCLUDE_SOURCES": "",
        }))

if __name__ == "__main__":
    unittest.main()
