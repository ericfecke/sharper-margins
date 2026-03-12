"""
fetch_kalshi.py — Fetch Kalshi prediction market prices and fuzzy-match to games.
No authentication required for read-only access.
Caches to .tmp/kalshi_{sport}_{date}.json.
"""

import json
import sys
from datetime import date
from pathlib import Path

import requests
from rapidfuzz import fuzz, process

TMP_DIR = Path(__file__).parent.parent / ".tmp"
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
FUZZY_THRESHOLD = 80


def fetch_kalshi(sport: str, games: list, today: date = None, force: bool = False) -> dict:
    """
    Fetch Kalshi markets for a sport and fuzzy-match to games list.

    Args:
        sport: Internal sport key.
        games: List of normalized game objects (from fetch_odds).
        today: Date override for cache.
        force: Force re-fetch.

    Returns:
        Dict mapping game_id -> kalshi match info:
            {"kalshi_probability": float | None, "kalshi_match": bool, "kalshi_market_title": str | None}
    """
    if today is None:
        today = date.today()

    TMP_DIR.mkdir(exist_ok=True)
    cache_path = TMP_DIR / f"kalshi_{sport}_{today.isoformat()}.json"

    if not force and cache_path.exists():
        with open(cache_path) as f:
            return json.load(f)

    markets = _fetch_markets(sport)
    result = {}

    for game in games:
        game_id = game["id"]
        home = game["home_team"]
        away = game["away_team"]
        match = _match_game_to_market(home, away, markets)
        result[game_id] = match

    with open(cache_path, "w") as f:
        json.dump(result, f, indent=2)

    return result


def _fetch_markets(sport: str) -> list:
    """Fetch active Kalshi markets relevant to the sport."""
    sport_series_map = {
        "nba": "NBA",
        "nfl": "NFL",
        "mlb": "MLB",
        "nhl": "NHL",
        "cfb": "NCAAF",
        "cbb": "NCAAB",
        "ufc": "UFC",
    }
    series_tag = sport_series_map.get(sport, sport.upper())

    markets = []
    try:
        url = f"{KALSHI_BASE}/markets"
        params = {"limit": 200, "status": "open"}
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        all_markets = data.get("markets", [])
        # Filter to sport-relevant markets
        for m in all_markets:
            title = m.get("title", "")
            subtitle = m.get("subtitle", "")
            if series_tag.lower() in title.lower() or series_tag.lower() in subtitle.lower():
                markets.append(m)
        print(f"[fetch_kalshi] {sport.upper()}: {len(markets)} relevant markets found")
    except Exception as e:
        print(f"[fetch_kalshi] Failed to fetch markets for {sport}: {e}", file=sys.stderr)

    return markets


def _match_game_to_market(home: str, away: str, markets: list) -> dict:
    """Fuzzy-match a game to a Kalshi market. Returns match info."""
    if not markets:
        return {"kalshi_probability": None, "kalshi_match": False, "kalshi_market_title": None}

    game_str = f"{away} vs {home}"
    market_titles = [m.get("title", "") + " " + m.get("subtitle", "") for m in markets]

    match_result = process.extractOne(
        game_str,
        market_titles,
        scorer=fuzz.token_set_ratio,
        score_cutoff=FUZZY_THRESHOLD,
    )

    if not match_result:
        return {"kalshi_probability": None, "kalshi_match": False, "kalshi_market_title": None}

    matched_title, score, idx = match_result
    market = markets[idx]

    # Extract home team win probability from yes/no market
    prob = _extract_probability(market, home)

    return {
        "kalshi_probability": prob,
        "kalshi_match": prob is not None,
        "kalshi_market_title": market.get("title"),
        "kalshi_match_score": score,
    }


def _extract_probability(market: dict, home_team: str) -> float | None:
    """Extract win probability for home team from Kalshi market."""
    try:
        yes_bid = market.get("yes_bid")
        yes_ask = market.get("yes_ask")
        no_bid = market.get("no_bid")
        no_ask = market.get("no_ask")

        # Use midpoint of bid/ask if available
        if yes_bid is not None and yes_ask is not None:
            yes_mid = (yes_bid + yes_ask) / 2
            return round(yes_mid / 100, 4)  # Kalshi prices in cents (0-100)

        # Fallback: last price
        last_price = market.get("last_price")
        if last_price is not None:
            return round(last_price / 100, 4)

    except Exception:
        pass
    return None


if __name__ == "__main__":
    # Quick test
    fake_games = [{"id": "test1", "home_team": "Lakers", "away_team": "Celtics"}]
    result = fetch_kalshi("nba", fake_games)
    print(json.dumps(result, indent=2))
