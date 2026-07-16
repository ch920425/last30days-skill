# How Last30Days Search Works

Last30Days runs a multi-source retrieval pipeline over its supported sources,
including Reddit, YouTube, TikTok, Instagram, Hacker News, Polymarket, GitHub,
Digg clusters, arXiv, Techmeme, and configured web-search backends.

## Pipeline

1. Resolve the topic into source-specific queries and communities.
2. Retrieve supported sources concurrently with bounded timeouts.
3. Normalize each result into the shared source-item schema.
4. Apply date, relevance, quality, and engagement gates.
5. Fuse and deduplicate candidates across sources.
6. Rerank the shortlist and render an evidence-backed brief.

Retries are source-scoped. A timeout, rate limit, or malformed response from one
source is reported without silently discarding successful results from others.

## Reddit

Reddit uses public retrieval first, then optional ScrapeCreators enrichment when
configured. Thread metadata and top comments are normalized into the same
evidence model used by the other supported sources.

## X/Twitter boundary

Last30Days never acquires X/Twitter content. Public posts, threads, and recent
searches belong to the separate bearer-token X API v2 skill. The local Grok CLI
is a labeled fallback or synthesis layer only. OAuth user context, browser
cookies, private bookmark discovery, and third-party X backends are unsupported.

## Digg boundary

Digg contributes its own curated cluster metadata only. Last30Days does not call
Digg post-enrichment endpoints or use Digg as an indirect X acquisition route.

## Failure behavior

- Unsupported source aliases are removed before planning.
- Direct attempts to retrieve X fail closed with an explicit routing error.
- Browser-cookie helpers refuse X/Twitter domains at every public entry point.
- Partial source failures remain visible as degraded or failed-source evidence.
