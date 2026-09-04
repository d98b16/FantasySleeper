#!/usr/bin/env python3
"""
rookies.py — what actually predicts a rookie's year-1 fantasy production?

The edge model excludes rookies by construction: they have no prior NFL season,
so there is nothing to lag. That is correct, but it is not the same as saying
nothing is knowable. This file tests the traits people actually cite, against
every rookie season in the panel, and reports what predicts and what does not.

TESTED
  draft capital        overall pick and round, from nflverse draft_picks
  landing spot         opportunity vacated by the team he joined -- targets and
                       carries produced last year by players no longer there
  athleticism          combine testing, where the player has it

NOT TESTED, and I am not going to pretend otherwise:
  college production   nflverse carries the college NAME but no college stats,
                       and I have no cached CFB source. "College dominator" is
                       therefore UNTESTED here, not disproven. Anyone claiming it
                       works from this repo's data is claiming something the data
                       cannot support either way.

    python3 rookies.py
"""
import os, warnings
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")
import league

HERE = os.path.dirname(os.path.abspath(__file__))
RAW  = os.path.join(HERE, "data", "raw")
OUT  = os.path.join(HERE, "data")
CLASS_YEAR = 2026


def load_panel():
    p = pd.read_parquet(os.path.join(OUT, "player_seasons.parquet"))
    p["pg"] = p.pts / p.games.replace(0, np.nan)
    return p


def draft_table():
    dp = pd.read_parquet(os.path.join(RAW, "draft_picks.parquet"))
    dp = dp[dp.position.isin(league.SKILL)].copy()
    dp["overall"] = pd.to_numeric(dp.pick, errors="coerce")
    dp["rd"] = pd.to_numeric(dp["round"], errors="coerce")
    return dp


def vacated(panel):
    """Opportunity a team lost going into season Y: targets and carries produced
    for that team in Y-1 by players who are not on it in Y. Computed from the
    panel's own team assignments, so it needs no roster file and works the same
    way for the historical test and for the current class."""
    rows = []
    for season in sorted(panel.season.unique()):
        prev = panel[panel.season == season - 1]
        cur = panel[panel.season == season]
        if prev.empty or cur.empty:
            continue
        stay = cur.groupby("team").player_id.apply(set).to_dict()
        for team, g in prev.groupby("team"):
            keep = stay.get(team, set())
            left = g[~g.player_id.isin(keep)]
            rows.append(dict(season=season, team=team,
                             vac_tgt=float(left.targets.sum()),
                             vac_car=float(left.carries.sum()),
                             vac_pts=float(left.pts.sum())))
    return pd.DataFrame(rows)


def build_rookie_seasons(panel, dp):
    """Every player's FIRST season in the panel, joined to his draft capital."""
    first = panel.sort_values("season").groupby("player_id", as_index=False).head(1)
    d = dp.dropna(subset=["gsis_id"])[["gsis_id", "season", "rd", "overall",
                                       "team", "college", "position"]]
    # the panel already carries a draft_year column, so use distinct names here
    d = d.rename(columns={"gsis_id": "player_id", "season": "dclass",
                          "team": "draft_team", "position": "draft_pos"})
    drop = [c for c in ("draft_round", "draft_pick", "draft_year") if c in first.columns]
    r = first.drop(columns=drop).merge(d, on="player_id", how="left")
    # a true rookie season: the first panel season IS his draft year
    r = r[r.dclass == r.season].copy()
    return r


def report(name, x, y, n_min=40):
    m = np.isfinite(x) & np.isfinite(y)
    x, y = np.asarray(x)[m], np.asarray(y)[m]
    if len(x) < n_min:
        print(f"  {name:34} n={len(x):<5} too few to test")
        return None
    rho = stats.spearmanr(x, y).correlation
    p = stats.spearmanr(x, y).pvalue
    verdict = ("PREDICTS" if p < 0.01 and abs(rho) >= 0.15 else
               "weak" if p < 0.05 else "no signal")
    print(f"  {name:34} n={len(x):<5} spearman {rho:+.3f}  p={p:.2e}  r2={rho**2:.3f}  {verdict}")
    return dict(trait=name, n=len(x), rho=rho, p=p, r2=rho ** 2, verdict=verdict)


def main():
    panel = load_panel()
    dp = draft_table()
    vac = vacated(panel)
    r = build_rookie_seasons(panel, dp)
    r = r.merge(vac.rename(columns={"team": "draft_team"}),
                on=["season", "draft_team"], how="left")
    print(f"  matched {len(r)} rookie seasons to draft capital")

    try:
        cb = pd.read_parquet(os.path.join(RAW, "combine.parquet"))
        idc = "pfr_id" if "pfr_id" in cb.columns else None
        if idc:
            keep = [c for c in ["forty", "vertical", "broad_jump", "cone", "shuttle"]
                    if c in cb.columns]
            cb = cb[[idc] + keep].rename(columns={idc: "pfr_id"})
            pl = pd.read_parquet(os.path.join(RAW, "players.parquet"))
            br = pl.dropna(subset=["gsis_id", "pfr_id"])[["gsis_id", "pfr_id"]]
            cb = cb.merge(br, on="pfr_id", how="inner").rename(columns={"gsis_id": "player_id"})
            r = r.merge(cb.drop(columns=["pfr_id"]).drop_duplicates("player_id"),
                        on="player_id", how="left")
    except Exception as e:
        print(f"  (combine unavailable: {e})")

    hist = r[(r.season >= 2013) & (r.season <= 2025)].copy()
    print("=" * 78)
    print("WHAT PREDICTS A ROOKIE'S YEAR-1 FANTASY PRODUCTION?")
    print(f"population: {len(hist)} rookie seasons, {int(hist.season.min())}-"
          f"{int(hist.season.max())}, positions {sorted(hist.position.unique())}")
    print("outcome: fantasy points per game under THIS league's rules")
    print("=" * 78)

    res = []
    for pos in ["ALL"] + league.SKILL:
        s = hist if pos == "ALL" else hist[hist.position == pos]
        if len(s) < 60:
            continue
        print(f"\n--- {pos}  (n={len(s)}) ---")
        res.append(report("draft pick (overall)", -s.overall, s.pg))
        res.append(report("draft round", -s.rd, s.pg))
        if pos in ("ALL", "WR", "TE"):
            res.append(report("targets vacated by his new team", s.vac_tgt, s.pg))
        if pos in ("ALL", "RB"):
            res.append(report("carries vacated by his new team", s.vac_car, s.pg))
        res.append(report("fantasy pts vacated by his new team", s.vac_pts, s.pg))
        if "forty" in s.columns:
            res.append(report("40 time (faster = better)", -s.forty, s.pg))
    out = pd.DataFrame([x for x in res if x])
    out.to_csv(os.path.join(OUT, "rookie_predictors.csv"), index=False, float_format="%.5f")

    print("\n" + "=" * 78)
    print("HIT RATE BY DRAFT CAPITAL  (hit = >=10 fantasy pts/game as a rookie)")
    hist["hit"] = (hist.pg >= 10).astype(int)
    hist["bucket"] = pd.cut(hist.overall, [0, 10, 32, 64, 105, 300],
                            labels=["top 10", "rest of rd 1", "rd 2", "rd 3", "rd 4+"])
    t = hist.groupby("bucket", observed=False).agg(
        n=("hit", "size"), hit_rate=("hit", "mean"), mean_pg=("pg", "mean"),
        median_games=("games", "median"))
    print(t.round(3).to_string())
    print("\nby position x capital:")
    piv = hist.pivot_table(index="position", columns="bucket", values="hit",
                           aggfunc="mean", observed=False)
    print(piv.round(2).to_string())
    hist.to_parquet(os.path.join(OUT, "rookie_history.parquet"), index=False)
    print(f"\ndata/rookie_predictors.csv + data/rookie_history.parquet written")
    return hist, r, vac, dp


if __name__ == "__main__":
    main()
