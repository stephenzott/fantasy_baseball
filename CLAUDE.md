# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Fantasy baseball projection analyzer that compares FanGraphs preseason projections vs. current in-season projections to generate BUY/SELL/HOLD signals for roster decisions. Supports stats: HR, R, RBI, SB, AVG, OBP.

## Environment Setup

```bash
source venv/bin/activate   # Python 3.13 venv with numpy + pandas
```

Python dependencies are minimal: `numpy` and `pandas` only (see `requirements.txt`).

## Running the Analysis

The primary workflow runs through the Jupyter notebook:

```bash
jupyter notebook projection_run.ipynb
```

The notebook imports `baseball_projections.py` and calls `run()`:

```python
from baseball_projections import run

df = run(
    pre_csv="fangraphs-preseason-projections-2026.csv",  # preseason baseline
    cur_csv="fangraphs-hitters-current.csv",               # current in-season
    pos="hitter",
    stat="HR",   # HR | R | RBI | SB | AVG | OBP
    buy=3,       # delta >= buy → BUY signal
    sell=-3      # delta <= sell → SELL signal
)
df.to_csv("results.csv", index=False)
```

## Downloading Fresh Projections

```bash
./fangraphs_downloader.sh
```

Fetches ZiPS update projections from the FanGraphs API and writes to `projections_updated.csv`. Logs to `download.log`.

## "Update the Page" — Full Refresh Workflow

When the user says "update the page" (or similar), run all five steps in this order:

1. **Embed projection data** — run the Python snippet in the "Updating Embedded HTML Data from CSVs" section below. The four CSVs have already been downloaded manually.
2. **Sync roster** — `source venv/bin/activate && python espn_roster_sync.py`
3. **Sync free agents** — `source venv/bin/activate && python espn_free_agents.py --json`
4. **Update scoreboard** — `source venv/bin/activate && python espn_scoreboard.py`
5. **Update league stats** — `source venv/bin/activate && python espn_league_stats.py`

Steps 1, 2, 4, and 5 can run in parallel. Step 3 handles its own commit and push to GitHub Pages. After steps 1, 2, 4, and 5 complete, commit `baseball_analyzer_interactive.html` (projection data), then sync to `index.html` and push.

## Updating Embedded HTML Data from CSVs

When the user asks to update the projection data in the HTML, run this Python snippet inline (no separate script needed). It reads the four CSVs, merges on `PlayerId`, regenerates `HITTERS_DATA` and `PITCHERS_DATA` in both HTML files (line numbers detected dynamically), and skips the commit if nothing changed.

```python
import pandas as pd, json

pre_h = pd.read_csv('fangraphs-preseason-hitters-projections-2026.csv')
cur_h = pd.read_csv('fangraphs-hitters-current.csv')
pre_p = pd.read_csv('fangraphs-preseason-pitcher-projections-2026.csv')
cur_p = pd.read_csv('fangraphs-pitchers-current.csv')

for df in [pre_h, cur_h, pre_p, cur_p]:
    df['PlayerId'] = df['PlayerId'].astype(str).str.strip()

with open('baseball_analyzer_interactive.html') as f:
    lines = f.readlines()

# Find data lines dynamically
h_idx = next(i for i, l in enumerate(lines) if l.startswith('const HITTERS_DATA'))
p_idx = next(i for i, l in enumerate(lines) if l.startswith('const PITCHERS_DATA'))

def extract_pos_map(js_line):
    start = js_line.index('['); end = js_line.rindex(']') + 1
    return {str(d['player_id']): d.get('pos', '') for d in json.loads(js_line[start:end])}

hitter_pos_map = extract_pos_map(lines[h_idx])
pitcher_pos_map = extract_pos_map(lines[p_idx])

merged_h = pd.merge(
    pre_h[['PlayerId','Name','Team','HR','R','RBI','SB','AVG','OBP']],
    cur_h[['PlayerId','Name','Team','HR','R','RBI','SB','AVG','OBP']],
    on='PlayerId', suffixes=('_pre','_cur'))

hitters_json = []
for _, row in merged_h.iterrows():
    pid = str(row['PlayerId'])
    hitters_json.append({'player_id': pid,
        'name': row['Name_cur'], 'team': row['Team_cur'],
        'stats': {
            'HR':  {'pre': round(float(row['HR_pre']),  4), 'cur': round(float(row['HR_cur']),  4)},
            'R':   {'pre': round(float(row['R_pre']),   4), 'cur': round(float(row['R_cur']),   4)},
            'RBI': {'pre': round(float(row['RBI_pre']), 4), 'cur': round(float(row['RBI_cur']), 4)},
            'SB':  {'pre': round(float(row['SB_pre']),  4), 'cur': round(float(row['SB_cur']),  4)},
            'AVG': {'pre': round(float(row['AVG_pre']), 6), 'cur': round(float(row['AVG_cur']), 6)},
            'OBP': {'pre': round(float(row['OBP_pre']), 6), 'cur': round(float(row['OBP_cur']), 6)},
        }, 'pos': hitter_pos_map.get(pid, '')})

cur_p['GS_val'] = pd.to_numeric(cur_p['GS'], errors='coerce').fillna(0)
merged_p = pd.merge(
    pre_p[['PlayerId','Name','Team','W','ERA','SO','K/BB','WHIP']],
    cur_p[['PlayerId','Name','Team','W','ERA','SO','K/BB','WHIP','GS_val']],
    on='PlayerId', suffixes=('_pre','_cur'))

pitchers_json = []
for _, row in merged_p.iterrows():
    pid = str(row['PlayerId'])
    existing = pitcher_pos_map.get(pid, '')
    pos = existing if existing else ('SP' if float(row['GS_val']) >= 5 else 'RP')
    pitchers_json.append({'player_id': pid,
        'name': row['Name_cur'], 'team': row['Team_cur'],
        'stats': {
            'W':    {'pre': round(float(row['W_pre']),    4), 'cur': round(float(row['W_cur']),    4)},
            'ERA':  {'pre': round(float(row['ERA_pre']),  5), 'cur': round(float(row['ERA_cur']),  5)},
            'K':    {'pre': round(float(row['SO_pre']),   4), 'cur': round(float(row['SO_cur']),   4)},
            'K/BB': {'pre': round(float(row['K/BB_pre']), 5), 'cur': round(float(row['K/BB_cur']), 5)},
            'WHIP': {'pre': round(float(row['WHIP_pre']), 6), 'cur': round(float(row['WHIP_cur']), 6)},
        }, 'pos': pos})

h_new = 'const HITTERS_DATA = ' + json.dumps(hitters_json, ensure_ascii=False) + ';\n'
p_new = 'const PITCHERS_DATA = ' + json.dumps(pitchers_json, ensure_ascii=False) + ';\n'

# Skip if data unchanged
if lines[h_idx] == h_new and lines[p_idx] == p_new:
    print("Data unchanged — no update needed.")
else:
    lines[h_idx] = h_new
    lines[p_idx] = p_new
    for fname in ['baseball_analyzer_interactive.html', 'index.html']:
        with open(fname, 'w') as f:
            f.writelines(lines)
    print(f"Updated — {len(hitters_json)} hitters, {len(pitchers_json)} pitchers")
```

After running, if files changed: `git add baseball_analyzer_interactive.html index.html`, commit, and push to deploy to GitHub Pages.

## Key Files

- **`baseball_projections.py`** — core module (currently missing from working tree; only `.pyc` in `__pycache__/`). Functions: `load_csv`, `compute_delta`, `add_signals`, `print_report`, `run`.
- **`baseball_analyzer_interactive.html`** — self-contained browser app with player data embedded as JSON. Open directly in a browser; no server needed. Supersedes the committed `index.html`.
- **`fangraphs-preseason-hitters-projections-2026.csv`** — preseason ZiPS projections (~1900 players).
- **`fangraphs-hitters-current.csv`** — current in-season projections (~465 players, hitters only).
- **`team_hitters.csv`** — your fantasy roster export from ESPN (Plain CSV just for highlighting on the html).
- **`results*.csv`** — output from `projection_run.ipynb`, one per stat.

## Architecture Notes

**Python pipeline (`baseball_projections.py`):**
- `load_csv` normalizes column names and filters by position (`hitter` vs pitcher).
- `compute_delta` merges preseason and current projections. It joins on `player_id` (FanGraphs integer ID) first; if types differ across CSVs (object vs int64), it falls back to normalized name matching.
- `add_signals` applies buy/sell thresholds to the delta column.
- `run` orchestrates the full pipeline and returns a DataFrame sorted by delta.

**HTML app (`baseball_analyzer_interactive.html`):**
- Entirely client-side; player data is embedded as a `PLAYERS_DATA` JSON array.
- Supports filtering by stat, adjusting buy/sell thresholds interactively.
- To regenerate the HTML with fresh data, the Python pipeline must embed the computed JSON into the HTML template.

**Deploying to GitHub Pages (`https://stephenzott.github.io/fantasy_baseball/`):**
- GitHub Pages serves `index.html`. Whenever `baseball_analyzer_interactive.html` is modified, copy it to `index.html` and push to `main`:
  ```bash
  cp baseball_analyzer_interactive.html index.html
  git add index.html && git commit -m "Sync index.html for GitHub Pages" && git push
  ```

## Development Rules

- **Never remove or overwrite existing features** unless explicitly instructed to do so. When adding new functionality (e.g. a new tab, filter, or section), always merge it with what's already in the HTML template — do not discard features that weren't part of the current task.

## ESPN Roster Sync Notes

- **Unmatched players are expected and ignorable.** `espn_roster_sync.py` matches ESPN names to FanGraphs CSVs; players on the IL or not yet in the current projections will show as unmatched. Do not add them to `roster.json` manually — they'll be picked up automatically on the next sync once they reappear in the current projections CSV.

## Known Issues

- Merging preseason (`player_id` as string) with current projections (`player_id` as int64) raises `ValueError`. Fix: cast both to the same type before merging, e.g. `df['player_id'] = df['player_id'].astype(str)` in `load_csv`.
- `baseball_projections.py` is absent from the working tree. The `.pyc` in `__pycache__` is from Python 3.13 and can serve as a reference but the source must be recreated.
