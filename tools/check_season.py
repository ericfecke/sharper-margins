"""
check_season.py — Determine which sports are currently in season.
Returns a list of active sport keys based on today's date.
"""

from datetime import date

SEASON_WINDOWS = {
    "nfl":  [(9, 1), (2, 28)],   # Sep–Feb
    "cfb":  [(8, 1), (1, 31)],   # Aug–Jan
    "nba":  [(10, 1), (6, 30)],  # Oct–Jun
    "cbb":  [(11, 1), (4, 30)],  # Nov–Apr
    "mlb":  [(3, 1), (10, 31)],  # Mar–Oct
    "nhl":  [(10, 1), (6, 30)],  # Oct–Jun
    "ufc":  None,                 # Year-round, event-driven
}


def _in_window(today: date, start: tuple, end: tuple) -> bool:
    """Check if today falls in a season window that may wrap across year boundary."""
    start_month, start_day = start
    end_month, end_day = end
    start_date = date(today.year, start_month, start_day)
    end_date = date(today.year, end_month, end_day)

    if start_date <= end_date:
        return start_date <= today <= end_date
    else:
        # Wraps across year boundary (e.g., Sep–Feb)
        return today >= start_date or today <= end_date


def check_season(today: date = None, include_ufc: bool = False) -> list:
    """
    Return list of sport keys active today.

    Args:
        today: Date to check (defaults to current date).
        include_ufc: Include UFC regardless of event schedule (for manual triggers).

    Returns:
        List of active sport keys, e.g. ['nba', 'mlb']
    """
    if today is None:
        today = date.today()

    active = []
    for sport, window in SEASON_WINDOWS.items():
        if sport == "ufc":
            if include_ufc:
                active.append("ufc")
            continue
        if window is None:
            continue
        start, end = window
        if _in_window(today, start, end):
            active.append(sport)

    return active


if __name__ == "__main__":
    active_sports = check_season()
    print(f"Active sports today: {active_sports}")
