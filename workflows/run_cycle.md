# Workflow: Run Cycle

## Objective
Execute the full daily Sharper Margins run cycle: check seasons, pull odds, fetch context, run models, calculate edges, write signals, render dashboard, push to GitHub Pages.

## Trigger
- GitHub Actions cron: weekdays 3:00 PM CST (`0 21 * * 1-5`), weekends 10:00 AM CST (`0 16 * * 0,6`)
- Manual: `python tools/run_cycle.py [--sport X] [--dry-run] [--include-ufc]`

## Inputs Required
- `ODDS_API_KEY` in `.env` (or GitHub Secret)
- Active internet connection (ESPN, Kalshi, Odds API)

## Sequence

1. **check_season()** → Returns list of active sport keys for today's date
2. **fetch_odds(sport)** → Pulls moneyline odds from The Odds API; caches to `.tmp/`
3. **fetch_kalshi(sport, games)** → Fuzzy-matches Kalshi markets; caches to `.tmp/`
4. **fetch_context(sport, games)** → ESPN hidden API — standings, injuries, schedule, stats; caches to `.tmp/`
5. **Route game → SME agent** → Each game context → sport-specific agent → probability estimate
6. **calculate_edge(sme, game, kalshi)** → Vig-adjusted edge. If ≥ 10%: write_signal()
7. **serve_dashboard()** → Render `output/dashboard.html`
8. **git pull --rebase → commit → push** → GitHub Pages

## CLI Flags
- `--sport nba` — Only process a single sport (useful for testing)
- `--dry-run` — Full cycle but skip git commit/push
- `--force` — Force re-fetch (ignore cache)
- `--include-ufc` — Include UFC (normally event-driven only)

## Error Handling
- Missing odds for a sport → log warning, skip sport
- ESPN endpoint failure → log warning, agent receives partial context, uses delta=0 for missing factors
- Kalshi match failure → kalshi_alignment = "no_match", signal still fires if edge ≥ 10%
- Agent exception → log error, skip game (never crash full cycle)

## Expected Output
- `output/dashboard.html` — Updated static HTML dashboard
- `output/signals.json` — Updated signal log (historical + new signals)
- Git commit pushed to `main` branch → reflected on GitHub Pages
