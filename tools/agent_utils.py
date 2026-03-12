"""
agent_utils.py — Shared utilities used by all SME agents.
Pure math functions, no I/O, no API calls.
"""

from datetime import date, datetime


def adjusted_winrate(wins: int | None, games: int | None, full_confidence_at: int) -> float:
    """
    Regress win rate toward 0.500 based on sample size.

    Args:
        wins: Number of wins.
        games: Total games played.
        full_confidence_at: Sample size at which we fully trust the raw rate.

    Returns:
        Regressed win rate between 0.0 and 1.0.
    """
    if wins is None or games is None or games == 0:
        return 0.500
    raw = wins / games
    confidence = min(games / full_confidence_at, 1.0)
    return (confidence * raw) + ((1 - confidence) * 0.500)


def clamp(value: float, low: float, high: float) -> float:
    """Clamp value to [low, high]."""
    return max(low, min(high, value))


def american_to_implied(odds: int | float) -> float:
    """Convert American odds to implied probability."""
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return abs(odds) / (abs(odds) + 100)


def remove_vig(implied_a: float, implied_b: float) -> tuple[float, float]:
    """Remove bookmaker vig from implied probabilities."""
    total = implied_a + implied_b
    if total == 0:
        return 0.5, 0.5
    return implied_a / total, implied_b / total


def recent_form_winrate(schedule: list | None, n: int = 10) -> float | None:
    """
    Calculate win rate from last n completed games.

    Args:
        schedule: List of game dicts with 'winner' bool and 'date'.
        n: Number of recent games to consider.

    Returns:
        Win rate float or None if insufficient data.
    """
    if not schedule:
        return None
    completed = [g for g in schedule if g.get("winner") is not None]
    if not completed:
        return None
    recent = completed[-n:]
    if len(recent) < 3:
        return None
    wins = sum(1 for g in recent if g.get("winner") is True)
    return wins / len(recent)


def days_since_last_game(schedule: list | None, today: date = None) -> int | None:
    """
    Calculate days since the team's most recent completed game.

    Args:
        schedule: Sorted list of game dicts with 'date' (ISO string) and 'winner'.
        today: Reference date.

    Returns:
        Days since last game, or None if no completed games found.
    """
    if today is None:
        today = date.today()
    if not schedule:
        return None
    completed = [g for g in schedule if g.get("winner") is not None]
    if not completed:
        return None
    last_game_str = completed[-1]["date"]
    try:
        last_game_date = date.fromisoformat(last_game_str[:10])
        return (today - last_game_date).days
    except Exception:
        return None


def had_bye_week(schedule: list | None, today: date = None, bye_threshold_days: int = 14) -> bool:
    """Check if team had a bye (no game in last N days)."""
    days = days_since_last_game(schedule, today)
    if days is None:
        return False
    return days >= bye_threshold_days


def parse_stat(stats: dict | None, *keys) -> float | None:
    """Try multiple stat key names, return first found value or None."""
    if not stats:
        return None
    for key in keys:
        val = stats.get(key)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                continue
    return None


def injury_score(injuries: list | None, position_weights: dict) -> float:
    """
    Calculate injury penalty score for a team.

    Args:
        injuries: List of injury dicts with 'position', 'status'.
        position_weights: Dict mapping position abbr to penalty float (OUT weight).

    Returns:
        Negative float representing injury drag. More negative = more impactful injuries.
    """
    if not injuries:
        return 0.0
    score = 0.0
    for inj in injuries:
        pos = (inj.get("position") or "").upper()
        status = (inj.get("status") or "").upper()
        weight = position_weights.get(pos, 0.005)
        if "OUT" in status or "IR" in status or "SUSPENDED" in status:
            score -= weight
        elif "QUESTIONABLE" in status or "DOUBTFUL" in status:
            score -= weight * 0.5
    return score
