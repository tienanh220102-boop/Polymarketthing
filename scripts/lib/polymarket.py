"""Gamma API client for Polymarket market discovery.

Uses gamma-api.polymarket.com - free, no auth, 15K req/10s.
Primary: GET /events (browse by volume)
Fallback: GET /public-search (keyword search, validated by last30days-skill)
"""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import urlencode

from . import http

GAMMA_EVENTS_URL = "https://gamma-api.polymarket.com/events"
GAMMA_SEARCH_URL = "https://gamma-api.polymarket.com/public-search"
# Public market-wide trade feed. NOT clob.polymarket.com/trades — that one is
# L2-authenticated and only returns the caller's own trades (401 without key).
DATA_API_TRADES_URL = "https://data-api.polymarket.com/trades"

# Sequential search queries — run one at a time with pacing to avoid IP blocks.
# 5 queries × 3 pages × 5 events = up to 75 events. Enough for top 20.
_SEARCH_QUERIES = [
    "election trump president",
    "ukraine russia war nato",
    "economy inflation trade tariff",
    "iran china nuclear sanctions",
    "israel gaza bitcoin crypto fed",
]

# Tokens that indicate politics/economics topics
_INTEREST_TOKENS = frozenset([
    # Politics / geopolitics
    "trump", "biden", "harris", "election", "vote", "ballot", "congress",
    "senate", "republican", "democrat", "white house", "nato", "ukraine",
    "russia", "china", "iran", "israel", "gaza", "war", "tariff", "sanction",
    "nuclear", "president", "parliament", "government", "minister",
    "geopolit", "diplomac", "treaty",
    # Economics / finance
    "economy", "economic", "inflation", "recession", "gdp", "federal reserve",
    "fed", "interest rate", "unemployment", "trade", "dollar", "debt",
    "budget", "oil", "energy", "bitcoin", "crypto", "ethereum", "sec",
    "ipo", "acquisition", "merger", "bankruptcy", "tariff",
])

_INTEREST_TAG_SLUGS = frozenset([
    "politics", "us-politics", "world", "economics", "business",
    "geopolitics", "crypto", "finance", "international",
])


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val or default)
    except (ValueError, TypeError):
        return default


def _get_volume(event: dict) -> float:
    v24 = _safe_float(event.get("volume24hr"))
    v1mo = _safe_float(event.get("volume1mo"))
    return v24 or (v1mo / 30)


def _get_liquidity(event: dict) -> float:
    return _safe_float(event.get("liquidity"))


def _is_interest(event: dict) -> bool:
    """Return True if event is politics or economics related."""
    title = (event.get("title") or "").lower()
    title_norm = re.sub(r"[^\w\s]", " ", title)
    title_tokens = set(title_norm.split())

    # Exact token match
    if title_tokens & _INTEREST_TOKENS:
        return True

    # Substring match for compound tokens (e.g., "geopolitical", "economic")
    for kw in _INTEREST_TOKENS:
        if len(kw) >= 5 and kw in title_norm:
            return True

    # Tag slug match
    for tag in event.get("tags") or []:
        slug = (tag.get("slug") or tag.get("label") or "").lower().replace(" ", "-")
        if slug in _INTEREST_TAG_SLUGS:
            return True

    return False


def _fetch_events_browse(limit: int = 200) -> list[dict]:
    """Fetch events from browse endpoint sorted by volume (no query needed)."""
    params = {"active": "true", "closed": "false", "limit": str(limit)}
    url = f"{GAMMA_EVENTS_URL}?{urlencode(params)}"
    try:
        data = http.get(url, timeout=20)
        if isinstance(data, list) and data and isinstance(data[0], dict) and "id" in data[0]:
            return data
        if isinstance(data, dict):
            events = data.get("events") or []
            if events:
                return events
    except Exception:
        pass
    return []


def _fetch_search_page(query: str, page: int) -> list[dict]:
    """Fetch one page from public-search endpoint."""
    params = {"q": query, "page": str(page), "events_status": "active", "keep_closed_markets": "0"}
    url = f"{GAMMA_SEARCH_URL}?{urlencode(params)}"
    try:
        data = http.get(url, timeout=20)
        return data.get("events") or []
    except Exception:
        return []


def _fetch_events_search() -> list[dict]:
    """Fetch events via sequential search queries with pacing to avoid rate limits.

    Sequential (not parallel) to stay within Gamma API's connection limits.
    5 queries × 3 pages = 15 requests, ~0.4s apart = ~6s total.
    """
    all_events: dict[str, dict] = {}

    for query in _SEARCH_QUERIES:
        for page in range(1, 4):
            for event in _fetch_search_page(query, page):
                eid = str(event.get("id", ""))
                if eid and eid not in all_events:
                    all_events[eid] = event
            time.sleep(0.4)  # pace requests to avoid connection resets

    return list(all_events.values())


def _parse_clob_token_ids(market: dict) -> list[str]:
    raw = market.get("clobTokenIds") or market.get("clob_token_ids") or []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    return [str(t) for t in (raw or [])]


def fetch_large_trades(condition_id: str, min_usd: float = 5000.0) -> list[dict]:
    """Fetch recent trades from the public Data API, keep those with USD notional >= min_usd.

    Notional = size (shares) x price. Filtering on raw size would flag cheap
    longshot fills (e.g. 6000 shares @ 5c = $300) as whale bets.
    Each trade carries: side, outcome, size, price, transactionHash,
    proxyWallet, pseudonym, timestamp.
    """
    if not condition_id:
        return []
    params = {"market": condition_id, "limit": "100", "takerOnly": "true"}
    url = f"{DATA_API_TRADES_URL}?{urlencode(params)}"
    try:
        data = http.get(url, timeout=15, retries=1)
        trades = data if isinstance(data, list) else (data.get("data") or [])
    except Exception:
        return []

    large = []
    for t in trades:
        usd = _safe_float(t.get("size")) * _safe_float(t.get("price"))
        if usd >= min_usd:
            t["usd_value"] = usd
            large.append(t)
    return large


def _parse_outcomes(market: dict) -> list[tuple[str, float]]:
    """Parse outcome names and prices from a market dict."""
    try:
        outcomes_raw = market.get("outcomes") or []
        if isinstance(outcomes_raw, str):
            outcomes_raw = json.loads(outcomes_raw)
    except (json.JSONDecodeError, TypeError):
        outcomes_raw = []

    try:
        prices_raw = market.get("outcomePrices") or []
        if isinstance(prices_raw, str):
            prices_raw = json.loads(prices_raw)
    except (json.JSONDecodeError, TypeError):
        return []

    result = []
    for i, price_str in enumerate(prices_raw):
        try:
            price = float(price_str)
        except (ValueError, TypeError):
            continue
        if price < 0.005:  # skip dust
            continue
        name = str(outcomes_raw[i]) if i < len(outcomes_raw) else f"Outcome {i + 1}"
        result.append((name, price))

    return result


def get_top_markets(n: int = 20, min_liquidity: float = 10_000) -> list[dict]:
    """Return top N active markets filtered by politics/economics, sorted by volume.

    Strategy: search endpoint (sequential, paced) gives volume-ranked results.
    Browse endpoint is tried first as a faster warm-up; search fills the gaps.
    """
    all_events: dict[str, dict] = {}

    # 1. Browse endpoint — fast, may return a small set
    for event in _fetch_events_browse():
        eid = str(event.get("id", ""))
        if eid:
            all_events[eid] = event

    # 2. Always supplement with search (sequential, paced) to get high-volume markets
    for event in _fetch_events_search():
        eid = str(event.get("id", ""))
        if eid and eid not in all_events:
            all_events[eid] = event

    events = list(all_events.values())

    # Filter: active, not closed, enough liquidity, has markets
    events = [
        e for e in events
        if e.get("active") is not False   # keep if field missing or True
        and not e.get("closed")
        and _get_liquidity(e) >= min_liquidity
        and e.get("markets")
    ]

    # Split into interest vs others, sort each by volume
    interest = sorted([e for e in events if _is_interest(e)], key=_get_volume, reverse=True)
    others = sorted([e for e in events if not _is_interest(e)], key=_get_volume, reverse=True)

    # Fill with interest first, pad with high-volume others if needed
    result = interest[:n]
    if len(result) < n:
        result += others[: n - len(result)]

    return result[:n]


def build_market_dict(event: dict) -> dict:
    """Build normalized market dict for monitoring from a raw Gamma API event."""
    markets = sorted(
        event.get("markets") or [],
        key=lambda m: _safe_float(m.get("volume")),
        reverse=True,
    )
    top = markets[0] if markets else {}

    slug = event.get("slug", "")
    event_id = str(event.get("id", ""))
    url = (
        f"https://polymarket.com/event/{slug}"
        if slug
        else f"https://polymarket.com/event/{event_id}"
    )

    end_date = ""
    if top.get("endDate"):
        end_date = str(top["endDate"])[:10]

    parsed = _parse_outcomes(top)
    outcomes = [{"name": name, "price": price} for name, price in parsed]

    try:
        outcomes_raw = top.get("outcomes") or []
        if isinstance(outcomes_raw, str):
            outcomes_raw = json.loads(outcomes_raw)
    except (json.JSONDecodeError, TypeError):
        outcomes_raw = []
    outcome_names = [str(o) for o in outcomes_raw]

    return {
        "event_id": event_id,
        "title": event.get("title", ""),
        "question": top.get("question", event.get("title", "")),
        "url": url,
        "volume24hr": _safe_float(event.get("volume24hr")),
        "liquidity": _safe_float(event.get("liquidity")),
        "end_date": end_date,
        "outcomes": outcomes,
        "condition_id": top.get("conditionId", ""),
        "clob_token_ids": _parse_clob_token_ids(top),
        "outcome_names": outcome_names,
    }
