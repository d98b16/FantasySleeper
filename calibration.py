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

            # CONFORMALISED: widening factors fit on the TRAINING seasons only,
            # exactly as project.py does it. This is the version that ships.
            k_lo = k_hi = 1.0
            ss = sorted(tr.y_season.dropna().unique())
            if len(ss) >= 4:
                cut = ss[-2]
                fp, cpt = tr[tr.y_season < cut], tr[tr.y_season >= cut]
                if len(fp) >= 60 and len(cpt) >= 40:
                    yf = fp.y_pts_pg.values; okf = np.isfinite(yf)
                    cal = {}
                    for q in (0.10, 0.50, 0.90):
                        cal[q] = HistGradientBoostingRegressor(
                            loss="quantile", quantile=q, **HGB).fit(
                            fp[pc].values[okf], yf[okf]).predict(cpt[pc].values)
                    cm = cal[0.50]
                    clo = np.clip(cm - cal[0.10], 1e-6, None)
                    chi = np.clip(cal[0.90] - cm, 1e-6, None)
                    resid = cpt.y_pts_pg.values - cm
                    fin = np.isfinite(resid); below = resid[fin] < 0
                    if below.sum() > 25:
                        k_lo = np.quantile(np.abs(resid[fin][below] / clo[fin][below]), 0.80)
                    if (~below).sum() > 25:
                        k_hi = np.quantile(resid[fin][~below] / chi[fin][~below], 0.80)
            k_lo, k_hi = float(np.clip(k_lo, 0.8, 4.0)), float(np.clip(k_hi, 0.8, 4.0))
            te["c10"] = centre - (med - te.m10.values) * k_lo
            te["c50"] = centre
            te["c90"] = centre + (te.m90.values - med) * k_hi
            te["k_lo"], te["k_hi"] = k_lo, k_hi
            rows.append(te)

    d = pd.concat(rows, ignore_index=True)
    d = d[np.isfinite(d.y_pts_pg)]
    print(f"n = {len(d)} held-out player-seasons, 2018-2025, players with an ADP\n")
    print(f"{'construction':16}{'below q10':>11}{'below q25':>11}{'below q50':>11}"
          f"{'below q75':>11}{'below q90':>11}")
    print(f"{'(target)':16}{'10%':>11}{'25%':>11}{'50%':>11}{'75%':>11}{'90%':>11}")
    out = {}
    for tag, label in (("m", "raw model"), ("s", "ADP centre, raw"),
                       ("c", "CONFORMALISED")):
        qq = QS if tag != "c" else (0.10, 0.50, 0.90)
        cov = [(d.y_pts_pg < d[f"{tag}{int(q*100)}"]).mean() if f"{tag}{int(q*100)}" in d
               else np.nan for q in QS]
        out[tag] = cov
        print(f"{label:16}" + "".join(
            (f"{c*100:>10.1f}%" if np.isfinite(c) else f"{'-':>11}") for c in cov))
    print()
    for tag, label in (("m", "raw model"), ("s", "ADP centre, raw"),
                       ("c", "CONFORMALISED (ships)")):
        lo, hi = out[tag][0], out[tag][-1]
        if not (np.isfinite(lo) and np.isfinite(hi)):
            continue
        inside = hi - lo
        print(f"  {label:20} 80% interval actually contains {inside*100:.1f}% of outcomes "
              f"(target 80%); {lo*100:.1f}% below floor, {(1-hi)*100:.1f}% above ceiling")
    print()
    print("  by position (CONFORMALISED, the version that ships):")
    for pos in league.SKILL:
        s = d[d.position == pos]
        if len(s) < 30:
            continue
        lo = (s.y_pts_pg < s.c10).mean(); hi = (s.y_pts_pg > s.c90).mean()
        print(f"    {pos}  n={len(s):>4}  below floor {lo*100:5.1f}%  "
              f"above ceiling {hi*100:5.1f}%  inside {(1-lo-hi)*100:5.1f}%")
    d.to_parquet(os.path.join(OUT, "calibration.parquet"), index=False)

    # ---- BUST CALIBRATION -------------------------------------------------
    # The fan gives the right SHAPE (who is riskier) but the wrong LEVEL: read
    # naively it predicted a mean bust rate of 33.7% against a realised 24.9%.
    # Fit an isotonic map from fan-implied bust to realised bust so the ranking
    # is preserved and the level is correct. project.py applies this map.
    fan_cols = ["c10", "c50", "c90"]
    if all(c in d.columns for c in fan_cols):
        qs3 = np.array([0.10, 0.50, 0.90])
        raw = []
        for _, r in d.iterrows():
            row = np.sort([r.c10, r.c50, r.c90])
            raw.append(np.interp(0.70 * r.c50, row, qs3, left=0.0, right=1.0))
        d["fan_bust"] = np.clip(raw, 0, 1)
        d["realised_bust"] = (d.y_pts_pg < 0.70 * d.c50).astype(int)
        iso = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip")
        iso.fit(d.fan_bust.values, d.realised_bust.values)
        grid = np.linspace(0, 1, 101)
        pd.DataFrame({"fan_bust": grid, "calibrated": iso.predict(grid)}).to_csv(
            os.path.join(OUT, "bust_calibration.csv"), index=False, float_format="%.5f")
        print(f"\n  BUST CALIBRATION  n={len(d)}")
        print(f"    fan-implied mean {d.fan_bust.mean():.1%}  ->  "
              f"realised {d.realised_bust.mean():.1%}")
        b = pd.cut(d.fan_bust, [-.01, .1, .2, .3, .4, 1.01])
        t = d.groupby(b).agg(n=("realised_bust", "size"),
                             predicted=("fan_bust", "mean"),
                             realised=("realised_bust", "mean"))
        print(t.round(3).to_string())
        print("    -> data/bust_calibration.csv written")
    return d


if __name__ == "__main__":
    main()
