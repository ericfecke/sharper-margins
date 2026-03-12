"""
nba_agent.py — NBA SME Agent.
Full deterministic probability model. No LLM calls, no API calls.
Receives pre-built context object from fetch_context.py.
"""

from agent_utils import (
    adjusted_winrate, clamp, parse_stat,
    recent_form_winrate, days_since_last_game, injury_score
)

NBA_INJURY_WEIGHTS = {
    "PG": 0.025, "SG": 0.025, "SF": 0.025,
    "PF": 0.020, "C": 0.020,
}
DEFAULT_NBA_INJURY_WEIGHT = 0.015
FULL_CONFIDENCE_GAMES = 40


def run(context: dict) -> dict:
    """
    Run NBA probability model for a single game.

    Args:
        context: Game context dict from fetch_context.py.

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

    home_rec = context.get("home_record") or {}
    away_rec = context.get("away_record") or {}
    home_stats = context.get("home_stats") or {}
    away_stats = context.get("away_stats") or {}
    home_sched = context.get("home_schedule") or []
    away_sched = context.get("away_schedule") or []
    home_injuries = context.get("home_injuries") or []
    away_injuries = context.get("away_injuries") or []
    neutral_site = context.get("neutral_site", False)

    # --- Base: Regressed win rate ---
    home_wins = home_rec.get("wins")
    home_games = home_rec.get("games_played")
    away_wins = away_rec.get("wins")
    away_games = away_rec.get("games_played")

    home_wr = adjusted_winrate(home_wins, home_games, FULL_CONFIDENCE_GAMES)
    away_wr = adjusted_winrate(away_wins, away_games, FULL_CONFIDENCE_GAMES)

    if home_wins is None or home_games is None:
        missing_factors.append("home_standings")
    if away_wins is None or away_games is None:
        missing_factors.append("away_standings")

    base = 0.500 + ((home_wr - away_wr) * 0.5)
    base = clamp(base, 0.30, 0.70)

    # --- Factor 1: Win rate differential ---
    wr_diff = home_wr - away_wr
    delta_wr = clamp(wr_diff * 0.4, -0.10, +0.10)
    deltas["win_rate_diff"] = delta_wr

    # --- Factor 2: Home court ---
    if not neutral_site:
        delta_home = +0.06
    else:
        delta_home = 0.0
    deltas["home_court"] = delta_home

    # --- Factor 3: Rest differential ---
    home_rest = days_since_last_game(home_sched)
    away_rest = days_since_last_game(away_sched)
    if home_rest is None or away_rest is None:
        delta_rest = 0.0
        missing_factors.append("rest_data")
    else:
        rest_diff = home_rest - away_rest
        delta_rest = clamp(rest_diff * 0.015, -0.04, +0.04)
    deltas["rest"] = delta_rest

    # --- Factor 4: Recent form (last 10) ---
    home_form = recent_form_winrate(home_sched, n=10)
    away_form = recent_form_winrate(away_sched, n=10)
    if home_form is None or away_form is None:
        delta_form = 0.0
        missing_factors.append("recent_form")
    else:
        form_diff = home_form - away_form
        delta_form = clamp(form_diff * 0.15, -0.06, +0.06)
    deltas["recent_form"] = delta_form

    # --- Factor 5: Injury impact ---
    injuries_available = context.get("injuries_data_available", False)
    home_inj_score = injury_score(home_injuries or [], NBA_INJURY_WEIGHTS)
    away_inj_score = injury_score(away_injuries or [], NBA_INJURY_WEIGHTS)
    net_inj = home_inj_score - away_inj_score
    delta_injury = clamp(net_inj, -0.08, 0.0)
    if not injuries_available:
        missing_factors.append("injury_data")
    deltas["injuries"] = delta_injury

    # --- Factor 6: Scoring average differential (proxy for net rating) ---
    # ESPN provides avgPoints (PPG); use differential as scoring edge signal
    home_ppg = parse_stat(home_stats, "avgPoints", "offensiveRating", "pointsPerGame")
    away_ppg = parse_stat(away_stats, "avgPoints", "offensiveRating", "pointsPerGame")

    if home_ppg is not None and away_ppg is not None:
        ppg_diff = home_ppg - away_ppg
        delta_rating = clamp(ppg_diff * 0.006, -0.05, +0.05)
    else:
        delta_rating = 0.0
        missing_factors.append("scoring_stats")
    deltas["net_rating"] = delta_rating

    # --- Factor 7: Head-to-head (simplified: use record data if available) ---
    # H2H requires historical season data — mark as missing if not in context
    h2h_data = context.get("h2h")
    if h2h_data and h2h_data.get("games", 0) >= 2:
        h2h_wr = h2h_data.get("home_win_rate", 0.500)
        delta_h2h = clamp((h2h_wr - 0.500) * 0.08, -0.02, +0.02)
    else:
        delta_h2h = 0.0
        # H2H missing is not flagged as low confidence — small factor
    deltas["h2h"] = delta_h2h

    # --- Final probability ---
    total_delta = sum(deltas.values())
    probability = clamp(base + total_delta - delta_wr, 0.10, 0.90)
    # Note: delta_wr already folded into base; add it back correctly
    # Recalculate: base is 0.5 + half the win rate spread; deltas include wr delta
    # Let's use a clean formula: start from 0.5, add all deltas
    probability = clamp(0.500 + sum(deltas.values()), 0.10, 0.90)

    confidence = "low" if missing_factors else "normal"

    # Build reasoning summary
    reasoning_parts = []
    if abs(delta_wr) >= 0.04:
        reasoning_parts.append(f"Win rate edge: {'home' if delta_wr > 0 else 'away'} favored ({home_wr:.2%} vs {away_wr:.2%})")
    if not neutral_site:
        reasoning_parts.append("Home court advantage applied")
    if abs(delta_form) >= 0.02:
        reasoning_parts.append(f"Recent form {'favors home' if delta_form > 0 else 'favors away'}")
    if delta_injury < -0.02:
        reasoning_parts.append(f"Injury drag: {delta_injury:.3f}")
    if abs(delta_rating) >= 0.02:
        reasoning_parts.append(f"Net rating advantage: {'home' if delta_rating > 0 else 'away'}")
    if not reasoning_parts:
        reasoning_parts.append("Teams evenly matched across factors")

    sme_reasoning = "; ".join(reasoning_parts)

    return {
        "probability": round(probability, 4),
        "confidence": confidence,
        "missing_factors": missing_factors,
        "sme_reasoning": sme_reasoning,
        "factor_deltas": {k: round(v, 4) for k, v in deltas.items()},
    }
