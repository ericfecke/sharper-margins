# Workflow: Calculate Edge

## Objective
Compare SME probability estimate to vig-adjusted implied probability from book odds. Surface bets where edge ≥ 10%.

## Tool
`tools/calculate_edge.py`

## Inputs
- SME result dict (probability, confidence, missing_factors, reasoning)
- Game odds object (home/away American odds per book)
- Kalshi match dict (optional)

## Math

### Step 1: Convert American odds to implied probability
```python
def american_to_implied(odds):
    if odds > 0:
        return 100 / (odds + 100)
    else:
        return abs(odds) / (abs(odds) + 100)
```

### Step 2: Remove vig
```python
def remove_vig(implied_a, implied_b):
    total = implied_a + implied_b
    return implied_a / total, implied_b / total
```

### Step 3: Calculate edge
```python
edge = our_probability - vig_adjusted_implied
if edge >= 0.10:
    # fire signal
```

## Kalshi Cross-Validation
- Gap ≤ 5% between SME prob and Kalshi prob → `kalshi_alignment: "confirms"`
- Gap > 5% → `kalshi_alignment: "contradicts"` — signal still fires, flagged in dashboard
- No match → `kalshi_alignment: "no_match"` — does not affect signal

## Output (if edge ≥ 0.10)
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
  "sme_reasoning": "Home court + win rate edge",
  "kalshi_probability": 0.61,
  "kalshi_match": true,
  "kalshi_alignment": "confirms"
}
```

Returns `None` if edge < 0.10 or probability is None (stub).

## Edge Color Coding (for dashboard)
- 🟡 10–14% — marginal
- 🟠 15–19% — solid
- 🟢 20%+ — strongest
