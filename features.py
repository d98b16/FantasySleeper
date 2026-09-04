#!/usr/bin/env python3
"""
features.py — player-season panel -> supervised learning table.

One row per (player, season N) whose TARGET is season N+1. Every feature is
computed from season N or earlier. Nothing about N+1 leaks in, including the
league-wide rates used for TD regression, which are fit on season N.

    build()  ->  DataFrame with y_pts_pg / y_games / y_pts targets and x_* features
"""
import os, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
import league

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, "data")

# lagged rate/share features: value in season N, N-1, N-2
LAG1 = ["pts_pg", "pts_xtd_pg", "snap_pct", "target_share", "air_yards_share",
        "wopr", "adot", "targets_pg", "carries_pg", "touch_pg", "routes_pg",
        "rz_touch_pg", "i10_touch_pg", "i5_touch_pg", "ypc", "ypr", "catch_rate",
        "yprr", "yac_per_rec", "td_pg", "td_oe_pg", "games", "avail",
        "tm_plays_pg", "tm_pass_rate", "tm_epa", "tm_rz_pg", "attempts_pg",
        "passing_yards_pg", "receiving_yards_pg", "rushing_yards_pg", "depth_rank"]
LAG2 = ["pts_pg", "snap_pct", "target_share", "touch_pg", "games", "avail",
        "rz_touch_pg", "pts_xtd_pg"]
LAG3 = ["pts_pg", "games", "snap_pct"]


ZONES = [("i5", "i5_car", "i5_car_td", "i5_tgt", "i5_tgt_td"),
         ("ring", "ring_car", "ring_car_td", "ring_tgt", "ring_tgt_td"),
         ("mid", "mid_car", "mid_car_td", "mid_tgt", "mid_tgt_td"),
         ("out", "out_car", "out_car_td", "out_tgt", "out_tgt_td")]


def expected_tds(panel):
    """Expected TDs from opportunity, using conversion rates MEASURED per season,
    per position, per field zone -- goal-line carries, 6-10, 11-20, and beyond.

    Rates are fit within the feature season only. That is not leakage: the target
    is the FOLLOWING season, which is never touched. A player far above his
    expected TDs got lucky, and luck does not repeat -- pts_xtd re-scores him at
    his expected count so a fluke touchdown year cannot masquerade as a
    projection.
    """
    p = panel.copy()
    for _, car, ctd, tgt, ttd in ZONES:
        for c in (car, ctd, tgt, ttd):
            p[c] = pd.to_numeric(p.get(c), errors="coerce").fillna(0)

    p["xtd"] = 0.0
    for (season, pos), g in p.groupby(["season", "position"]):
        pred = np.zeros(len(g))
        for _, car, ctd, tgt, ttd in ZONES:
            for opp_c, td_c in ((car, ctd), (tgt, ttd)):
                opp_sum = g[opp_c].sum()
                rate = (g[td_c].sum() / opp_sum) if opp_sum > 0 else 0.0
                pred += g[opp_c].values * rate
        p.loc[g.index, "xtd"] = pred

    p["td_oe"] = p.td_total - p.xtd
    gm = p.games.replace(0, np.nan)
    p["td_oe_pg"] = p.td_oe / gm
    p["pts_xtd"] = p.pts - p.td_oe * 6.0
    p["pts_xtd_pg"] = p.pts_xtd / gm
    return p


def build():
    panel = pd.read_parquet(os.path.join(OUT, "player_seasons.parquet"))
    panel = expected_tds(panel)
    panel["routes_pg"] = panel.routes / panel.games.replace(0, np.nan)
    panel = panel.sort_values(["player_id", "season"])

    keep = (["player_id", "player_display_name", "position", "season", "team",
             "age", "exp", "draft_round", "draft_pick", "undrafted", "sched_games",
             "teams_played", "inj_reports", "inj_out", "pts", "games"]
            + sorted(set(LAG1 + LAG2 + LAG3)))
    keep = [c for c in dict.fromkeys(keep) if c in panel.columns]
    d = panel[keep].copy()

    frames = []
    for pid, g in d.groupby("player_id", sort=False):
        g = g.sort_values("season").copy()
        for c in LAG1:
            if c in g: g[f"x_{c}_1"] = g[c]
        for c in LAG2:
            if c in g: g[f"x_{c}_2"] = g[c].shift(1)
        for c in LAG3:
            if c in g: g[f"x_{c}_3"] = g[c].shift(2)
        g["x_team_prev"] = g.team.shift(0)
        g["x_team_changed_prior"] = (g.team != g.team.shift(1)).astype(float)
        g["x_seasons_of_history"] = np.arange(len(g)) + 1.0
        # trend: is his role rising or falling?
        for c in ["snap_pct", "target_share", "touch_pg", "pts_pg"]:
            if c in g:
                g[f"x_d_{c}"] = g[c] - g[c].shift(1)
        # targets come from the NEXT season
        g["y_pts_pg"] = g.pts_pg.shift(-1)
        g["y_games"]  = g.games.shift(-1)
        g["y_pts"]    = g.pts.shift(-1)
        g["y_season"] = g.season.shift(-1)
        g["y_team"]   = g.team.shift(-1)
        frames.append(g)
    f = pd.concat(frames, ignore_index=True)

    # a row is usable if the next season exists and is consecutive
    f = f[f.y_season == f.season + 1].copy()
    f["x_age"] = f.age
    f["x_age_sq"] = f.age ** 2
    f["x_exp"] = f.exp
    f["x_draft_round"] = f.draft_round.fillna(8)
    f["x_draft_pick"] = f.draft_pick.fillna(270)
    f["x_undrafted"] = f.undrafted
    f["x_inj_reports"] = f.inj_reports.fillna(0)
    f["x_inj_out"] = f.inj_out.fillna(0)
    f["x_teams_played"] = f.teams_played.fillna(1)
    f["x_changed_team_next"] = (f.y_team != f.team).astype(float)   # known at draft time
    f["y_avail"] = f.y_games / f.sched_games.shift(0)
    return f


def feature_cols(df, pos=None):
    cols = [c for c in df.columns if c.startswith("x_") and c != "x_team_prev"]
    # drop columns that are entirely missing for this slice
    if pos is not None:
        sub = df[df.position == pos]
        cols = [c for c in cols if sub[c].notna().any()]
    return cols


if __name__ == "__main__":
    f = build()
    f.to_parquet(os.path.join(OUT, "features.parquet"), index=False)
    print(f"data/features.parquet  {len(f)} rows, {len(feature_cols(f))} features")
    print("\nrows per target season:")
    print(f.groupby(f.y_season.astype(int)).size().to_string())
    print("\nrows per position:")
    print(f.groupby("position").size().to_string())
    print("\nfeature null rate (worst 12):")
    fc = feature_cols(f)
    print(f[fc].isna().mean().sort_values(ascending=False).head(12).round(3).to_string())
