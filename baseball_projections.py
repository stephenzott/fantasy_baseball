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
PITCHER_STATS = ["WAR", "ERA", "WHIP", "W", "SV", "IP", "K9", "BB9"]
LOWER_IS_BETTER = {"ERA", "WHIP", "BB9"}


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
