"""
serve_dashboard.py — Render static dashboard.html from signals.json.
Self-contained HTML. No CDN dependencies. Dark background. Client-side JS sorting.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SIGNALS_PATH = Path(__file__).parent.parent / "output" / "signals.json"
DASHBOARD_PATH = Path(__file__).parent.parent / "output" / "dashboard.html"


def render_dashboard(signals: list = None, active_sports: list = None, stub_games: dict = None) -> None:
    """
    Render the static dashboard HTML.

    Args:
        signals: List of all signal dicts (from signals.json).
        active_sports: List of currently active sport keys.
        stub_games: Dict mapping sport -> list of game strings for stub sports.
    """
    if signals is None:
        signals = _load_signals()
    if active_sports is None:
        active_sports = []
    if stub_games is None:
        stub_games = {}

    now = datetime.now(timezone.utc)
    generated_at = now.strftime("%Y-%m-%d %H:%M UTC")

    # Separate signals by confidence level and recency
    active_signals = _get_active_signals(signals, now)
    normal_signals = [s for s in active_signals if s.get("confidence") == "normal" and s.get("edge", 0) >= 0.10]
    low_conf_signals = [s for s in active_signals if s.get("confidence") == "low" and s.get("edge", 0) >= 0.10]
    historical = [s for s in signals if s not in active_signals and s.get("result") is not None]

    # Sort by edge descending
    normal_signals.sort(key=lambda x: x.get("edge", 0), reverse=True)
    low_conf_signals.sort(key=lambda x: x.get("edge", 0), reverse=True)
    historical.sort(key=lambda x: x.get("generated_at", ""), reverse=True)

    stub_sports = {s for s in ["nhl", "cbb", "ufc"] if s in active_sports}

    html = _build_html(
        generated_at=generated_at,
        normal_signals=normal_signals,
        low_conf_signals=low_conf_signals,
        historical=historical,
        stub_sports=stub_sports,
        stub_games=stub_games,
    )

    DASHBOARD_PATH.parent.mkdir(exist_ok=True)
    with open(DASHBOARD_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    total = len(normal_signals) + len(low_conf_signals)
    print(f"[serve_dashboard] Dashboard rendered: {total} active signals → {DASHBOARD_PATH}")


def _load_signals() -> list:
    if not SIGNALS_PATH.exists():
        return []
    try:
        with open(SIGNALS_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _get_active_signals(signals: list, now: datetime) -> list:
    active = []
    for sig in signals:
        try:
            commence = datetime.fromisoformat(sig.get("commence_time", "").replace("Z", "+00:00"))
            hours_ago = (now - commence).total_seconds() / 3600
            if hours_ago < 6:
                active.append(sig)
        except Exception:
            pass
    return active


def _edge_color_class(edge: float) -> str:
    if edge >= 0.20:
        return "edge-green"
    elif edge >= 0.15:
        return "edge-orange"
    return "edge-yellow"


def _edge_emoji(edge: float) -> str:
    if edge >= 0.20:
        return "🟢"
    elif edge >= 0.15:
        return "🟠"
    return "🟡"


def _format_commence(time_str: str) -> str:
    try:
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        return dt.strftime("%b %d %I:%M %p UTC")
    except Exception:
        return time_str


def _format_odds(odds: int | float | None) -> str:
    if odds is None:
        return "N/A"
    if odds > 0:
        return f"+{int(odds)}"
    return str(int(odds))


def _signal_row_html(sig: dict, idx: int) -> str:
    edge = sig.get("edge", 0)
    color_class = _edge_color_class(edge)
    emoji = _edge_emoji(edge)
    sport = sig.get("sport", "")
    game = sig.get("game", "")
    book = sig.get("book", "")
    rec = sig.get("recommendation", "")
    our_pct = f"{sig.get('our_probability', 0):.1%}"
    implied_pct = f"{sig.get('implied_probability', 0):.1%}"
    edge_pct = f"{edge:.1%}"
    confidence = sig.get("confidence", "normal")
    commence = _format_commence(sig.get("commence_time", ""))
    reasoning = sig.get("sme_reasoning", "")
    missing = sig.get("missing_factors", [])
    kalshi_align = sig.get("kalshi_alignment", "no_match")
    kalshi_prob = sig.get("kalshi_probability")
    home_odds = _format_odds(sig.get("home_odds"))
    away_odds = _format_odds(sig.get("away_odds"))
    factors = sig.get("factor_deltas", {})

    kalshi_html = ""
    if kalshi_align == "confirms":
        kalshi_html = f'<span class="kalshi-confirm">✓ Kalshi confirms ({kalshi_prob:.1%})</span>' if kalshi_prob else '<span class="kalshi-confirm">✓ Kalshi confirms</span>'
    elif kalshi_align == "contradicts":
        kalshi_html = f'<span class="kalshi-contra">⚠ Kalshi contradicts ({kalshi_prob:.1%})</span>' if kalshi_prob else '<span class="kalshi-contra">⚠ Kalshi contradicts</span>'
    else:
        kalshi_html = '<span class="kalshi-none">— No Kalshi match</span>'

    missing_html = ""
    if missing:
        missing_html = f'<div class="missing-factors">Missing data: {", ".join(missing)}</div>'

    factors_html = ""
    if factors:
        factor_items = []
        for k, v in factors.items():
            sign = "+" if v >= 0 else ""
            factor_items.append(f'<span class="factor-item">{k}: {sign}{v:.3f}</span>')
        factors_html = f'<div class="factor-grid">{"".join(factor_items)}</div>'

    return f"""
    <tr class="signal-row {color_class}" data-sport="{sport}" data-book="{book}" data-edge="{edge}" onclick="toggleRow({idx})">
      <td><span class="sport-badge">{sport}</span></td>
      <td class="game-cell">{game}<div class="game-time">{commence}</div></td>
      <td>{book}</td>
      <td><strong class="{color_class}">{emoji} {edge_pct}</strong></td>
      <td>{our_pct}</td>
      <td>{implied_pct}</td>
      <td><strong>{rec}</strong></td>
    </tr>
    <tr id="detail-{idx}" class="detail-row" style="display:none">
      <td colspan="7">
        <div class="detail-panel">
          <div class="detail-grid">
            <div class="detail-section">
              <h4>Analysis</h4>
              <p>{reasoning}</p>
              {missing_html}
            </div>
            <div class="detail-section">
              <h4>Odds</h4>
              <p>DK/FD Home: <code>{home_odds}</code> | Away: <code>{away_odds}</code></p>
              {kalshi_html}
            </div>
          </div>
          {factors_html}
        </div>
      </td>
    </tr>"""


def _history_row_html(sig: dict) -> str:
    result = sig.get("result", "—")
    result_class = {"W": "result-win", "L": "result-loss", "P": "result-push"}.get(result, "")
    edge = sig.get("edge", 0)
    return f"""
    <tr>
      <td><span class="sport-badge">{sig.get('sport','')}</span></td>
      <td>{sig.get('game','')}</td>
      <td>{sig.get('recommendation','')}</td>
      <td>{edge:.1%}</td>
      <td>{sig.get('book','')}</td>
      <td><span class="{result_class}">{result or '—'}</span></td>
    </tr>"""


def _build_html(generated_at, normal_signals, low_conf_signals, historical, stub_sports, stub_games) -> str:
    total_active = len(normal_signals) + len(low_conf_signals)
    green_count = sum(1 for s in normal_signals + low_conf_signals if s.get("edge", 0) >= 0.20)
    orange_count = sum(1 for s in normal_signals + low_conf_signals if 0.15 <= s.get("edge", 0) < 0.20)
    yellow_count = sum(1 for s in normal_signals + low_conf_signals if 0.10 <= s.get("edge", 0) < 0.15)

    signal_rows_html = ""
    row_idx = 0
    for sig in normal_signals:
        signal_rows_html += _signal_row_html(sig, row_idx)
        row_idx += 1

    low_conf_section = ""
    if low_conf_signals:
        lc_rows = ""
        for sig in low_conf_signals:
            lc_rows += _signal_row_html(sig, row_idx)
            row_idx += 1
        low_conf_section = f"""
        <div class="section-header low-conf-header">
          <h2>⚠ Low Confidence Signals</h2>
          <p class="section-desc">Edge ≥ 10% but missing data — proceed with caution</p>
        </div>
        <table class="signals-table" id="low-conf-table">
          <thead><tr>
            <th>Sport</th><th>Game</th><th>Book</th>
            <th onclick="sortTable('low-conf-table',3)" class="sortable">Edge ▼</th>
            <th>Our %</th><th>Implied %</th><th>Recommendation</th>
          </tr></thead>
          <tbody>{lc_rows}</tbody>
        </table>"""

    stub_section = ""
    if stub_sports:
        stub_items = ""
        for sport in sorted(stub_sports):
            games_for_sport = stub_games.get(sport, [])
            if games_for_sport:
                game_list = "".join(f'<li>{g}</li>' for g in games_for_sport)
                stub_items += f'<div class="stub-sport"><h4>{sport.upper()}</h4><ul>{game_list}</ul></div>'
            else:
                stub_items += f'<div class="stub-sport"><h4>{sport.upper()}</h4><p class="no-games">No games found today</p></div>'
        stub_section = f"""
        <div class="section-header">
          <h2>🚧 Model Coming Soon</h2>
          <p class="section-desc">This sport's model is under development. Signals will appear here when ready.</p>
        </div>
        <div class="stub-grid">{stub_items}</div>"""

    history_rows = "".join(_history_row_html(s) for s in historical[:50])
    history_section = ""
    if historical:
        # Calculate W/L stats
        w = sum(1 for s in historical if s.get("result") == "W")
        l = sum(1 for s in historical if s.get("result") == "L")
        p = sum(1 for s in historical if s.get("result") == "P")
        total = w + l + p
        win_rate = f"{w/total:.1%}" if total > 0 else "—"
        history_section = f"""
        <div class="section-header">
          <h2>📊 Signal History</h2>
          <div class="wl-record">
            <span class="result-win">W: {w}</span>
            <span class="result-loss">L: {l}</span>
            <span class="result-push">P: {p}</span>
            <span>Win Rate: {win_rate}</span>
          </div>
        </div>
        <table class="history-table">
          <thead><tr>
            <th>Sport</th><th>Game</th><th>Pick</th><th>Edge</th><th>Book</th><th>Result</th>
          </tr></thead>
          <tbody>{history_rows}</tbody>
        </table>"""

    empty_state = ""
    if total_active == 0:
        empty_state = '<div class="empty-state"><p>No edges ≥ 10% identified today. Check back after next model run.</p></div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sharper Margins — Edge Dashboard</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  :root {{
    --bg: #0f1117;
    --bg2: #1a1d27;
    --bg3: #22263a;
    --border: #2e3347;
    --text: #e2e8f0;
    --text-muted: #94a3b8;
    --green: #22c55e;
    --orange: #f97316;
    --yellow: #eab308;
    --red: #ef4444;
    --blue: #3b82f6;
    --purple: #a855f7;
    --accent: #6366f1;
  }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    font-size: 14px;
    line-height: 1.5;
    min-height: 100vh;
  }}
  .header {{
    background: var(--bg2);
    border-bottom: 1px solid var(--border);
    padding: 16px 24px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
  }}
  .header h1 {{
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 0.05em;
    color: var(--accent);
  }}
  .header .meta {{ color: var(--text-muted); font-size: 12px; }}
  .stats-bar {{
    background: var(--bg2);
    border-bottom: 1px solid var(--border);
    padding: 10px 24px;
    display: flex;
    gap: 24px;
    align-items: center;
    flex-wrap: wrap;
  }}
  .stat-item {{ display: flex; align-items: center; gap: 6px; }}
  .stat-label {{ color: var(--text-muted); font-size: 12px; }}
  .stat-value {{ font-weight: 600; }}
  .filters {{
    background: var(--bg2);
    border-bottom: 1px solid var(--border);
    padding: 10px 24px;
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
  }}
  .filter-btn {{
    background: var(--bg3);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 4px 12px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 12px;
    transition: all 0.15s;
  }}
  .filter-btn:hover, .filter-btn.active {{
    background: var(--accent);
    border-color: var(--accent);
    color: white;
  }}
  .search-input {{
    background: var(--bg3);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 4px 10px;
    border-radius: 4px;
    font-size: 12px;
    width: 160px;
  }}
  .search-input::placeholder {{ color: var(--text-muted); }}
  .container {{ padding: 20px 24px; max-width: 1400px; margin: 0 auto; }}
  .section-header {{
    margin: 24px 0 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--border);
  }}
  .section-header h2 {{ font-size: 16px; font-weight: 600; }}
  .section-desc {{ color: var(--text-muted); font-size: 12px; margin-top: 4px; }}
  .low-conf-header h2 {{ color: var(--yellow); }}
  .signals-table, .history-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    margin-bottom: 8px;
  }}
  .signals-table th, .history-table th {{
    background: var(--bg3);
    color: var(--text-muted);
    font-weight: 500;
    text-align: left;
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }}
  .sortable {{ cursor: pointer; user-select: none; }}
  .sortable:hover {{ color: var(--text); }}
  .signals-table td, .history-table td {{
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }}
  .signal-row {{ cursor: pointer; transition: background 0.1s; }}
  .signal-row:hover {{ background: var(--bg3); }}
  .sport-badge {{
    display: inline-block;
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 1px 6px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.05em;
    color: var(--text-muted);
  }}
  .game-cell {{ max-width: 220px; }}
  .game-time {{ color: var(--text-muted); font-size: 11px; margin-top: 2px; }}
  .edge-green {{ color: var(--green); }}
  .edge-orange {{ color: var(--orange); }}
  .edge-yellow {{ color: var(--yellow); }}
  .detail-row td {{ padding: 0; }}
  .detail-panel {{
    background: var(--bg3);
    border-left: 3px solid var(--accent);
    padding: 16px 20px;
    font-size: 13px;
  }}
  .detail-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-bottom: 12px;
  }}
  @media (max-width: 700px) {{ .detail-grid {{ grid-template-columns: 1fr; }} }}
  .detail-section h4 {{ font-size: 12px; color: var(--text-muted); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.08em; }}
  .factor-grid {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 8px;
  }}
  .factor-item {{
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 2px 8px;
    font-size: 11px;
    font-family: monospace;
  }}
  .kalshi-confirm {{ color: var(--green); font-size: 12px; }}
  .kalshi-contra {{ color: var(--yellow); font-size: 12px; }}
  .kalshi-none {{ color: var(--text-muted); font-size: 12px; }}
  .missing-factors {{
    color: var(--yellow);
    font-size: 11px;
    margin-top: 6px;
  }}
  code {{
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 1px 5px;
    font-family: monospace;
    font-size: 12px;
  }}
  .stub-grid {{
    display: flex;
    gap: 16px;
    flex-wrap: wrap;
    margin-bottom: 16px;
  }}
  .stub-sport {{
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px 16px;
    min-width: 200px;
  }}
  .stub-sport h4 {{
    font-size: 13px;
    font-weight: 600;
    color: var(--text-muted);
    margin-bottom: 8px;
  }}
  .stub-sport ul {{ list-style: none; padding: 0; }}
  .stub-sport li {{ font-size: 12px; padding: 3px 0; border-bottom: 1px solid var(--border); }}
  .stub-sport li:last-child {{ border-bottom: none; }}
  .no-games {{ color: var(--text-muted); font-size: 12px; }}
  .wl-record {{
    display: flex;
    gap: 16px;
    margin-top: 6px;
    font-size: 13px;
  }}
  .result-win {{ color: var(--green); font-weight: 600; }}
  .result-loss {{ color: var(--red); font-weight: 600; }}
  .result-push {{ color: var(--text-muted); font-weight: 600; }}
  .empty-state {{
    text-align: center;
    padding: 48px 24px;
    color: var(--text-muted);
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 6px;
    margin: 16px 0;
  }}
  .hidden {{ display: none !important; }}
</style>
</head>
<body>

<div class="header">
  <h1>SHARPER MARGINS</h1>
  <div class="meta">Generated: {generated_at}</div>
</div>

<div class="stats-bar">
  <div class="stat-item">
    <span class="stat-label">Active Signals:</span>
    <span class="stat-value">{total_active}</span>
  </div>
  <div class="stat-item">
    <span class="stat-label">🟢 20%+:</span>
    <span class="stat-value edge-green">{green_count}</span>
  </div>
  <div class="stat-item">
    <span class="stat-label">🟠 15–19%:</span>
    <span class="stat-value edge-orange">{orange_count}</span>
  </div>
  <div class="stat-item">
    <span class="stat-label">🟡 10–14%:</span>
    <span class="stat-value edge-yellow">{yellow_count}</span>
  </div>
</div>

<div class="filters" id="filters">
  <button class="filter-btn active" onclick="filterSport('all', this)">All Sports</button>
  <button class="filter-btn" onclick="filterSport('NFL', this)">NFL</button>
  <button class="filter-btn" onclick="filterSport('CFB', this)">CFB</button>
  <button class="filter-btn" onclick="filterSport('NBA', this)">NBA</button>
  <button class="filter-btn" onclick="filterSport('MLB', this)">MLB</button>
  <button class="filter-btn" onclick="filterSport('NHL', this)">NHL</button>
  <button class="filter-btn" onclick="filterSport('CBB', this)">CBB</button>
  <span style="color:var(--text-muted); padding: 0 4px;">|</span>
  <button class="filter-btn active-book" onclick="filterBook('all', this)">All Books</button>
  <button class="filter-btn" onclick="filterBook('DraftKings', this)">DraftKings</button>
  <button class="filter-btn" onclick="filterBook('FanDuel', this)">FanDuel</button>
  <span style="color:var(--text-muted); padding: 0 4px;">|</span>
  <input class="search-input" type="text" placeholder="Search teams..." oninput="searchSignals(this.value)">
</div>

<div class="container">

  <div class="section-header">
    <h2>Active Signals</h2>
    <p class="section-desc">Edges ≥ 10% — our estimated probability vs vig-adjusted implied. Click row to expand.</p>
  </div>

  {empty_state}

  {"" if total_active == 0 else f'''
  <table class="signals-table" id="main-table">
    <thead><tr>
      <th>Sport</th>
      <th>Game</th>
      <th>Book</th>
      <th onclick="sortTable(\'main-table\',3)" class="sortable">Edge ▼</th>
      <th>Our %</th>
      <th>Implied %</th>
      <th>Recommendation</th>
    </tr></thead>
    <tbody id="main-tbody">
{signal_rows_html}
    </tbody>
  </table>'''}

  {low_conf_section}

  {stub_section}

  {history_section}

</div>

<script>
var openRow = null;
function toggleRow(idx) {{
  var row = document.getElementById('detail-' + idx);
  if (!row) return;
  if (openRow !== null && openRow !== idx) {{
    var prev = document.getElementById('detail-' + openRow);
    if (prev) prev.style.display = 'none';
  }}
  row.style.display = (row.style.display === 'none') ? 'table-row' : 'none';
  openRow = (row.style.display === 'none') ? null : idx;
}}

var activeSport = 'all';
var activeBook = 'all';
var searchTerm = '';

function filterSport(sport, btn) {{
  activeSport = sport;
  document.querySelectorAll('.filter-btn').forEach(function(b) {{
    if (b.textContent.replace(/\\s/g,'') === sport || (sport === 'all' && b.textContent.trim() === 'All Sports')) {{
      b.classList.add('active');
    }} else if (b.onclick && b.onclick.toString().includes('filterSport')) {{
      b.classList.remove('active');
    }}
  }});
  applyFilters();
}}

function filterBook(book, btn) {{
  activeBook = book;
  document.querySelectorAll('.filter-btn').forEach(function(b) {{
    if (b.onclick && b.onclick.toString().includes('filterBook')) {{
      b.classList.toggle('active', b.textContent.trim().replace(' ', '') === book || (book === 'all' && b.textContent.trim() === 'All Books'));
    }}
  }});
  applyFilters();
}}

function searchSignals(val) {{
  searchTerm = val.toLowerCase();
  applyFilters();
}}

function applyFilters() {{
  document.querySelectorAll('.signal-row').forEach(function(row) {{
    var sport = row.dataset.sport || '';
    var book = row.dataset.book || '';
    var text = row.textContent.toLowerCase();
    var idx = row.getAttribute('onclick').match(/\\d+/);
    var sportMatch = activeSport === 'all' || sport === activeSport;
    var bookMatch = activeBook === 'all' || book === activeBook;
    var searchMatch = !searchTerm || text.includes(searchTerm);
    var visible = sportMatch && bookMatch && searchMatch;
    row.style.display = visible ? '' : 'none';
    if (!visible && idx) {{
      var detail = document.getElementById('detail-' + idx[0]);
      if (detail) detail.style.display = 'none';
    }}
  }});
}}

function sortTable(tableId, colIdx) {{
  var table = document.getElementById(tableId);
  if (!table) return;
  var tbody = table.querySelector('tbody');
  var rows = Array.from(tbody.querySelectorAll('tr.signal-row'));
  var details = {{}};
  rows.forEach(function(r) {{
    var m = r.getAttribute('onclick').match(/\\d+/);
    if (m) {{
      var d = document.getElementById('detail-' + m[0]);
      if (d) details[m[0]] = d;
    }}
  }});
  rows.sort(function(a, b) {{
    var ea = parseFloat(a.dataset.edge) || 0;
    var eb = parseFloat(b.dataset.edge) || 0;
    return eb - ea;
  }});
  rows.forEach(function(r) {{
    tbody.appendChild(r);
    var m = r.getAttribute('onclick').match(/\\d+/);
    if (m && details[m[0]]) tbody.appendChild(details[m[0]]);
  }});
}}
</script>

</body>
</html>"""


if __name__ == "__main__":
    render_dashboard()
