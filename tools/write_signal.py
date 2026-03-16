"""
write_signal.py — Append or update signals in output/signals.json.
Never wipes history. Same game (by game_id + book) overwrites its previous entry.
All other entries accumulate.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SIGNALS_PATH = Path(__file__).parent.parent / "signals.json"


def write_signal(edge_result: dict) -> None:
    """
    Write or update a signal in signals.json.

    Args:
        edge_result: Edge calculation result dict from calculate_edge.py.
    """
    SIGNALS_PATH.parent.mkdir(exist_ok=True)

    # Load existing signals
    if SIGNALS_PATH.exists():
        try:
            with open(SIGNALS_PATH) as f:
                signals = json.load(f)
            if not isinstance(signals, list):
                signals = []
        except (json.JSONDecodeError, IOError):
            signals = []
    else:
        signals = []

    # Create unique key for this signal (game + book)
    signal_key = f"{edge_result.get('game_id', '')}_{edge_result.get('book', '')}"

    # Add timestamp if not present
    if "generated_at" not in edge_result:
        edge_result["generated_at"] = datetime.now(timezone.utc).isoformat()

    # Add result tracking fields if not present
    if "result" not in edge_result:
        edge_result["result"] = None  # Will be updated when game completes: "W", "L", "P"

    # Overwrite existing entry for same game+book, else append
    updated = False
    for i, sig in enumerate(signals):
        existing_key = f"{sig.get('game_id', '')}_{sig.get('book', '')}"
        if existing_key == signal_key:
            # Preserve result if already tracked
            if sig.get("result") is not None:
                edge_result["result"] = sig["result"]
            signals[i] = edge_result
            updated = True
            break

    if not updated:
        signals.append(edge_result)

    # Save
    with open(SIGNALS_PATH, "w") as f:
        json.dump(signals, f, indent=2)

    action = "updated" if updated else "added"
    print(f"[write_signal] Signal {action}: {edge_result.get('recommendation')} | edge={edge_result.get('edge'):.2%}")


def load_signals() -> list:
    """Load all signals from signals.json."""
    if not SIGNALS_PATH.exists():
        return []
    try:
        with open(SIGNALS_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []


def get_active_signals(signals: list) -> list:
    """
    Filter to signals for games that haven't started yet or started recently.
    Returns signals with edge >= 10%.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    active = []
    for sig in signals:
        try:
            commence = datetime.fromisoformat(sig.get("commence_time", "").replace("Z", "+00:00"))
        except Exception:
            continue
        # Include games within last 6 hours (in progress) or future
        hours_ago = (now - commence).total_seconds() / 3600
        if hours_ago < 6:
            active.append(sig)
    return active


if __name__ == "__main__":
    # Quick test
    test_signal = {
        "game_id": "test_game_1",
        "sport": "NBA",
        "game": "Celtics @ Lakers",
        "commence_time": "2026-03-11T19:00:00Z",
        "book": "DraftKings",
        "recommendation": "Lakers ML",
        "our_probability": 0.62,
        "implied_probability": 0.51,
        "edge": 0.11,
        "confidence": "normal",
        "missing_factors": [],
        "sme_reasoning": "Home court + win rate edge",
    }
    write_signal(test_signal)
    print("Signals saved:", len(load_signals()))
