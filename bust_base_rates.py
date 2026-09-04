#!/usr/bin/env python3
"""
bust_base_rates.py — how often did drafted players actually bust, historically?

"Bust" = returned under 70% of the season points his ADP implied, where the
ADP-implied expectation is a walk-forward isotonic fit on prior seasons only.
This is the exact definition project.py ships, so the two are comparable.

The output is the base rate by position and ADP tier. project.py calibrates its
fan-derived bust probability to these, because a probability read off a five-point
quantile fan gets the ORDERING right and the LEVEL wrong: uncalibrated it
predicted a mean of 33.7% against a realised 24.9%.

    python3 bust_base_rates.py
"""
import os, warnings
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

warnings.filterwarnings("ignore")
import league

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data")
TIERS = [0, 6, 12, 24, 48, 999]
TIER_LABELS = ["1-6", "7-12", "13-24", "25-48", "49+"]


def main():
    f = pd.read_parquet(os.path.join(OUT, "features.parquet"))
    adp = pd.read_parquet(os.path.join(OUT, "adp.parquet"))
    a = (adp.dropna(subset=["player_id"])[["player_id", "season", "adp_pos_rank"]]
            .drop_duplicates(["player_id", "season"]).rename(columns={"season": "y_season"}))
    f = f.merge(a, on=["player_id", "y_season"], how="left")
    f = f[f.adp_pos_rank.notna() & np.isfinite(f.y_pts)]

    rows = []
    for T in range(2016, 2026):
        tr, te = f[f.y_season < T], f[f.y_season == T]
        for pos in league.SKILL:
            t1, t2 = tr[tr.position == pos], te[te.position == pos].copy()
            if len(t1) < 60 or len(t2) < 10:
                continue
            iso = IsotonicRegression(increasing=False, out_of_bounds="clip")
            iso.fit(t1.adp_pos_rank.values, t1.y_pts.values)
            t2["exp_pts"] = iso.predict(t2.adp_pos_rank.values)
            t2["bust"] = (t2.y_pts < 0.70 * t2.exp_pts).astype(int)
            rows.append(t2)
    d = pd.concat(rows, ignore_index=True)
    d["tier"] = pd.cut(d.adp_pos_rank, TIERS, labels=TIER_LABELS)

    print(f"REALISED BUST RATE  (returned <70% of ADP-implied season points)")
    print(f"  overall {d.bust.mean():.1%} on n={len(d)}, {int(d.y_season.min())}-"
          f"{int(d.y_season.max())}\n")
    piv = d.pivot_table(index="position", columns="tier", values="bust",
                        aggfunc="mean", observed=False)
    cnt = d.pivot_table(index="position", columns="tier", values="bust",
                        aggfunc="size", observed=False)
    print("  rate by position x ADP tier:")
    print(piv.round(3).to_string())
    print("\n  n per cell:")
    print(cnt.to_string())

    out = (d.groupby(["position", "tier"], observed=False)
             .agg(n=("bust", "size"), rate=("bust", "mean")).reset_index())
    # thin cells fall back to the position mean, then the overall mean
    pos_rate = d.groupby("position").bust.mean()
    out["rate"] = np.where(out.n >= 25, out.rate,
                           out.position.map(pos_rate).fillna(d.bust.mean()))
    out.to_csv(os.path.join(OUT, "bust_base_rates.csv"), index=False,
               float_format="%.4f")
    print(f"\n  data/bust_base_rates.csv written ({len(out)} cells)")
    return out


if __name__ == "__main__":
    main()
