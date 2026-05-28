"""
run_cycle.py — Master entry point for the Sharper Margins daily run cycle.

Sequence:
1. check_season()     — which sports active today
2. fetch_odds()       — moneyline only, DK + FD, cache to .tmp/
3. fetch_kalshi()     — Kalshi public API, fuzzy match, cache to .tmp/
4. fetch_context()    — ESPN hidden API per sport, cache to .tmp/
5. Route each game to SME agent
6. calculate_edge()   — if edge >= 10%, write_signal()
7. serve_dashboard()  — render output/dashboard.html
8. git pull --rebase → commit → push

CLI flags:
  --sport NBA         Run for a specific sport only
  --dry-run           Run full cycle but skip git commit/push
  --force             Force re-fetch even if cache exists
  --include-ufc       Include UFC (event-driven)
"""

import argparse
import importlib
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

# Add tools directory to path so relative imports work
sys.path.insert(0, str(Path(__file__).parent))

from check_season import check_season
from fetch_odds import fetch_odds
from fetch_kalshi import fetch_kalshi
from fetch_context import fetch_context
from fetch_results import update_results
from calculate_edge import calculate_edge
from write_signal import write_signal, load_signals
from serve_dashboard import render_dashboard

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent

SPORT_AGENT_MAP = {
    "nba": "nba_agent",
    "nfl": "nfl_agent",
    "cfb": "cfb_agent",
    "mlb": "mlb_agent",
    "nhl": "nhl_agent",
    "cbb": "cbb_agent",
    "ufc": "ufc_agent",
}

STUB_SPORTS = {"nhl", "cbb", "ufc"}


def main():
    parser = argparse.ArgumentParser(description="Sharper Margins daily run cycle")
    parser.add_argument("--sport", type=str, help="Run for a specific sport only (e.g. nba)")
    parser.add_argument("--dry-run", action="store_true", help="Skip git commit/push")
    parser.add_argument("--force", action="store_true", help="Force re-fetch data")
    parser.add_argument("--include-ufc", action="store_true", help="Include UFC in run")
    args = parser.parse_args()

    today = date.today()
    print(f"\n{'='*60}")
    print(f"  SHARPER MARGINS — Run Cycle {today.isoformat()}")
    print(f"{'='*60}\n")

    # Step 0: Backfill results for any completed games
    logger.info("Checking for completed game results...")
    update_results()

    # Step 1: Determine active sports
    if args.sport:
        active_sports = [args.sport.lower()]
        logger.info("Sport override: %s", active_sports)
    else:
        active_sports = check_season(today=today, include_ufc=args.include_ufc)
        logger.info("Active sports: %s", active_sports)

    if not active_sports:
        logger.info("No active sports today. Rendering empty dashboard.")
        render_dashboard(signals=load_signals(), active_sports=[])
        _git_commit_push(0, [], dry_run=args.dry_run)
        return

    signals_fired = 0
    stub_games = {}  # sport -> list of game strings for dashboard stub section

    for sport in active_sports:
        print(f"\n--- {sport.upper()} ---")

        # Step 2: Fetch odds
        games = fetch_odds(sport, today=today, force=args.force)
        if not games:
            logger.info("No games found for %s — skipping", sport.upper())
            continue

        logger.info("%d games found for %s", len(games), sport.upper())

        # Collect stub sport games for dashboard display
        if sport in STUB_SPORTS:
            stub_games[sport] = [f"{g['away_team']} @ {g['home_team']}" for g in games]

        # Step 3: Fetch Kalshi
        kalshi_data = fetch_kalshi(sport, games, today=today, force=args.force)

        # Step 4: Fetch ESPN context
        context = fetch_context(sport, games, today=today, force=args.force)

        # Step 5: Route to SME agent
        agent_module_name = SPORT_AGENT_MAP.get(sport)
        if not agent_module_name:
            print(f"[run_cycle] No agent for {sport} — skipping")
            continue

        try:
            agent = importlib.import_module(agent_module_name)
        except ImportError as e:
            logger.error("Failed to import %s: %s", agent_module_name, e)
            continue

        # Process each game
        for game in games:
            game_id = game["id"]
            game_ctx = context.get(game_id, {})
            if not game_ctx:
                game_ctx = {
                    "home_team": game["home_team"],
                    "away_team": game["away_team"],
                    "game_id": game_id,
                    "commence_time": game["commence_time"],
                }

            try:
                sme_result = agent.run(game_ctx)
            except Exception as e:
                logger.error("Agent error for %s: %s", game_id, e)
                continue

            if sme_result.get("probability") is None:
                continue  # Stub — skip edge calculation

            kalshi_match = kalshi_data.get(game_id)

            # Step 6: Calculate edge
            edge_result = calculate_edge(sme_result, game, kalshi_match)
            if edge_result:
                edge_result["sport"] = sport.upper()
                write_signal(edge_result)
                signals_fired += 1
                logger.info("SIGNAL: %s | edge=%.1f%% | %s", edge_result["recommendation"], edge_result["edge"] * 100, edge_result["confidence"])
            else:
                prob = sme_result.get("probability", 0)
                logger.debug("No edge: %s @ %s (our_prob=%.2f%%)", game["away_team"], game["home_team"], prob * 100)

    logger.info("Cycle complete: %d signal(s) fired", signals_fired)

    # Step 7: Render dashboard
    all_signals = load_signals()
    render_dashboard(signals=all_signals, active_sports=active_sports, stub_games=stub_games)

    # Step 8: Git operations
    _git_commit_push(signals_fired, active_sports, dry_run=args.dry_run)


def _git_commit_push(signal_count: int, active_sports: list, dry_run: bool = False):
    """Pull, commit, and push dashboard update."""
    if dry_run:
        print("[run_cycle] Dry run — skipping git operations")
        return

    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%d %H:%M")
    sports_str = ", ".join(s.upper() for s in active_sports) if active_sports else "none"
    commit_msg = f"[{timestamp}] {signal_count} signals — sports active: {sports_str}"

    try:
        # Pull before push
        result = subprocess.run(
            ["git", "-C", str(ROOT), "pull", "--rebase", "origin", "main"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            logger.warning("git pull warning: %s", result.stderr.strip())

        # Stage dashboard and signals at repo root
        subprocess.run(
            ["git", "-C", str(ROOT), "add", "index.html", "signals.json"],
            check=True, capture_output=True
        )

        # Check if there's anything to commit
        status = subprocess.run(
            ["git", "-C", str(ROOT), "status", "--porcelain"],
            capture_output=True, text=True
        )
        if not status.stdout.strip():
            logger.info("Nothing to commit — dashboard unchanged")
            return

        subprocess.run(
            ["git", "-C", str(ROOT), "commit", "-m", commit_msg],
            check=True, capture_output=True
        )

        subprocess.run(
            ["git", "-C", str(ROOT), "push", "origin", "main"],
            check=True, capture_output=True
        )

        logger.info("Committed and pushed: %s", commit_msg)

    except subprocess.CalledProcessError as e:
        logger.error("Git error: %s\nstdout: %s\nstderr: %s", e, e.stdout, e.stderr)


if __name__ == "__main__":
    main()
