"""Digg AI 1000 cluster source for Last30Days.

Shells out to ``digg-pp-cli`` (read-only, no auth required) to surface
curated story clusters. Each cluster carries a published TLDR and curatorial
rank. Post-level social enrichment is intentionally not requested.

Activation gate: this source is only available when ``digg-pp-cli`` is
on PATH. ``pipeline.available_sources`` checks ``shutil.which`` before
including ``digg`` in the source list. The functions below also detect
the missing-binary case as a defensive fallback.

Primary path: ``digg-pp-cli search <topic> --since 30d --agent --limit N``.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from . import log, subproc
from .relevance import token_overlap_relevance


CLI_BIN = "digg-pp-cli"

# Per-depth knobs.
DEPTH_CONFIG = {
    "quick": 8,
    "default": 20,
    "deep": 40,
}

SEARCH_TIMEOUT = 30



def _log(msg: str) -> None:
    log.source_log("Digg", msg, tty_only=False)


def _is_available() -> bool:
    """True when the digg-pp-cli binary is on PATH."""
    return shutil.which(CLI_BIN) is not None


def _today() -> datetime:
    return datetime.now(timezone.utc)


def _parse_first_post_age(age: Optional[str], today: Optional[datetime] = None) -> Optional[str]:
    """Convert a digg firstPostAge token (e.g. '5d', '17d', '5h', '1w', '1m')
    into a YYYY-MM-DD string. Returns None when the value is outside the
    last-30-day window or cannot be parsed.

    Digg uses minutes-symbol-collision for 'months' (per agent-context:
    'Nh, Nd, Nw, Nm (e.g. 30d, 1w, 12h, 1m)'), so 'Nm' is months ~30 days.
    """
    if not age or not isinstance(age, str):
        return None
    age = age.strip().lower()
    if len(age) < 2:
        return None
    unit = age[-1]
    try:
        amount = int(age[:-1])
    except (ValueError, TypeError):
        return None
    if amount < 0:
        return None

    base = today or _today()

    if unit == "h":
        delta = timedelta(hours=amount)
    elif unit == "d":
        delta = timedelta(days=amount)
    elif unit == "w":
        delta = timedelta(weeks=amount)
    elif unit == "m":
        delta = timedelta(days=amount * 30)
    else:
        return None

    if delta > timedelta(days=30):
        return None

    point = base - delta
    return point.date().isoformat()


def _build_search_args(query: str, limit: int) -> List[str]:
    return [
        CLI_BIN,
        "search",
        query,
        "--since",
        "30d",
        "--agent",
        "--limit",
        str(limit),
    ]



def _run_cli(cmd: List[str], timeout: int) -> Dict[str, Any]:
    """Invoke digg-pp-cli and parse the JSON envelope.

    Returns ``{"results": [...]}`` on success, ``{"results": [], "error": "..."}``
    on failure. Never raises; the pipeline relies on shape consistency.
    """
    if not _is_available():
        return {"results": [], "error": f"{CLI_BIN} not on PATH"}
    try:
        result = subproc.run_with_timeout(cmd, timeout=timeout)
    except subproc.SubprocTimeout as exc:
        _log(f"Timeout: {exc}")
        return {"results": [], "error": str(exc)}
    except FileNotFoundError as exc:
        _log(f"Binary missing: {exc}")
        return {"results": [], "error": str(exc)}
    except OSError as exc:
        _log(f"Spawn failed: {exc}")
        return {"results": [], "error": str(exc)}

    if result.returncode != 0:
        snippet = (result.stderr or "").strip().splitlines()[:1]
        first = snippet[0] if snippet else f"exit {result.returncode}"
        _log(f"CLI exit {result.returncode}: {first}")
        return {"results": [], "error": first}

    stdout = result.stdout or ""
    if not stdout.strip():
        return {"results": []}
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        _log(f"JSON decode failed: {exc}")
        return {"results": [], "error": f"json decode: {exc}"}

    if not isinstance(data, dict):
        return {"results": []}
    results = data.get("results")
    if not isinstance(results, list):
        return {"results": []}
    return data


def search_digg(
    topic: str,
    from_date: str,
    to_date: str,
    depth: str = "default",
) -> Dict[str, Any]:
    """Search Digg AI 1000 clusters via digg-pp-cli.

    Args:
        topic: search query.
        from_date: YYYY-MM-DD start (advisory; --since 30d is the actual filter).
        to_date: YYYY-MM-DD end (advisory; same).
        depth: 'quick' | 'default' | 'deep'.

    Returns:
        Dict with ``results`` list. On failure, ``results`` is empty and an
        ``error`` key carries a one-line description.
    """
    limit = DEPTH_CONFIG.get(depth, DEPTH_CONFIG["default"])
    if not topic or not topic.strip():
        return {"results": []}
    cmd = _build_search_args(topic, limit)
    _log(f"search '{topic}' (limit={limit}, since=30d)")
    response = _run_cli(cmd, timeout=SEARCH_TIMEOUT)
    n = len(response.get("results") or [])
    _log(f"found {n} clusters")
    return response


def _build_url(cluster_url_id: str) -> str:
    return f"https://di.gg/ai/{cluster_url_id}"


def _rank_score(rank: Optional[int]) -> float:
    """Convert Digg rank (lower is better, top 50 are notable) into a
    positive engagement-style signal in [0, 50]. Anything off the top-50
    leaderboard contributes 0.
    """
    if rank is None:
        return 0.0
    try:
        r = int(rank)
    except (TypeError, ValueError):
        return 0.0
    if r < 1 or r > 50:
        return 0.0
    return float(51 - r)


def parse_digg_response(
    response: Dict[str, Any],
    query: str = "",
) -> List[Dict[str, Any]]:
    """Parse a digg search envelope into normalized item dicts.

    Args:
        response: payload from ``search_digg``.
        query: original search query, used for token-overlap relevance.

    Returns:
        List of dicts ready for ``normalize._normalize_digg``.
    """
    raw = response.get("results") if isinstance(response, dict) else None
    if not isinstance(raw, list):
        return []

    items: List[Dict[str, Any]] = []
    for i, cluster in enumerate(raw):
        if not isinstance(cluster, dict):
            continue
        cluster_url_id = cluster.get("clusterUrlId")
        if not cluster_url_id:
            continue

        title = str(cluster.get("title") or "").strip()
        tldr = str(cluster.get("tldr") or "").strip()
        rank = cluster.get("rank")
        post_count = cluster.get("postCount") or 0
        unique_authors = cluster.get("uniqueAuthors") or 0
        first_post_age = cluster.get("firstPostAge")
        date_str = _parse_first_post_age(first_post_age)
        if date_str is None and first_post_age:
            # firstPostAge present but outside 30d -> drop; last30days contract.
            continue

        rank_decay = max(0.3, 1.0 - (i * 0.02))
        if query:
            content_score = token_overlap_relevance(query, f"{title} {tldr}".strip())
        else:
            content_score = 0.5
        rank_boost = min(0.2, _rank_score(rank) / 250.0)
        relevance = min(1.0, 0.55 * rank_decay + 0.35 * content_score + rank_boost)

        items.append(
            {
                "id": str(cluster_url_id),
                "title": title or f"Digg cluster {i + 1}",
                "url": _build_url(str(cluster_url_id)),
                "tldr": tldr,
                "author": "",
                "date": date_str,
                "engagement": {
                    "postCount": int(post_count) if isinstance(post_count, (int, float)) else 0,
                    "uniqueAuthors": int(unique_authors) if isinstance(unique_authors, (int, float)) else 0,
                    "rank": int(rank) if isinstance(rank, (int, float)) else None,
                    "rank_score": _rank_score(rank),
                },
                "first_post_age": first_post_age,
                "posts": [],
                "relevance": round(relevance, 2),
                "why_relevant": (
                    f"Digg cluster (rank {rank}, {post_count} posts, {unique_authors} authors)"
                    if rank is not None
                    else f"Digg cluster ({post_count} posts, {unique_authors} authors)"
                ),
            }
        )

    return items
