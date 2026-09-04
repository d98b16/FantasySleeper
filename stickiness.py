#!/usr/bin/env python3
"""
stickiness.py — which stats carry year to year, and which are noise.

For every stat and position, regress next season's value on this season's:

    next = mean + slope * (this - mean)

`slope` is the answer. It is the fraction of a player's deviation from the
positional average that survives into the next year:

    slope ~ 1.0   fully sticky -- last year IS the projection
    slope ~ 0.5   half of the edge repeats, half regresses
    slope ~ 0.0   pure noise -- last year tells you nothing

This is the shrinkage the model should apply, measured rather than assumed, and
it is why "he scored 14 TDs" is a much weaker input than "he had 42 carries
inside the 10".

Volume gates keep tiny samples from dominating: a receiver with 4 targets has a
catch rate, but it means nothing. n is reported for every cell so a low-n row can
be discounted rather than read as fact.

    python3 stickiness.py
"""
import os, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
import features

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data")

# stat -> (label, volume gate column, minimum, positions)
STATS = [
    ("snap_pct",      "snap share",           "games",    8,  "QB RB WR TE"),
    ("target_share",  "target share",         "targets",  30, "RB WR TE"),
    ("air_yards_share","air-yards share",     "targets",  30, "WR TE"),
    ("routes_pg",     "routes / game",        "games",    8,  "RB WR TE"),
    ("targets_pg",    "targets / game",       "games",    8,  "RB WR TE"),
    ("carries_pg",    "carries / game",       "games",    8,  "RB"),
    ("touch_pg",      "touches / game",       "games",    8,  "RB WR TE"),
    ("rz_touch_pg",   "red-zone touches / g", "games",    8,  "RB WR TE"),
    ("i10_touch_pg",  "inside-10 touches / g","games",    8,  "RB WR TE"),
    ("adot",          "aDOT",                 "targets",  30, "WR TE"),
    ("attempts_pg",   "pass attempts / game", "games",    8,  "QB"),
    ("catch_rate",    "catch rate",           "targets",  40, "RB WR TE"),
    ("ypc",           "yards per carry",      "carries",  60, "RB"),
    ("ypr",           "yards per reception",  "receptions",25,"WR TE"),
    ("yprr",          "yards per route",      "routes",   150,"WR TE"),
    ("yac_per_rec",   "YAC per reception",    "receptions",25,"RB WR TE"),
    ("yac_per_carry", "yds after contact/car","carries",  60, "RB"),
    ("td_pg",         "TDs / game",           "games",    8,  "RB WR TE"),
    ("td_oe_pg",      "TDs over expected / g","games",    8,  "RB WR TE"),
    ("pts_pg",        "fantasy pts / game",   "games",    8,  "QB RB WR TE"),
    ("pts_xtd_pg",    "TD-adj pts / game",    "games",    8,  "QB RB WR TE"),
    ("games",         "games played",         "games",    1,  "QB RB WR TE"),
    ("avail",         "availability",         "games",    1,  "QB RB WR TE"),
]


def slope_of(x, y):
    """OLS slope of y on x, plus correlations. Returns None if degenerate."""
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if len(x) < 25 or x.std() == 0:
        return None
    b = np.polyfit(x, y, 1)[0]
    r = np.corrcoef(x, y)[0, 1]
    sx = pd.Series(x).rank(); sy = pd.Series(y).rank()
    rho = np.corrcoef(sx, sy)[0, 1]
    return dict(n=len(x), slope=b, r=r, r2=r ** 2, spearman=rho)


def main():
    panel = features.expected_tds(pd.read_parquet(os.path.join(OUT, "player_seasons.parquet")))
    panel["routes_pg"] = panel.routes / panel.games.replace(0, np.nan)
    panel = panel.sort_values(["player_id", "season"])

    rows = []
    for stat, label, gate, gmin, poss in STATS:
        if stat not in panel.columns:
            continue
        for pos in poss.split():
            cols = list(dict.fromkeys(          # a stat can be its own gate
                ["player_id", "season", stat] + ([gate] if gate in panel else [])))
            d = panel[panel.position == pos][cols].copy()
            d = d.sort_values(["player_id", "season"])
            d["nxt"] = d.groupby("player_id")[stat].shift(-1)
            d["nxt_season"] = d.groupby("player_id").season.shift(-1)
            d["gate_next"] = (d.groupby("player_id")[gate].shift(-1)
                              if gate in d.columns else np.nan)
            d = d[d.nxt_season == d.season + 1]
            if gate in d.columns:
                d = d[(d[gate] >= gmin) & (d.gate_next >= gmin)]
            r = slope_of(d[stat].values.astype(float), d.nxt.values.astype(float))
            if r:
                rows.append(dict(stat=stat, label=label, pos=pos, **r))
    t = pd.DataFrame(rows)
    t["verdict"] = pd.cut(t.slope, [-9, 0.15, 0.35, 0.55, 0.75, 9],
                          labels=["noise", "mostly noise", "half repeats",
                                  "mostly sticky", "very sticky"])
    t = t.sort_values(["pos", "slope"], ascending=[True, False])
    t.to_csv(os.path.join(OUT, "stickiness.csv"), index=False, float_format="%.4f")

    print("YEAR-OVER-YEAR STICKINESS  (slope = fraction of a player's edge that repeats)\n")
    for pos in ["QB", "RB", "WR", "TE"]:
        s = t[t.pos == pos]
        if s.empty:
            continue
        print(f"--- {pos} " + "-" * 62)
        print(f"{'stat':24}{'slope':>7}{'r':>7}{'r2':>7}{'n':>6}   verdict")
        for _, r in s.iterrows():
            print(f"{r.label:24}{r.slope:>7.2f}{r.r:>7.2f}{r.r2:>7.2f}{r.n:>6}   {r.verdict}")
        print()
    print(f"data/stickiness.csv  {len(t)} rows")
    return t


if __name__ == "__main__":
    main()
