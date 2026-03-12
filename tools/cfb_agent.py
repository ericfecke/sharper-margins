"""
cfb_agent.py — College Football SME Agent.
Full deterministic probability model. SOS-adjusted win rate base.
No LLM calls, no API calls.
"""

from agent_utils import (
    adjusted_winrate, clamp, parse_stat,
    recent_form_winrate, days_since_last_game, injury_score
)

CFB_INJURY_WEIGHTS = {
    "QB": 0.100,  # Thinner backup depth in CFB
    "WR": 0.020, "RB": 0.020, "TE": 0.020, "OL": 0.020, "OT": 0.020,
    "DE": 0.012, "CB": 0.012, "LB": 0.012, "S": 0.012, "DT": 0.012,
}
DEFAULT_CFB_INJURY_WEIGHT = 0.008
FULL_CONFIDENCE_GAMES = 8

CONFERENCE_TIER = {
    "SEC": 1, "Big Ten": 1,
    "Big 12": 2, "ACC": 2,
    "American Athletic": 3, "American": 3, "Mountain West": 3,
    "Sun Belt": 3, "MAC": 3, "Conference USA": 3, "CUSA": 3,
    "Independents": 2,  # Notre Dame pulls this up
}

# Team timezone for travel penalty (approximate)
TEAM_TIMEZONE = {
    "Pacific": ["UCLA", "USC", "Oregon", "Oregon State", "Washington", "Washington State",
                "Stanford", "California", "San Diego State", "Fresno State", "UNLV",
                "Boise State", "Nevada", "Utah State", "Air Force", "Wyoming",
                "Colorado State", "Hawaii"],
    "Mountain": ["Utah", "Colorado", "Arizona", "Arizona State", "BYU", "New Mexico",
                 "New Mexico State", "Colorado", "TCU"],
    "Central": ["Texas", "Texas A&M", "Oklahoma", "Oklahoma State", "Kansas", "Kansas State",
                "Iowa State", "Missouri", "Arkansas", "LSU", "Ole Miss", "Mississippi State",
                "Alabama", "Auburn", "Vanderbilt", "Tennessee", "Kentucky", "Georgia",
                "Florida", "Miami", "Florida State", "Georgia Tech", "Clemson",
                "South Carolina", "Wake Forest", "North Carolina", "NC State", "Duke",
                "Virginia", "Virginia Tech", "Pittsburgh", "Louisville", "Syracuse",
                "Notre Dame", "Purdue", "Indiana", "Illinois", "Northwestern",
                "Wisconsin", "Minnesota", "Iowa", "Nebraska", "Michigan", "Michigan State",
                "Ohio State", "Penn State", "Maryland", "Rutgers", "Buffalo", "Army",
                "Navy", "Connecticut", "Temple", "SMU", "UCF", "Tulsa", "Tulane",
                "Houston", "Memphis", "Cincinnati", "South Florida"],
    "Eastern": ["Boston College", "UConn"],
}

TEAM_TZ_OFFSET = {}
for tz, teams in TEAM_TIMEZONE.items():
    offset = {"Pacific": 0, "Mountain": 1, "Central": 2, "Eastern": 3}[tz]
    for team in teams:
        TEAM_TZ_OFFSET[team] = offset


def _get_tz_offset(team_name: str) -> int:
    """Get timezone offset index (0=Pacific, 3=Eastern) for a team."""
    for team, offset in TEAM_TZ_OFFSET.items():
        if team.lower() in team_name.lower() or team_name.lower() in team.lower():
            return offset
    return 2  # Default to Central


def _get_conference_tier(team_name: str, stats: dict) -> int:
    """Get conference tier for a team. Default to 3 if unknown."""
    conf = (stats or {}).get("conference", "")
    return CONFERENCE_TIER.get(conf, 3)


def run(context: dict) -> dict:
    """
    Run CFB probability model for a single game.

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

    # --- Base: SOS-adjusted and regressed win rate ---
    home_wins = home_rec.get("wins")
    home_games = home_rec.get("games_played")
    away_wins = away_rec.get("wins")
    away_games = away_rec.get("games_played")

    if home_wins is None:
        missing_factors.append("home_standings")
    if away_wins is None:
        missing_factors.append("away_standings")

    home_wr = adjusted_winrate(home_wins, home_games, FULL_CONFIDENCE_GAMES)
    away_wr = adjusted_winrate(away_wins, away_games, FULL_CONFIDENCE_GAMES)

    # --- Factor 1: Conference tier differential ---
    home_tier = _get_conference_tier(home_team, home_stats)
    away_tier = _get_conference_tier(away_team, away_stats)
    # Higher tier number = weaker conference
    # tier_diff positive = away team in stronger conference (lower tier number)
    tier_diff = home_tier - away_tier  # positive = home in weaker conf
    # If home is in stronger conf (lower tier number), tier_diff < 0 → we want + delta
    delta_conf = clamp(-tier_diff * 0.06, -0.10, +0.10)
    deltas["conference_tier"] = delta_conf

    # --- Factor 2: Win rate differential (on top of conference context) ---
    wr_diff = home_wr - away_wr
    delta_wr = clamp(wr_diff * 0.4, -0.10, +0.10)
    deltas["win_rate_diff"] = delta_wr

    # --- Factor 3: AP Rankings ---
    ap_rank_home = context.get("ap_rank_home")
    ap_rank_away = context.get("ap_rank_away")
    delta_rank = _rank_delta(ap_rank_home, ap_rank_away)
    if ap_rank_home is None and ap_rank_away is None:
        missing_factors.append("ap_rankings")
    deltas["ap_ranking"] = delta_rank

    # --- Factor 4: Home field / neutral site ---
    if neutral_site:
        delta_home = 0.0
    else:
        delta_home = +0.07
    deltas["home_field"] = delta_home

    # --- Factor 5: Injury impact (QB-heavy) ---
    injuries_available = context.get("injuries_data_available", False)
    home_inj_score = _cfb_injury_score(home_injuries or [])
    away_inj_score = _cfb_injury_score(away_injuries or [])
    net_inj = home_inj_score - away_inj_score
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
        delta_margin = clamp(margin_diff * 0.007, -0.07, +0.07)
    else:
        delta_margin = 0.0
        missing_factors.append("scoring_margin")
    deltas["scoring_margin"] = delta_margin

    # --- Factor 7: Recent form (last 5) ---
    home_form = recent_form_winrate(home_sched, n=5)
    away_form = recent_form_winrate(away_sched, n=5)
    if home_form is None or away_form is None:
        delta_form = 0.0
        missing_factors.append("recent_form")
    else:
        delta_form = clamp((home_form - away_form) * 0.15, -0.05, +0.05)
    deltas["recent_form"] = delta_form

    # --- Factor 8: Rest + travel penalty ---
    home_rest = days_since_last_game(home_sched)
    away_rest = days_since_last_game(away_sched)
    if home_rest is None or away_rest is None:
        delta_rest = 0.0
        missing_factors.append("rest_data")
    else:
        rest_diff = home_rest - away_rest
        delta_rest = clamp(rest_diff * 0.008, -0.03, +0.03)

    # Travel penalty: away team crosses 2+ time zones
    away_tz = _get_tz_offset(away_team)
    home_tz = _get_tz_offset(home_team)
    tz_diff = abs(away_tz - home_tz)
    travel_penalty = -0.02 if (not neutral_site and tz_diff >= 2) else 0.0
    # travel penalty hurts away team → home team benefits
    delta_travel = -travel_penalty  # positive for home if penalty applies
    deltas["rest_travel"] = delta_rest + (-travel_penalty)

    # --- Factor 9: Head-to-head ---
    h2h_data = context.get("h2h")
    if h2h_data and h2h_data.get("games", 0) >= 2:
        h2h_wr = h2h_data.get("home_win_rate", 0.500)
        delta_h2h = clamp((h2h_wr - 0.500) * 0.06, -0.02, +0.02)
    else:
        delta_h2h = 0.0
    deltas["h2h"] = delta_h2h

    # --- Final ---
    probability = clamp(0.500 + sum(deltas.values()), 0.10, 0.90)
    confidence = "low" if missing_factors else "normal"

    reasoning_parts = []
    if abs(delta_conf) >= 0.04:
        stronger = "home" if delta_conf > 0 else "away"
        reasoning_parts.append(f"Conference tier edge favors {stronger}")
    if abs(delta_rank) >= 0.03:
        reasoning_parts.append(f"AP ranking differential applied ({delta_rank:+.3f})")
    if not neutral_site:
        reasoning_parts.append("Home field advantage (college: +7%)")
    if delta_injury < -0.03:
        reasoning_parts.append(f"Injury drag: {delta_injury:+.3f}")
    if travel_penalty:
        reasoning_parts.append(f"Away team travel penalty (2+ TZ crossing)")
    if not reasoning_parts:
        reasoning_parts.append("Teams evenly matched across modeled factors")

    return {
        "probability": round(probability, 4),
        "confidence": confidence,
        "missing_factors": missing_factors,
        "sme_reasoning": "; ".join(reasoning_parts),
        "factor_deltas": {k: round(v, 4) for k, v in deltas.items()},
    }


def _rank_delta(rank_home: int | None, rank_away: int | None) -> float:
    """Calculate delta from AP ranking differential."""
    r_home = rank_home if rank_home is not None else 99
    r_away = rank_away if rank_away is not None else 99

    if r_home == 99 and r_away == 99:
        return 0.0
    elif r_home == 99:
        return -0.06
    elif r_away == 99:
        return +0.06
    else:
        rank_diff = r_away - r_home  # positive = home ranked higher
        return clamp(rank_diff * 0.002, -0.06, +0.06)


def _cfb_injury_score(injuries: list) -> float:
    """CFB-specific injury score with heavy QB weighting."""
    score = 0.0
    for inj in injuries:
        pos = (inj.get("position") or "").upper()
        status = (inj.get("status") or "").upper()
        weight = CFB_INJURY_WEIGHTS.get(pos, DEFAULT_CFB_INJURY_WEIGHT)
        if "OUT" in status or "IR" in status:
            score -= weight
        elif "QUESTIONABLE" in status or "DOUBTFUL" in status:
            score -= weight * 0.5
    return score
