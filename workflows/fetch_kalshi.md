# Workflow: Fetch Kalshi

## Objective
Fetch Kalshi prediction market prices and fuzzy-match them to today's games for cross-validation signal.

## Tool
`tools/fetch_kalshi.py`

## Inputs
- Sport key (internal)
- List of normalized game objects (from fetch_odds)

## API Details
- Base URL: `https://api.elections.kalshi.com/trade-api/v2/markets`
- No authentication required for read-only
- Filter by sport tag in title/subtitle
- Limit: 200 markets per request

## Matching Logic
- Use `rapidfuzz.fuzz.token_set_ratio` with 80% confidence threshold
- Match format: `"{away_team} vs {home_team}"` against market title+subtitle
- If no match at 80%+ → `kalshi_alignment: "no_match"` — never blocks a signal
- UFC fighter naming is inconsistent — treat as best-effort

## Cross-Validation (in calculate_edge.py)
- Kalshi aligns with SME (gap ≤ 5%) → `kalshi_alignment: "confirms"`
- Kalshi contradicts SME (gap > 5%) → `kalshi_alignment: "contradicts"` — flags in dashboard
- No match → `kalshi_alignment: "no_match"`

## Cache
- Cache path: `.tmp/kalshi_{sport}_{YYYY-MM-DD}.json`
- One pull per sport per day

## Output Format
```json
{
  "game_id_1": {
    "kalshi_probability": 0.61,
    "kalshi_match": true,
    "kalshi_market_title": "NBA: Will Lakers win vs Celtics?"
  },
  "game_id_2": {
    "kalshi_probability": null,
    "kalshi_match": false,
    "kalshi_market_title": null
  }
}
```
