#!/usr/bin/env python3
"""
calibration.py — are the floor/ceiling intervals actually calibrated?

A quantile model that says "10th percentile" must be wrong 10% of the time on the
low side, or the floor shipped to the user is a lie. This runs the SAME
walk-forward protocol as the backtest and measures realised coverage.

    python3 calibration.py
"""
import os, warnings
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.isotonic import IsotonicRegression

warnings.filterwarnings("ignore")
import features, league

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, "data")
QS   = (0.10, 0.25, 0.50, 0.75, 0.90)
HGB  = dict(max_iter=300, learning_rate=0.06, max_depth=4, min_samples_leaf=25,
            l2_regularization=1.0, early_stopping=False, random_state=0)


def main():
    f = pd.read_parquet(os.path.join(OUT, "features.parquet"))
    adp = pd.read_parquet(os.path.join(OUT, "adp.parquet"))
    a = (adp.dropna(subset=["player_id"])[["player_id", "season", "adp_pos_rank"]]
            .drop_duplicates(["player_id", "season"]).rename(columns={"season": "y_season"}))
    f = f.merge(a, on=["player_id", "y_season"], how="left")
    f["x_adp_pos_rank"] = f.adp_pos_rank
    cols = features.feature_cols(f)

    rows = []
    for T in range(2018, 2026):
        tr_all, te_all = f[f.y_season < T], f[f.y_season == T]
        for pos in league.SKILL:
            tr = tr_all[tr_all.position == pos]
            te = te_all[(te_all.position == pos) & te_all.adp_pos_rank.notna()].copy()
            if len(tr) < 80 or len(te) < 15:
                continue
            pc = [c for c in cols if tr[c].notna().any()]
            y = tr.y_pts_pg.values
            ok = np.isfinite(y)
            fit = {}
            for q in QS:
                fit[q] = HistGradientBoostingRegressor(loss="quantile", quantile=q, **HGB) \
                    .fit(tr[pc].values[ok], y[ok]).predict(te[pc].values)
            # raw model quantiles
            for q in QS:
                te[f"m{int(q*100)}"] = fit[q]
            # the SHIPPED construction: ADP centre, model spread around it
            anchor = IsotonicRegression(increasing=False, out_of_bounds="clip")
            atr = tr[tr.adp_pos_rank.notna() & np.isfinite(tr.y_pts_pg)]
            anchor.fit(atr.adp_pos_rank.values, atr.y_pts_pg.values)
            centre = anchor.predict(te.x_adp_pos_rank.values)
            med = te.m50.values
            for q in QS:
                te[f"s{int(q*100)}"] = te[f"m{int(q*100)}"].values - med + centre
            rows.append(te)

    d = pd.concat(rows, ignore_index=True)
    d = d[np.isfinite(d.y_pts_pg)]
    print(f"n = {len(d)} held-out player-seasons, 2018-2025, players with an ADP\n")
    print(f"{'construction':16}{'below q10':>11}{'below q25':>11}{'below q50':>11}"
          f"{'below q75':>11}{'below q90':>11}")
    print(f"{'(target)':16}{'10%':>11}{'25%':>11}{'50%':>11}{'75%':>11}{'90%':>11}")
    out = {}
    for tag, label in (("m", "model quantiles"), ("s", "SHIPPED (ADP centre)")):
        cov = [(d.y_pts_pg < d[f"{tag}{int(q*100)}"]).mean() for q in QS]
        out[tag] = cov
        print(f"{label:16}" + "".join(f"{c*100:>10.1f}%" for c in cov))
    print()
    for tag, label in (("m", "model quantiles"), ("s", "SHIPPED")):
        lo, hi = out[tag][0], out[tag][-1]
        inside = hi - lo
        print(f"  {label:20} 80% interval actually contains {inside*100:.1f}% of outcomes "
              f"(target 80%); {lo*100:.1f}% below floor, {(1-hi)*100:.1f}% above ceiling")
    print()
    print("  by position (SHIPPED construction, 80% interval coverage):")
    for pos in league.SKILL:
        s = d[d.position == pos]
        if len(s) < 30:
            continue
        lo = (s.y_pts_pg < s.s10).mean(); hi = (s.y_pts_pg > s.s90).mean()
        print(f"    {pos}  n={len(s):>4}  below floor {lo*100:5.1f}%  "
              f"above ceiling {hi*100:5.1f}%  inside {(1-lo-hi)*100:5.1f}%")
    d.to_parquet(os.path.join(OUT, "calibration.parquet"), index=False)
    return d


if __name__ == "__main__":
    main()
