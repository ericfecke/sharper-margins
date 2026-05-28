"""
fetch_results.py — Update W/L/P results for completed signals.
Checks ESPN scoreboard for completed games and matches them to pending signals.
No API key required. Run at the start of each cycle to backfill results.
"""

import logging
from datetime import datetime, timezone

import requests

from write_signal import load_signals, update_result

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"

SPORT_ESPN_PATH = {
    "NBA":  ("basketball", "nba"),
    "NFL":  ("football", "nfl"),
    "CFB":  ("football", "college-football"),
    "MLB":  ("baseball", "mlb"),
    "NHL":  ("icehockey", "nhl"),
    "CBB":  ("basketball", "mens-college-basketball"),
}

logger = logging.getLogger(__name__)


def update_results() -> int:
    """
    Check ESPN for completed games and update W/L/P on pending signals.

    Returns:
        Number of signals updated.
    """
    signals = load_signals()
    pending = [s for s in signals if s.get("result") is None and s.get("game_id")]
    if not pending:
        logger.info("No pending signals to check for results")
        return 0

    # Group pending signals by sport
    by_sport: dict[str, list] = {}
    for sig in pending:
        sport = (sig.get("sport") or "").upper()
        if sport in SPORT_ESPN_PATH:
            by_sport.setdefault(sport, []).append(sig)

    updated_count = 0
    for sport, sport_signals in by_sport.items():
        completed = _fetch_completed_games(sport)
        if not completed:
            continue
        for sig in sport_signals:
            result = _match_result(
                sig.get("game", ""),
                sig.get("recommendation", ""),
                completed,
            )
            if result:
                if update_result(sig["game_id"], sig["book"], result):
                    updated_count += 1

    logger.info("Results updated: %d signal(s)", updated_count)
    return updated_count


def _fetch_completed_games(sport: str) -> list:
    """Fetch completed games from ESPN scoreboard for a sport."""
    sport_cat, league = SPORT_ESPN_PATH[sport]
    url = f"{ESPN_BASE}/{sport_cat}/{league}/scoreboard"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return _parse_completed_games(resp.json())
    except Exception as e:
        logger.error("Failed to fetch scoreboard for %s: %s", sport, e)
        return []


def _parse_completed_games(data: dict) -> list:
    """Parse completed game results from ESPN scoreboard response."""
    completed = []
    for event in data.get("events", []):
        competitions = event.get("competitions", [])
        if not competitions:
            continue
        comp = competitions[0]
        status = comp.get("status", {}).get("type", {})
        if not status.get("completed", False):
            continue
        competitors = comp.get("competitors", [])
        home_comp = next((c for c in competitors if c.get("homeAway") == "home"), None)
        away_comp = next((c for c in competitors if c.get("homeAway") == "away"), None)
        if not home_comp or not away_comp:
            continue
        try:
            home_score = int(home_comp.get("score", {}).get("value", 0) or 0)
            away_score = int(away_comp.get("score", {}).get("value", 0) or 0)
        except (TypeError, ValueError):
            home_score, away_score = 0, 0
        completed.append({
            "home_team": (home_comp.get("team") or {}).get("displayName", "").lower(),
            "away_team": (away_comp.get("team") or {}).get("displayName", "").lower(),
            "home_score": home_score,
            "away_score": away_score,
        })
    return completed


def _match_result(game_str: str, recommendation: str, completed: list) -> str | None:
    """
    Match a signal game string to a completed game and determine W/L/P.

    Args:
        game_str: Format "Away @ Home" (from signal's "game" field).
        recommendation: Format "Team Name ML".
        completed: List of completed game dicts from ESPN.

    Returns:
        "W", "L", "P", or None if no match found.
    """
    if not game_str or not recommendation:
        return None

    # Parse "Away @ Home"
    parts = game_str.split("@")
    if len(parts) != 2:
        return None
    signal_away = parts[0].strip().lower()
    signal_home = parts[1].strip().lower()

    # Strip " ML" suffix from recommendation
    bet_team = recommendation.lower().replace(" ml", "").strip()

    for cg in completed:
        cg_home = cg["home_team"]
        cg_away = cg["away_team"]

        # Containment match on both sides
        home_match = signal_home in cg_home or cg_home in signal_home
        away_match = signal_away in cg_away or cg_away in signal_away
        if not (home_match and away_match):
            continue

        home_score = cg["home_score"]
        away_score = cg["away_score"]

        # Determine which side was bet
        is_home_bet = (bet_team in cg_home or cg_home in bet_team)

        if home_score == away_score:
            return "P"
        if is_home_bet:
            return "W" if home_score > away_score else "L"
        else:
            return "W" if away_score > home_score else "L"

    return None


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    n = update_results()
    print(f"Updated {n} signal(s)")
