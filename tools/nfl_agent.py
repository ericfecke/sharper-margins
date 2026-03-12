"""
nfl_agent.py — NFL SME Agent.
Full deterministic probability model. High variance sport — outputs cluster 0.35–0.70.
No LLM calls, no API calls.
"""

from agent_utils import (
    adjusted_winrate, clamp, parse_stat,
    recent_form_winrate, days_since_last_game, had_bye_week, injury_score
)

NFL_INJURY_WEIGHTS = {
    "QB": 0.080,
    "WR": 0.020, "RB": 0.020, "TE": 0.020, "OL": 0.020, "OT": 0.020, "OG": 0.020, "C": 0.020,
    "DE": 0.015, "CB": 0.015, "LB": 0.015, "S": 0.015, "DT": 0.015,
}
DEFAULT_NFL_INJURY_WEIGHT = 0.010
FULL_CONFIDENCE_GAMES = 10

# NFL division membership for divisional compression factor
NFL_DIVISIONS = {
    "AFC East": ["Buffalo Bills", "Miami Dolphins", "New England Patriots", "New York Jets"],
    "AFC North": ["Baltimore Ravens", "Cincinnati Bengals", "Cleveland Browns", "Pittsburgh Steelers"],
    "AFC South": ["Houston Texans", "Indianapolis Colts", "Jacksonville Jaguars", "Tennessee Titans"],
    "AFC West": ["Denver Broncos", "Kansas City Chiefs", "Las Vegas Raiders", "Los Angeles Chargers"],
    "NFC East": ["Dallas Cowboys", "New York Giants", "Philadelphia Eagles", "Washington Commanders"],
    "NFC North": ["Chicago Bears", "Detroit Lions", "Green Bay Packers", "Minnesota Vikings"],
    "NFC South": ["Atlanta Falcons", "Carolina Panthers", "New Orleans Saints", "Tampa Bay Buccaneers"],
    "NFC West": ["Arizona Cardinals", "Los Angeles Rams", "San Francisco 49ers", "Seattle Seahawks"],
}

# Build reverse lookup: team name → division
TEAM_DIVISION = {}
for div, teams in NFL_DIVISIONS.items():
    for team in teams:
        TEAM_DIVISION[team] = div


def same_division(team_a: str, team_b: str) -> bool:
    """Check if two teams are in the same NFL division."""
    div_a = TEAM_DIVISION.get(team_a)
    div_b = TEAM_DIVISION.get(team_b)
    if div_a and div_b:
        return div_a == div_b
    # Fuzzy: check if any division name appears in team name
    for div, teams in NFL_DIVISIONS.items():
        in_a = any(t in team_a or team_a in t for t in teams)
        in_b = any(t in team_b or team_b in t for t in teams)
        if in_a and in_b:
            return True
    return False


def run(context: dict) -> dict:
    """
    Run NFL probability model for a single game.

    Returns:
        {
            "probability": float (home team win probability),
            "confidence": "normal" | "low",
            "missing_factors": list[str],
            "sme_reasoning": str,
            "qb_injury_flag": bool,
        }
    """
    missing_factors = []
    deltas = {}
    qb_injury_flag = False

    home_team = context.get("home_team", "")
    away_team = context.get("away_team", "")
    home_rec = context.get("home_record") or {}
    away_rec = context.get("away_record") or {}
    home_stats = context.get("home_stats") or {}
    away_stats = context.get("away_stats") or {}
    home_sched = context.get("home_schedule") or []
    away_sched = context.get("away_schedule") or []
    home_injuries = context.get("home_injuries") or []
    away_injuries = context.get("away_injuries") or []
    neutral_site = context.get("neutral_site", False)
    scoreboard = context.get("scoreboard_event") or {}

    # --- Base: Regressed win rate ---
    home_wins = home_rec.get("wins")
    home_games = home_rec.get("games_played")
    away_wins = away_rec.get("wins")
    away_games = away_rec.get("games_played")

    home_wr = adjusted_winrate(home_wins, home_games, FULL_CONFIDENCE_GAMES)
    away_wr = adjusted_winrate(away_wins, away_games, FULL_CONFIDENCE_GAMES)

    if home_wins is None:
        missing_factors.append("home_standings")
    if away_wins is None:
        missing_factors.append("away_standings")

    # --- Factor 1: Win rate differential ---
    wr_diff = home_wr - away_wr
    delta_wr = clamp(wr_diff * 0.4, -0.10, +0.10)
    deltas["win_rate_diff"] = delta_wr

    # --- Factor 2: Home field ---
    if not neutral_site:
        delta_home = +0.04
    else:
        delta_home = 0.0
    deltas["home_field"] = delta_home

    # --- Factor 3: Rest / bye week ---
    home_had_bye = had_bye_week(home_sched)
    away_had_bye = had_bye_week(away_sched)
    home_rest = days_since_last_game(home_sched)
    away_rest = days_since_last_game(away_sched)

    if home_had_bye and not away_had_bye:
        delta_rest = +0.04
    elif away_had_bye and not home_had_bye:
        delta_rest = -0.04
    elif home_rest is not None and away_rest is not None:
        rest_diff = home_rest - away_rest
        delta_rest = clamp(rest_diff * 0.008, -0.02, +0.02)
    else:
        delta_rest = 0.0
        missing_factors.append("rest_data")
    deltas["rest_bye"] = delta_rest

    # --- Factor 4: Recent form (last 5) ---
    home_form = recent_form_winrate(home_sched, n=5)
    away_form = recent_form_winrate(away_sched, n=5)
    if home_form is None or away_form is None:
        delta_form = 0.0
        missing_factors.append("recent_form")
    else:
        form_diff = home_form - away_form
        delta_form = clamp(form_diff * 0.15, -0.05, +0.05)
    deltas["recent_form"] = delta_form

    # --- Factor 5: Injury impact (QB-weighted) ---
    # Check for QB out
    for inj in (home_injuries or []):
        if inj.get("position", "").upper() == "QB":
            status = inj.get("status", "").upper()
            if "OUT" in status or "IR" in status:
                qb_injury_flag = True
                break

    injuries_available = context.get("injuries_data_available", False)
    home_inj = _nfl_injury_score(home_injuries or [])
    away_inj = _nfl_injury_score(away_injuries or [])
    net_inj = home_inj - away_inj
    delta_injury = clamp(net_inj, -0.10, +0.10)
    if not injuries_available:
        missing_factors.append("injury_data")
    deltas["injuries"] = delta_injury

    # --- Factor 6: Scoring margin differential ---
    home_ppg = parse_stat(home_stats, "avgPoints", "pointsPerGame", "scoring")
    home_papg = parse_stat(home_stats, "avgPointsAllowed", "pointsAllowedPerGame", "opponentPointsPerGame")
    away_ppg = parse_stat(away_stats, "avgPoints", "pointsPerGame", "scoring")
    away_papg = parse_stat(away_stats, "avgPointsAllowed", "pointsAllowedPerGame", "opponentPointsPerGame")

    if all(v is not None for v in [home_ppg, home_papg, away_ppg, away_papg]):
        margin_diff = (home_ppg - home_papg) - (away_ppg - away_papg)
        delta_margin = clamp(margin_diff * 0.007, -0.05, +0.05)
    else:
        delta_margin = 0.0
        missing_factors.append("scoring_margin")
    deltas["scoring_margin"] = delta_margin

    # --- Factor 7: Weather compression ---
    weather = scoreboard.get("weather") or {}
    indoor = scoreboard.get("indoor", False)
    running_prob = 0.500 + sum(deltas.values())

    if not indoor and weather:
        wind_mph = weather.get("windSpeed", 0) or 0
        precipitation = bool(weather.get("precipitation") or weather.get("isPrecipitation"))
        temp_f = weather.get("temperature", 70) or 70

        compression = 0.0
        if wind_mph > 20:
            compression += 0.015
        if wind_mph > 30:
            compression += 0.015
        if precipitation:
            compression += 0.015
        if temp_f < 32:
            compression += 0.010

        if running_prob > 0.500:
            delta_weather = -compression
        else:
            delta_weather = +compression
    else:
        delta_weather = 0.0
    deltas["weather"] = delta_weather

    # --- Factor 8: Divisional compression ---
    running_prob2 = 0.500 + sum(deltas.values())
    if same_division(home_team, away_team):
        if running_prob2 > 0.500:
            delta_div = -0.02
        else:
            delta_div = +0.02
    else:
        delta_div = 0.0
    deltas["divisional"] = delta_div

    # --- Factor 9: Head-to-head ---
    h2h_data = context.get("h2h")
    if h2h_data and h2h_data.get("games", 0) >= 3:
        h2h_wr = h2h_data.get("home_win_rate", 0.500)
        delta_h2h = clamp((h2h_wr - 0.500) * 0.06, -0.02, +0.02)
    else:
        delta_h2h = 0.0
    deltas["h2h"] = delta_h2h

    # --- Final ---
    probability = clamp(0.500 + sum(deltas.values()), 0.10, 0.90)
    confidence = "low" if missing_factors else "normal"

    reasoning_parts = []
    if abs(delta_wr) >= 0.04:
        reasoning_parts.append(f"Win rate edge: {'home' if delta_wr > 0 else 'away'} ({home_wr:.2%} vs {away_wr:.2%})")
    if home_had_bye:
        reasoning_parts.append("Home team coming off bye week")
    elif away_had_bye:
        reasoning_parts.append("Away team coming off bye week")
    if qb_injury_flag:
        reasoning_parts.append("HOME QB OUT — significant drag applied")
    if delta_weather != 0:
        reasoning_parts.append(f"Weather compression applied ({delta_weather:+.3f})")
    if same_division(home_team, away_team):
        reasoning_parts.append("Divisional game — spread compressed")
    if not reasoning_parts:
        reasoning_parts.append("Teams evenly matched across modeled factors")

    return {
        "probability": round(probability, 4),
        "confidence": confidence,
        "missing_factors": missing_factors,
        "sme_reasoning": "; ".join(reasoning_parts),
        "qb_injury_flag": qb_injury_flag,
        "factor_deltas": {k: round(v, 4) for k, v in deltas.items()},
    }


def _nfl_injury_score(injuries: list) -> float:
    """NFL-specific injury scoring with QB-heavy weighting."""
    score = 0.0
    for inj in injuries:
        pos = (inj.get("position") or "").upper()
        status = (inj.get("status") or "").upper()
        weight = NFL_INJURY_WEIGHTS.get(pos, DEFAULT_NFL_INJURY_WEIGHT)
        if "OUT" in status or "IR" in status or "SUSPENDED" in status:
            score -= weight
        elif "QUESTIONABLE" in status or "DOUBTFUL" in status:
            score -= weight * 0.5
    return score
