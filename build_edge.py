#!/usr/bin/env python3
"""
build_edge.py — the console payload, v3: multi-season, and honest about what it
does not know.

WHAT CHANGED FROM v2, AND WHY
    v2 shipped an "edge" column that was my rank minus ADP rank, driven mostly by
    TD regression on a single season. Tested properly across 2013-2025 with draft
    price controlled, that signal is worth +0.2 positional ranks with p=0.80 --
    indistinguishable from nothing. The market had already priced it. See
    edge_tests.py. Shipping it again would be shipping noise.

    So v3 does not claim to out-rank the market. It carries three things the
    market genuinely does not give you:

      1. AN OUTCOME RANGE. ADP is one number. floor / mean / ceiling come from
         quantile models over 13 seasons. At pick 22 the question is usually
         "how wide is this outcome", and the market cannot answer it.
      2. A BUST PROBABILITY -- the chance of finishing below replacement.
      3. THE ONE TESTED EDGE. Nine or fewer games last season predicts finishing
         about 3 positional ranks below ADP even after the market's own
         discount (p=0.0011, survives Bonferroni over 7 tests). It is applied at
         its measured size and labelled, not inflated.

    Every player also carries a confidence marker so a strong signal is
    distinguishable from a weak one at a glance.

    python3 build_edge.py     (or, preferably, python3 sync.py)
"""
import json, os, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
import league

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, "data")

# Measured effects from edge_tests.py, in SEASON POINTS against a walk-forward
# ADP-implied expectation. Both clear Bonferroni for seven tests (p<0.0071).
# Reported in points rather than positional ranks because a rank near the top of
# a position is worth several times what a rank in the 40s is worth -- judging
# by ranks is what made an earlier version wrongly demote young_role.
SIGNALS = {
    "young_role":  dict(effect_pts=+13.3, effect_ranks=+2.2, p=0.0009,
                        label="24 or younger with a starter's snap share", tested=True),
    "injury_fade": dict(effect_pts=-16.0, effect_ranks=-3.1, p=0.0028,
                        label="9 or fewer games last season", tested=True),
}


def human_why(r):
    """One line a person can evaluate at the table. Facts and measured effects
    only -- no scores, and nothing that failed its own test.

    Risk leads when the player carries above-tier bust risk, so a row appearing
    in the bust list does not open with a reason to like him."""
    bits = []
    risky = r.get("bust_excess", 0) >= 0.05
    if risky and r.get("bust_excess", 0) >= 0.05:
        bits.append(f"{r['bust_prob']*100:.0f}% bust risk, "
                    f"{r['bust_excess']*100:+.0f} pts above his price tier")
    if r.get("injury_fade"):
        bits.append(f"{int(r['games_prev'])} games in 2025 — tested fade, -16 pts")
    if r.get("young_role") and not risky:
        bits.append("young with a starter's snap share — tested, +13 pts")
    span = r["ceil_season"] - r["floor_season"]
    if r.get("young_role") and risky:
        bits.append("but young with a starter's snap share — tested, +13 pts")
    elif span >= 180:
        bits.append(f"very wide range: {r['floor_season']:.0f} to {r['ceil_season']:.0f} pts")
    elif r["bust_prob"] <= 0.05 and span <= 130:
        bits.append(f"tight range {r['floor_season']:.0f}-{r['ceil_season']:.0f}, low bust risk")
    if r["conf"] == "none":
        bits.append("no 2025 NFL snaps — not projected, ADP only")
    elif r["conf"] == "low":
        bits.append(f"only {int(r['games_prev'])} games of 2025 evidence")
    if not bits:
        bits.append(f"{r['mean_season']:.0f} pts projected, "
                    f"{r['floor_season']:.0f}-{r['ceil_season']:.0f} range")
    return "; ".join(bits[:2])


def main_with_edge():
    P = pd.read_parquet(os.path.join(OUT, "projections_2026.parquet"))
    tests = pd.read_csv(os.path.join(OUT, "edge_tests.csv")) \
        if os.path.exists(os.path.join(OUT, "edge_tests.csv")) else pd.DataFrame()
    bt = pd.read_csv(os.path.join(OUT, "backtest_results.csv")) \
        if os.path.exists(os.path.join(OUT, "backtest_results.csv")) else pd.DataFrame()

    P = P.copy()
    P["games_prev"] = P.x_games_1
    P["conf"] = P.confidence
    P["young_role"] = ((P.get("x_age", pd.Series(np.nan, index=P.index)) <= 24)
                       & (P.x_snap_pct_1 >= 0.55)).fillna(False)
    # net tested edge, in positional ranks, at measured size and nothing more
    P["edge_ranks"] = (P.injury_fade.astype(float) * SIGNALS["injury_fade"]["effect_ranks"]
                       + P.young_role.astype(float) * SIGNALS["young_role"]["effect_ranks"])
    P["edge_pts"] = (P.injury_fade.astype(float) * SIGNALS["injury_fade"]["effect_pts"]
                     + P.young_role.astype(float) * SIGNALS["young_role"]["effect_pts"])
    P["why"] = P.apply(lambda r: human_why(r), axis=1)

    players = []
    for _, r in P.iterrows():
        players.append({
            "name": r["name"], "pos": r["pos"], "rank": int(r["rank"]),
            "mean": round(float(r.mean_season), 1),
            "floor": round(float(r.floor_season), 1),
            "ceil": round(float(r.ceil_season), 1),
            "pg": round(float(r.mean_pg), 2),
            "games": round(float(r.games_proj), 1),
            "vor": round(float(r.vor_season), 1),
            "bust": round(float(r.bust_prob), 3),
            "bust_excess": round(float(r.bust_excess), 3) if pd.notna(r.bust_excess) else 0.0,
            "edge": round(float(r.edge_ranks), 1),
            "edge_pts": round(float(r.edge_pts), 1),
            "conf": r["conf"],
            "flags": [k for k in ("injury_fade", "young_role") if bool(r.get(k))],
            "why": r["why"],
        })

    # what the backtest says, shipped alongside so the console can be honest
    verdict = {}
    if len(bt):
        b = bt[bt.target == "pts_per_game"]
        for pos in league.SKILL:
            s = b[b.pos == pos]
            if s.empty:
                continue
            adp = s[s.model == "adp"]
            mdl = s[s.model == "model+adp"]
            if len(adp) and len(mdl):
                a = np.average(adp.mae, weights=adp.n)
                m = np.average(mdl.mae, weights=mdl.n)
                verdict[pos] = {"adp_mae": round(float(a), 3),
                                "model_mae": round(float(m), 3),
                                "model_beats_adp": bool(m < a)}

    # the 6-point result, now on 14 seasons instead of 2
    six = {}
    sp = os.path.join(OUT, "sixpoint.csv")
    if os.path.exists(sp):
        sd = pd.read_csv(sp)
        for tier in ("top6", "top3", "QB1"):
            t = sd[sd.tier == tier].gain_season
            if len(t):
                by_season = sd[sd.tier == tier].groupby("season").gain_season.median()
                se = t.std(ddof=1) / np.sqrt(by_season.size)
                six[tier] = {
                    "median": round(float(t.median()), 1),
                    "mean": round(float(t.mean()), 1),
                    "ci_lo": round(float(t.mean() - 1.96 * se), 1),
                    "ci_hi": round(float(t.mean() + 1.96 * se), 1),
                    "seasons": int(by_season.size),
                    "negative_seasons": int((by_season < 0).sum()),
                }
        six["cells"] = int(len(sd))

    payload = {
        "version": 3,
        "sixpoint": six,
        "generated_from": "nflverse 2012-2025 + FantasyFootballCalculator ADP 2010-2025",
        "scoring": {"half_ppr": 0.5, "pass_td": 6, "pass_int": -2,
                    "note": "verified live against Sleeper league scoring_settings"},
        "honesty": {
            "model_beats_adp": False,
            "detail": ("Walk-forward across 2016-2025, ADP has lower MAE and higher "
                       "rank correlation than the model at every position. The board "
                       "order stays ADP. What the model adds is the outcome range."),
            "per_position": verdict,
            "tested_signals": SIGNALS,
            "n_tested": 7, "n_survived": 2,
            "failed_signals": (tests[tests.passes == False].test.tolist()
                               if len(tests) and "passes" in tests else []),
        },
        "replacement": {k: round(float(v), 2) for k, v in
                        P.groupby("pos").repl_pg.first().items()},
        "players": players,
    }
    with open(os.path.join(HERE, "edge.json"), "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"  edge.json v3  {len(players)} players, "
          f"{int(P.injury_fade.sum())} injury-fade, {int(P.young_role.sum())} young-role")
    return P


if __name__ == "__main__":
    main_with_edge()
