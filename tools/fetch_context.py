"""
fetch_context.py — Fetch ESPN hidden API data for all active sports/games.
Builds context objects consumed by SME agents.
Caches to .tmp/context_{sport}_{date}.json. One pull per sport per day.
"""

import json
import sys
from datetime import date, datetime
from pathlib import Path

import requests

TMP_DIR = Path(__file__).parent.parent / ".tmp"
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports"
ESPN_CORE = "https://sports.core.api.espn.com/v2/sports"

# Sport → ESPN path segments
SPORT_ESPN_PATH = {
    "nba":  ("basketball", "nba"),
    "nfl":  ("football", "nfl"),
    "cfb":  ("football", "college-football"),
    "mlb":  ("baseball", "mlb"),
    "nhl":  ("icehockey", "nhl"),
    "cbb":  ("basketball", "mens-college-basketball"),
    "ufc":  ("mma", "ufc"),
}

SPORT_ESPN_CORE_PATH = {
    "nba": ("basketball", "nba"),
    "nfl": ("football", "nfl"),
    "cfb": ("football", "college-football"),
    "mlb": ("baseball", "mlb"),
    "nhl": ("icehockey", "nhl"),
    "cbb": ("basketball", "mens-college-basketball"),
}


def fetch_context(sport: str, games: list, today: date = None, force: bool = False) -> dict:
    """
    Fetch ESPN context for all games in a sport.

    Args:
        sport: Internal sport key.
        games: Normalized game list from fetch_odds.
        today: Date override.
        force: Force re-fetch.

    Returns:
        Dict keyed by game_id with full context object per game.
    """
    if today is None:
        today = date.today()

    TMP_DIR.mkdir(exist_ok=True)
    cache_path = TMP_DIR / f"context_{sport}_{today.isoformat()}.json"

    if not force and cache_path.exists():
        with open(cache_path) as f:
            return json.load(f)

    if sport not in SPORT_ESPN_PATH:
        print(f"[fetch_context] Unknown sport: {sport}", file=sys.stderr)
        return {}

    context = _build_context(sport, games, today)

    with open(cache_path, "w") as f:
        json.dump(context, f, indent=2)

    return context


def _get(url: str, params: dict = None) -> dict | None:
    """Safe ESPN GET with error handling."""
    try:
        resp = requests.get(url, params=params or {}, timeout=15)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"[fetch_context] GET failed {url}: {e}", file=sys.stderr)
        return None


def _build_context(sport: str, games: list, today: date) -> dict:
    """Build full context dict for all games in sport."""
    sport_cat, league = SPORT_ESPN_PATH[sport]
    base = f"{ESPN_BASE}/{sport_cat}/{league}"

    print(f"[fetch_context] Fetching ESPN data for {sport.upper()}...")

    # Pull shared data once
    standings_data = _get(f"{base}/standings")
    scoreboard_data = _get(f"{base}/scoreboard")
    injuries_data = _get(f"{base}/injuries") if sport != "ufc" else None

    # Build team standings map
    team_records = _parse_standings(standings_data, sport)
    team_injuries = _parse_injuries(injuries_data)

    # Match games to ESPN scoreboard events
    scoreboard_events = _parse_scoreboard(scoreboard_data)

    context = {}
    for game in games:
        game_id = game["id"]
        home_team = game["home_team"]
        away_team = game["away_team"]

        ctx = _build_game_context(
            sport=sport,
            base=base,
            game=game,
            home_team=home_team,
            away_team=away_team,
            team_records=team_records,
            team_injuries=team_injuries,
            scoreboard_events=scoreboard_events,
            today=today,
        )
        context[game_id] = ctx

    print(f"[fetch_context] {sport.upper()}: context built for {len(context)} games")
    return context


def _build_game_context(sport, base, game, home_team, away_team,
                        team_records, team_injuries, scoreboard_events, today):
    """Build context for a single game."""
    ctx = {
        "sport": sport,
        "home_team": home_team,
        "away_team": away_team,
        "game_id": game["id"],
        "commence_time": game["commence_time"],
    }

    # Find ESPN team IDs from records
    home_rec = _find_team_record(home_team, team_records)
    away_rec = _find_team_record(away_team, team_records)

    ctx["home_record"] = home_rec
    ctx["away_record"] = away_rec

    # Find scoreboard event for this game (home field, venue info)
    event = _find_scoreboard_event(home_team, away_team, scoreboard_events)
    ctx["scoreboard_event"] = event

    if event:
        ctx["venue"] = event.get("venue")
        ctx["neutral_site"] = event.get("neutral_site", False)
        ctx["is_home"] = True  # home_team in this game object IS the home team
    else:
        ctx["venue"] = None
        ctx["neutral_site"] = False
        ctx["is_home"] = True

    # Injuries for each team
    ctx["home_injuries"] = team_injuries.get(_normalize_team_name(home_team), [])
    ctx["away_injuries"] = team_injuries.get(_normalize_team_name(away_team), [])

    # Fetch per-team stats and schedule if we have team IDs
    home_id = home_rec.get("team_id") if home_rec else None
    away_id = away_rec.get("team_id") if away_rec else None

    if home_id:
        ctx["home_stats"] = _fetch_team_stats(base, home_id)
        ctx["home_schedule"] = _fetch_team_schedule(base, home_id, today)
    else:
        ctx["home_stats"] = None
        ctx["home_schedule"] = None

    if away_id:
        ctx["away_stats"] = _fetch_team_stats(base, away_id)
        ctx["away_schedule"] = _fetch_team_schedule(base, away_id, today)
    else:
        ctx["away_stats"] = None
        ctx["away_schedule"] = None

    return ctx


def _parse_standings(data: dict | None, sport: str) -> list:
    """Parse ESPN standings into flat list of team records."""
    if not data:
        return []
    teams = []
    try:
        groups = (
            data.get("children", []) or
            [data] if "standings" in data else
            data.get("standings", {}).get("entries", [])
        )
        # Flatten nested ESPN standings structure
        def _walk(node):
            if isinstance(node, list):
                for item in node:
                    _walk(item)
            elif isinstance(node, dict):
                entries = node.get("entries", [])
                for entry in entries:
                    team_info = entry.get("team", {})
                    stats = {s["name"]: s.get("value") for s in entry.get("stats", [])}
                    teams.append({
                        "team_id": str(team_info.get("id", "")),
                        "team_name": team_info.get("displayName", ""),
                        "team_abbr": team_info.get("abbreviation", ""),
                        "wins": stats.get("wins"),
                        "losses": stats.get("losses"),
                        "win_pct": stats.get("winPercent") or stats.get("gamesBehind"),
                        "games_played": stats.get("gamesPlayed"),
                        "raw_stats": stats,
                    })
                for child in node.get("children", []):
                    _walk(child)
        _walk(data)
    except Exception as e:
        print(f"[fetch_context] Standings parse error: {e}", file=sys.stderr)
    return teams


def _parse_injuries(data: dict | None) -> dict:
    """Parse injuries into dict keyed by normalized team name."""
    result = {}
    if not data:
        return result
    try:
        for injury in data.get("injuries", []):
            team = injury.get("team", {})
            team_name = _normalize_team_name(team.get("displayName", ""))
            items = injury.get("injuries", [])
            if team_name not in result:
                result[team_name] = []
            for item in items:
                athlete = item.get("athlete", {})
                result[team_name].append({
                    "name": athlete.get("displayName"),
                    "position": athlete.get("position", {}).get("abbreviation"),
                    "status": item.get("status"),
                    "type": item.get("type"),
                })
    except Exception as e:
        print(f"[fetch_context] Injuries parse error: {e}", file=sys.stderr)
    return result


def _parse_scoreboard(data: dict | None) -> list:
    """Parse scoreboard events list."""
    if not data:
        return []
    events = []
    try:
        for event in data.get("events", []):
            competitions = event.get("competitions", [])
            if not competitions:
                continue
            comp = competitions[0]
            competitors = comp.get("competitors", [])
            home_team = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "home"), None)
            away_team = next((c["team"]["displayName"] for c in competitors if c.get("homeAway") == "away"), None)
            venue = comp.get("venue", {})
            events.append({
                "id": event.get("id"),
                "home_team": home_team,
                "away_team": away_team,
                "venue": venue.get("fullName"),
                "neutral_site": comp.get("neutralSite", False),
                "weather": comp.get("weather"),
                "indoor": venue.get("indoor", False),
            })
    except Exception as e:
        print(f"[fetch_context] Scoreboard parse error: {e}", file=sys.stderr)
    return events


def _fetch_team_stats(base: str, team_id: str) -> dict | None:
    """Fetch team statistics from ESPN."""
    data = _get(f"{base}/teams/{team_id}/statistics")
    if not data:
        return None
    try:
        stats = {}
        for split in data.get("splits", {}).get("categories", []):
            for stat in split.get("stats", []):
                stats[stat["name"]] = stat.get("value")
        return stats
    except Exception as e:
        print(f"[fetch_context] Team stats parse error for {team_id}: {e}", file=sys.stderr)
        return None


def _fetch_team_schedule(base: str, team_id: str, today: date) -> list | None:
    """Fetch recent team schedule from ESPN."""
    data = _get(f"{base}/teams/{team_id}/schedule")
    if not data:
        return None
    try:
        games = []
        for event in data.get("events", []):
            game_date_str = event.get("date", "")
            try:
                game_date = datetime.fromisoformat(game_date_str.replace("Z", "+00:00")).date()
            except Exception:
                continue
            if game_date > today:
                continue  # Future games
            competitions = event.get("competitions", [])
            if not competitions:
                continue
            comp = competitions[0]
            competitors = comp.get("competitors", [])
            result_obj = next((c for c in competitors if str(c.get("team", {}).get("id")) == str(team_id)), None)
            opp = next((c for c in competitors if str(c.get("team", {}).get("id")) != str(team_id)), None)
            games.append({
                "date": game_date.isoformat(),
                "home_away": result_obj.get("homeAway") if result_obj else None,
                "score": result_obj.get("score") if result_obj else None,
                "opp_score": opp.get("score") if opp else None,
                "winner": result_obj.get("winner") if result_obj else None,
                "opp_name": opp.get("team", {}).get("displayName") if opp else None,
            })
        return sorted(games, key=lambda g: g["date"])
    except Exception as e:
        print(f"[fetch_context] Schedule parse error for {team_id}: {e}", file=sys.stderr)
        return None


def _find_team_record(team_name: str, records: list) -> dict | None:
    """Find team record by fuzzy name match."""
    if not records:
        return None
    normalized = _normalize_team_name(team_name)
    for rec in records:
        if normalized in _normalize_team_name(rec.get("team_name", "")):
            return rec
        if normalized in _normalize_team_name(rec.get("team_abbr", "")):
            return rec
    # Partial match fallback
    for rec in records:
        rec_name = _normalize_team_name(rec.get("team_name", ""))
        # Check if any word in team_name matches
        for word in normalized.split():
            if len(word) > 3 and word in rec_name:
                return rec
    return None


def _find_scoreboard_event(home: str, away: str, events: list) -> dict | None:
    """Find scoreboard event matching this game."""
    home_norm = _normalize_team_name(home)
    away_norm = _normalize_team_name(away)
    for event in events:
        evt_home = _normalize_team_name(event.get("home_team", ""))
        evt_away = _normalize_team_name(event.get("away_team", ""))
        if home_norm in evt_home or evt_home in home_norm:
            if away_norm in evt_away or evt_away in away_norm:
                return event
    return None


def _normalize_team_name(name: str) -> str:
    """Lowercase, remove common suffixes for matching."""
    return name.lower().strip()


if __name__ == "__main__":
    sport = sys.argv[1] if len(sys.argv) > 1 else "nba"
    fake_games = [{"id": "test1", "home_team": "Los Angeles Lakers", "away_team": "Boston Celtics"}]
    ctx = fetch_context(sport, fake_games)
    print(json.dumps(list(ctx.values())[:1], indent=2, default=str))
