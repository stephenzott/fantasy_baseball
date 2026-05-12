#!/usr/bin/env python3
"""
Pull ESPN free agents and show FanGraphs projection deltas (BUY/HOLD/SELL).

Usage:
    python espn_free_agents.py                  # all positions, hitters + pitchers
    python espn_free_agents.py --pos OF         # filter by ESPN slot (OF, 1B, SP, RP, …)
    python espn_free_agents.py --pos SP --size 100
    python espn_free_agents.py --stat HR        # rank by a single stat delta
"""

import argparse
import os
import sys
import unicodedata

import pandas as pd
from espn_api.baseball import League


# ── Defaults ────────────────────────────────────────────────────────────────
HITTER_STATS  = ["HR", "R", "RBI", "SB", "AVG", "OBP"]
PITCHER_STATS = ["W", "ERA", "SO", "K/BB", "WHIP"]
PITCHER_SLOTS = {"SP", "RP", "P"}

BUY_THRESHOLDS = {
    "HR": 3, "R": 10, "RBI": 10, "SB": 3,
    "AVG": 0.01, "OBP": 0.01,
    "W": 2, "ERA": -0.30, "SO": 15, "K/BB": 0.20, "WHIP": -0.05,
}
SELL_THRESHOLDS = {k: -v for k, v in BUY_THRESHOLDS.items()}
# ERA and WHIP: lower is better, so invert signal logic
INVERT_STATS = {"ERA", "WHIP"}


def load_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())


def normalize(name):
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def load_fg(path, cols):
    df = pd.read_csv(path, encoding="utf-8-sig")
    df["PlayerId"] = df["PlayerId"].astype(str).str.strip()
    df["_key"]     = df["Name"].apply(normalize)
    df["_abbrev"]  = df["_key"].apply(
        lambda k: (k.split()[0][0] + " " + k.split()[-1]) if len(k.split()) >= 2 else k
    )
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def find_row(espn_name, df):
    key = normalize(espn_name)
    match = df[df["_key"] == key]
    if not match.empty:
        return match.iloc[0]
    parts = key.split()
    if len(parts) >= 2:
        abbrev = parts[0][0] + " " + parts[-1]
        match = df[df["_abbrev"] == abbrev]
        if len(match) == 1:
            return match.iloc[0]
    return None


def signal(delta, stat):
    buy_t  = BUY_THRESHOLDS.get(stat, 0)
    sell_t = SELL_THRESHOLDS.get(stat, 0)
    if stat in INVERT_STATS:
        # negative delta = improvement for ERA/WHIP → BUY
        if delta <= buy_t:
            return "BUY"
        if delta >= -sell_t:
            return "SELL"
    else:
        if delta >= buy_t:
            return "BUY"
        if delta <= sell_t:
            return "SELL"
    return "HOLD"


def build_rows(free_agents, pre_h, cur_h, pre_p, cur_p, pos_filter):
    rows = []
    for player in free_agents:
        slots      = set(player.eligibleSlots)
        is_pitcher = bool(slots & PITCHER_SLOTS) and "C" not in slots
        pos_label  = "/".join(sorted(slots - {"BE", "IL", "IL+"})) or "?"

        if pos_filter:
            if pos_filter not in slots:
                continue

        if is_pitcher:
            pre_row = find_row(player.name, pre_p)
            cur_row = find_row(player.name, cur_p)
            stats   = PITCHER_STATS
        else:
            pre_row = find_row(player.name, pre_h)
            cur_row = find_row(player.name, cur_h)
            stats   = HITTER_STATS

        if pre_row is None or cur_row is None:
            continue  # not in FanGraphs projections — skip

        fg_id = str(pre_row["PlayerId"])
        row = {
            "PlayerId": fg_id,
            "Name":     player.name,
            "Pos":      pos_label,
            "Type":     "P" if is_pitcher else "H",
        }
        for s in stats:
            try:
                pre_val = float(pre_row[s])
                cur_val = float(cur_row[s])
                delta   = round(cur_val - pre_val, 4)
                row[f"{s}_pre"]   = pre_val
                row[f"{s}_cur"]   = cur_val
                row[f"{s}_delta"] = delta
                row[f"{s}_sig"]   = signal(delta, s)
            except (KeyError, TypeError, ValueError):
                pass

        rows.append(row)
    return rows


def print_table(rows, rank_stat, player_type):
    subset = [r for r in rows if r.get("Type") == player_type]
    if not subset:
        return

    stats = PITCHER_STATS if player_type == "P" else HITTER_STATS
    delta_col = f"{rank_stat}_delta" if rank_stat else None

    if delta_col and delta_col in (subset[0] if subset else {}):
        reverse = rank_stat not in INVERT_STATS
        subset.sort(key=lambda r: r.get(delta_col, 0), reverse=reverse)
    else:
        # default: sort by first stat delta descending
        default = f"{stats[0]}_delta"
        subset.sort(key=lambda r: r.get(default, 0), reverse=(stats[0] not in INVERT_STATS))

    label = "PITCHERS" if player_type == "P" else "HITTERS"
    print(f"\n{'─'*70}")
    print(f"  FREE AGENT {label}  ({len(subset)} matched to FanGraphs)")
    print(f"{'─'*70}")

    for r in subset:
        sigs = [r.get(f"{s}_sig", "?") for s in stats if f"{s}_sig" in r]
        buy_count  = sigs.count("BUY")
        sell_count = sigs.count("SELL")
        overall = "BUY" if buy_count > sell_count else ("SELL" if sell_count > buy_count else "HOLD")

        parts = []
        for s in stats:
            delta = r.get(f"{s}_delta")
            sig   = r.get(f"{s}_sig", "")
            if delta is not None:
                tag = {"BUY": "+", "SELL": "-", "HOLD": "~"}.get(sig, "")
                parts.append(f"{s}:{tag}{delta:+.3f}")

        print(f"[{overall:<4}] {r['Name']:<22} {r['Pos']:<12}  {' | '.join(parts)}")


def main():
    load_env()

    LEAGUE_ID = int(os.getenv("ESPN_LEAGUE_ID", "0"))
    YEAR      = int(os.getenv("ESPN_YEAR", "2026"))
    ESPN_S2   = os.getenv("ESPN_S2", "")
    SWID      = os.getenv("ESPN_SWID", "")

    if not LEAGUE_ID or not ESPN_S2 or not SWID:
        print("Missing credentials. Copy .env.example → .env and fill in your values.")
        sys.exit(1)

    parser = argparse.ArgumentParser(description="ESPN free agent projection scanner")
    parser.add_argument("--pos",  default=None,  help="ESPN position slot to filter (e.g. OF, SP, 1B)")
    parser.add_argument("--size", type=int, default=150, help="Number of free agents to fetch (default 150)")
    parser.add_argument("--stat", default=None, help="Stat to rank by (e.g. HR, ERA)")
    parser.add_argument("--json", action="store_true", help="Write free_agents.json with FanGraphs IDs (for HTML star badges)")
    args = parser.parse_args()

    print(f"Connecting to ESPN league {LEAGUE_ID}…")
    league = League(league_id=LEAGUE_ID, year=YEAR, espn_s2=ESPN_S2, swid=SWID)

    print(f"Fetching up to {args.size} free agents{f' at {args.pos}' if args.pos else ''}…")
    fas = league.free_agents(size=args.size, position=args.pos)
    print(f"  ESPN returned {len(fas)} players")

    pre_h = load_fg("fangraphs-preseason-hitters-projections-2026.csv", HITTER_STATS)
    cur_h = load_fg("fangraphs-hitters-current.csv",  HITTER_STATS)
    pre_p = load_fg("fangraphs-preseason-pitcher-projections-2026.csv", PITCHER_STATS)
    cur_p = load_fg("fangraphs-pitchers-current.csv", PITCHER_STATS)

    rows = build_rows(fas, pre_h, cur_h, pre_p, cur_p, args.pos)

    if args.json:
        import json, subprocess
        hitter_ids  = [r["PlayerId"] for r in rows if r["Type"] == "H"]
        pitcher_ids = [r["PlayerId"] for r in rows if r["Type"] == "P"]
        print(f"Embedding FA IDs — {len(hitter_ids)} hitters, {len(pitcher_ids)} pitchers")

        h_new = "const FREE_AGENT_HITTER_IDS  = " + json.dumps(hitter_ids) + ";\n"
        p_new = "const FREE_AGENT_PITCHER_IDS = " + json.dumps(pitcher_ids) + ";\n"

        for fname in ["baseball_analyzer_interactive.html", "index.html"]:
            with open(fname) as f:
                lines = f.readlines()
            h_idx = next((i for i, l in enumerate(lines) if l.startswith("const FREE_AGENT_HITTER_IDS")), None)
            p_idx = next((i for i, l in enumerate(lines) if l.startswith("const FREE_AGENT_PITCHER_IDS")), None)
            if h_idx is None or p_idx is None:
                print(f"  Skipping {fname} — FREE_AGENT lines not found")
                continue
            if lines[h_idx] == h_new and lines[p_idx] == p_new:
                print(f"  {fname}: unchanged")
                continue
            lines[h_idx] = h_new
            lines[p_idx] = p_new
            with open(fname, "w") as f:
                f.writelines(lines)
            print(f"  Updated {fname}")

        script_dir = os.path.dirname(os.path.abspath(__file__))
        subprocess.run(["git", "add", "baseball_analyzer_interactive.html", "index.html"], cwd=script_dir, check=True)
        result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=script_dir)
        if result.returncode != 0:
            subprocess.run(["git", "commit", "-m", "Update free agents list"], cwd=script_dir, check=True)
            subprocess.run(["git", "push"], cwd=script_dir, check=True)
            print("Pushed — GitHub Pages will update in ~60s.")
        else:
            print("HTML unchanged — nothing to push.")
    else:
        print_table(rows, args.stat, "H")
        print_table(rows, args.stat, "P")

    if not rows:
        print("No players matched FanGraphs projections.")


if __name__ == "__main__":
    main()
