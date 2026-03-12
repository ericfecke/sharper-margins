# Workflow: Run SME Agents

## Objective
Route each game's context object to the correct sport-specific probability model. Collect probability estimates for edge calculation.

## Tools
- `tools/nba_agent.py` — Full model
- `tools/nfl_agent.py` — Full model
- `tools/cfb_agent.py` — Full model
- `tools/mlb_agent.py` — Full model (pitching-first)
- `tools/nhl_agent.py` — Stub (returns probability: None)
- `tools/cbb_agent.py` — Stub (returns probability: None)
- `tools/ufc_agent.py` — Stub (returns probability: None)

## Agent Contract
All agents implement a single `run(context: dict) -> dict` function:

**Input:** Pre-built context object (from fetch_context.py)

**Output:**
```json
{
  "probability": 0.62,
  "confidence": "normal",
  "missing_factors": [],
  "sme_reasoning": "Short summary of key factors",
  "factor_deltas": {"win_rate_diff": 0.06, "home_court": 0.06, ...}
}
```

- `probability`: Home team win probability (0.10–0.90). **None for stub agents.**
- `confidence`: "normal" (all data present) | "low" (missing factors) | "stub" (not implemented)
- `missing_factors`: List of factor names where ESPN returned None
- `factor_deltas`: Dict of individual factor contributions for dashboard display

## Rules
- Agents **never** fetch data. All data comes from context object.
- Agents **never** make LLM calls. Pure deterministic Python math.
- Missing factor → delta = 0 for that factor, append name to missing_factors
- Any factor delta is individually clamped to its max range before summing
- Final probability clamped to [0.10, 0.90]

## Stub Behavior
- NHL, CBB, UFC stubs return `probability: None`
- `calculate_edge.py` skips any game where probability is None
- Dashboard shows these sports in "Model Coming Soon" section

## Factor Model Summary (NBA example)
Base = 0.500, then sum of deltas:
| Factor | Max Delta |
|---|---|
| Win rate differential | ±0.10 |
| Home court | ±0.06 |
| Rest differential | ±0.04 |
| Recent form (L10) | ±0.06 |
| Injury impact | -0.08 to 0 |
| Net rating matchup | ±0.05 |
| Head-to-head | ±0.02 |

Final = clamp(0.500 + Σ deltas, 0.10, 0.90)
