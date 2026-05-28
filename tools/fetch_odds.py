"""
fetch_odds.py — Pull moneyline odds from The Odds API for DraftKings and FanDuel.
Caches results to .tmp/odds_{sport}_{date}.json. One pull per sport per day.
"""

import json
import logging
import os
import time
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

from config import FETCH_MAX_RETRIES, FETCH_RETRY_BACKOFF

load_dotenv()
logger = logging.getLogger(__name__)

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
        logger.error("ODDS_API_KEY not set in .env")
        return []

    odds_sport = SPORT_MAP.get(sport)
    if not odds_sport:
        logger.error("Unknown sport: %s", sport)
        return []

    url = f"{BASE_URL}/{odds_sport}/odds"
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h",
        "bookmakers": ",".join(BOOKMAKERS),
        "oddsFormat": "american",
    }

    for attempt in range(FETCH_MAX_RETRIES):
        try:
            resp = requests.get(url, params=params, timeout=15)

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", FETCH_RETRY_BACKOFF[attempt]))
                logger.warning("Rate limited (429) for %s — retrying in %ds", sport.upper(), retry_after)
                time.sleep(retry_after)
                continue

            resp.raise_for_status()
            games = resp.json()
            logger.info("%s: fetched %d games", sport.upper(), len(games))

            remaining = resp.headers.get("x-requests-remaining", "?")
            used = resp.headers.get("x-requests-used", "?")
            logger.info("API credits — used: %s, remaining: %s", used, remaining)
            if remaining != "?" and int(remaining) < 50:
                logger.warning("Odds API credits running low: %s remaining", remaining)

            normalized = [_normalize_game(g) for g in games]
            dropped = sum(1 for g in normalized if g is None)
            normalized = [g for g in normalized if g]
            if dropped:
                logger.warning("%s: dropped %d malformed game(s) during normalization", sport.upper(), dropped)

            with open(cache_path, "w") as f:
                json.dump(normalized, f, indent=2)

            return normalized

        except requests.exceptions.HTTPError as e:
            logger.error("HTTP error for %s (attempt %d/%d): %s", sport, attempt + 1, FETCH_MAX_RETRIES, e)
        except requests.exceptions.RequestException as e:
            logger.error("Request failed for %s (attempt %d/%d): %s", sport, attempt + 1, FETCH_MAX_RETRIES, e)

        if attempt < FETCH_MAX_RETRIES - 1:
            sleep_s = FETCH_RETRY_BACKOFF[attempt] if attempt < len(FETCH_RETRY_BACKOFF) else FETCH_RETRY_BACKOFF[-1]
            logger.info("Retrying %s in %ds...", sport.upper(), sleep_s)
            time.sleep(sleep_s)

    logger.error("All %d attempts failed for %s", FETCH_MAX_RETRIES, sport.upper())
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
        logger.warning("Failed to normalize game: %s", e)
        return None


if __name__ == "__main__":
    sport = sys.argv[1] if len(sys.argv) > 1 else "nba"
    games = fetch_odds(sport)
    print(json.dumps(games[:2], indent=2))
