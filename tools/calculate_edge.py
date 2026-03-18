"""
calculate_edge.py — Statistician agent.
Sport-agnostic edge calculation with vig removal and Kalshi cross-validation.
Receives SME output + odds object. Returns edge result or None if no edge.
"""

import sys
from agent_utils import american_to_implied, remove_vig, clamp

EDGE_THRESHOLD = 0.10
KALSHI_ALIGNMENT_THRESHOLD = 0.05
# Minimum vig-adjusted implied probability for a signal to fire.
# Filters out extreme underdogs (+300 or longer) where the model's
# probability ceiling (~83%) creates false edges against heavily
# priced favorites (-400 and beyond). Market pricing on extreme
# mismatches is almost always correct.
MIN_SIGNAL_IMPLIED = 0.25


def calculate_edge(
    sme_result: dict,
    game: dict,
    kalshi_match: dict = None,
) -> dict | None:
    """
    Calculate edge for a game given SME probability estimate and book odds.

    Args:
        sme_result: Output from an SME agent {probability, confidence, ...}
        game: Normalized game object from fetch_odds {home_team, away_team, odds, ...}
        kalshi_match: Kalshi match result for this game (or None).

    Returns:
        Edge result dict if edge >= 10%, else None.
        Returns None if sme_result.probability is None (stub agents).
    """
    our_prob = sme_result.get("probability")
    if our_prob is None:
        return None  # Stub agent — skip

    home_team = game.get("home_team", "")
    away_team = game.get("away_team", "")
    odds_by_book = game.get("odds", {})

    best_edge = None
    best_result = None

    for book, odds in odds_by_book.items():
        home_odds = odds.get("home")
        away_odds = odds.get("away")

        if home_odds is None or away_odds is None:
            continue

        # Convert to implied probabilities
        implied_home_raw = american_to_implied(home_odds)
        implied_away_raw = american_to_implied(away_odds)

        # Remove vig
        implied_home, implied_away = remove_vig(implied_home_raw, implied_away_raw)

        # Calculate edge for home and away
        edge_home = our_prob - implied_home
        edge_away = (1.0 - our_prob) - implied_away

        # Find the strongest edge
        if abs(edge_home) >= abs(edge_away):
            candidate_edge = edge_home
            candidate_team = home_team
            candidate_implied = implied_home
            candidate_odds = home_odds
            candidate_rec = f"{home_team} ML"
        else:
            candidate_edge = edge_away
            candidate_team = away_team
            candidate_implied = implied_away
            candidate_odds = away_odds
            candidate_rec = f"{away_team} ML"

        if candidate_edge < EDGE_THRESHOLD:
            continue

        # Filter extreme underdogs — model doesn't have enough resolution
        # to reliably price teams the market has at +300 or longer.
        if candidate_implied < MIN_SIGNAL_IMPLIED:
            continue

        # Kalshi cross-validation
        kalshi_prob = None
        kalshi_alignment = "no_match"
        if kalshi_match:
            kalshi_prob = kalshi_match.get("kalshi_probability")
            if kalshi_prob is not None:
                # Align to same team (home)
                if candidate_team == away_team:
                    kalshi_comp = 1.0 - kalshi_prob
                else:
                    kalshi_comp = kalshi_prob
                gap = abs(our_prob - kalshi_comp)
                if gap <= KALSHI_ALIGNMENT_THRESHOLD:
                    kalshi_alignment = "confirms"
                else:
                    kalshi_alignment = "contradicts"

        result = {
            "sport": game.get("sport_key", "").split("_")[0].upper(),
            "game": f"{away_team} @ {home_team}",
            "commence_time": game.get("commence_time", ""),
            "book": _format_book(book),
            "recommendation": candidate_rec,
            "our_probability": round(our_prob if candidate_team == home_team else 1.0 - our_prob, 4),
            "implied_probability": round(candidate_implied, 4),
            "edge": round(candidate_edge, 4),
            "confidence": sme_result.get("confidence", "normal"),
            "missing_factors": sme_result.get("missing_factors", []),
            "sme_reasoning": sme_result.get("sme_reasoning", ""),
            "factor_deltas": sme_result.get("factor_deltas", {}),
            "kalshi_probability": round(kalshi_prob, 4) if kalshi_prob is not None else None,
            "kalshi_match": kalshi_prob is not None,
            "kalshi_alignment": kalshi_alignment,
            "home_odds": home_odds,
            "away_odds": away_odds,
            "game_id": game.get("id", ""),
        }

        if best_edge is None or candidate_edge > best_edge:
            best_edge = candidate_edge
            best_result = result

    return best_result


def _format_book(book_key: str) -> str:
    """Format bookmaker key to display name."""
    mapping = {
        "draftkings": "DraftKings",
        "fanduel": "FanDuel",
    }
    return mapping.get(book_key.lower(), book_key.title())


def edge_color(edge: float) -> str:
    """Return color category for edge value."""
    if edge >= 0.20:
        return "green"
    elif edge >= 0.15:
        return "orange"
    elif edge >= 0.10:
        return "yellow"
    return "none"


if __name__ == "__main__":
    # Quick test
    test_sme = {
        "probability": 0.62,
        "confidence": "normal",
        "missing_factors": [],
        "sme_reasoning": "Test",
    }
    test_game = {
        "id": "test1",
        "sport_key": "basketball_nba",
        "home_team": "Lakers",
        "away_team": "Celtics",
        "commence_time": "2026-03-11T19:00:00Z",
        "odds": {
            "draftkings": {"home": -110, "away": -110},
        }
    }
    result = calculate_edge(test_sme, test_game)
    import json
    print(json.dumps(result, indent=2))
