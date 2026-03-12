# Workflow: Fetch Odds

## Objective
Pull live moneyline odds from The Odds API for DraftKings and FanDuel. Cache results to avoid repeat API calls within the same calendar day.

## Tool
`tools/fetch_odds.py`

## Inputs
- Sport key (internal): `nba`, `nfl`, `cfb`, `mlb`, `nhl`, `cbb`, `ufc`
- `ODDS_API_KEY` from `.env`

## API Details
- Base URL: `https://api.the-odds-api.com/v4/sports/{sport_key}/odds`
- Markets: `h2h` (moneyline) only — no spreads, no totals
- Bookmakers: `draftkings,fanduel`
- Regions: `us`
- Format: `american` odds

## Cache
- Cache path: `.tmp/odds_{sport}_{YYYY-MM-DD}.json`
- Never re-pull within the same calendar day unless `--force` flag passed
- Max 7 API requests per day across all sports (free tier: 500 credits/month)

## Output Format
```json
[
  {
    "id": "...",
    "sport_key": "basketball_nba",
    "home_team": "Los Angeles Lakers",
    "away_team": "Boston Celtics",
    "commence_time": "2026-03-11T19:00:00Z",
    "odds": {
      "draftkings": {"home": -140, "away": +120},
      "fanduel": {"home": -135, "away": +115}
    }
  }
]
```

## Error Handling
- 401/403 → log API key issue, return []
- 404 → sport not available on Odds API, return []
- Timeout → log and return []
- Never crash run_cycle — return empty list on any failure
