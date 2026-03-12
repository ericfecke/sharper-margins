# Workflow: Fetch Context

## Objective
Pull ESPN hidden API data for all active games in a sport. Build pre-assembled context objects that SME agents consume. No API calls inside agents — all data flows through this tool.

## Tool
`tools/fetch_context.py`

## Inputs
- Sport key (internal)
- List of normalized game objects (from fetch_odds)

## ESPN API Pattern
Base: `site.api.espn.com/apis/site/v2/sports/{category}/{league}/{resource}`
Core: `sports.core.api.espn.com/v2/sports/{category}/leagues/{league}/...`

The ESPN API is unofficial and undocumented. Build defensively:
- Wrap all calls in try/except
- Return None for any field that fails to parse
- Never abort the run due to ESPN failures

## Data Pulled Per Sport (max ~10 calls)
1. Standings → team win/loss records
2. Scoreboard → today's games, venue info, weather (NFL)
3. Injuries → per-team injury list with positions and status
4. Team statistics (per team in games found) → offensive/defensive stats
5. Team schedule (per team) → recent results for form/rest calculation

## Cache
- Cache path: `.tmp/context_{sport}_{YYYY-MM-DD}.json`
- One pull per sport per day

## Context Object Per Game
```json
{
  "sport": "nba",
  "home_team": "Los Angeles Lakers",
  "away_team": "Boston Celtics",
  "game_id": "...",
  "commence_time": "2026-03-11T19:00:00Z",
  "home_record": {"team_id": "13", "wins": 35, "losses": 20, "games_played": 55},
  "away_record": {"team_id": "2", "wins": 42, "losses": 13, "games_played": 55},
  "home_stats": {"offensiveRating": 115.2, "defensiveRating": 110.1},
  "away_stats": {"offensiveRating": 118.4, "defensiveRating": 108.2},
  "home_schedule": [...],
  "away_schedule": [...],
  "home_injuries": [{"name": "Player X", "position": "PG", "status": "Out"}],
  "away_injuries": [],
  "scoreboard_event": {"venue": "Staples Center", "neutral_site": false, "indoor": true},
  "neutral_site": false
}
```

## Missing Data Handling
- Any ESPN field that fails → set to None in context object
- SME agents check for None → delta = 0 for that factor, append to `missing_factors`
- confidence → "low" if any factor is missing
- Signal still fires — missing data reduces confidence, does not abort
