"""Public X search through the local GET-only X API v2 wrapper."""

import json
import os
import re
import subprocess
from typing import Any, Dict, List, Optional

from . import log
from .relevance import token_overlap_relevance as _compute_relevance


def _log(msg: str) -> None:
    log.source_log("xurl", msg, tty_only=False)


# Depth configurations: number of results to request
DEPTH_CONFIG = {
    "quick": 10,
    "default": 30,
    "deep": 60,
}


def is_available(bearer_token: str | None = None) -> bool:
    """Return whether the hardened wrapper and bearer token are available."""
    import shutil

    token = bearer_token or os.environ.get("X_BEARER_TOKEN")
    return shutil.which("xurl") is not None and bool(str(token or "").strip())


def has_stored_auth(bearer_token: str | None = None) -> bool:
    """Compatibility alias for local availability checks."""
    return is_available(bearer_token)


def clear_availability_cache() -> None:
    """Compatibility no-op; availability is intentionally checked fresh."""


def search_x(
    query: str,
    depth: str = "default",
    bearer_token: str | None = None,
) -> Dict[str, Any]:
    """Search public X posts through the API v2 recent-search endpoint.

    Args:
        query: Search query string
        depth: "quick", "default", or "deep"

    Returns:
        Raw JSON response from X API v2 tweets/search/recent, or a dict
        with an "error" key on failure.
    """
    max_results = DEPTH_CONFIG.get(depth, DEPTH_CONFIG["default"])
    # X API v2 search/recent requires max_results in 10–100 range
    max_results = max(10, min(100, max_results))

    try:
        child_env = os.environ.copy()
        if bearer_token:
            child_env["X_BEARER_TOKEN"] = bearer_token
        result = subprocess.run(
            [
                "xurl",
                "/tweets/search/recent",
                "--get",
                "--data-urlencode",
                f"query={query}",
                "--data-urlencode",
                f"max_results={max_results}",
                "--data-urlencode",
                "tweet.fields=author_id,created_at,public_metrics,text",
                "--data-urlencode",
                "expansions=author_id",
                "--data-urlencode",
                "user.fields=username,name",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=child_env,
        )

        if result.returncode != 0:
            error_text = result.stderr.strip() or result.stdout.strip()
            return {"error": f"xurl search failed: {error_text}"}

        return json.loads(result.stdout)

    except FileNotFoundError:
        return {"error": "xurl not found in PATH"}
    except subprocess.TimeoutExpired:
        return {"error": "xurl search timed out (30s)"}
    except json.JSONDecodeError as exc:
        return {"error": f"Invalid JSON from xurl: {exc}"}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def parse_x_response(
    response: Dict[str, Any],
    topic: str = "",
) -> List[Dict[str, Any]]:
    """Parse xurl search response into normalized item dicts.

    Output format matches the existing X item schema:
    id, text, url, author_handle, date, engagement, why_relevant, relevance.

    Args:
        response: Raw X API v2 response dict from search_x()
        topic: Original search topic (used for relevance scoring)

    Returns:
        List of item dicts.  Empty list on error or no results.
    """
    items: List[Dict[str, Any]] = []

    if "error" in response:
        _log(f"Error in response: {response['error']}")
        return items

    data = response.get("data") or []
    if not data:
        return items

    # Build author lookup from includes.users
    authors: Dict[str, Dict[str, Any]] = {}
    for user in (response.get("includes") or {}).get("users") or []:
        authors[user["id"]] = user

    for i, tweet in enumerate(data):
        author_id = tweet.get("author_id", "")
        author = authors.get(author_id, {})
        username = author.get("username", "")

        tweet_id = tweet.get("id", "")
        url = f"https://x.com/{username}/status/{tweet_id}" if username else ""

        # Parse public_metrics
        engagement: Optional[Dict[str, Any]] = None
        metrics = tweet.get("public_metrics") or {}
        if metrics:
            engagement = {
                "likes": metrics.get("like_count", 0),
                "reposts": metrics.get("retweet_count", 0),
                "replies": metrics.get("reply_count", 0),
                "quotes": metrics.get("quote_count", 0),
            }

        # Parse ISO 8601 date → YYYY-MM-DD
        date: Optional[str] = None
        created = tweet.get("created_at", "")
        if created:
            m = re.match(r"(\d{4}-\d{2}-\d{2})", created)
            if m:
                date = m.group(1)

        text = tweet.get("text", "").strip()

        # Relevance score via shared token-overlap function
        relevance = _compute_relevance(topic, text) if topic else 0.5

        items.append({
            "id": f"XURL{i + 1}",
            "text": text[:500],
            "url": url,
            "author_handle": username,
            "date": date,
            "engagement": engagement,
            "why_relevant": "",
            "relevance": relevance,
        })

    return items
