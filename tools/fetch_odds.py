"""
fetch_odds.py — Pull moneyline odds from The Odds API for DraftKings and FanDuel.
Caches results to .tmp/odds_{sport}_{date}.json. One pull per sport per day.
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
BASE_URL = "https://api.the-odds-api.com/v4/sports"
TMP_DIR = Path(__file__).parent.parent / ".tmp"

# Map internal sport keys to Odds API sport keys
SPORT_MAP = {
    "nfl": "americanfootball_nfl",
    "cfb": "americanfootball_ncaaf",
    "nba": "basketball_nba",
    "cbb": "basketball_ncaab",
    "mlb": "baseball_mlb",
    "nhl": "icehockey_nhl",
    "ufc": "mma_mixed_martial_arts",
}

BOOKMAKERS = ["draftkings", "fanduel"]


def fetch_odds(sport: str, today: date = None, force: bool = False) -> list:
    """
    Fetch moneyline odds for a sport. Returns cached data if already pulled today.

    Args:
        sport: Internal sport key ('nba', 'nfl', etc.)
        today: Date override for cache key.
        force: Force re-fetch even if cache exists.

    Returns:
        List of game objects with odds, or [] on failure.
    """
    if today is None:
        today = date.today()

    TMP_DIR.mkdir(exist_ok=True)
    cache_path = TMP_DIR / f"odds_{sport}_{today.isoformat()}.json"

    if not force and cache_path.exists():
        with open(cache_path) as f:
            return json.load(f)

    if not ODDS_API_KEY:
        print(f"[fetch_odds] ERROR: ODDS_API_KEY not set in .env", file=sys.stderr)
        return []

    odds_sport = SPORT_MAP.get(sport)
    if not odds_sport:
        print(f"[fetch_odds] Unknown sport: {sport}", file=sys.stderr)
        return []

    url = f"{BASE_URL}/{odds_sport}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h",
        "bookmakers": ",".join(BOOKMAKERS),
        "oddsFormat": "american",
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        games = resp.json()
        print(f"[fetch_odds] {sport.upper()}: fetched {len(games)} games")

        # Log remaining API credits
        remaining = resp.headers.get("x-requests-remaining", "?")
        used = resp.headers.get("x-requests-used", "?")
        print(f"[fetch_odds] API credits — used: {used}, remaining: {remaining}")

        # Normalize to internal format
        normalized = [_normalize_game(g) for g in games]
        normalized = [g for g in normalized if g]  # drop nulls

        with open(cache_path, "w") as f:
            json.dump(normalized, f, indent=2)

        return normalized

    except requests.exceptions.HTTPError as e:
        print(f"[fetch_odds] HTTP error for {sport}: {e}", file=sys.stderr)
        return []
    except requests.exceptions.RequestException as e:
        print(f"[fetch_odds] Request failed for {sport}: {e}", file=sys.stderr)
        return []


def _normalize_game(game: dict) -> dict | None:
    """Normalize Odds API game object to internal format."""
    try:
        game_id = game["id"]
        sport_key = game["sport_key"]
        home_team = game["home_team"]
        away_team = game["away_team"]
        commence_time = game["commence_time"]

        odds_by_book = {}
        for bookmaker in game.get("bookmakers", []):
            book_key = bookmaker["key"]
            if book_key not in BOOKMAKERS:
                continue
            for market in bookmaker.get("markets", []):
                if market["key"] != "h2h":
                    continue
                outcomes = {o["name"]: o["price"] for o in market.get("outcomes", [])}
                if home_team in outcomes and away_team in outcomes:
                    odds_by_book[book_key] = {
                        "home": outcomes[home_team],
                        "away": outcomes[away_team],
                    }

        if not odds_by_book:
            return None

        return {
            "id": game_id,
            "sport_key": sport_key,
            "home_team": home_team,
            "away_team": away_team,
            "commence_time": commence_time,
            "odds": odds_by_book,
        }
    except (KeyError, TypeError) as e:
        print(f"[fetch_odds] Failed to normalize game: {e}", file=sys.stderr)
        return None


if __name__ == "__main__":
    sport = sys.argv[1] if len(sys.argv) > 1 else "nba"
    games = fetch_odds(sport)
    print(json.dumps(games[:2], indent=2))
