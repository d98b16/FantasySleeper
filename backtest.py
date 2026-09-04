#!/usr/bin/env python3
"""
backtest.py — walk-forward validation against three baselines, including ADP.

THE BAR IS ADP. It is a sharp market with an information advantage the model does
not have: it is set days before the season and already prices in training camp,
holdouts, preseason injuries and depth-chart news. Beating it out of sample is
the only result that justifies using a model at all. If the model loses, this
script says so.

PROTOCOL
    For each target season T, train on every (N -> N+1) pair with N+1 < T, then
    predict T. No row from T or later ever touches training. The first evaluated
    season is 2016 so that even the earliest model sees three seasons of pairs.

TWO MODELS, because rate and availability are different questions:
    rate model         y = fantasy points per game
    availability model y = games played
    season projection  = rate x games

BASELINES
    last_year   next year's rate = this year's rate (naive persistence)
    pos_mean    next year's rate = the positional average in the training data
    adp         ADP rank mapped to expected points by an isotonic fit on PRIOR
                seasons only -- this converts a rank into a point projection so
                it can be scored on the same footing as the model

POPULATION
    Everything is evaluated on the players who actually had an ADP that season,
    because that is the draftable universe and the only place ADP exists. The
    model is not allowed to look good by predicting players nobody would draft.
"""
import os, json, warnings
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

warnings.filterwarnings("ignore")
import features, league

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, "data")
FIRST_EVAL = 2016
POSITIONS = ["QB", "RB", "WR", "TE"]

HGB = dict(max_iter=300, learning_rate=0.06, max_depth=4, min_samples_leaf=25,
           l2_regularization=1.0, early_stopping=False, random_state=0)


def load():
    f = pd.read_parquet(os.path.join(OUT, "features.parquet"))
    adp = pd.read_parquet(os.path.join(OUT, "adp.parquet"))
    a = (adp.dropna(subset=["player_id"])[["player_id", "season", "adp", "adp_rank",
                                           "adp_pos_rank", "adp_sd", "adp_source"]]
            .drop_duplicates(["player_id", "season"]))
    # ADP for season S is the market's view of season S -- join it to the row
    # whose TARGET is season S, i.e. the feature row for season S-1.
    a = a.rename(columns={"season": "y_season"})
    f = f.merge(a, on=["player_id", "y_season"], how="left")
    f["has_adp"] = f.adp.notna()
    # ADP is PUBLIC at draft time, so a projection system is entitled to use it.
    # Withholding it makes the model fight the market with one hand tied: it
    # cannot see offseason team changes, coaching hires, holdouts or camp
    # reports, all of which ADP already prices in. Using it is not leakage --
    # ADP for season S is published before season S is played.
    f["x_adp_rank"] = f.adp_rank
    f["x_adp_pos_rank"] = f.adp_pos_rank
    f["x_adp_sd"] = f.adp_sd
    f["x_log_adp"] = np.log1p(f.adp)
    return f


def fit_predict(train, test, cols, target, quantiles=(0.1, 0.5, 0.9)):
    """Mean model plus quantile models. HistGradientBoosting handles NaN
    natively, which matters here: routes start in 2016 and PFR advanced stats in
    2018, and 'unknown' must not be imputed to 'zero'."""
    Xtr, ytr = train[cols].values, train[target].values
    m = np.isfinite(ytr)
    Xtr, ytr = Xtr[m], ytr[m]
    if len(ytr) < 40:
        return None
    out = {}
    mean = HistGradientBoostingRegressor(loss="squared_error", **HGB).fit(Xtr, ytr)
    out["mean"] = mean.predict(test[cols].values)
    for q in quantiles:
        qm = HistGradientBoostingRegressor(loss="quantile", quantile=q, **HGB).fit(Xtr, ytr)
        out[f"q{int(q*100)}"] = qm.predict(test[cols].values)
    return out


def adp_baseline(train, test, target="y_pts_pg"):
    """Turn an ADP rank into a point projection using only prior seasons.

    Fit WITHIN POSITION on the positional ADP rank, not on the overall rank. An
    overall-rank fit is a strawman: a QB at overall pick 80 would be assigned the
    average points of every player drafted around pick 80, who are mostly RB/WR
    scoring far less per game, so ADP would "lose" on QB by a huge margin purely
    because of how the baseline was built. Measured: the overall-rank version
    gave ADP a QB MAE of 10.1 pts/game against the model's 4.2, while ADP still
    had the BETTER rank correlation (0.475 vs 0.261) -- the gap was entirely
    calibration, not skill.

    Isotonic because rank -> points is monotone but very much not linear.
    """
    tr = train[train.has_adp & np.isfinite(train[target]) & np.isfinite(train.adp_pos_rank)]
    out = np.full(len(test), np.nan)
    if len(tr) < 40:
        return out
    iso = IsotonicRegression(increasing=False, out_of_bounds="clip")
    iso.fit(tr.adp_pos_rank.values, tr[target].values)
    m = np.isfinite(test.adp_pos_rank.values)
    if m.any():
        out[m] = iso.predict(test.adp_pos_rank.values[m])
    return out


def metrics(y, p, label, n_top=24):
    m = np.isfinite(y) & np.isfinite(p)
    y, p = np.asarray(y)[m], np.asarray(p)[m]
    if len(y) < 10:
        return None
    err = p - y
    sy, sp = pd.Series(y).rank(), pd.Series(p).rank()
    spearman = np.corrcoef(sy, sp)[0, 1]
    k = min(n_top, len(y) // 3)
    top_actual = set(np.argsort(-y)[:k])
    top_pred = set(np.argsort(-p)[:k])
    hit = len(top_actual & top_pred) / k if k else np.nan
    return dict(model=label, n=len(y), mae=np.abs(err).mean(),
                rmse=np.sqrt((err ** 2).mean()), bias=err.mean(),
                spearman=spearman, top_hit=hit)


def run():
    f = load()
    cols = features.feature_cols(f)
    seasons = sorted(int(s) for s in f.y_season.dropna().unique() if s >= FIRST_EVAL)
    rows, preds = [], []

    for T in seasons:
        train = f[f.y_season < T]
        test = f[f.y_season == T].copy()
        if len(train) < 200 or test.empty:
            continue
        for pos in POSITIONS:
            tr = train[train.position == pos]
            te = test[test.position == pos].copy()
            if len(tr) < 60 or len(te) < 15:
                continue
            pc_all = [c for c in cols if tr[c].notna().any()]
            pc_noadp = [c for c in pc_all if not c.startswith("x_adp")
                        and c != "x_log_adp"]
            # two models: stats only (can it beat the market unaided?) and
            # stats + ADP (can it improve ON the market?)
            rate = fit_predict(tr, te, pc_all, "y_pts_pg")
            rate_noadp = fit_predict(tr, te, pc_noadp, "y_pts_pg")
            games = fit_predict(tr, te, pc_all, "y_games", quantiles=())
            if rate is None or rate_noadp is None:
                continue
            te["p_rate_noadp"] = rate_noadp["mean"]
            # both baselines fit within this position, on prior seasons only
            te["b_adp"] = adp_baseline(tr, te, "y_pts_pg")
            te["b_adp_games"] = adp_baseline(tr, te, "y_games")

            # ---- RESIDUAL FRAMING -------------------------------------------
            # Predicting points from scratch makes the model re-learn the whole
            # rank->points curve that ADP already encodes, with a few hundred
            # rows. The question that actually matters is narrower: given the
            # market price, where is it WRONG? So fit on the residual from the
            # ADP baseline and add the prediction back. If the residual is
            # unpredictable, this collapses to ADP and loses nothing.
            tr_r = tr.copy()
            tr_r["b_adp"] = adp_baseline(tr, tr, "y_pts_pg")
            tr_r["resid"] = tr_r.y_pts_pg - tr_r.b_adp
            fit_r = tr_r[np.isfinite(tr_r.resid)]
            te["p_resid_gbm"] = np.nan
            te["p_resid_ridge"] = np.nan
            if len(fit_r) >= 60:
                rr = fit_predict(fit_r, te, pc_all, "resid", quantiles=())
                if rr is not None:
                    te["p_resid_gbm"] = te.b_adp + rr["mean"]
                # a heavily regularised linear model is a better match for a few
                # hundred rows than a boosted ensemble; included so the negative
                # result cannot be blamed on one model class
                ridge = make_pipeline(
                    SimpleImputer(strategy="median"), StandardScaler(),
                    RidgeCV(alphas=np.logspace(-1, 4, 20)))
                yv = fit_r["resid"].values
                ok = np.isfinite(yv)
                if ok.sum() >= 60:
                    ridge.fit(fit_r[pc_all].values[ok], yv[ok])
                    te["p_resid_ridge"] = te.b_adp + ridge.predict(te[pc_all].values)
            te["p_rate"] = rate["mean"]
            te["p_rate_q10"] = rate["q10"]
            te["p_rate_q50"] = rate["q50"]
            te["p_rate_q90"] = rate["q90"]
            te["p_games"] = np.clip(games["mean"], 0, te.sched_games.max()) if games else np.nan
            te["p_season"] = te.p_rate * te.p_games
            te["b_last"] = te.x_pts_pg_1
            te["b_posmean"] = tr.y_pts_pg.mean()
            preds.append(te)

            ev = te[te.has_adp]              # the draftable universe
            if len(ev) < 15:
                continue
            for label, col in [("model+adp", "p_rate"), ("model_statsonly", "p_rate_noadp"),
                               ("adp+resid_gbm", "p_resid_gbm"),
                               ("adp+resid_ridge", "p_resid_ridge"),
                               ("last_year", "b_last"),
                               ("pos_mean", "b_posmean"), ("adp", "b_adp")]:
                r = metrics(ev.y_pts_pg.values, ev[col].values, label)
                if r:
                    rows.append(dict(season=T, pos=pos, target="pts_per_game", **r))
            # season totals: each method gets its OWN games estimate, so ADP is
            # not silently handed the model's availability forecast
            for label, p in [("model+adp", ev.p_rate * ev.p_games),
                             ("model_statsonly", ev.p_rate_noadp * ev.p_games),
                             ("adp", ev.b_adp * ev.b_adp_games),
                             ("last_year", ev.b_last * ev.x_games_1)]:
                r = metrics(ev.y_pts.values, p.values, label)
                if r:
                    rows.append(dict(season=T, pos=pos, target="season_points", **r))

    res = pd.DataFrame(rows)
    P = pd.concat(preds, ignore_index=True)
    res.to_csv(os.path.join(OUT, "backtest_results.csv"), index=False, float_format="%.4f")
    P.to_parquet(os.path.join(OUT, "backtest_predictions.parquet"), index=False)
    return res, P


def report(res, P):
    print("=" * 78)
    print("WALK-FORWARD BACKTEST — train on every season before T, predict T")
    print(f"evaluated on players with an ADP that season | {res.season.min()}-{res.season.max()}")
    print("=" * 78)

    for target in ["pts_per_game", "season_points"]:
        r = res[res.target == target]
        if r.empty:
            continue
        print(f"\n### TARGET: {target}  (pooled over all seasons, weighted by n)\n")
        agg = (r.groupby(["pos", "model"])
                 .apply(lambda g: pd.Series({
                     "n": g.n.sum(),
                     "MAE": np.average(g.mae, weights=g.n),
                     "RMSE": np.average(g.rmse, weights=g.n),
                     "Spearman": np.average(g.spearman, weights=g.n),
                     "top24_hit": np.average(g.top_hit, weights=g.n)}))
                 .reset_index())
        for pos in POSITIONS:
            a = agg[agg.pos == pos]
            if a.empty:
                continue
            base = a[a.model == "adp"]
            print(f"  {pos}")
            print(f"    {'model':11}{'n':>6}{'MAE':>8}{'RMSE':>8}{'Spearman':>10}{'top24':>8}   vs ADP")
            for _, x in a.sort_values("MAE").iterrows():
                if len(base) and x.model != "adp":
                    d = (base.MAE.iloc[0] - x.MAE) / base.MAE.iloc[0] * 100
                    ds = f"{d:+5.1f}% MAE"
                else:
                    ds = "—" if x.model == "adp" else ""
                print(f"    {x.model:11}{int(x.n):>6}{x.MAE:>8.3f}{x.RMSE:>8.3f}"
                      f"{x.Spearman:>10.3f}{x.top24_hit:>8.2f}   {ds}")
            print()
    return res


if __name__ == "__main__":
    res, P = run()
    report(res, P)
    print(f"\ndata/backtest_results.csv  {len(res)} rows")
    print(f"data/backtest_predictions.parquet  {len(P)} rows")
