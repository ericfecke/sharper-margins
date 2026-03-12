# Workflow: Render Dashboard

## Objective
Generate a self-contained static HTML dashboard from signals.json. No CDN dependencies. Dark background. Client-side filtering and sorting.

## Tool
`tools/serve_dashboard.py`

## Inputs
- `output/signals.json` — all signals (historical + new)
- `active_sports` — list of currently active sports
- `stub_games` — dict mapping stub sport keys to their game lists

## Output
- `output/dashboard.html` — overwritten on every run

## Layout
```
Header: SHARPER MARGINS | Generated: timestamp
Stats bar: Active signals count | 🟢 20%+ | 🟠 15-19% | 🟡 10-14%
Filters: [Sport buttons] [Book buttons] [Search]
Active Signals table (edge descending, expandable rows)
Low Confidence Signals section (if any)
Model Coming Soon section (NHL, CBB, UFC)
Signal History W/L/Push tracker
```

## Signal Table Columns
Sport | Game | Book | Edge ↓ | Our % | Implied % | Recommendation

## Expandable Row Detail
Click any row to expand inline:
- SME reasoning summary
- Missing factors list (if any)
- DK vs FD odds side by side
- Kalshi alignment status with price
- Factor delta breakdown

## Design Rules
- Dark background (`#0f1117`)
- No external dependencies (no CDN, no fonts from web)
- Fully functional offline
- Default sort: edge descending
- One row open at a time
- Edge color: 🟢 ≥20% | 🟠 15-19% | 🟡 10-14%

## Historical Tracking
- Signal history tab shows W/L/PUSH results
- `result` field in signals.json updated externally when game concludes
- Win rate shown: W / (W+L+P)

## Stub Section
For NHL, CBB, UFC when in season:
- List all games found (matchups only)
- No edge, no recommendation, no signal color
- Clear label: "This sport's model is under development."
