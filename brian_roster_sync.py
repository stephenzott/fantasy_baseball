#!/usr/bin/env python3
"""
Sync Brian's fantasy roster from a shared Google Sheet into the HTML defaults.

Setup (one-time):
  1. Open the Google Sheet and share it as "Anyone with the link can view"
  2. Run this script: python3 brian_roster_sync.py

The script reads player names from the sheet, matches them to FanGraphs IDs
(using current + preseason CSVs), then updates DEFAULT_BRIAN_HITTER_IDS and
DEFAULT_BRIAN_PITCHER_IDS in both baseball_analyzer_interactive.html and index.html.
"""

import json
import re
import unicodedata
import pandas as pd

SHEET_ID = "1aORRK8-_IeumjyB1YL4C6zX5iGqaBVNbABrJ3zEpTYQ"
SHEET_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"

HTML_FILES = ["baseball_analyzer_interactive.html", "index.html"]

HITTER_CSVS   = ["fangraphs-hitters-current.csv", "fangraphs-preseason-hitters-projections-2026.csv"]
PITCHER_CSVS  = ["fangraphs-pitchers-current.csv", "fangraphs-preseason-pitcher-projections-2026.csv"]


def normalize(name: str) -> str:
    name = unicodedata.normalize("NFD", name)
    name = "".join(c for c in name if unicodedata.category(c) != "Mn")
    return name.lower().strip()


def build_name_map(csv_paths: list[str]) -> dict[str, str]:
    """Return {normalized_name: player_id} from one or more CSVs (first match wins)."""
    result: dict[str, str] = {}
    for path in csv_paths:
        try:
            df = pd.read_csv(path)
        except FileNotFoundError:
            continue
        df["PlayerId"] = df["PlayerId"].astype(str).str.strip()
        for _, row in df.iterrows():
            key = normalize(str(row["Name"]))
            if key not in result:
                result[key] = str(row["PlayerId"])
    return result


def update_html(hitter_ids: list[str], pitcher_ids: list[str]) -> bool:
    h_line = f'const DEFAULT_BRIAN_HITTER_IDS  = {json.dumps(hitter_ids)};\n'
    p_line = f'const DEFAULT_BRIAN_PITCHER_IDS = {json.dumps(pitcher_ids)};\n'

    with open(HTML_FILES[0]) as f:
        lines = f.readlines()

    h_idx = next((i for i, l in enumerate(lines) if l.startswith("const DEFAULT_BRIAN_HITTER_IDS")), None)
    p_idx = next((i for i, l in enumerate(lines) if l.startswith("const DEFAULT_BRIAN_PITCHER_IDS")), None)

    if h_idx is None or p_idx is None:
        print("ERROR: Could not find DEFAULT_BRIAN_HITTER_IDS or DEFAULT_BRIAN_PITCHER_IDS in HTML.")
        return False

    if lines[h_idx] == h_line and lines[p_idx] == p_line:
        print("Roster unchanged — no update needed.")
        return False

    lines[h_idx] = h_line
    lines[p_idx] = p_line

    for fname in HTML_FILES:
        with open(fname, "w") as f:
            f.writelines(lines)

    return True


def main():
    print(f"Reading roster from Google Sheet: {SHEET_CSV_URL}\n")

    try:
        df = pd.read_csv(SHEET_CSV_URL)
    except Exception as e:
        print(f"ERROR: Could not read Google Sheet.\n"
              f"Make sure the sheet is shared as 'Anyone with the link can view'.\n{e}")
        return

    df.columns = [c.strip() for c in df.columns]
    df = df.dropna(subset=["Name"])
    df["Type"] = df["Type"].str.strip().str.lower()
    df["Name"] = df["Name"].str.strip()

    hitter_names  = df[df["Type"] == "hitter"]["Name"].tolist()
    pitcher_names = df[df["Type"] == "pitcher"]["Name"].tolist()

    hitter_map  = build_name_map(HITTER_CSVS)
    pitcher_map = build_name_map(PITCHER_CSVS)

    hitter_ids, pitcher_ids = [], []
    unmatched = []

    for name in hitter_names:
        pid = hitter_map.get(normalize(name))
        if pid:
            hitter_ids.append(pid)
        else:
            unmatched.append(f"  Hitter: {name!r}")

    for name in pitcher_names:
        pid = pitcher_map.get(normalize(name))
        if pid:
            pitcher_ids.append(pid)
        else:
            unmatched.append(f"  Pitcher: {name!r}")

    print(f"Matched {len(hitter_ids)}/{len(hitter_names)} hitters, "
          f"{len(pitcher_ids)}/{len(pitcher_names)} pitchers")

    if unmatched:
        print("\nUnmatched players (IL or name mismatch — safe to ignore if on IL):")
        print("\n".join(unmatched))

    changed = update_html(hitter_ids, pitcher_ids)
    if changed:
        print(f"\nUpdated DEFAULT_BRIAN_HITTER_IDS and DEFAULT_BRIAN_PITCHER_IDS in: {', '.join(HTML_FILES)}")
        print("Next: git add baseball_analyzer_interactive.html index.html && git commit -m 'Sync Brian roster' && git push")
    else:
        print("\nNo HTML changes needed.")


if __name__ == "__main__":
    main()
