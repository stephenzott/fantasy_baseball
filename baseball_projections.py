"""
Baseball Projection Analyzer
-----------------------------
- Preseason: local CSV (e.g. FanGraphs Steamer preseason)
- Current:   local CSV (e.g. FanGraphs ZiPS update)
- Output:    Buy / Sell / Hold signals based on stat deltas

Usage in Jupyter:
    from baseball_projections import run
    df = run(
        pre_csv="fangraphs-preseason-hitters-projections-2026.csv",
        cur_csv="fangraphs-hitters-current.csv",
        pos="hitter",
        stat="HR",
        buy=3,
        sell=-3
    )
"""

import argparse
import pandas as pd

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HITTER_STATS  = ["WAR", "HR", "R", "RBI", "SB", "AVG", "OBP", "SLG", "wRC+"]
PITCHER_STATS = ["WAR", "ERA", "WHIP", "W", "K", "K/BB", "SV", "IP"]
LOWER_IS_BETTER = {"ERA", "WHIP"}

HITTER_EMBED_STATS  = ["HR", "R", "RBI", "SB", "AVG", "OBP"]
PITCHER_EMBED_STATS = ["W", "ERA", "K", "K/BB", "WHIP"]


# ---------------------------------------------------------------------------
# 1. Load CSV
# ---------------------------------------------------------------------------

def load_csv(csv_path: str, pos: str, label: str = "") -> pd.DataFrame:
    """Load a FanGraphs projection CSV and normalise column names."""
    df = pd.read_csv(csv_path)

    rename = {
        "playerid":   "player_id",
        "PlayerId":   "player_id",
        "Name":       "name",
        "PlayerName": "name",
        "Team":       "team",
        "SO":         "K",
        "K/9":        "K9",
        "BB/9":       "BB9",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    stat_cols = HITTER_STATS if pos == "hitter" else PITCHER_STATS
    for col in stat_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    tag = f" ({label})" if label else ""
    print(f"  Loaded{tag}: {len(df)} players from {csv_path}")
    return df


# ---------------------------------------------------------------------------
# 2. Merge & compute delta
# ---------------------------------------------------------------------------

def compute_delta(pre: pd.DataFrame, cur: pd.DataFrame, pos: str, stat: str) -> pd.DataFrame:
    """
    Match players by player_id (FanGraphs ID), fall back to name matching.
    Computes delta = current - preseason for the chosen stat.
    """
    stat_cols = HITTER_STATS if pos == "hitter" else PITCHER_STATS
    if stat not in stat_cols:
        raise ValueError(f"'{stat}' not available. Choose from: {stat_cols}")

    # Prefer joining on player_id since both CSVs are from FanGraphs
    if "player_id" in pre.columns and "player_id" in cur.columns:
        # Convert player_id to string to ensure consistent types for merging
        pre["player_id"] = pre["player_id"].astype(str)
        cur["player_id"] = cur["player_id"].astype(str)
        pre_slim = pre[["player_id", "name", "team", stat]].rename(columns={stat: "pre"})
        cur_slim = cur[["player_id", "team", stat]].rename(columns={stat: "cur", "team": "team_cur"})
        merged = pre_slim.merge(cur_slim, on="player_id", how="inner")
        print(f"  Matched on player_id: {len(merged)} players")
    else:
        # Fall back to normalised name matching
        def norm(s):
            return str(s).lower().strip().replace(".", "").replace("-", " ")
        pre = pre.copy()
        cur = cur.copy()
        pre["_key"] = pre["name"].apply(norm)
        cur["_key"] = cur["name"].apply(norm)
        pre_slim = pre[["_key", "name", "team", stat]].rename(columns={stat: "pre"})
        cur_slim = cur[["_key", "team", stat]].rename(columns={stat: "cur", "team": "team_cur"})
        merged = pre_slim.merge(cur_slim, on="_key", how="inner")
        merged.drop(columns=["_key"], inplace=True)
        print(f"  Matched on name: {len(merged)} players")

    merged["team"] = merged["team_cur"].fillna(merged["team"])
    merged.drop(columns=["team_cur"], inplace=True)

    merged["delta"] = merged["cur"] - merged["pre"]
    merged = merged.dropna(subset=["delta"])
    merged = merged.sort_values("delta", ascending=False).reset_index(drop=True)
    return merged


# ---------------------------------------------------------------------------
# 3. Signal generation
# ---------------------------------------------------------------------------

def add_signals(df: pd.DataFrame, stat: str, buy: float, sell: float) -> pd.DataFrame:
    higher_better = stat not in LOWER_IS_BETTER

    def signal(delta):
        eff = -delta if not higher_better else delta
        if eff >= buy:  return "BUY"
        if eff <= sell: return "SELL"
        return "HOLD"

    df = df.copy()
    df["signal"] = df["delta"].apply(signal)
    return df


# ---------------------------------------------------------------------------
# 4. Report
# ---------------------------------------------------------------------------

def print_report(df: pd.DataFrame, stat: str, top_n: int = 30) -> None:
    colors = {"BUY": "\033[92m", "SELL": "\033[91m", "HOLD": "\033[93m"}
    reset  = "\033[0m"

    print(f"\n{'='*68}")
    print(f"  Projection delta — {stat}")
    print(f"{'='*68}")
    print(f"  {'Player':<24} {'Tm':<5} {'Pre':>7} {'Cur':>7} {'Δ':>8}  Signal")
    print(f"  {'-'*24} {'-'*5} {'-'*7} {'-'*7} {'-'*8}  ------")

    for _, r in df.head(top_n).iterrows():
        c = colors.get(r["signal"], "")
        print(
            f"  {r['name']:<24} {r.get('team',''):<5} "
            f"{r['pre']:>7.2f} {r['cur']:>7.2f} {r['delta']:>+8.2f}  "
            f"{c}{r['signal']}{reset}"
        )

    buys  = (df["signal"] == "BUY").sum()
    sells = (df["signal"] == "SELL").sum()
    holds = (df["signal"] == "HOLD").sum()
    print(f"\n  {buys} BUY  |  {holds} HOLD  |  {sells} SELL   (of {len(df)} matched)")
    print(f"{'='*68}\n")


# ---------------------------------------------------------------------------
# 5. run() — call this from Jupyter
# ---------------------------------------------------------------------------

def run(
    pre_csv: str,
    cur_csv: str,
    pos: str    = "hitter",
    stat: str   = "HR",
    buy: float  = 3.0,
    sell: float = -3.0,
    top_n: int  = 30,
    export: str = None,
) -> pd.DataFrame:
    """
    Full pipeline. Returns the merged DataFrame with signals.

    Example:
        from baseball_projections import run
        df = run(
            pre_csv="fangraphs-preseason-projections-2026.csv",
            cur_csv="fangraphs-may4-projection.csv",
            pos="hitter",
            stat="HR",
            buy=3,
            sell=-3
        )
        df[df.signal == "BUY"]
    """
    print(f"\nRunning: {pos} | stat={stat} | buy≥{buy:+} sell≤{sell:+}\n")

    pre = load_csv(pre_csv, pos, label="preseason")
    cur = load_csv(cur_csv, pos, label="current")
    df  = compute_delta(pre, cur, pos, stat)
    df  = add_signals(df, stat, buy, sell)

    print_report(df, stat, top_n)

    if export:
        df.to_csv(export, index=False)
        print(f"  Saved to {export}")

    return df


# ---------------------------------------------------------------------------
# 6. HTML generation
# ---------------------------------------------------------------------------

_OF_POSITIONS  = {"LF", "CF", "RF"}
_DH_POSITIONS  = {"TWP"}  # two-way players bat as DH

def fetch_positions(mlbam_ids: list, batch_size: int = 200) -> dict:
    """Return {mlbam_id_str: position_abbr} via the free MLB Stats API."""
    import urllib.request
    result = {}
    ids = [i for i in mlbam_ids if i and str(i) not in ("", "nan", "0")]
    for start in range(0, len(ids), batch_size):
        chunk = ids[start:start + batch_size]
        url = "https://statsapi.mlb.com/api/v1/people?personIds=" + ",".join(str(i) for i in chunk)
        with urllib.request.urlopen(url, timeout=15) as resp:
            import json
            data = json.loads(resp.read())
        for person in data.get("people", []):
            pos = person.get("primaryPosition", {}).get("abbreviation", "")
            if pos in _OF_POSITIONS:
                pos = "OF"
            elif pos in _DH_POSITIONS:
                pos = "DH"
            result[str(person["id"])] = pos
    print(f"  Fetched positions for {len(result)} players from MLB Stats API")
    return result


def build_embed_data(pre_csv: str, cur_csv: str, pos: str, stats: list, fetch_pos: bool = False) -> list:
    """Load two CSVs and return a list of player dicts for HTML embedding."""
    pre = load_csv(pre_csv, pos, label="preseason")
    cur = load_csv(cur_csv, pos, label="current")

    pre["player_id"] = pre["player_id"].astype(str)
    cur["player_id"] = cur["player_id"].astype(str)

    avail_stats = [s for s in stats if s in pre.columns and s in cur.columns]

    # Carry MLBAMID from cur for position lookup (cur has fresher roster data)
    cur_cols = ["player_id"] + avail_stats
    if fetch_pos and "MLBAMID" in cur.columns:
        cur["mlbam_id"] = cur["MLBAMID"].astype(str)
        cur_cols.append("mlbam_id")

    pre_slim = pre[["player_id", "name", "team"] + avail_stats]
    cur_slim = cur[cur_cols]

    merged = pre_slim.merge(cur_slim, on="player_id", how="inner", suffixes=("_pre", "_cur"))

    position_map = {}
    if fetch_pos and "mlbam_id" in merged.columns:
        mlbam_ids = merged["mlbam_id"].dropna().unique().tolist()
        position_map = fetch_positions(mlbam_ids)

    players = []
    for _, row in merged.iterrows():
        stat_data = {}
        for stat in avail_stats:
            pre_val = row.get(f"{stat}_pre")
            cur_val = row.get(f"{stat}_cur")
            if pd.notna(pre_val) and pd.notna(cur_val):
                stat_data[stat] = {"pre": round(float(pre_val), 6), "cur": round(float(cur_val), 6)}
        if stat_data:
            entry = {
                "player_id": str(row["player_id"]),
                "name":      str(row["name"]),
                "team":      str(row["team"]) if pd.notna(row["team"]) else "",
                "stats":     stat_data,
            }
            if fetch_pos and "mlbam_id" in row:
                entry["pos"] = position_map.get(str(row["mlbam_id"]), "")
            players.append(entry)
    return players


def generate_html(
    hitter_pre_csv:  str,
    hitter_cur_csv:  str,
    pitcher_pre_csv: str,
    pitcher_cur_csv: str,
    output_file: str = "baseball_analyzer_interactive.html",
    subtitle: str    = None,
) -> None:
    """Generate a self-contained two-tab HTML analyzer with embedded JSON data."""
    import json, datetime

    print("Building hitter data (fetching positions from MLB API)...")
    hitters = build_embed_data(hitter_pre_csv, hitter_cur_csv, "hitter", HITTER_EMBED_STATS, fetch_pos=True)
    print("Building pitcher data...")
    pitchers = build_embed_data(pitcher_pre_csv, pitcher_cur_csv, "pitcher", PITCHER_EMBED_STATS)

    hitters_json  = json.dumps(hitters,  separators=(',', ':'))
    pitchers_json = json.dumps(pitchers, separators=(',', ':'))

    today = datetime.date.today().strftime("%B %-d, %Y")
    sub   = subtitle or f"Preseason vs Current ({today}) · Interactive Thresholds"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Baseball Projection Analyzer</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Bebas+Neue&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #0d0f14;
    --surface: #13161e;
    --border: #1e2230;
    --text: #e8eaf0;
    --muted: #5a6070;
    --buy: #22c97a;
    --sell: #f04060;
    --hold: #f0a030;
    --buy-bg: rgba(34,201,122,0.08);
    --sell-bg: rgba(240,64,96,0.08);
    --hold-bg: rgba(240,160,48,0.08);
    --accent: #4f8fff;
  }}

  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'DM Sans', sans-serif;
    font-size: 14px;
    min-height: 100vh;
  }}

  body::before {{
    content: '';
    position: fixed;
    inset: 0;
    background-image:
      linear-gradient(rgba(255,255,255,0.015) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255,255,255,0.015) 1px, transparent 1px);
    background-size: 40px 40px;
    pointer-events: none;
    z-index: 0;
  }}

  .wrap {{ position: relative; z-index: 1; max-width: 1100px; margin: 0 auto; padding: 40px 24px 80px; }}

  .header {{ margin-bottom: 32px; border-bottom: 1px solid var(--border); padding-bottom: 24px; }}
  .logo {{ font-family: 'Bebas Neue', sans-serif; font-size: 48px; letter-spacing: 2px; color: var(--text); line-height: 1; }}
  .subtitle {{ font-size: 12px; color: var(--muted); font-family: 'DM Mono', monospace; margin-top: 8px; letter-spacing: 1px; }}
  .date-badge {{ font-family: 'DM Mono', monospace; font-size: 11px; color: var(--muted); margin-top: 4px; }}

  .tabs {{
    display: flex;
    gap: 4px;
    margin-bottom: 20px;
    border-bottom: 1px solid var(--border);
    padding-bottom: 0;
  }}

  .tab-btn {{
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--muted);
    cursor: pointer;
    font-family: 'DM Mono', monospace;
    font-size: 12px;
    font-weight: 500;
    letter-spacing: 1px;
    padding: 10px 20px;
    text-transform: uppercase;
    transition: color 0.2s, border-color 0.2s;
    margin-bottom: -1px;
  }}

  .tab-btn:hover {{ color: var(--text); }}
  .tab-btn.active {{ color: var(--accent); border-bottom-color: var(--accent); }}

  .controls {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 24px;
  }}

  .control-row {{
    display: flex;
    gap: 20px;
    align-items: flex-end;
    flex-wrap: wrap;
  }}

  .control-group {{
    display: flex;
    flex-direction: column;
    gap: 8px;
  }}

  .control-group label {{
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 1px;
  }}

  select, input[type="number"] {{
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--text);
    font-family: 'DM Sans', sans-serif;
    font-size: 13px;
    padding: 8px 12px;
    border-radius: 6px;
    outline: none;
    transition: border-color 0.2s;
  }}

  select:hover, select:focus, input[type="number"]:hover, input[type="number"]:focus {{
    border-color: var(--accent);
  }}

  input[type="number"] {{
    width: 100px;
    font-family: 'DM Mono', monospace;
  }}

  .summary {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin-bottom: 24px;
  }}

  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    text-align: center;
  }}

  .card-label {{
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 8px;
  }}

  .card-value {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 32px;
    letter-spacing: 1px;
  }}

  .card.total .card-value {{ color: var(--text); }}
  .card.buy   .card-value {{ color: var(--buy); }}
  .card.hold  .card-value {{ color: var(--hold); }}
  .card.sell  .card-value {{ color: var(--sell); }}

  .section-title {{
    font-family: 'DM Mono', monospace;
    font-size: 11px;
    font-weight: 500;
    color: var(--muted);
    letter-spacing: 2px;
    text-transform: uppercase;
    margin: 28px 0 12px;
  }}

  table {{
    width: 100%;
    border-collapse: collapse;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
  }}

  thead {{ background: rgba(255,255,255,0.02); }}
  th {{
    padding: 10px 14px;
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    font-weight: 500;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 1px;
    text-align: left;
    border-bottom: 1px solid var(--border);
  }}

  tbody tr {{ border-bottom: 1px solid rgba(255,255,255,0.03); }}
  tbody tr:hover {{ background: rgba(255,255,255,0.03); }}

  td {{ padding: 11px 14px; font-size: 13px; }}
  td.name {{ font-weight: 500; color: var(--text); }}
  td.team {{ font-family: 'DM Mono', monospace; font-size: 11px; color: var(--muted); }}
  td.num  {{ font-family: 'DM Mono', monospace; text-align: right; color: var(--muted); }}
  td.delta {{ font-family: 'DM Mono', monospace; font-weight: 500; text-align: right; }}
  td.delta.pos {{ color: var(--buy); }}
  td.delta.neg {{ color: var(--sell); }}

  .signal-pill {{
    display: inline-block;
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    font-weight: 500;
    letter-spacing: 1px;
    padding: 3px 10px;
    border-radius: 4px;
    text-transform: uppercase;
  }}
  .signal-pill.BUY  {{ background: var(--buy-bg);  color: var(--buy);  border: 1px solid rgba(34,201,122,0.25); }}
  .signal-pill.SELL {{ background: var(--sell-bg); color: var(--sell); border: 1px solid rgba(240,64,96,0.25); }}
  .signal-pill.HOLD {{ background: var(--hold-bg); color: var(--hold); border: 1px solid rgba(240,160,48,0.25); }}
</style>
</head>
<body>
<div class="wrap">

  <div class="header">
    <div class="logo">Baseball Projection Analyzer</div>
    <div class="subtitle">{sub}</div>
    <div class="date-badge" id="generated-date"></div>
  </div>

  <div class="tabs">
    <button class="tab-btn active" onclick="switchTab('hitters')">Hitters</button>
    <button class="tab-btn" onclick="switchTab('pitchers')">Pitchers</button>
  </div>

  <!-- HITTER SECTION -->
  <div id="hitter-section">
    <div class="controls">
      <div class="control-row">
        <div class="control-group">
          <label for="h-stat-select">Stat</label>
          <select id="h-stat-select" onchange="updateAnalysis('hitter')">
            <option value="HR">Home Runs (HR)</option>
            <option value="R">Runs (R)</option>
            <option value="RBI">RBI</option>
            <option value="SB">Stolen Bases (SB)</option>
            <option value="AVG">Batting Average (AVG)</option>
            <option value="OBP">On-Base Percentage (OBP)</option>
          </select>
        </div>
        <div class="control-group">
          <label for="h-pos-filter">Position</label>
          <select id="h-pos-filter" onchange="updateAnalysis('hitter')">
            <option value="">All</option>
            <option value="C">C</option>
            <option value="1B">1B</option>
            <option value="2B">2B</option>
            <option value="3B">3B</option>
            <option value="SS">SS</option>
            <option value="OF">OF</option>
            <option value="DH">DH</option>
          </select>
        </div>
        <div class="control-group">
          <label for="h-buy-threshold">Buy Threshold ≥</label>
          <input type="number" id="h-buy-threshold" value="3" step="0.5" onchange="updateAnalysis('hitter')">
        </div>
        <div class="control-group">
          <label for="h-sell-threshold">Sell Threshold ≤</label>
          <input type="number" id="h-sell-threshold" value="-3" step="0.5" onchange="updateAnalysis('hitter')">
        </div>
      </div>
    </div>

    <div class="summary">
      <div class="card total"><div class="card-label">Total Players</div><div class="card-value" id="h-sum-total">-</div></div>
      <div class="card buy"><div class="card-label">Buy Signals</div><div class="card-value" id="h-sum-buy">-</div></div>
      <div class="card hold"><div class="card-label">Hold</div><div class="card-value" id="h-sum-hold">-</div></div>
      <div class="card sell"><div class="card-label">Sell Signals</div><div class="card-value" id="h-sum-sell">-</div></div>
    </div>
    <div id="hitter-content"></div>
  </div>

  <!-- PITCHER SECTION -->
  <div id="pitcher-section" style="display:none">
    <div class="controls">
      <div class="control-row">
        <div class="control-group">
          <label for="p-stat-select">Stat</label>
          <select id="p-stat-select" onchange="updateAnalysis('pitcher')">
            <option value="W">Wins (W)</option>
            <option value="ERA">ERA</option>
            <option value="K">Strikeouts (K)</option>
            <option value="K/BB">K/BB Ratio</option>
            <option value="WHIP">WHIP</option>
          </select>
        </div>
        <div class="control-group">
          <label for="p-buy-threshold">Buy Threshold ≥</label>
          <input type="number" id="p-buy-threshold" value="1" step="0.5" onchange="updateAnalysis('pitcher')">
        </div>
        <div class="control-group">
          <label for="p-sell-threshold">Sell Threshold ≤</label>
          <input type="number" id="p-sell-threshold" value="-1" step="0.5" onchange="updateAnalysis('pitcher')">
        </div>
      </div>
    </div>

    <div class="summary">
      <div class="card total"><div class="card-label">Total Pitchers</div><div class="card-value" id="p-sum-total">-</div></div>
      <div class="card buy"><div class="card-label">Buy Signals</div><div class="card-value" id="p-sum-buy">-</div></div>
      <div class="card hold"><div class="card-label">Hold</div><div class="card-value" id="p-sum-hold">-</div></div>
      <div class="card sell"><div class="card-label">Sell Signals</div><div class="card-value" id="p-sum-sell">-</div></div>
    </div>
    <div id="pitcher-content"></div>
  </div>

</div>

<script>
const HITTERS_DATA = {hitters_json};
const PITCHERS_DATA = {pitchers_json};

const HITTER_STAT_INFO = {{
  'HR':  {{ label: 'Home Runs',           decimals: 0, defaultBuy: 3,     defaultSell: -3,     step: '0.5',  lowerBetter: false }},
  'R':   {{ label: 'Runs',                decimals: 0, defaultBuy: 5,     defaultSell: -5,     step: '0.5',  lowerBetter: false }},
  'RBI': {{ label: 'RBI',                 decimals: 0, defaultBuy: 5,     defaultSell: -5,     step: '0.5',  lowerBetter: false }},
  'SB':  {{ label: 'Stolen Bases',        decimals: 0, defaultBuy: 3,     defaultSell: -3,     step: '0.5',  lowerBetter: false }},
  'AVG': {{ label: 'Batting Average',     decimals: 3, defaultBuy: 0.010, defaultSell: -0.010, step: '0.001',lowerBetter: false }},
  'OBP': {{ label: 'On-Base Percentage',  decimals: 3, defaultBuy: 0.010, defaultSell: -0.010, step: '0.001',lowerBetter: false }},
}};

const PITCHER_STAT_INFO = {{
  'W':    {{ label: 'Wins',         decimals: 1, defaultBuy: 1,    defaultSell: -1,    step: '0.5',  lowerBetter: false }},
  'ERA':  {{ label: 'ERA',          decimals: 2, defaultBuy: 0.25, defaultSell: -0.25, step: '0.01', lowerBetter: true  }},
  'K':    {{ label: 'Strikeouts',   decimals: 0, defaultBuy: 15,   defaultSell: -15,   step: '5',    lowerBetter: false }},
  'K/BB': {{ label: 'K/BB Ratio',   decimals: 2, defaultBuy: 0.5,  defaultSell: -0.5,  step: '0.1',  lowerBetter: false }},
  'WHIP': {{ label: 'WHIP',         decimals: 3, defaultBuy: 0.05, defaultSell: -0.05, step: '0.01', lowerBetter: true  }},
}};

let activeTab = 'hitters';

function switchTab(tab) {{
  activeTab = tab;
  document.getElementById('hitter-section').style.display = tab === 'hitters' ? '' : 'none';
  document.getElementById('pitcher-section').style.display = tab === 'pitchers' ? '' : 'none';
  document.querySelectorAll('.tab-btn').forEach((btn, i) => {{
    btn.classList.toggle('active', (i === 0) === (tab === 'hitters'));
  }});
}}

function updateAnalysis(pos) {{
  if (pos === 'hitter') {{
    const stat      = document.getElementById('h-stat-select').value;
    const info      = HITTER_STAT_INFO[stat];
    const buy       = parseFloat(document.getElementById('h-buy-threshold').value);
    const sell      = parseFloat(document.getElementById('h-sell-threshold').value);
    const posFilter = document.getElementById('h-pos-filter').value;
    document.getElementById('h-buy-threshold').step  = info.step;
    document.getElementById('h-sell-threshold').step = info.step;
    calculateAndDisplay(HITTERS_DATA, stat, info, buy, sell, 'hitter', posFilter);
  }} else {{
    const stat = document.getElementById('p-stat-select').value;
    const info = PITCHER_STAT_INFO[stat];
    const buy  = parseFloat(document.getElementById('p-buy-threshold').value);
    const sell = parseFloat(document.getElementById('p-sell-threshold').value);
    document.getElementById('p-buy-threshold').step  = info.step;
    document.getElementById('p-sell-threshold').step = info.step;
    calculateAndDisplay(PITCHERS_DATA, stat, info, buy, sell, 'pitcher', '');
  }}
}}

function calculateAndDisplay(data, stat, info, buyThreshold, sellThreshold, prefix, posFilter) {{
  const decimals = info.decimals;
  const results = [];

  data.forEach(player => {{
    if (!player.stats[stat]) return;
    if (posFilter && player.pos !== posFilter) return;
    const pre   = player.stats[stat].pre;
    const cur   = player.stats[stat].cur;
    const delta = cur - pre;
    const eff   = info.lowerBetter ? -delta : delta;

    let signal;
    if (eff >= buyThreshold)  signal = 'BUY';
    else if (eff <= sellThreshold) signal = 'SELL';
    else                           signal = 'HOLD';

    results.push({{ name: player.name, team: player.team, pos: player.pos || '', pre, cur, delta, signal }});
  }});

  const counts = {{ BUY: 0, SELL: 0, HOLD: 0 }};
  results.forEach(r => counts[r.signal]++);
  document.getElementById(`${{prefix[0]}}-sum-total`).textContent = results.length;
  document.getElementById(`${{prefix[0]}}-sum-buy`).textContent  = counts.BUY;
  document.getElementById(`${{prefix[0]}}-sum-sell`).textContent = counts.SELL;
  document.getElementById(`${{prefix[0]}}-sum-hold`).textContent = counts.HOLD;
  document.getElementById('generated-date').textContent =
    `Generated: ${{new Date().toLocaleDateString('en-US', {{ month: 'short', day: 'numeric', year: 'numeric' }})}}`;

  const buys  = results.filter(r => r.signal === 'BUY').sort((a, b) =>
    info.lowerBetter ? a.delta - b.delta : b.delta - a.delta);
  const sells = results.filter(r => r.signal === 'SELL').sort((a, b) =>
    info.lowerBetter ? b.delta - a.delta : a.delta - b.delta);

  const buyLabel  = info.lowerBetter ? 'Improving' : 'Trending Up';
  const sellLabel = info.lowerBetter ? 'Declining'  : 'Trending Down';

  let html = '';

  if (buys.length > 0) {{
    html += `
      <div class="section-title">🔥 Buy Signals (${{buys.length}}) — ${{info.label}} ${{buyLabel}}</div>
      <table>
        <thead><tr>
          <th>Player</th><th>Team</th><th>Pos</th>
          <th style="text-align:right">Preseason</th>
          <th style="text-align:right">Current</th>
          <th style="text-align:right">Change</th>
          <th>Signal</th>
        </tr></thead><tbody>`;
    buys.forEach(r => {{
      const sign = r.delta >= 0 ? '+' : '';
      const cls  = r.delta >= 0 ? 'pos' : 'neg';
      html += `<tr>
        <td class="name">${{r.name}}</td>
        <td class="team">${{r.team}}</td>
        <td class="team">${{r.pos}}</td>
        <td class="num">${{r.pre.toFixed(decimals)}}</td>
        <td class="num">${{r.cur.toFixed(decimals)}}</td>
        <td class="delta ${{cls}}">${{sign}}${{r.delta.toFixed(decimals)}}</td>
        <td><span class="signal-pill BUY">BUY</span></td>
      </tr>`;
    }});
    html += `</tbody></table>`;
  }}

  if (sells.length > 0) {{
    html += `
      <div class="section-title">📉 Sell Signals (${{sells.length}}) — ${{info.label}} ${{sellLabel}}</div>
      <table>
        <thead><tr>
          <th>Player</th><th>Team</th><th>Pos</th>
          <th style="text-align:right">Preseason</th>
          <th style="text-align:right">Current</th>
          <th style="text-align:right">Change</th>
          <th>Signal</th>
        </tr></thead><tbody>`;
    sells.forEach(r => {{
      const sign = r.delta >= 0 ? '+' : '';
      const cls  = r.delta >= 0 ? 'pos' : 'neg';
      html += `<tr>
        <td class="name">${{r.name}}</td>
        <td class="team">${{r.team}}</td>
        <td class="team">${{r.pos}}</td>
        <td class="num">${{r.pre.toFixed(decimals)}}</td>
        <td class="num">${{r.cur.toFixed(decimals)}}</td>
        <td class="delta ${{cls}}">${{sign}}${{r.delta.toFixed(decimals)}}</td>
        <td><span class="signal-pill SELL">SELL</span></td>
      </tr>`;
    }});
    html += `</tbody></table>`;
  }}

  document.getElementById(`${{prefix}}-content`).innerHTML = html;
}}

// Sync stat dropdown changes to reset thresholds
document.getElementById('h-stat-select').addEventListener('change', function() {{
  const info = HITTER_STAT_INFO[this.value];
  document.getElementById('h-buy-threshold').value  = info.defaultBuy;
  document.getElementById('h-sell-threshold').value = info.defaultSell;
}});

document.getElementById('p-stat-select').addEventListener('change', function() {{
  const info = PITCHER_STAT_INFO[this.value];
  document.getElementById('p-buy-threshold').value  = info.defaultBuy;
  document.getElementById('p-sell-threshold').value = info.defaultSell;
}});

updateAnalysis('hitter');
updateAnalysis('pitcher');
</script>
</body>
</html>"""

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"\nGenerated {output_file} ({len(hitters)} hitters, {len(pitchers)} pitchers)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Baseball projection buy/sell analyzer")
    p.add_argument("--pre-csv", required=True)
    p.add_argument("--cur-csv", required=True)
    p.add_argument("--pos",     default="hitter", choices=["hitter", "pitcher"])
    p.add_argument("--stat",    default="HR")
    p.add_argument("--buy",     type=float, default=3.0)
    p.add_argument("--sell",    type=float, default=-3.0)
    p.add_argument("--top",     type=int,   default=30)
    p.add_argument("--export",  default=None)
    args = p.parse_args()

    run(
        pre_csv=args.pre_csv,
        cur_csv=args.cur_csv,
        pos=args.pos,
        stat=args.stat,
        buy=args.buy,
        sell=args.sell,
        top_n=args.top,
        export=args.export,
    )
