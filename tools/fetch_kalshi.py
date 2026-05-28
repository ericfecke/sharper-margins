"""
fetch_kalshi.py — Fetch Kalshi prediction market prices and fuzzy-match to games.
No authentication required for read-only access.
Caches to .tmp/kalshi_{sport}_{date}.json.
"""

import json
import logging
from datetime import date
from pathlib import Path

import requests
from rapidfuzz import fuzz, process

from config import FUZZY_THRESHOLD

TMP_DIR = Path(__file__).parent.parent / ".tmp"
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
logger = logging.getLogger(__name__)

# Common abbreviation → full team name (lowercase) for fuzzy matching.
# Kalshi titles often use short codes that differ from full names in the odds feed.
_TEAM_ABBR = {
    # NBA
    "lal": "los angeles lakers", "lac": "los angeles clippers", "gsw": "golden state warriors",
    "bos": "boston celtics", "nyk": "new york knicks", "bkn": "brooklyn nets",
    "phi": "philadelphia 76ers", "atl": "atlanta hawks", "chi": "chicago bulls",
    "cle": "cleveland cavaliers", "det": "detroit pistons", "ind": "indiana pacers",
    "mil": "milwaukee bucks", "tor": "toronto raptors", "cha": "charlotte hornets",
    "mia": "miami heat", "orl": "orlando magic", "was": "washington wizards",
    "den": "denver nuggets", "min": "minnesota timberwolves", "okc": "oklahoma city thunder",
    "por": "portland trail blazers", "uta": "utah jazz", "sac": "sacramento kings",
    "phx": "phoenix suns", "dal": "dallas mavericks", "hou": "houston rockets",
    "mem": "memphis grizzlies", "nop": "new orleans pelicans", "sas": "san antonio spurs",
    # NFL
    "ne": "new england patriots", "nyg": "new york giants", "nyj": "new york jets",
    "kc": "kansas city chiefs", "sf": "san francisco 49ers", "gb": "green bay packers",
    "tb": "tampa bay buccaneers", "lac_nfl": "los angeles chargers", "lar": "los angeles rams",
    "no": "new orleans saints", "pit": "pittsburgh steelers", "bal": "baltimore ravens",
    # MLB
    "nyy": "new york yankees", "nym": "new york mets", "bos_mlb": "boston red sox",
    "lad": "los angeles dodgers", "sf_mlb": "san francisco giants",
    "chc": "chicago cubs", "cws": "chicago white sox", "stl": "st. louis cardinals",
    "hou_mlb": "houston astros", "atl_mlb": "atlanta braves",
    # NHL
    "nyr": "new york rangers", "nyi": "new york islanders", "njd": "new jersey devils",
    "tor_nhl": "toronto maple leafs", "mtl": "montreal canadiens", "bos_nhl": "boston bruins",
    "chi_nhl": "chicago blackhawks", "det_nhl": "detroit red wings",
    "pit_nhl": "pittsburgh penguins", "phi_nhl": "philadelphia flyers",
}


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
        logger.info("%s: %d relevant markets found", sport.upper(), len(markets))
    except Exception as e:
        logger.error("Failed to fetch markets for %s: %s", sport, e)

    return markets


def _expand_name(name: str) -> str:
    """Expand a short team abbreviation to its full lowercase name if known."""
    key = name.lower().strip()
    return _TEAM_ABBR.get(key, key)


def _match_game_to_market(home: str, away: str, markets: list) -> dict:
    """Fuzzy-match a game to a Kalshi market. Returns match info."""
    if not markets:
        return {"kalshi_probability": None, "kalshi_match": False, "kalshi_market_title": None}

    market_titles = [m.get("title", "") + " " + m.get("subtitle", "") for m in markets]

    # Try with expanded (full) team names first, fall back to raw names
    for home_str, away_str in [
        (_expand_name(home), _expand_name(away)),
        (home.lower(), away.lower()),
    ]:
        game_str = f"{away_str} vs {home_str}"
        match_result = process.extractOne(
            game_str,
            market_titles,
            scorer=fuzz.token_set_ratio,
            score_cutoff=FUZZY_THRESHOLD,
        )
        if match_result:
            break

    if not match_result:
        return {"kalshi_probability": None, "kalshi_match": False, "kalshi_market_title": None}

    matched_title, score, idx = match_result
    market = markets[idx]

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
