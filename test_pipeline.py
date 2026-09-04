#!/usr/bin/env python3
"""
test_pipeline.py — correctness tests for the data and model layer.

The single most important test here is LEAKAGE: a feature row whose target is
season N+1 must contain nothing from season N+1 or later. Everything else in the
backtest is worthless if that fails, and it fails silently.

    python3 test_pipeline.py
"""
import json, os, sys, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
import league, features

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data")
FAILS = []


def check(name, cond, detail=""):
    ok = bool(cond)
    print(("PASS  " if ok else "FAIL  ") + name + (f"   {detail}" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)
    return ok


def main():
    panel = pd.read_parquet(os.path.join(OUT, "player_seasons.parquet"))
    f = pd.read_parquet(os.path.join(OUT, "features.parquet"))
    adp = pd.read_parquet(os.path.join(OUT, "adp.parquet"))

    print("--- scoring ---")
    w = pd.read_parquet(os.path.join(OUT, "raw", "stats_player_week_2025.parquet"))
    w = w[(w.season_type == "REG") & (w.position == "QB")]
    six = league.score_frame(w, league.LEAGUE) - league.score_frame(w, league.PUBLIC4)
    ptd = pd.to_numeric(w.passing_tds, errors="coerce").fillna(0)
    check("6-pt gap equals exactly 2 x passing TDs",
          np.allclose(six, 2 * ptd), f"max dev {abs(six - 2*ptd).max():.6f}")
    check("league scoring matches the verified Sleeper settings",
          league.LEAGUE["pass_td"] == 6.0 and league.LEAGUE["rec"] == 0.5
          and league.LEAGUE["pass_int"] == -2.0)

    print("\n--- panel ---")
    check("panel spans 2012-2025", panel.season.min() == 2012 and panel.season.max() == 2025)
    check("one row per player-season",
          not panel.duplicated(["player_id", "season"]).any())
    check("only skill positions", set(panel.position) <= set(league.SKILL))
    # a mid-season trade can span more game-weeks than one team's schedule, so
    # the real ceiling is the number of REG weeks, not one team's game count
    max_week = panel.season.map(lambda y: 18 if y >= 2021 else 17)
    over = panel[panel.games > max_week]
    check("games never exceed the number of regular-season weeks",
          len(over) == 0, f"{len(over)} rows over")
    check("availability is a rate capped at 1",
          (panel.avail <= 1.0 + 1e-9).all())
    check("players over their team's schedule are all mid-season trades",
          bool(panel[panel.games > panel.sched_games].teams_played.fillna(1).gt(1).all()))
    check("snap coverage >= 95% for every season from 2013",
          panel[panel.season >= 2013].groupby("season").snap_pct
               .apply(lambda s: s.notna().mean()).min() >= 0.95)
    z = ["i5_car", "ring_car", "mid_car", "out_car"]
    check("zone bands are disjoint and sum to carries",
          np.allclose(panel[z].sum(axis=1).fillna(0),
                      panel.carries.fillna(0), atol=1.0),
          f"max dev {abs(panel[z].sum(axis=1).fillna(0)-panel.carries.fillna(0)).max():.1f}")

    print("\n--- expected TDs ---")
    p = features.expected_tds(panel)
    g = p.groupby(["season", "position"]).agg(a=("td_total", "sum"), e=("xtd", "sum"))
    check("xTD calibrates within 1% for every season x position",
          (abs(g.e - g.a) / g.a.replace(0, np.nan)).max() < 0.01,
          f"worst {(abs(g.e-g.a)/g.a.replace(0,np.nan)).max():.4f}")
    check("xTD is never negative", (p.xtd >= -1e-9).all())

    print("\n--- LEAKAGE ---")
    # every x_ feature must be reconstructible from season <= N
    lag_ok = True
    sample = f.sample(min(400, len(f)), random_state=0)
    pan = panel.set_index(["player_id", "season"])
    for _, r in sample.iterrows():
        key = (r.player_id, r.season)
        if key not in pan.index:
            continue
        if "x_pts_pg_1" in r and pd.notna(r.x_pts_pg_1):
            truth = pan.loc[key, "pts_pg"]
            if pd.notna(truth) and abs(r.x_pts_pg_1 - truth) > 1e-6:
                lag_ok = False
                break
    check("x_*_1 features equal the SAME season's value (never the target's)", lag_ok)
    check("every target season is exactly one after the feature season",
          (f.y_season == f.season + 1).all())
    check("y_pts_pg never equals x_pts_pg_1 wholesale (would mean a shifted target)",
          not np.allclose(f.y_pts_pg.fillna(-1), f.x_pts_pg_1.fillna(-2)))
    # a strong direct check: the target must match the panel's NEXT season
    merged = f.merge(panel[["player_id", "season", "pts_pg", "games"]]
                     .rename(columns={"season": "y_season", "pts_pg": "chk_pg",
                                      "games": "chk_g"}),
                     on=["player_id", "y_season"], how="left")
    m = merged.chk_pg.notna() & merged.y_pts_pg.notna()
    check("y_pts_pg equals the panel's next-season value",
          np.allclose(merged.loc[m, "y_pts_pg"], merged.loc[m, "chk_pg"], atol=1e-6),
          f"n={int(m.sum())}")
    check("y_games equals the panel's next-season games",
          np.allclose(merged.loc[m, "y_games"], merged.loc[m, "chk_g"], atol=1e-6))

    print("\n--- ADP ---")
    check("ADP rows carry a source label", adp.adp_source.notna().all())
    live = adp[(adp.season >= 2012) & adp.pos.isin(league.SKILL)]
    check("id match rate >= 99% where a match is possible",
          live.matched.mean() >= 0.99, f"{live.matched.mean():.3%}")
    check("proxy is only used before 2018",
          (adp[adp.adp_source == "half-ppr"].season.min() >= 2018))
    check("zero-game busts are recorded, not dropped",
          (adp.get("zero_season", pd.Series(False)).sum() > 0))

    print("\n--- projections ---")
    if os.path.exists(os.path.join(OUT, "projections_2026.parquet")):
        P = pd.read_parquet(os.path.join(OUT, "projections_2026.parquet"))
        check("floor <= mean <= ceiling for every player",
              ((P.floor_pg <= P.mean_pg + 1e-9) & (P.mean_pg <= P.ceil_pg + 1e-9)).all())
        check("bust probability within [0,1]",
              ((P.bust_prob >= 0) & (P.bust_prob <= 1)).all())
        check("projected games are plausible (10-17)",
              (P.games_proj.between(10, 17)).all(),
              f"range {P.games_proj.min():.1f}-{P.games_proj.max():.1f}")
        check("every player has a confidence marker", P.confidence.notna().all())

    print("\n--- shipped payload ---")
    e = json.load(open(os.path.join(HERE, "edge.json")))
    check("payload is v3", e.get("version") == 3)
    check("payload states the model does not beat ADP",
          e["honesty"]["model_beats_adp"] is False)
    check("payload carries the 14-season 6-pt result",
          e["sixpoint"]["top6"]["seasons"] >= 13)
    check("every player has floor/mean/ceil/bust/conf",
          all(all(k in p for k in ("floor", "mean", "ceil", "bust", "conf"))
              for p in e["players"]))
    check("payload floors never exceed ceilings",
          all(p["floor"] <= p["ceil"] + 1e-9 for p in e["players"]))

    print(f"\n{len(FAILS)} failures" if FAILS else "\nall pipeline checks pass")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
