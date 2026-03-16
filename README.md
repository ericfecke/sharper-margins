# Sharper Margins

Automated sports betting edge detection. Pulls live moneyline odds from DraftKings and FanDuel, runs them through sport-specific probability models, and surfaces bets where estimated true probability exceeds the book's implied probability by 10% or more.

Output is a static dashboard published to GitHub Pages, updated automatically on a daily cron schedule.

**Cost to run: $0.**

---

## How It Works

The system is built on the **WAT framework** — Workflows, Agents, Tools — which separates orchestration logic from execution to keep the system reliable and testable.

```
check_season → fetch_odds → fetch_context → fetch_kalshi
     → SME agent (per sport) → calculate_edge → write_signal → render dashboard → push
```

**Workflows** define the sequence and rules for each stage. **Agents** (deterministic Python models, one per sport) receive pre-built context objects and return a probability estimate. **Tools** handle all I/O: API calls, edge math, signal writes, HTML rendering.

No LLM calls anywhere in the pipeline. Every probability estimate is produced by explicit factor math with defined weights and delta caps.

### Data Sources

| Source | What It Provides | Cost |
|---|---|---|
| [The Odds API](https://the-odds-api.com) | Live moneyline odds — DraftKings + FanDuel | Free (500 credits/month) |
| ESPN Hidden API | Standings, injuries, schedules, team stats | Free, no key |
| [Kalshi](https://kalshi.com) | Prediction market prices for cross-validation | Free, no key |

### Edge Calculation

Implied probabilities are extracted from American odds and vig-adjusted before comparison:

```python
def american_to_implied(odds):
    if odds > 0: return 100 / (odds + 100)
    else: return abs(odds) / (abs(odds) + 100)

def remove_vig(implied_a, implied_b):
    total = implied_a + implied_b
    return implied_a / total, implied_b / total

edge = our_probability - vig_adjusted_implied
# Signal fires if edge >= 0.10
```

Kalshi prediction market prices are used as a cross-validation signal. If Kalshi aligns with the model (gap ≤ 5%), the signal is marked `confirms`. If it contradicts (gap > 5%), the signal is flagged in the dashboard. A missing Kalshi match never blocks a signal.

### Dashboard

Self-contained static HTML. No CDN dependencies. Dark background. Signals sorted by edge descending, expandable rows with full factor breakdown, DK vs FD odds, and Kalshi alignment. Live at:

**`https://ericfecke.github.io/sharper-margins/`**

---

## Sports Coverage

| Sport | Model | Status |
|---|---|---|
| NBA | 7-factor: win rate, home court, rest, form, injuries, scoring, H2H | ✅ Live |
| NFL | 9-factor: win rate, injuries (QB-weighted), form, scoring margin, home field, rest/bye, weather, divisional compression, H2H | ✅ Live |
| CFB | 9-factor: conference tier, win rate, AP rankings, home field, injuries (QB-heavy), scoring margin, form, rest + travel penalty, H2H | ✅ Live |
| MLB | Pitching-first: ERA/WHIP blended 50/50 with team base, run differential, form, bullpen fatigue, park factors, injuries, H2H | ✅ Live |
| NHL | — | 🚧 Coming soon |
| CBB | — | 🚧 Coming soon |
| UFC | — | 🚧 Coming soon |

Stub sports appear in the dashboard with matchups listed but no signals fired.

---

## Run Schedule

Triggered automatically via GitHub Actions:

| Day | Time |
|---|---|
| Weekdays | 3:00 PM CST |
| Weekends | 10:00 AM CST |

UFC is event-driven — trigger manually from the Actions tab when a card is scheduled.

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/ericfecke/sharper-margins.git
cd sharper-margins
pip install -r requirements.txt
```

### 2. Add your Odds API key

Create a `.env` file at the repo root:

```
ODDS_API_KEY=your_key_here
```

Get a free key at [the-odds-api.com](https://the-odds-api.com). The free tier (500 credits/month) is sufficient.

### 3. Enable GitHub Pages

`Settings → Pages → Source: Branch main, Folder / (root) → Save`

### 4. Add the GitHub Actions secret

`Settings → Secrets and variables → Actions → New repository secret`

- Name: `ODDS_API_KEY`
- Value: your key from step 2

### 5. Run locally

```bash
# Test a single sport (dry run — no git push)
cd tools && python run_cycle.py --sport nba --dry-run

# Full run
cd tools && python run_cycle.py

# Force re-fetch (ignore cache)
cd tools && python run_cycle.py --sport mlb --force

# Include UFC (manual trigger for event days)
cd tools && python run_cycle.py --include-ufc
```

---

## Project Structure

```
sharper-margins/
├── tools/
│   ├── run_cycle.py          # Orchestrator — full pipeline entry point
│   ├── check_season.py       # Season window detection
│   ├── fetch_odds.py         # The Odds API integration
│   ├── fetch_kalshi.py       # Kalshi markets + fuzzy matching
│   ├── fetch_context.py      # ESPN data — standings, injuries, schedules, stats
│   ├── nba_agent.py          # ✅ Full model
│   ├── nfl_agent.py          # ✅ Full model
│   ├── cfb_agent.py          # ✅ Full model
│   ├── mlb_agent.py          # ✅ Full model
│   ├── nhl_agent.py          # 🚧 Stub
│   ├── cbb_agent.py          # 🚧 Stub
│   ├── ufc_agent.py          # 🚧 Stub
│   ├── agent_utils.py        # Shared math (winrate regression, clamp, vig removal)
│   ├── calculate_edge.py     # Edge calculation + Kalshi cross-validation
│   ├── write_signal.py       # Signal persistence
│   └── serve_dashboard.py    # Static HTML dashboard renderer
├── workflows/                # Markdown SOPs for each pipeline stage
├── index.html                # Dashboard (overwritten each run)
├── signals.json              # Signal history (never wiped)
└── .github/workflows/
    └── run_cycle.yml         # Cron + manual dispatch
```

---

## Signal Format

```json
{
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
  "sme_reasoning": "Win rate edge + home court; recent form favors home",
  "kalshi_probability": 0.61,
  "kalshi_match": true,
  "kalshi_alignment": "confirms"
}
```

`confidence: "low"` fires the signal but flags it in a separate dashboard section — indicates one or more ESPN data points were unavailable for that game.

---

## Operational Notes

- ESPN's hidden API is unofficial and undocumented. All calls are wrapped in try/except with graceful fallback — a failed endpoint sets that factor's delta to 0 and flags `low_confidence`, but never aborts the run.
- Odds API credits are tracked in the run log. At one pull per sport per day, usage stays well within the free tier.
- `signals.json` is append-only. Same game + book combination overwrites its previous entry; all other history accumulates.
- Paper trade for at least 4 weeks before treating signals as actionable. Model weights are informed estimates, not backtested.
