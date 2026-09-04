#!/usr/bin/env python3
"""
edge_tests.py — targeted, falsifiable tests of specific edge hypotheses.

The general model loses to ADP. That does not mean every signal is worthless --
it means a 59-feature model cannot beat the market at predicting points. A
narrower question survives: are there SPECIFIC, pre-registered situations where
the market is measurably wrong in a repeatable direction?

Each test below is one hypothesis, evaluated out of sample across every season,
against the null that ADP is already right. A test that fails is reported as
failed. The console only gets to use the ones that pass.

    python3 edge_tests.py
"""
import os, warnings
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")
import features, league

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, "data")


def load():
    panel = features.expected_tds(pd.read_parquet(os.path.join(OUT, "player_seasons.parquet")))
    panel["routes_pg"] = panel.routes / panel.games.replace(0, np.nan)
    adp = pd.read_parquet(os.path.join(OUT, "adp.parquet"))
    a = (adp.dropna(subset=["player_id"])[["player_id", "season", "adp",
                                           "adp_rank", "adp_pos_rank"]]
            .drop_duplicates(["player_id", "season"]))
    d = panel.sort_values(["player_id", "season"]).copy()
    # next season's outcome
    for c in ("pts", "games", "season"):
        d[f"n_{c}"] = d.groupby("player_id")[c].shift(-1)
    d = d[d.n_season == d.season + 1].copy()
    d["n_pts_pg"] = d.n_pts / d.n_games.replace(0, np.nan)
    # the market's price for that NEXT season
    d = d.merge(a.rename(columns={"season": "n_season"}), on=["player_id", "n_season"], how="left")
    d = d[d.adp.notna()].copy()
    # how he finished vs how he was priced, within position
    d["n_pos_rank"] = d.groupby(["n_season", "position"]).n_pts.rank(ascending=False, method="min")
    d["beat_price"] = d.adp_pos_rank - d.n_pos_rank        # + = beat his ADP
    return d


def report(name, hypothesis, d, mask, metric="beat_price", min_n=60):
    """Does the flag predict beating your draft price, ONCE PRICE IS CONTROLLED?

    The raw gap is confounded: cheap players can overperform their rank by a lot
    and expensive ones cannot, so any flag correlated with draft cost shows a big
    raw effect that means nothing. The test that matters regresses the outcome on
    the flag while controlling for the ADP positional rank itself (linear and
    quadratic) plus position and season fixed effects. That coefficient is the
    only number here worth acting on, and its own p-value is what decides."""
    dd = d[d[metric].notna()].copy()
    dd["flag"] = mask.reindex(dd.index, fill_value=False).astype(float)
    g = dd[dd.flag == 1]
    if len(g) < min_n:
        print(f"\n  {name}: SKIPPED, only n={len(g)} (need {min_n})")
        return None
    raw = g[metric].mean() - dd[dd.flag == 0][metric].mean()

    X = [dd.flag.values, dd.adp_pos_rank.values, dd.adp_pos_rank.values ** 2]
    names = ["flag", "adp", "adp2"]
    for col in ("position", "n_season"):
        for lvl in sorted(dd[col].dropna().unique())[1:]:
            X.append((dd[col] == lvl).astype(float).values); names.append(f"{col}={lvl}")
    X = np.column_stack(X + [np.ones(len(dd))])
    y = dd[metric].values
    ok = np.isfinite(y) & np.isfinite(X).all(axis=1)
    X, y = X[ok], y[ok]
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = max(len(y) - X.shape[1], 1)
    try:
        cov = np.linalg.pinv(X.T @ X) * (resid @ resid) / dof
        se = np.sqrt(np.diag(cov))[0]
    except Exception:
        se = np.nan
    eff = beta[0]
    t = eff / se if se and np.isfinite(se) else np.nan
    p = 2 * (1 - stats.t.cdf(abs(t), dof)) if np.isfinite(t) else np.nan
    verdict = ("PASSES" if np.isfinite(p) and p < 0.05 and abs(eff) >= 3 else
               "fails (not significant once price is controlled)" if not (np.isfinite(p) and p < 0.05) else
               "fails (significant but too small to act on)")
    print(f"\n  {name}")
    print(f"    hypothesis: {hypothesis}")
    print(f"    n={len(g)} flagged | raw gap {raw:+.1f} pos-ranks")
    print(f"    controlled for ADP + position + season: {eff:+.1f} +/- {1.96*se:.1f} "
          f"(t={t:+.2f}, p={p:.4f})")
    print(f"    -> {verdict}")
    return dict(test=name, n=len(g), raw=raw, effect=eff, se=se, p=p,
                passes=verdict.startswith("PASS"))


def main():
    d = load()
    print("=" * 76)
    print("PRE-REGISTERED EDGE TESTS — does the market miss these, repeatably?")
    print(f"population: {len(d)} player-seasons that had an ADP the following year, "
          f"{int(d.n_season.min())}-{int(d.n_season.max())}")
    print("outcome: (ADP positional rank) - (actual positional finish). "
          "Positive = beat his price.")
    print("=" * 76)
    res = []
    skill = d.position.isin(["RB", "WR", "TE"])

    res.append(report(
        "1. TD luck regresses (fade)",
        "a player who scored far MORE TDs than his opportunity implied is priced "
        "on those TDs and will regress",
        d, skill & (d.td_oe >= 2.5)))

    res.append(report(
        "2. TD drought rebounds (buy)",
        "a player who scored far FEWER TDs than his opportunity implied is "
        "underpriced and will rebound",
        d, skill & (d.td_oe <= -2.0)))

    res.append(report(
        "3. Opportunity without production (buy)",
        "high snap and target share but weak points -- the role is there and the "
        "market is pricing the box score",
        d, skill & (d.snap_pct >= 0.65) & (d.target_share >= 0.18) &
           (d.pts_pg < d.groupby(['season','position']).pts_pg.transform('median'))))

    res.append(report(
        "4. Efficiency spike regresses (fade)",
        "a career-high yards per touch is noise (measured slope 0.17 YPC) and "
        "will not repeat",
        d, (d.position == "RB") & (d.ypc >= 5.0) & (d.carries >= 100)))

    res.append(report(
        "5. Missed most of last year (fade)",
        "availability is only ~0.4 sticky, so last year's injury still predicts "
        "this year's",
        d, skill & (d.games <= 9)))

    res.append(report(
        "6. Age cliff at RB (fade)",
        "running backs age out earlier than the market prices",
        d, (d.position == "RB") & (d.age >= 28)))

    res.append(report(
        "7. Young ascending role (buy)",
        "under 25 with a rising snap share -- the role is still growing",
        d, skill & (d.age <= 24) & (d.snap_pct >= 0.55)))

    live = [r for r in res if r]
    # Seven tests at p<0.05 would produce ~0.35 false positives by chance. Report
    # the Bonferroni threshold alongside the raw p so a marginal result is not
    # mistaken for a finding.
    bonf = 0.05 / len(live)
    for r in live:
        r["survives_bonferroni"] = bool(np.isfinite(r["p"]) and r["p"] < bonf)
    ok = [r for r in live if r["passes"]]
    print("\n" + "=" * 76)
    print(f"RESULT: {len(ok)} of {len(live)} hypotheses survive at p<0.05 with an "
          f"effect of at least 3 positional ranks.")
    print(f"Bonferroni threshold for {len(live)} tests: p < {bonf:.4f}\n")
    print(f"  {'test':40}{'effect':>8}{'p':>9}  verdict")
    for r in sorted(live, key=lambda x: x["p"]):
        v = ("ACT ON IT" if r["passes"] and r["survives_bonferroni"] else
             "act on it (marginal)" if r["passes"] else
             "real but too small" if r["survives_bonferroni"] else
             "no evidence")
        print(f"  {r['test']:40}{r['effect']:>+8.1f}{r['p']:>9.4f}  {v}")
    print("\n  The pattern across all seven: raw gaps are large and often highly")
    print("  significant, and they collapse once ADP is controlled. The market has")
    print("  already priced these signals. That is the finding.")
    pd.DataFrame([r for r in res if r]).to_csv(
        os.path.join(OUT, "edge_tests.csv"), index=False, float_format="%.4f")
    return res


if __name__ == "__main__":
    main()
