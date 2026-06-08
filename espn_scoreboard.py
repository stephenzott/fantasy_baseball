#!/usr/bin/env python3
"""Fetch ESPN current-week matchup scoreboard and embed it into the HTML."""

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


def fmt_score(val, stat_info):
    if val is None:
        return '—'
    if stat_info['name'] in ('AVG', 'OPS', 'WHIP', 'K/BB', 'ERA'):
        return f'{val:.3f}'
    return str(int(round(val)))


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

    current_period = league.scoreboard()[0].away_team  # just to trigger load
    current_period = None  # reset

    raw = league.espn_request.league_get(params={
        'view': ['mMatchup', 'mMatchupScore'],
        'scoringPeriodId': league.scoringPeriodId,
    })

    status = raw.get('status', {})
    matchup_period = status.get('currentMatchupPeriod', league.current_week)

    # Build team ID → name map
    team_map = {t.team_id: t.team_name for t in league.teams}

    sched = raw.get('schedule', [])
    current = [s for s in sched if s.get('matchupPeriodId') == matchup_period]

    my_match = None
    my_side  = None
    for m in current:
        home_id = m.get('home', {}).get('teamId')
        away_id = m.get('away', {}).get('teamId')
        if home_id == TEAM_ID:
            my_match, my_side = m, 'home'
            break
        if away_id == TEAM_ID:
            my_match, my_side = m, 'away'
            break

    if not my_match:
        print(f'No matchup found for team {TEAM_ID} in period {matchup_period}')
        raise SystemExit(1)

    opp_side = 'away' if my_side == 'home' else 'home'
    my_data  = my_match[my_side]
    opp_data = my_match[opp_side]

    my_cum  = my_data.get('cumulativeScore', {})
    opp_cum = opp_data.get('cumulativeScore', {})

    my_sbs  = my_cum.get('scoreByStat', {})
    opp_sbs = opp_cum.get('scoreByStat', {})

    categories = []
    for stat_id, info in SCORING_STATS.items():
        sid = str(stat_id)
        my_entry  = my_sbs.get(sid, {})
        opp_entry = opp_sbs.get(sid, {})

        my_raw  = my_entry.get('score',  0.0)
        opp_raw = opp_entry.get('score', 0.0)
        result  = my_entry.get('result') or 'TIE'
        ineligible = my_entry.get('ineligible', False) or opp_entry.get('ineligible', False)

        # ESPN can return "Infinity" as a string for ERA/WHIP with 0 IP
        try:
            my_score  = float(my_raw)  if my_raw  not in (None, 'Infinity', float('inf')) else None
            opp_score = float(opp_raw) if opp_raw not in (None, 'Infinity', float('inf')) else None
        except (TypeError, ValueError):
            my_score = opp_score = None

        categories.append({
            'stat_id':    stat_id,
            'name':       info['name'],
            'label':      info['label'],
            'my_score':   my_score,
            'opp_score':  opp_score,
            'result':     result,
            'lower_better': info['lower_better'],
            'ineligible': ineligible,
        })

    my_team_id  = my_data.get('teamId')
    opp_team_id = opp_data.get('teamId')

    scoreboard = {
        'week':           matchup_period,
        'scoring_period': league.scoringPeriodId,
        'my_team':        team_map.get(my_team_id, f'Team {my_team_id}'),
        'opp_team':       team_map.get(opp_team_id, f'Team {opp_team_id}'),
        'my_wins':        my_cum.get('wins', 0),
        'opp_wins':       opp_cum.get('wins', 0),
        'ties':           my_cum.get('ties', 0),
        'winner':         my_match.get('winner', 'UNDECIDED'),
        'categories':     categories,
        'generated':      datetime.now(timezone.utc).isoformat(),
    }

    with open('scoreboard.json', 'w') as f:
        json.dump(scoreboard, f, indent=2)
    print(f"Wrote scoreboard.json — Week {matchup_period}: {scoreboard['my_team']} vs {scoreboard['opp_team']}")
    print(f"  Standing: {scoreboard['my_wins']}W – {scoreboard['opp_wins']}W – {scoreboard['ties']}T")
    for cat in categories:
        my_fmt  = fmt_score(cat['my_score'],  SCORING_STATS[cat['stat_id']])
        opp_fmt = fmt_score(cat['opp_score'], SCORING_STATS[cat['stat_id']])
        flag = '🔒' if cat['ineligible'] else {'WIN': '✓', 'LOSS': '✗', 'TIE': '~'}.get(cat['result'], '~')
        print(f"  {flag} {cat['name']:<6} {my_fmt:>8} vs {opp_fmt:<8}  [{cat['result']}]")

    # Embed into HTML files
    new_line = 'const SCOREBOARD_DATA = ' + json.dumps(scoreboard, ensure_ascii=False) + ';\n'

    script_dir = os.path.dirname(os.path.abspath(__file__))
    changed = []
    for fname in ['baseball_analyzer_interactive.html', 'index.html']:
        path = os.path.join(script_dir, fname)
        with open(path) as f:
            lines = f.readlines()
        idx = next((i for i, l in enumerate(lines) if l.startswith('const SCOREBOARD_DATA')), None)
        if idx is None:
            print(f'  {fname}: SCOREBOARD_DATA line not found — skipping embed')
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
        subprocess.run(['git', 'add'] + changed + ['scoreboard.json'], cwd=script_dir, check=True)
        result = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=script_dir)
        if result.returncode != 0:
            subprocess.run(['git', 'commit', '-m', f'Update scoreboard: Week {matchup_period}'], cwd=script_dir, check=True)
            subprocess.run(['git', 'push'], cwd=script_dir, check=True)
            print('Pushed — GitHub Pages will update in ~60s.')
        else:
            print('No changes to commit.')


if __name__ == '__main__':
    main()
