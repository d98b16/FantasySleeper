#!/usr/bin/env python3
"""
league.py — the league's scoring rules, in one place.

VERIFIED LIVE against GET /v1/league/1389326749023608832 (scoring_settings and
roster_positions). Every script that scores a player imports from here so the
model, the edge table and the spreadsheet can never disagree about what a point
is worth. PUBLIC4 differs from LEAGUE in pass_td ONLY, so any measured gap
between them is attributable to the 6-point rule and nothing else.
"""

LEAGUE = dict(
    pass_yd=0.04, pass_td=6.0, pass_int=-2.0, pass_2pt=2.0,
    rush_yd=0.10, rush_td=6.0, rush_2pt=2.0,
    rec=0.5, rec_yd=0.10, rec_td=6.0, rec_2pt=2.0,
    fum_lost=-2.0,
)
PUBLIC4 = {**LEAGUE, "pass_td": 4.0}

# Team-defense scoring, same source.
DEF_RULES = dict(sack=1.0, interception=2.0, fumble_rec=2.0, def_td=6.0,
                 safety=2.0, blocked_kick=2.0)
DEF_PTS_ALLOWED = [(0, 10.0), (6, 7.0), (13, 4.0), (20, 1.0),
                   (27, 0.0), (34, -1.0), (999, -4.0)]

# Roster shape. Drives replacement level everywhere.
TEAMS, ROUNDS, BENCH = 12, 12, 4
STARTERS = dict(QB=1, RB=2, WR=2, TE=1, DEF=1)
FLEX = 1
FLEX_SPLIT = dict(RB=0.50, WR=0.42, TE=0.08)   # half-PPR flex usage
SKILL = ["QB", "RB", "WR", "TE"]
GAMES_17 = 17          # regular-season games since 2021 (16 before)


def season_games(season):
    """Regular-season game count. 17 from 2021; 16 before; 2020 was 16 too."""
    return 17 if season >= 2021 else 16


def score_frame(df, rules=LEAGUE):
    """Fantasy points for a stats_player_week-shaped frame. NaN-safe."""
    import pandas as pd
    g = lambda c: pd.to_numeric(df[c], errors="coerce").fillna(0) if c in df else 0
    return (g("passing_yards") * rules["pass_yd"]
            + g("passing_tds") * rules["pass_td"]
            + g("passing_interceptions") * rules["pass_int"]
            + g("passing_2pt_conversions") * rules["pass_2pt"]
            + g("rushing_yards") * rules["rush_yd"]
            + g("rushing_tds") * rules["rush_td"]
            + g("rushing_2pt_conversions") * rules["rush_2pt"]
            + g("receptions") * rules["rec"]
            + g("receiving_yards") * rules["rec_yd"]
            + g("receiving_tds") * rules["rec_td"]
            + g("receiving_2pt_conversions") * rules["rec_2pt"]
            + g("fumbles_lost_total") * rules["fum_lost"])


def def_points_allowed(pts):
    for cap, val in DEF_PTS_ALLOWED:
        if pts <= cap:
            return val
    return -4.0


def replacement_ranks():
    """Which rank at each position is 'replacement', from the roster shape."""
    out = {}
    for pos in SKILL:
        base = STARTERS.get(pos, 0) * TEAMS
        flex = round(FLEX_SPLIT.get(pos, 0) * FLEX * TEAMS)
        out[pos] = int(base + flex) + 1
    return out


import re as _re
_SUFFIX = _re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def norm(s):
    """Name key. Mirrors index.html norm() and sleeper_sync.gs norm() exactly."""
    s = str(s or "").lower()
    s = _re.sub(r"[.'’-]", " ", s)
    s = _SUFFIX.sub(" ", s)
    return _re.sub(r"[^a-z0-9]", "", s)
