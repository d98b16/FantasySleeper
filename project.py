#!/usr/bin/env python3
"""
project.py — 2026 projections with a distribution, not a point.

WHAT THE BACKTEST FORCES THIS TO BE
    The walk-forward test says ADP beats the model at ranking players, at every
    position, on both per-game and season targets. So this file does NOT ship a
    model ranking dressed up as a projection. It ships:

      * an ADP-anchored MEAN, because that is what won;
      * a FLOOR and CEILING from quantile models, because ADP is a single number
        and gives you no distribution at all -- this is the one thing the model
        provides that the market does not;
      * a BUST PROBABILITY, same source;
      * the one edge signal that survived out-of-sample testing with price
        controlled (heavy games-missed last season), applied as a small,
        explicitly-sized adjustment rather than a re-ranking.

    Everything is precomputed here and shipped as static JSON. The browser does
    no modelling.

    python3 project.py
"""
import json, os, warnings
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.isotonic import IsotonicRegression

warnings.filterwarnings("ignore")
import features, league

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, "data")
TARGET_SEASON = 2026
HGB = dict(max_iter=300, learning_rate=0.06, max_depth=4, min_samples_leaf=25,
           l2_regularization=1.0, early_stopping=False, random_state=0)
QUANTILES = (0.10, 0.25, 0.50, 0.75, 0.90)
# the single edge that survived edge_tests.py with ADP controlled
INJURY_FADE_GAMES = 9
INJURY_FADE_RANKS = 3.1


def build_training():
    # rebuild with the final season's untargeted rows included; the cached
    # features.parquet is training-only by design
    f = features.build(keep_untargeted=True)
    adp = pd.read_parquet(os.path.join(OUT, "adp.parquet"))
    a = (adp.dropna(subset=["player_id"])[["player_id", "season", "adp", "adp_rank",
                                           "adp_pos_rank", "adp_sd"]]
            .drop_duplicates(["player_id", "season"])
            .rename(columns={"season": "y_season"}))
    f = f.merge(a, on=["player_id", "y_season"], how="left")
    f["x_adp_rank"] = f.adp_rank
    f["x_adp_pos_rank"] = f.adp_pos_rank
    f["x_adp_sd"] = f.adp_sd
    f["x_log_adp"] = np.log1p(f.adp)
    return f


def current_board():
    """The 2025 season row for every player on the live draft board, plus his
    2026 ADP from ranks.json. This is the row we project forward."""
    ranks = json.load(open(os.path.join(HERE, "ranks.json")))["ranks"]
    board = pd.DataFrame(ranks)
    board["key"] = board.name.map(league.norm)
    f = build_training()
    latest = f[f.is_projection_row].copy() if "is_projection_row" in f.columns \
             else f[f.season == f.season.max()].copy()
    latest["key"] = latest.player_display_name.map(league.norm)
    if latest.empty:
        raise SystemExit("no projection rows -- features.build(keep_untargeted=True)?")
    m = board.merge(latest, on="key", how="left", suffixes=("", "_p"))
    # the board's own ADP is the market price for 2026
    m["adp_rank"] = m.groupby("pos").rank(method="min")["rank"]
    m["x_adp_pos_rank"] = m.groupby("pos")["rank"].rank(method="min")
    m["x_adp_rank"] = m["rank"]
    m["x_log_adp"] = np.log1p(m.adp.fillna(m["rank"]))
    m["x_adp_sd"] = np.nan
    return m, f


def fit_position(train, test, cols, target):
    X, y = train[cols].values, train[target].values
    ok = np.isfinite(y)
    if ok.sum() < 50:
        return None
    out = {}
    out["mean"] = HistGradientBoostingRegressor(loss="squared_error", **HGB) \
        .fit(X[ok], y[ok]).predict(test[cols].values)
    for q in QUANTILES:
        out[f"q{int(q*100)}"] = HistGradientBoostingRegressor(
            loss="quantile", quantile=q, **HGB).fit(X[ok], y[ok]).predict(test[cols].values)
    return out


def main():
    board, f = current_board()
    train = f[np.isfinite(f.y_pts_pg)]           # never includes projection rows
    cols = [c for c in features.feature_cols(f) if c in board.columns]
    rows = []

    for pos in league.SKILL:
        tr = train[train.position == pos]
        te = board[board.pos == pos].copy()
        if len(tr) < 60 or te.empty:
            continue
        pc = [c for c in cols if tr[c].notna().any()]
        rate = fit_position(tr, te, pc, "y_pts_pg")
        games = fit_position(tr, te, pc, "y_games")
        if rate is None:
            continue

        # ---- CENTRE: ADP anchor. ---------------------------------------
        # The walk-forward test says ADP beats the model at ranking players at
        # every position. So the central estimate is the market's, mapped from
        # positional rank to points by isotonic regression on all prior seasons.
        # The model is NOT used for the centre -- using it would contradict this
        # project's own backtest.
        anchor = IsotonicRegression(increasing=False, out_of_bounds="clip")
        atr = tr[tr.adp_pos_rank.notna() & np.isfinite(tr.y_pts_pg)]
        anchor.fit(atr.adp_pos_rank.values, atr.y_pts_pg.values)
        te["anchor_pg"] = anchor.predict(te.x_adp_pos_rank.values)

        # Availability is modelled as a RATE (games / scheduled) so that
        # 16-game seasons before 2021 are comparable to 17-game ones, then
        # scaled back to this season's 17.
        ganchor = IsotonicRegression(increasing=False, out_of_bounds="clip")
        gtr = tr[tr.adp_pos_rank.notna() & np.isfinite(tr.y_avail)]
        ganchor.fit(gtr.adp_pos_rank.values, gtr.y_avail.values)
        te["anchor_avail"] = np.clip(ganchor.predict(te.x_adp_pos_rank.values), 0, 1)

        # ---- SPREAD: the model. ----------------------------------------
        # This is the one thing the market does not give you. ADP is a single
        # number; the quantile models supply the width around it. The spread is
        # taken RELATIVE to the model's own median so that a model that is
        # mis-centred (it is) still contributes a usable shape.
        med = rate["q50"]
        spread_lo = np.clip(med - rate["q10"], 0, None)
        spread_hi = np.clip(rate["q90"] - med, 0, None)
        te["mean_pg"] = te.anchor_pg
        te["floor_pg"] = np.clip(te.anchor_pg - spread_lo, 0, None)
        te["ceil_pg"] = te.anchor_pg + spread_hi
        te["model_pg"] = rate["mean"]          # kept for transparency, not used

        av_lo = np.clip(games["q10"] / np.clip(games["q50"], 1e-6, None), 0.2, 1.0) \
                if games else 0.75
        te["games_proj"] = np.clip(te.anchor_avail * 17.0, 0, 17)
        te["games_floor"] = np.clip(te.games_proj * av_lo, 0, 17)

        # the one surviving edge, applied as a stated adjustment not a re-rank
        hurt = (te.x_games_1 <= INJURY_FADE_GAMES) & te.x_games_1.notna()
        te["injury_fade"] = hurt
        rp = league.replacement_ranks()[pos]
        repl_pg = float(anchor.predict([rp])[0])
        te["repl_pg"] = repl_pg

        # BUST is defined RELATIVE TO DRAFT COST, not to a league-wide line.
        # Measuring it against replacement made every player drafted after the
        # starter cutoff "100% bust" -- a WR taken in round 10 who finishes WR35
        # is not a bust, he is exactly what you paid for. Bust here is the chance
        # of returning less than 70% of his own projection, read off the fitted
        # quantile fan by interpolating the CDF.
        qs = np.array(QUANTILES)
        fan = np.column_stack([rate[f"q{int(q*100)}"] for q in qs])
        fan = np.sort(fan, axis=1)                 # enforce monotone quantiles
        med = fan[:, len(qs) // 2]
        shifted = fan - med[:, None] + te.anchor_pg.values[:, None]
        thresh = 0.70 * te.anchor_pg.values
        bust = np.array([np.interp(t, row, qs, left=0.0, right=1.0)
                         for t, row in zip(thresh, shifted)])
        te["bust_prob"] = np.clip(bust, 0, 1)
        # P(below the position's replacement line) kept separately: it is the
        # right question for a STARTER slot even though it is the wrong one for
        # a bench pick.
        te["sub_repl_prob"] = np.clip(
            np.array([np.interp(repl_pg, row, qs, left=0.0, right=1.0)
                      for row in shifted]), 0, 1)
        te.loc[hurt, "bust_prob"] = np.clip(te.loc[hurt, "bust_prob"] + 0.08, 0, 1)

        te["mean_season"] = te.mean_pg * te.games_proj
        te["floor_season"] = te.floor_pg * np.where(np.isfinite(te.games_floor),
                                                    te.games_floor, te.games_proj)
        te["ceil_season"] = te.ceil_pg * 17.0
        te["ceil_season"] = te.ceil_pg * 17
        te["vor_season"] = (te.mean_pg - repl_pg) * te.games_proj
        rows.append(te)

    P = pd.concat(rows, ignore_index=True)
    P["confidence"] = np.where(P.x_games_1.isna(), "none",
                       np.where(P.x_games_1 >= 14, "high",
                        np.where(P.x_games_1 >= 9, "med", "low")))
    keep = ["name", "pos", "team", "bye", "rank", "adp", "tier", "mean_pg", "floor_pg",
            "ceil_pg", "model_pg", "repl_pg", "games_proj", "mean_season",
            "floor_season", "ceil_season", "vor_season", "bust_prob", "sub_repl_prob",
            "injury_fade", "confidence", "x_games_1", "x_snap_pct_1",
            "x_target_share_1", "x_td_oe_pg_1", "x_pts_pg_1", "x_age", "x_exp",
            "x_adp_pos_rank"]
    P = P[[c for c in keep if c in P.columns]].sort_values("rank")
    P.to_csv(os.path.join(OUT, "projections_2026.csv"), index=False, float_format="%.3f")
    P.to_parquet(os.path.join(OUT, "projections_2026.parquet"), index=False)
    print(f"data/projections_2026.csv  {len(P)} players")
    print(f"  matched to a 2025 season: {P.x_games_1.notna().sum()}")
    print(f"  injury-fade flagged:      {int(P.injury_fade.sum())}")
    print("\ntop 12 by projected season points:")
    show = ["name", "pos", "rank", "mean_season", "floor_season", "ceil_season",
            "bust_prob", "confidence"]
    print(P.nlargest(12, "mean_season")[show].round(2).to_string(index=False))
    return P


if __name__ == "__main__":
    main()
