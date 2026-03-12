# Sharper Margins — Agent Instructions

You're working inside the **WAT framework** (Workflows, Agents, Tools). This project builds a multi-agent sports betting analysis system that identifies exploitable edges in DraftKings and FanDuel moneyline odds across NBA, NFL, CFB, MLB, NHL, CBB, and UFC. Kalshi prediction market prices are used as a cross-validation signal to strengthen or flag edge cases.

Probabilistic reasoning handles probability estimation. Deterministic Python handles data fetching, edge calculation, signal writing, and dashboard rendering. That separation is what keeps the system reliable.

---

## Project Objective

Sharper Margins identifies exploitable edges in DraftKings and FanDuel moneyline odds across NBA, NFL, CFB, MLB, NHL, CBB, and UFC.

The system pulls live odds, runs them through sport-specific probability models, and surfaces bets where our estimated true probability exceeds the book's implied probability by 10% or more.

Output is a live static dashboard on GitHub Pages showing active signals and historical model performance.

**Cost target: $0.** No paid APIs, no LLM API calls. All SME agent logic is deterministic Python math.

---

## The WAT Architecture

**Layer 1: Workflows (The Instructions)**
- Markdown SOPs stored in `workflows/`
- Each workflow defines the objective, required inputs, which tools to use, expected outputs, and edge case handling

**Layer 2: Agents (The Decision-Maker)**
- This is your role. You read the relevant workflow, call tools in the correct sequence, handle failures gracefully
- Do not fetch data or perform execution directly — call the appropriate tool

**Layer 3: Tools (The Execution)**
- Python scripts in `tools/` that do the actual work
- API calls, probability calculations, edge math, signal writes, dashboard rendering
- Deterministic, testable, no LLM calls

**Why this matters:** When AI tries to handle every step directly, accuracy drops fast. If each step is 90% accurate, five steps in a row yields 59% success. Deterministic tools stay at 100% for what they do — offload execution to them and stay focused on orchestration.

---

## Data Sources

### Live Odds
**The Odds API** (https://the-odds-api.com)
- Moneyline odds for NBA, NFL, CFB, MLB, NHL, CBB, UFC
- DraftKings and FanDuel only
- Free tier: 500 credits/month — sufficient at one pull per sport per day
- Auth: `ODDS_API_KEY` in `.env`
- Pull `h2h` (moneyline) market only — no spreads, no totals

### Stats & Contextual Data
**ESPN Hidden API** — no key, no auth, completely free
- Base pattern: `site.api.espn.com/apis/site/v2/sports/{sport}/{league}/{resource}`
- Covers all sports in this project: standings, team stats, schedules, injuries, scoreboard, rankings, H2H
- No BallDontLie — removed from architecture (free tier too limited)
- Specific endpoints documented per sport in the SME Agent section below
- ESPN endpoints are unofficial and undocumented — build defensively, handle 404s and schema changes gracefully

### Kalshi Prediction Markets
**Kalshi public API** (https://api.elections.kalshi.com)
- No authentication required for read-only market data
- Used as cross-validation signal by the Statistician — not a replacement for sportsbook odds
- Fuzzy match Kalshi markets to games using `rapidfuzz` (80% confidence threshold)
- Missing match = `"no_match"` — never blocks a signal
- UFC fighter naming is inconsistent — treat UFC Kalshi alignment as best-effort
- Cache to `.tmp/kalshi_{sport}_{date}.json`

### Static Data (baked into code — no API call needed)
- NFL/CFB division membership lookup dict
- MLB park factors lookup dict (all 30 parks)
- CFB conference tier lookup dict
- Team timezone lookup (for CFB travel penalty)

---

## API Cost Management

- One pull per active sport per day
- Cache all results in `.tmp/` — never re-pull within the same calendar day
- Only poll sports currently in season
- Max ESPN calls per run: ~10 (standings + schedule + injuries per sport)
- Odds API max: 7 requests/day (one per sport) — within free tier

**Season windows:**
| Sport | Season |
|---|---|
| NFL | September – February |
| CFB | August – January |
| NBA | October – June |
| CBB | November – April |
| MLB | March – October |
| NHL | October – June |
| UFC | Year-round, event-driven |

**Run schedule (GitHub Actions cron):**
- Weekdays 3:00 PM CST → `0 21 * * 1-5`
- Weekends 10:00 AM CST → `0 16 * * 0,6`
- UFC: day-of-event only or manual trigger

---

## Agent Roster

### Orchestrator (`run_cycle.py`)
Entry point for the full daily cycle.
1. `check_season()` — which sports active today
2. `fetch_odds()` — moneyline only, DK + FD
3. `fetch_context()` — ESPN data per sport/game
4. `fetch_kalshi()` — fuzzy match to games
5. Route each game to correct SME agent
6. Pass SME output to `calculate_edge()`
7. If edge ≥ 10%: `write_signal()`
8. `serve_dashboard()` — render static HTML
9. `git pull --rebase` → commit → push

CLI flags: `--sport nba`, `--dry-run`

---

### Statistician (`calculate_edge.py`)
Sport-agnostic. Receives SME output and odds object.

**Implied probability conversion (vig removal):**
```python
def american_to_implied(odds):
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return abs(odds) / (abs(odds) + 100)

def remove_vig(implied_a, implied_b):
    total = implied_a + implied_b
    return implied_a / total, implied_b / total
```

**Edge calculation:**
```python
edge = our_probability - vig_adjusted_implied
if edge >= 0.10:
    # fire signal
```

**Kalshi cross-validation:**
- Kalshi aligns with SME (within 5%) → `kalshi_alignment: "confirms"`
- Kalshi contradicts SME (>5% gap) → `kalshi_alignment: "contradicts"`, flag in output
- No match → `kalshi_alignment: "no_match"`

---

### Signal Format
```json
{
  "sport": "NBA",
  "game": "Lakers vs Celtics",
  "commence_time": "2026-03-11T19:00:00Z",
  "book": "DraftKings",
  "our_probability": 0.62,
  "implied_probability": 0.51,
  "edge": 0.11,
  "recommendation": "Lakers ML",
  "confidence": "normal",
  "missing_factors": [],
  "sme_reasoning": "Short summary of key factors",
  "kalshi_probability": 0.61,
  "kalshi_match": true,
  "kalshi_alignment": "confirms"
}
```

`confidence` values: `"normal"` | `"low"` (fires signal but flags it in dashboard)

---

## SME Agent Models

All SME agents are **pure deterministic Python math**. No LLM calls. No API calls inside agents. They receive a pre-built context object from `fetch_context.py` and return a probability + reasoning string.

### Shared Utilities (used by all agents)

**Regressed win rate:**
```python
def adjusted_winrate(wins, games, full_confidence_at):
    if games == 0:
        return 0.500
    raw = wins / games
    confidence = min(games / full_confidence_at, 1.0)
    return (confidence * raw) + ((1 - confidence) * 0.500)

def clamp(value, low, high):
    return max(low, min(high, value))
```

**Missing factor handling:**
- Any factor where ESPN returned None → delta = 0, add factor name to `missing_factors`
- If any factor is missing → `confidence: "low"`
- Signal still fires — missing data reduces confidence, does not abort

---

### NBA Agent (`nba_agent.py`)

**Base:** Regressed win rate. Full confidence at 40 games.

**Factors:**

| Factor | ESPN Data | Max Delta |
|---|---|---|
| Win rate differential | standings | ±0.10 |
| Recent form (last 10) | team schedule | ±0.06 |
| Home court | scoreboard | ±0.06 |
| Injury impact | injuries | -0.08 to 0 |
| Net rating matchup | team statistics | ±0.05 |
| Rest differential | team schedule | ±0.04 |
| Head-to-head | team record | ±0.02 |

**Win rate differential:**
```python
winrate_diff = adj_wr_a - adj_wr_b
delta = clamp(winrate_diff * 0.4, -0.10, +0.10)
```

**Home court:**
```python
delta = +0.06 if home else -0.06
```

**Rest:**
```python
rest_diff = days_rest_a - days_rest_b
delta = clamp(rest_diff * 0.015, -0.04, +0.04)
```

**Form (last 10):**
```python
form_diff = last10_wr_a - last10_wr_b
delta = clamp(form_diff * 0.15, -0.06, +0.06)
```

**Injuries:**
```python
# Per player OUT on team:
#   PG/SG/SF: -0.025 | PF/C: -0.020
# Per QUESTIONABLE: -0.010
# net_injury_score = team_a_score - team_b_score
delta = clamp(net_injury_score, -0.08, 0.0)
```

**Net rating (offensive rating minus defensive rating):**
```python
rating_diff = (off_rtg_a - def_rtg_a) - (off_rtg_b - def_rtg_b)
delta = clamp(rating_diff * 0.008, -0.05, +0.05)
```

**H2H (min 2 games this season):**
```python
if h2h_games >= 2:
    delta = clamp((h2h_wr_a - 0.500) * 0.08, -0.02, +0.02)
else:
    delta = 0
```

**Final output:** `clamp(base + sum(all_deltas), 0.10, 0.90)`

**ESPN endpoints:**
```
site.api.espn.com/apis/site/v2/sports/basketball/nba/standings
site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard
site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{id}/statistics
site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{id}/schedule
site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries
sports.core.api.espn.com/v2/sports/basketball/leagues/nba/teams/{id}/record
```

---

### NFL Agent (`nfl_agent.py`)

**Base:** Regressed win rate. Full confidence at 10 games (week 10).

**Key NFL note:** High variance sport — outputs realistically cluster 0.35–0.70. Do not expect outputs near 0.90.

**Factors:**

| Factor | ESPN Data | Max Delta |
|---|---|---|
| Win rate differential | standings | ±0.10 |
| Injury impact (QB-weighted) | injuries | ±0.10 |
| Recent form (last 5) | team schedule | ±0.05 |
| Scoring margin differential | team statistics | ±0.05 |
| Home field | scoreboard | ±0.04 |
| Rest / bye week | team schedule | ±0.04 |
| Weather compression | scoreboard event | up to -0.055 |
| Divisional compression | static lookup | ±0.02 |
| Head-to-head (last 3 seasons) | team record | ±0.02 |

**Injuries (QB tiered separately):**
```python
# Per player OUT:
#   QB: -0.08 | WR/RB/TE/OL: -0.020 | DE/CB/LB/S: -0.015
# QUESTIONABLE: multiply individual score by 0.5
# net = team_a_score - team_b_score
delta = clamp(net_injury_score, -0.10, +0.10)
# Set qb_injury_flag = True in output if QB is OUT
```

**Rest / bye:**
```python
if team_a had bye (no game in 14+ days) and team_b did not:
    delta = +0.04
elif team_b had bye and team_a did not:
    delta = -0.04
else:
    rest_diff = days_rest_a - days_rest_b
    delta = clamp(rest_diff * 0.008, -0.02, +0.02)
```

**Scoring margin:**
```python
margin_diff = (ppg_a - papg_a) - (ppg_b - papg_b)
delta = clamp(margin_diff * 0.007, -0.05, +0.05)
```

**Weather (skip entirely if dome venue):**
```python
compression = 0.0
if wind_mph > 20:   compression += 0.015
if wind_mph > 30:   compression += 0.015  # stacks with above
if precipitation:   compression += 0.015
if temp_f < 32:     compression += 0.010
# Push running probability toward 0.500
if running_prob > 0.500:
    delta -= compression
else:
    delta += compression
```

**Divisional compression:**
```python
if same_division(team_a, team_b):
    if running_prob > 0.500:
        delta -= 0.02
    else:
        delta += 0.02
```

**H2H (last 3 seasons, min 3 games):**
```python
if h2h_games >= 3:
    delta = clamp((h2h_wr_a - 0.500) * 0.06, -0.02, +0.02)
```

**ESPN endpoints:**
```
site.api.espn.com/apis/site/v2/sports/football/nfl/standings
site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard
site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{id}/statistics
site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{id}/schedule
site.api.espn.com/apis/site/v2/sports/football/nfl/injuries
sports.core.api.espn.com/v2/sports/football/leagues/nfl/teams/{id}/record
```

Weather and dome/outdoor flag come from the scoreboard event payload.

---

### CFB Agent (`cfb_agent.py`)

**Base:** SOS-adjusted win rate. Full confidence at 8 games.

**SOS adjustment:**
```python
sos_adj = (opponent_avg_winrate - 0.500) * 0.15
adjusted = raw_winrate + sos_adj
# Then regress toward 0.500 using confidence weight
```

**Factors:**

| Factor | ESPN Data | Max Delta |
|---|---|---|
| Conference tier differential | static lookup | ±0.10 |
| Injury impact (QB-weighted) | injuries | ±0.10 |
| Scoring margin differential | team statistics | ±0.07 |
| Home field / neutral site | scoreboard | ±0.07 |
| AP ranking differential | rankings | ±0.06 |
| Recent form (last 5) | team schedule | ±0.05 |
| Rest + travel penalty | schedule + static | ±0.05 |
| H2H (last 3 seasons) | team record | ±0.02 |

**Conference tiers (static dict in code):**
```python
CONFERENCE_TIER = {
    'SEC': 1, 'Big Ten': 1,
    'Big 12': 2, 'ACC': 2,
    'American': 3, 'Mountain West': 3,
    'Sun Belt': 3, 'MAC': 3, 'CUSA': 3,
    'Independents': 2,  # Notre Dame pulls this up
}
tier_diff = tier_b - tier_a  # positive = team_a in stronger conference
delta = clamp(tier_diff * 0.06, -0.10, +0.10)
```

**Rankings:**
```python
rank_a = ap_rank_a or 99   # unranked = 99
rank_b = ap_rank_b or 99
if rank_a == 99 and rank_b == 99:
    delta = 0
elif rank_a == 99:
    delta = -0.06
elif rank_b == 99:
    delta = +0.06
else:
    rank_diff = rank_b - rank_a  # positive = team_a ranked higher
    delta = clamp(rank_diff * 0.002, -0.06, +0.06)
```

**Home field:**
```python
if neutral_site:
    delta = 0
elif team_a is home:
    delta = +0.07
else:
    delta = -0.07
```

**QB injury weight is higher in CFB (thinner backup depth):**
```python
# QB OUT: -0.10 | skill position OUT: -0.020 | defensive OUT: -0.012
# Same QUESTIONABLE multiplier (0.5) as NFL
```

**Rest + travel:**
```python
rest_delta = clamp(rest_diff_days * 0.008, -0.03, +0.03)
travel_delta = -0.02 if (team_a is away AND timezone_diff >= 2) else 0
delta = rest_delta + travel_delta
```

**ESPN endpoints:**
```
site.api.espn.com/apis/site/v2/sports/football/college-football/standings
site.api.espn.com/apis/site/v2/sports/football/college-football/rankings
site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard
site.api.espn.com/apis/site/v2/sports/football/college-football/teams/{id}/statistics
site.api.espn.com/apis/site/v2/sports/football/college-football/teams/{id}/schedule
site.api.espn.com/apis/site/v2/sports/football/college-football/injuries
```

---

### MLB Agent (`mlb_agent.py`)

**MLB-specific structure:** Pitching matchup is built first and blended 50/50 with team win rate as the base. Do not use pure win rate as base — it undersells pitcher importance.

**Base construction:**
```python
pitching_delta = pitcher_delta(era_a, whip_a, era_b, whip_b)
team_base = adjusted_winrate(wins_a, games_a, full_confidence_at=50)
base = (team_base * 0.50) + (0.500 + pitching_delta) * 0.50
```

**Pitcher quality delta:**
```python
era_diff = era_b - era_a    # positive = team_a pitcher better
whip_diff = whip_b - whip_a
pitching_score = (era_diff * 0.06) + (whip_diff * 0.04)
pitching_delta = clamp(pitching_score, -0.15, +0.15)
```

**If starting pitcher unknown:** pitching_delta = 0, append `'starting_pitcher'` to `missing_factors`, force `confidence: 'low'`.

**Factors (applied on top of blended base):**

| Factor | ESPN Data | Max Delta |
|---|---|---|
| Run differential | team statistics | ±0.06 |
| Recent form (last 10) | team schedule | ±0.05 |
| Injury impact | injuries | ±0.05 |
| Bullpen fatigue | team schedule | ±0.03 |
| Home field | scoreboard | ±0.03 |
| Park factor | static lookup | ±0.025 |
| H2H (min 4 games) | team record | ±0.02 |

**Run differential:**
```python
rd_a = (runs_scored_a - runs_allowed_a) / games_a
rd_b = (runs_scored_b - runs_allowed_b) / games_b
delta = clamp((rd_a - rd_b) * 0.025, -0.06, +0.06)
```

**Bullpen fatigue (relief IP in last 48 hours):**
```python
if bullpen_ip_a > 8:   bullpen_score_a = -0.02
elif bullpen_ip_a > 5: bullpen_score_a = -0.01
else:                  bullpen_score_a = 0
# same for team_b
delta = clamp(bullpen_score_a - bullpen_score_b, -0.03, +0.03)
```

**Park factors (static dict — maintain for all 30 parks):**
```python
PARK_FACTORS = {
    'COL': +0.025,   # Coors — extreme hitter friendly
    'CIN': +0.015,
    'TEX': +0.010,
    'SF':  -0.020,   # Oracle — extreme pitcher friendly
    'NYM': -0.015,
    'OAK': -0.010,
    # remaining parks: values between -0.008 and +0.008
}
park_val = PARK_FACTORS.get(home_team_abbr, 0.0)
delta = park_val if team_a is home else -park_val
```

**ESPN endpoints:**
```
site.api.espn.com/apis/site/v2/sports/baseball/mlb/scoreboard
site.api.espn.com/apis/site/v2/sports/baseball/mlb/standings
site.api.espn.com/apis/site/v2/sports/baseball/mlb/teams/{id}/statistics
site.api.espn.com/apis/site/v2/sports/baseball/mlb/teams/{id}/schedule
site.api.espn.com/apis/site/v2/sports/baseball/mlb/injuries
```

---

### NHL, CBB, UFC Agents — STUBS

These three agents are **not yet modeled**. Build them as stubs that:
1. Return `probability: None`
2. Return `confidence: 'stub'`
3. Return `reasoning: 'Model not yet implemented'`
4. Never trigger edge calculation — `calculate_edge.py` skips any game where `probability is None`

The dashboard shows these sports in a **"Model Coming Soon"** section below active signals. Games are listed with sport label and matchup but no edge, no recommendation, no signal color. Clear label: *"This sport's model is under development. Signals will appear here when ready."*

When NHL, CBB, and UFC models are designed, update the stub file with real logic. No other pipeline changes required.

---

## Run Cycle

```
1. check_season()     → which sports active today
2. fetch_odds()       → The Odds API, h2h only, DK + FD, cache to .tmp/
3. fetch_kalshi()     → Kalshi public API, fuzzy match, cache to .tmp/
4. fetch_context()    → ESPN hidden API per sport, cache to .tmp/
5. for each game:
       sme = sport_agent(game, context)
       if sme.probability is not None:
           edge = calculate_edge(sme, odds)
           if edge >= 0.10:
               write_signal(edge_result)
6. serve_dashboard()  → render output/dashboard.html
7. git pull --rebase → commit → push → GitHub Pages
```

---

## Dashboard

Static self-contained HTML. No CDN dependencies. No server required. Client-side JS sorting.

**Layout:**
```
┌─────────────────────────────────────────────────────────────┐
│  SHARPER MARGINS                   Generated: 2026-03-11    │
├─────────────────────────────────────────────────────────────┤
│  Active Signals: N  │  🟢 20%+  │  🟠 15–19%  │  🟡 10–14%  │
├─────────────────────────────────────────────────────────────┤
│  [All/NFL/CFB/NBA/MLB] [All Books/DK/FD] [Search]          │
├─────────────────────────────────────────────────────────────┤
│  Sport │ Game │ Book │ Our% │ Implied% │ Edge ▼            │
│    ▼ expanded: reasoning, factors, Kalshi alignment         │
├─────────────────────────────────────────────────────────────┤
│  LOW CONFIDENCE SIGNALS                                     │
│  (edge ≥ 10% but missing data — proceed with caution)      │
├─────────────────────────────────────────────────────────────┤
│  MODEL COMING SOON                                         │
│  NHL · CBB · UFC — games listed, no signals                │
├─────────────────────────────────────────────────────────────┤
│  SIGNAL HISTORY — W/L/PUSH tracking                        │
└─────────────────────────────────────────────────────────────┘
```

**Edge color coding:**
- 🟡 10–14% — marginal
- 🟠 15–19% — solid
- 🟢 20%+ — strongest

**Expandable rows:** Click to expand inline. Shows SME reasoning, key factors used, which factors were missing, Kalshi alignment with price, DK vs FD odds side by side. One row open at a time.

**Design rules:** Dark background. No external dependencies. Fully functional offline. Default sort: edge descending.

---

## File Structure

```
sharper-margins/
│
├── .github/
│   └── workflows/
│       └── run_cycle.yml           # cron trigger
│
├── tools/
│   ├── run_cycle.py                # master entry point
│   ├── check_season.py             # season window check
│   ├── fetch_odds.py               # The Odds API
│   ├── fetch_kalshi.py             # Kalshi + rapidfuzz matching
│   ├── fetch_context.py            # ESPN hidden API, all sports
│   ├── nba_agent.py                # ✅ full model
│   ├── nfl_agent.py                # ✅ full model
│   ├── cfb_agent.py                # ✅ full model
│   ├── mlb_agent.py                # ✅ full model
│   ├── nhl_agent.py                # 🚧 stub
│   ├── cbb_agent.py                # 🚧 stub
│   ├── ufc_agent.py                # 🚧 stub
│   ├── calculate_edge.py           # vig removal + edge calc
│   ├── write_signal.py             # append/update signals.json
│   └── serve_dashboard.py          # render dashboard.html
│
├── workflows/
│   ├── run_cycle.md
│   ├── fetch_odds.md
│   ├── fetch_kalshi.md
│   ├── fetch_context.md
│   ├── run_sme_agents.md
│   ├── calculate_edge.md
│   └── render_dashboard.md
│
├── output/
│   ├── dashboard.html              # overwritten each run
│   └── signals.json               # never wiped, history preserved
│
├── .tmp/                           # cache — never commit
│   ├── odds_{sport}_{date}.json
│   ├── kalshi_{sport}_{date}.json
│   └── context_{sport}_{date}.json
│
├── .env                            # never commit
├── .gitignore                      # .env, .tmp/, __pycache__/, *.pyc
├── requirements.txt
└── CLAUDE.md
```

---

## Dependencies

```
requests        # ESPN API + Odds API + Kalshi HTTP calls
rapidfuzz       # Kalshi fuzzy market matching
pandas          # signal log management
numpy           # probability math
jinja2          # dashboard HTML templating
python-dotenv   # .env loading
```

Standard library (no install): `json`, `os`, `sys`, `datetime`, `pathlib`, `argparse`

**No `anthropic` package. No LLM API calls. Zero cost to run.**

---

## GitHub Secrets Required

In repo Settings → Secrets → Actions:
- `ODDS_API_KEY` — from the-odds-api.com (free account)

No other secrets needed. ESPN and Kalshi require no keys.

---

## Git Protocol

- Always `git pull --rebase` before pushing
- Never commit `.tmp/`, `.env`, `__pycache__/`, `*.pyc`
- Commit message format: `[YYYY-MM-DD HH:MM] N signals — sports active: X`
- Example: `[2026-03-11 15:00] 3 signals — sports active: NBA, MLB`

---

## Operational Rules

- **Check season first.** No odds pull if nothing is active today.
- **Agents never fetch their own data.** All data flows through `fetch_context.py`. Agents receive pre-built context objects.
- **Cache aggressively.** One ESPN pull per sport per day. Reuse within same calendar day.
- **Degrade gracefully.** Missing ESPN data → delta = 0 for that factor, flag `low_confidence`. Never abort the run.
- **Preserve signal history.** `signals.json` is never wiped. Same game overwrites its previous entry. Everything else accumulates.
- **Nothing surfaces below 10% edge.** If the signal isn't there, nothing shows.
- **Stubs never fire signals.** NHL/CBB/UFC return `probability: None`. `calculate_edge.py` skips them entirely.

---

## Known Limitations

- NHL, CBB, UFC models not yet built — stubs only, no signals fire for these sports
- ESPN hidden API is unofficial — endpoints can change without notice; wrap all calls in try/except with graceful fallback
- CFB and CBB: ESPN may not carry all mid-major programs — log missing teams and skip
- UFC ESPN data is limited — fight center data available but fighter-level stats are sparse
- Kalshi sports market coverage inconsistent for smaller matchups (CBB, CFB non-conference)
- MLB park factors dict requires manual maintenance if teams move stadiums
- Historical odds for model validation not yet sourced — paper trade for 4 weeks before treating signals as actionable
- Free tier Odds API: 500 credits/month — monitor usage, do not add extra polling passes

---

## Roadmap

1. Paper trade signals for 4 weeks before treating output as actionable
2. Add W/L/PUSH result tracking to `signals.json` for accuracy feedback loop
3. Build NHL model (goalie-driven, similar structure to NBA)
4. Build CBB model (ranking + conference-heavy, similar structure to CFB)
5. Build UFC model (most unique — styles, reach, layoff, finish rate)
6. Explore push notifications for 20%+ signals

---

## Self-Improvement Loop

1. Identify what broke (bad estimate, stale cache, missing ESPN field)
2. Fix the tool or adjust the agent's factor weights
3. Verify the fix on a known upcoming game using `--dry-run`
4. Update the relevant workflow markdown
5. Log the lesson in Known Limitations if it's a recurring gap

If a sport agent is consistently over or underestimating, adjust the weight multipliers and delta caps. The signal history tab is the ground truth — track it, learn from it.

---

## Bottom Line

One job: find where the books are wrong by 10% or more. Surface it cleanly. Cost: $0.

Each cycle: check season → pull odds → fetch ESPN context → run models → calculate edge → write signals → push dashboard.

No noise. No marginal math. No LLM calls. If the edge isn't there, nothing surfaces.
