#!/usr/bin/env python3
"""Fetch ESPN season-long category stats for all league teams and embed into HTML."""

import json
import os
import subprocess
from datetime import datetime, timezone


SCORING_STATS = {
    20: {'name': 'R',    'label': 'Runs',          'lower_better': False},
    5:  {'name': 'HR',   'label': 'Home Runs',      'lower_better': False},
    21: {'name': 'RBI',  'label': 'RBI',            'lower_better': False},
    23: {'name': 'SB',   'label': 'Stolen Bases',   'lower_better': False},
    2:  {'name': 'AVG',  'label': 'AVG',            'lower_better': False},
    18: {'name': 'OPS',  'label': 'OPS',            'lower_better': False},
    53: {'name': 'W',    'label': 'Wins',           'lower_better': False},
    48: {'name': 'K',    'label': 'Strikeouts',     'lower_better': False},
    82: {'name': 'K/BB', 'label': 'K/BB',           'lower_better': False},
    83: {'name': 'SVHD', 'label': 'Saves+Holds',    'lower_better': False},
    47: {'name': 'ERA',  'label': 'ERA',            'lower_better': True},
    41: {'name': 'WHIP', 'label': 'WHIP',           'lower_better': True},
}


def load_env():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, _, v = line.partition('=')
                    os.environ.setdefault(k.strip(), v.strip())


def main():
    load_env()

    LEAGUE_ID = int(os.getenv('ESPN_LEAGUE_ID', '0'))
    YEAR      = int(os.getenv('ESPN_YEAR', '2026'))
    ESPN_S2   = os.getenv('ESPN_S2', '')
    SWID      = os.getenv('ESPN_SWID', '')
    TEAM_ID   = int(os.getenv('ESPN_TEAM_ID', '0'))

    if not LEAGUE_ID or not ESPN_S2 or not SWID or not TEAM_ID:
        print('Missing credentials. Copy .env.example → .env and fill in your values.')
        raise SystemExit(1)

    from espn_api.baseball import League
    league = League(league_id=LEAGUE_ID, year=YEAR, espn_s2=ESPN_S2, swid=SWID)

    raw = league.espn_request.league_get(params={
        'view': 'mTeam',
        'scoringPeriodId': league.scoringPeriodId,
    })

    teams_raw = raw.get('teams', [])

    # Build per-category rankings
    categories = []
    for stat_id, info in SCORING_STATS.items():
        sid = str(stat_id)
        team_vals = []
        for t in teams_raw:
            val = t.get('valuesByStat', {}).get(sid)
            if val is not None:
                team_vals.append({
                    'team_id':   t['id'],
                    'team_name': t.get('name', f'Team {t["id"]}'),
                    'value':     float(val),
                })

        # Rank: lower_better → ascending, else descending
        team_vals.sort(key=lambda x: x['value'], reverse=not info['lower_better'])
        for i, tv in enumerate(team_vals):
            tv['rank'] = i + 1

        categories.append({
            'stat_id':     stat_id,
            'name':        info['name'],
            'label':       info['label'],
            'lower_better': info['lower_better'],
            'teams':       team_vals,
        })

    output = {
        'generated':      datetime.now(timezone.utc).isoformat(),
        'scoring_period': league.scoringPeriodId,
        'my_team_id':     TEAM_ID,
        'total_teams':    len(teams_raw),
        'categories':     categories,
    }

    with open('league_stats.json', 'w') as f:
        json.dump(output, f, indent=2)

    print(f'Wrote league_stats.json — {len(teams_raw)} teams, {len(categories)} categories')
    for cat in categories:
        my = next((t for t in cat['teams'] if t['team_id'] == TEAM_ID), None)
        if my:
            n = output['total_teams']
            val = my['value']
            fmt = f'{val:.3f}' if cat['name'] in ('AVG', 'OPS', 'ERA', 'WHIP', 'K/BB') else str(int(round(val)))
            print(f'  {cat["name"]:<6} {my["rank"]:2d}/{n}  {fmt}')

    # Embed into HTML files
    new_line = 'const LEAGUE_STATS_DATA = ' + json.dumps(output, ensure_ascii=False) + ';\n'

    script_dir = os.path.dirname(os.path.abspath(__file__))
    changed = []
    for fname in ['baseball_analyzer_interactive.html', 'index.html']:
        path = os.path.join(script_dir, fname)
        with open(path) as f:
            lines = f.readlines()
        idx = next((i for i, l in enumerate(lines) if l.startswith('const LEAGUE_STATS_DATA')), None)
        if idx is None:
            print(f'  {fname}: LEAGUE_STATS_DATA line not found — skipping embed')
            continue
        if lines[idx] == new_line:
            print(f'  {fname}: unchanged')
        else:
            lines[idx] = new_line
            with open(path, 'w') as f:
                f.writelines(lines)
            changed.append(fname)
            print(f'  Updated {fname}')

    if changed:
        subprocess.run(['git', 'add'] + changed + ['league_stats.json'], cwd=script_dir, check=True)
        result = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=script_dir)
        if result.returncode != 0:
            subprocess.run(['git', 'commit', '-m', 'Update league category stats'], cwd=script_dir, check=True)
            subprocess.run(['git', 'push'], cwd=script_dir, check=True)
            print('Pushed — GitHub Pages will update in ~60s.')
        else:
            print('No changes to commit.')


if __name__ == '__main__':
    main()
