"""
mlb_agent.py — MLB SME Agent.
Full deterministic probability model. Pitching-first: blended 50/50 with team win rate.
No LLM calls, no API calls.
"""

from agent_utils import (
    adjusted_winrate, clamp, parse_stat,
    recent_form_winrate, injury_score
)

MLB_INJURY_WEIGHTS = {
    "SP": 0.050, "P": 0.030,
    "C": 0.015, "1B": 0.012, "2B": 0.012, "3B": 0.012, "SS": 0.015,
    "LF": 0.010, "CF": 0.010, "RF": 0.010, "DH": 0.008,
}
DEFAULT_MLB_INJURY_WEIGHT = 0.008
FULL_CONFIDENCE_GAMES = 50

# Park factors — static dict maintained for all 30 parks
# Positive = hitter friendly (home team benefits), Negative = pitcher friendly
PARK_FACTORS = {
    "COL": +0.025,   # Coors Field — extreme hitter
    "CIN": +0.015,   # Great American Ballpark
    "TEX": +0.010,   # Globe Life Field
    "HOU": +0.008,   # Minute Maid Park
    "MIL": +0.007,   # American Family Field
    "PHI": +0.006,   # Citizens Bank Park
    "BOS": +0.005,   # Fenway Park
    "CHC": +0.004,   # Wrigley Field
    "BAL": +0.003,   # Camden Yards
    "TOR": +0.002,   # Rogers Centre
    "KC": +0.002,    # Kauffman Stadium
    "MIN": +0.001,   # Target Field
    "CWS": 0.000,    # Guaranteed Rate Field
    "DET": 0.000,    # Comerica Park
    "PIT": 0.000,    # PNC Park
    "STL": -0.001,   # Busch Stadium
    "LAD": -0.002,   # Dodger Stadium
    "MIA": -0.003,   # loanDepot park
    "NYY": -0.003,   # Yankee Stadium
    "WSH": -0.004,   # Nationals Park
    "TB": -0.004,    # Tropicana Field
    "CLE": -0.005,   # Progressive Field
    "SEA": -0.006,   # T-Mobile Park
    "LAA": -0.007,   # Angel Stadium
    "ATL": -0.007,   # Truist Park
    "SD": -0.008,    # Petco Park
    "ARI": -0.009,   # Chase Field
    "CHW": 0.000,    # Same as CWS
    "OAK": -0.010,   # Oakland Coliseum / athletics
    "NYM": -0.015,   # Citi Field
    "SF": -0.020,    # Oracle Park — extreme pitcher
}


def run(context: dict) -> dict:
    """
    Run MLB probability model for a single game.
    Structure: pitching-first base, then contextual adjustments.

    Returns:
        {
            "probability": float (home team win probability),
            "confidence": "normal" | "low",
            "missing_factors": list[str],
            "sme_reasoning": str,
        }
    """
    missing_factors = []
    deltas = {}

    home_team = context.get("home_team", "")
    home_rec = context.get("home_record") or {}
    away_rec = context.get("away_record") or {}
    home_stats = context.get("home_stats") or {}
    away_stats = context.get("away_stats") or {}
    home_sched = context.get("home_schedule") or []
    away_sched = context.get("away_schedule") or []
    home_injuries = context.get("home_injuries") or []
    away_injuries = context.get("away_injuries") or []
    neutral_site = context.get("neutral_site", False)

    # Starting pitcher data
    home_starter = context.get("home_starter") or {}
    away_starter = context.get("away_starter") or {}

    # --- Base construction: blended pitching + team win rate ---
    home_wins = home_rec.get("wins")
    home_games = home_rec.get("games_played")
    away_wins = away_rec.get("wins")
    away_games = away_rec.get("games_played")

    if home_wins is None:
        missing_factors.append("home_standings")
    if away_wins is None:
        missing_factors.append("away_standings")

    team_base = adjusted_winrate(home_wins, home_games, FULL_CONFIDENCE_GAMES)

    # Pitching delta
    home_era = home_starter.get("era") or parse_stat(home_stats, "ERA", "era")
    home_whip = home_starter.get("whip") or parse_stat(home_stats, "WHIP", "whip")
    away_era = away_starter.get("era") or parse_stat(away_stats, "ERA", "era")
    away_whip = away_starter.get("whip") or parse_stat(away_stats, "WHIP", "whip")

    if all(v is not None for v in [home_era, home_whip, away_era, away_whip]):
        era_diff = away_era - home_era      # positive = home pitcher has better ERA
        whip_diff = away_whip - home_whip  # positive = home pitcher has better WHIP
        pitching_score = (era_diff * 0.06) + (whip_diff * 0.04)
        pitching_delta = clamp(pitching_score, -0.15, +0.15)
    else:
        pitching_delta = 0.0
        missing_factors.append("starting_pitcher")

    pitching_base = 0.500 + pitching_delta
    base = (team_base * 0.50) + (pitching_base * 0.50)

    # --- Factor 1: Run differential ---
    home_runs = parse_stat(home_stats, "runsScored", "runs", "runsScoredPerGame")
    home_runs_allowed = parse_stat(home_stats, "runsAllowed", "earnedRunsAllowed")
    away_runs = parse_stat(away_stats, "runsScored", "runs", "runsScoredPerGame")
    away_runs_allowed = parse_stat(away_stats, "runsAllowed", "earnedRunsAllowed")

    if all(v is not None for v in [home_runs, home_runs_allowed, away_runs, away_runs_allowed]):
        home_gp = home_games or 1
        away_gp = away_games or 1
        rd_home = (home_runs - home_runs_allowed) / home_gp
        rd_away = (away_runs - away_runs_allowed) / away_gp
        delta_rd = clamp((rd_home - rd_away) * 0.025, -0.06, +0.06)
    else:
        delta_rd = 0.0
        missing_factors.append("run_differential")
    deltas["run_differential"] = delta_rd

    # --- Factor 2: Recent form (last 10) ---
    home_form = recent_form_winrate(home_sched, n=10)
    away_form = recent_form_winrate(away_sched, n=10)
    if home_form is None or away_form is None:
        delta_form = 0.0
        missing_factors.append("recent_form")
    else:
        delta_form = clamp((home_form - away_form) * 0.15, -0.05, +0.05)
    deltas["recent_form"] = delta_form

    # --- Factor 3: Injury impact ---
    home_inj = injury_score(home_injuries, MLB_INJURY_WEIGHTS)
    away_inj = injury_score(away_injuries, MLB_INJURY_WEIGHTS)
    net_inj = home_inj - away_inj
    delta_injury = clamp(net_inj, -0.05, +0.05)
    if not home_injuries and not away_injuries:
        missing_factors.append("injury_data")
    deltas["injuries"] = delta_injury

    # --- Factor 4: Bullpen fatigue (relief IP in last 48h) ---
    home_bullpen_ip = context.get("home_bullpen_ip_48h", 0) or 0
    away_bullpen_ip = context.get("away_bullpen_ip_48h", 0) or 0

    def _bullpen_penalty(ip: float) -> float:
        if ip > 8:
            return -0.02
        elif ip > 5:
            return -0.01
        return 0.0

    delta_bullpen = clamp(_bullpen_penalty(home_bullpen_ip) - _bullpen_penalty(away_bullpen_ip), -0.03, +0.03)
    deltas["bullpen_fatigue"] = delta_bullpen

    # --- Factor 5: Home field ---
    delta_home = +0.03 if not neutral_site else 0.0
    deltas["home_field"] = delta_home

    # --- Factor 6: Park factor ---
    # Find home team abbreviation
    home_abbr = _find_team_abbr(home_team, home_rec)
    park_val = PARK_FACTORS.get(home_abbr, 0.0)
    deltas["park_factor"] = park_val

    # --- Factor 7: Head-to-head ---
    h2h_data = context.get("h2h")
    if h2h_data and h2h_data.get("games", 0) >= 4:
        h2h_wr = h2h_data.get("home_win_rate", 0.500)
        delta_h2h = clamp((h2h_wr - 0.500) * 0.06, -0.02, +0.02)
    else:
        delta_h2h = 0.0
    deltas["h2h"] = delta_h2h

    # --- Final ---
    probability = clamp(base + sum(deltas.values()), 0.10, 0.90)
    confidence = "low" if missing_factors else "normal"

    reasoning_parts = []
    if abs(pitching_delta) >= 0.05:
        stronger = "home" if pitching_delta > 0 else "away"
        reasoning_parts.append(f"Starting pitcher advantage: {stronger} (ERA/WHIP differential)")
    if "starting_pitcher" in missing_factors:
        reasoning_parts.append("Starting pitchers unknown — model reduced to team stats")
    if abs(delta_rd) >= 0.03:
        reasoning_parts.append(f"Run differential edge: {'home' if delta_rd > 0 else 'away'}")
    if abs(park_val) >= 0.010:
        friendly = "hitter" if park_val > 0 else "pitcher"
        reasoning_parts.append(f"Park factor: {home_team} plays in {friendly}-friendly venue")
    if not reasoning_parts:
        reasoning_parts.append("Balanced matchup — no dominant edge identified")

    return {
        "probability": round(probability, 4),
        "confidence": confidence,
        "missing_factors": missing_factors,
        "sme_reasoning": "; ".join(reasoning_parts),
        "factor_deltas": {k: round(v, 4) for k, v in deltas.items()},
        "pitching_delta": round(pitching_delta, 4),
    }


def _find_team_abbr(team_name: str, record: dict) -> str:
    """Find team abbreviation from record or name."""
    abbr = record.get("team_abbr", "")
    if abbr:
        return abbr.upper()
    # Try to match from park factors keys
    name_upper = team_name.upper()
    for key in PARK_FACTORS:
        if key in name_upper:
            return key
    return ""
