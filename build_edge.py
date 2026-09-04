#!/usr/bin/env python3
"""
build_edge.py — 2025 nflverse season -> league-specific edge model -> data/ + edge.json

WHY THIS EXISTS
    Public ADP is built on 4-point passing TDs and full/half PPR generic scoring.
    This league (GovSmart Gridiron) uses 0.5 PPR and 6-POINT passing TDs. That
    mismatch systematically misprices quarterbacks. This script re-scores every
    2025 player under the league's *exact* verified rules, weights opportunity
    over raw production, builds value-over-replacement against the league's real
    roster shape, and diffs the result against the ADP already in ranks.json.

    The DELTA is the edge.

DATA LAYER
    data/raw/*.parquet   cached nflverse pulls (gitignored, never re-downloaded)
    data/player_2025.parquet / .csv   the tidy computed layer, version controlled
    edge.json            precomputed output the browser reads. The browser does
                         NO modeling — same pattern as ranks.json.

RUN
    python3 build_edge.py          (add --refresh to re-pull nflverse)
"""
import json, os, sys, re, urllib.request
import pandas as pd
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RAW  = os.path.join(HERE, "data", "raw")
OUT  = os.path.join(HERE, "data")
os.makedirs(RAW, exist_ok=True)

NFLVERSE = "https://github.com/nflverse/nflverse-data/releases/download"
SOURCES = {
    "stats_player_week_2025.parquet": f"{NFLVERSE}/stats_player/stats_player_week_2025.parquet",
    # 2024 is pulled ONLY to test whether the 6-pt result replicates. One season
    # is a small sample and the headline claim should not rest on one point
    # estimate from one year at one replacement rank.
    "stats_player_week_2024.parquet": f"{NFLVERSE}/stats_player/stats_player_week_2024.parquet",
    "snap_counts_2025.parquet":       f"{NFLVERSE}/snap_counts/snap_counts_2025.parquet",
    "roster_weekly_2025.parquet":     f"{NFLVERSE}/weekly_rosters/roster_weekly_2025.parquet",
    "play_by_play_2025.parquet":      f"{NFLVERSE}/pbp/play_by_play_2025.parquet",
}

# ---------------------------------------------------------------- league rules
# VERIFIED LIVE against GET /v1/league/1389326749023608832 scoring_settings.
# The only difference between LEAGUE and PUBLIC4 is pass_td: everything else is
# held identical so the measured gap is attributable to the 6-pt rule alone.
LEAGUE  = dict(pass_yd=.04, pass_td=6.0, pass_int=-2.0, pass_2pt=2.0,
               rush_yd=.10, rush_td=6.0, rush_2pt=2.0,
               rec=0.5, rec_yd=.10, rec_td=6.0, rec_2pt=2.0, fum_lost=-2.0)
PUBLIC4 = {**LEAGUE, "pass_td": 4.0}

# Roster shape drives replacement level. 12 teams, 8 starters, only 4 bench.
TEAMS, ROUNDS, BENCH = 12, 12, 4
STARTERS = dict(QB=1, RB=2, WR=2, TE=1, DEF=1)
FLEX = 1
# Half-PPR flex is RB/WR dominant; TE rarely flexes. Used only to set replacement.
FLEX_SPLIT = dict(RB=.50, WR=.42, TE=.08)


def fetch(refresh=False):
    for fn, url in SOURCES.items():
        p = os.path.join(RAW, fn)
        if os.path.exists(p) and os.path.getsize(p) > 0 and not refresh:
            print(f"  cached  {fn}")
            continue
        print(f"  fetch   {fn} ...", end="", flush=True)
        urllib.request.urlretrieve(url, p)
        print(f" {os.path.getsize(p)/1e6:.1f}MB")


def score(df, rules):
    """Fantasy points under an explicit rule dict. Vectorised, NaN-safe."""
    g = lambda c: pd.to_numeric(df.get(c, 0), errors="coerce").fillna(0)
    return (g("passing_yards")   * rules["pass_yd"]
          + g("passing_tds")     * rules["pass_td"]
          + g("passing_interceptions") * rules["pass_int"]
          + g("passing_2pt_conversions") * rules["pass_2pt"]
          + g("rushing_yards")   * rules["rush_yd"]
          + g("rushing_tds")     * rules["rush_td"]
          + g("rushing_2pt_conversions") * rules["rush_2pt"]
          + g("receptions")      * rules["rec"]
          + g("receiving_yards") * rules["rec_yd"]
          + g("receiving_tds")   * rules["rec_td"]
          + g("receiving_2pt_conversions") * rules["rec_2pt"]
          + g("fumbles_lost_total") * rules["fum_lost"])


SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")
def norm(s):
    """Mirrors index.html's norm() exactly so joins and the console agree."""
    s = str(s or "").lower()
    s = re.sub(r"[.'’-]", " ", s)
    s = SUFFIX.sub(" ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def main():
    refresh = "--refresh" in sys.argv
    print("nflverse 2025 ->")
    fetch(refresh)

    # ---------------------------------------------------- weekly player stats
    wk = pd.read_parquet(os.path.join(RAW, "stats_player_week_2025.parquet"))
    wk = wk[(wk.season_type == "REG")].copy()
    wk["pts_league"] = score(wk, LEAGUE)
    wk["pts_pub4"]   = score(wk, PUBLIC4)

    SKILL = ["QB", "RB", "WR", "TE"]
    wk = wk[wk.position.isin(SKILL)].copy()

    num = ["passing_yards","passing_tds","passing_interceptions","rushing_yards",
           "rushing_tds","carries","receptions","targets","receiving_yards",
           "receiving_tds","receiving_air_yards","pts_league","pts_pub4"]
    for c in num:
        wk[c] = pd.to_numeric(wk[c], errors="coerce").fillna(0)

    agg = wk.groupby(["player_id","player_display_name","position"], as_index=False).agg(
        games=("week","nunique"),
        **{c:(c,"sum") for c in num},
        target_share=("target_share","mean"),
        air_yards_share=("air_yards_share","mean"),
        wopr=("wopr","mean"),
    )
    # last team actually played for in 2025
    last = wk.sort_values("week").groupby("player_id").tail(1)[["player_id","team"]]
    agg = agg.merge(last.rename(columns={"team":"team_2025"}), on="player_id", how="left")

    # ---------------------------------------------------------- snap share
    ro = pd.read_parquet(os.path.join(RAW,"roster_weekly_2025.parquet"),
                         columns=["gsis_id","pfr_id","sleeper_id","week"])
    bridge = ro.dropna(subset=["gsis_id","pfr_id"]).sort_values("week") \
               .groupby("pfr_id", as_index=False).tail(1)[["gsis_id","pfr_id"]]
    sn = pd.read_parquet(os.path.join(RAW,"snap_counts_2025.parquet"))
    # Do NOT filter on snap_counts.position: it carries PFR codes, where running
    # backs appear as HB and fullbacks as FB. Filtering to QB/RB/WR/TE silently
    # dropped 226 rows across 17 players -- Chase Brown, a top-30 board player,
    # lost his entire snap share. Join on player id and let the stats table's
    # position govern instead.
    sn = sn[sn.game_type == "REG"]
    sn = sn.merge(bridge, left_on="pfr_player_id", right_on="pfr_id", how="left")
    snap = sn.dropna(subset=["gsis_id"]).groupby("gsis_id", as_index=False) \
             .agg(snap_pct=("offense_pct","mean"), snap_games=("offense_pct","size"))
    agg = agg.merge(snap, left_on="player_id", right_on="gsis_id", how="left").drop(columns=["gsis_id"])

    # ------------------------------------------------------- red zone (pbp)
    pbp = pd.read_parquet(os.path.join(RAW,"play_by_play_2025.parquet"),
        columns=["season_type","yardline_100","rush_attempt","pass_attempt",
                 "rusher_player_id","receiver_player_id","rush_touchdown",
                 "pass_touchdown","touchdown","play_type","posteam","two_point_attempt"])
    pbp = pbp[(pbp.season_type=="REG") & (pbp.two_point_attempt != 1)]
    rz  = pbp[pbp.yardline_100 <= 20]
    i10 = pbp[pbp.yardline_100 <= 10]

    def touches(frame, tag):
        r = frame[frame.rush_attempt==1].groupby("rusher_player_id").size().rename(f"{tag}_carries")
        t = frame[frame.pass_attempt==1].groupby("receiver_player_id").size().rename(f"{tag}_targets")
        return pd.concat([r,t], axis=1).fillna(0)
    rzt  = touches(rz,  "rz")
    i10t = touches(i10, "i10")
    rz_td = pd.concat([
        rz[(rz.rush_attempt==1)&(rz.rush_touchdown==1)].groupby("rusher_player_id").size(),
        rz[(rz.pass_attempt==1)&(rz.pass_touchdown==1)].groupby("receiver_player_id").size(),
    ], axis=1).fillna(0).sum(axis=1).rename("rz_tds")
    rzall = rzt.join(i10t, how="outer").join(rz_td, how="outer").fillna(0)
    rzall.index.name = "player_id"
    agg = agg.merge(rzall.reset_index(), on="player_id", how="left")

    # team red-zone opportunity share (how big a slice of your offense's RZ work)
    team_rz = rz[rz.play_type.isin(["run","pass"])].groupby("posteam").size().rename("team_rz_plays")
    agg = agg.merge(team_rz.reset_index().rename(columns={"posteam":"team_2025"}),
                    on="team_2025", how="left")
    for c in ["rz_carries","rz_targets","i10_carries","i10_targets","rz_tds",
              "snap_pct","target_share","air_yards_share","wopr","team_rz_plays"]:
        agg[c] = pd.to_numeric(agg[c], errors="coerce").fillna(0)
    agg["rz_touches"]  = agg.rz_carries + agg.rz_targets
    agg["i10_touches"] = agg.i10_carries + agg.i10_targets
    agg["rz_share"] = np.where(agg.team_rz_plays > 0, agg.rz_touches / agg.team_rz_plays, 0.0)

    # ------------------------------------------------ TD regression (xTD)
    # League-average TD conversion per opportunity, by field zone, fit on 2025.
    # A player far above his expected TDs got lucky; luck does not repeat, so we
    # re-score him at his expected TD count. This is the concrete implementation
    # of "don't let a lucky TD year masquerade as a projection".
    # Rates must be POSITION-SPECIFIC. A single league-wide rate per zone is
    # calibrated in aggregate but badly biased per position -- a QB sneak from the
    # 1 converts nothing like a WR carry, so pooling them inflated QB xTD by ~28%
    # and deflated RB xTD by ~11%. Attach each play's position from the stats
    # table and fit within position, falling back to the pooled rate where a
    # position/zone cell is too thin to estimate.
    POSMAP = dict(zip(wk.player_id, wk.position))
    pbp = pbp.copy()
    pbp["rush_pos"] = pbp.rusher_player_id.map(POSMAP)
    pbp["rec_pos"]  = pbp.receiver_player_id.map(POSMAP)

    def zone_rates(frame, kind, min_n=40):
        """P(TD | one opportunity), per position, with a pooled fallback."""
        if kind == "rush":
            f = frame[(frame.rush_attempt == 1) & frame.rush_pos.notna()]
            td, key = "rush_touchdown", "rush_pos"
        else:
            f = frame[(frame.pass_attempt == 1) & frame.rec_pos.notna()]
            td, key = "pass_touchdown", "rec_pos"
        pooled = (f[td].sum() / len(f)) if len(f) else 0.0
        out = {"*": pooled}
        for pos, g in f.groupby(key):
            out[pos] = (g[td].sum() / len(g)) if len(g) >= min_n else pooled
        return out

    inside10  = pbp[pbp.yardline_100 <= 10]
    ring1120  = pbp[(pbp.yardline_100 > 10) & (pbp.yardline_100 <= 20)]
    outside20 = pbp[pbp.yardline_100 > 20]
    RATES = {
        "i10_rush":  zone_rates(inside10,  "rush"),
        "i10_rec":   zone_rates(inside10,  "rec"),
        "rz_rush":   zone_rates(ring1120,  "rush"),
        "rz_rec":    zone_rates(ring1120,  "rec"),
        "out_rush":  zone_rates(outside20, "rush"),
        "out_rec":   zone_rates(outside20, "rec"),
    }
    for k, v in RATES.items():
        shown = "  ".join(f"{p}={v[p]:.3f}" for p in ("*", "QB", "RB", "WR", "TE") if p in v)
        print(f"  TD rate {k:9} {shown}")

    def rate_for(key):
        """Vectorised per-player rate lookup for RATES[key], by his position."""
        tbl = RATES[key]
        return agg.position.map(lambda p: tbl.get(p, tbl["*"])).astype(float)

    # split each player's opportunities into the same three zones
    agg["ring_carries"] = (agg.rz_carries - agg.i10_carries).clip(lower=0)
    agg["ring_targets"] = (agg.rz_targets - agg.i10_targets).clip(lower=0)
    agg["out_carries"]  = (agg.carries - agg.rz_carries).clip(lower=0)
    agg["out_targets"]  = (agg.targets - agg.rz_targets).clip(lower=0)
    agg["xtd"] = (agg.i10_carries  * rate_for("i10_rush")
                + agg.ring_carries * rate_for("rz_rush")
                + agg.out_carries  * rate_for("out_rush")
                + agg.i10_targets  * rate_for("i10_rec")
                + agg.ring_targets * rate_for("rz_rec")
                + agg.out_targets  * rate_for("out_rec"))
    agg["actual_td"] = agg.rushing_tds + agg.receiving_tds
    agg["td_oe"] = agg.actual_td - agg.xtd            # + = lucky, - = due positive regression

    # QB passing TD regression: pass TDs over expected, from team RZ pass volume
    qb_rz_att = rz[rz.pass_attempt==1].groupby("posteam").size().rename("team_rz_pass")
    agg = agg.merge(qb_rz_att.reset_index().rename(columns={"posteam":"team_2025"}),
                    on="team_2025", how="left")
    agg["team_rz_pass"] = agg.team_rz_pass.fillna(0)

    # ------------------------------------- opportunity-weighted expected points
    # Replace realised TDs with expected TDs. This is the whole "don't let a lucky
    # TD year masquerade as a projection" requirement, made concrete.
    agg["pts_league_pg"] = np.where(agg.games>0, agg.pts_league/agg.games, 0.0)
    agg["pts_pub4_pg"]   = np.where(agg.games>0, agg.pts_pub4/agg.games, 0.0)
    agg["pts_xtd"]       = agg.pts_league - (agg.actual_td - agg.xtd) * 6.0
    agg["pts_xtd_pg"]    = np.where(agg.games>0, agg.pts_xtd/agg.games, 0.0)
    agg["sixpt_gap"]     = agg.pts_league - agg.pts_pub4        # == 2 * passing_tds
    agg["sixpt_gap_pg"]  = np.where(agg.games>0, agg.sixpt_gap/agg.games, 0.0)

    # ============================================================
    # OPPORTUNITY-WEIGHTED PROJECTION BASIS
    # ============================================================
    # The requirement: weight opportunity over raw fantasy points, because
    # target share / snap share / red-zone role predict next season better than
    # last season's points do. Implementation, in two steps:
    #   1. pts_xtd_pg  -- last year's points per game with lucky/unlucky TDs
    #                     regressed out (see xTD above).
    #   2. role_pg     -- points per game IMPLIED BY ROLE ALONE. Fit within each
    #                     position by least squares on opportunity features only,
    #                     LEAVE-ONE-OUT, so a player's own scoring never enters his
    #                     own prediction at all. The R2 printed below is therefore
    #                     out-of-sample.
    # The blend leans on role (55/45), so a player whose production outran his
    # role gets pulled down and a player buried by his own offense gets pulled up.
    FEATURES = {
        "QB": ["snap_pct", "att_pg", "rush_att_pg", "rz_pass_pg"],
        "RB": ["snap_pct", "carries_pg", "targets_pg", "rz_touch_pg", "i10_touch_pg"],
        "WR": ["snap_pct", "targets_pg", "target_share", "air_yards_share", "rz_target_pg"],
        "TE": ["snap_pct", "targets_pg", "target_share", "air_yards_share", "rz_target_pg"],
    }
    g = agg.games.replace(0, np.nan)
    agg["att_pg"]       = (agg.passing_yards * 0 + wk.groupby("player_id").attempts.sum()
                           .reindex(agg.player_id).values) / g
    agg["rush_att_pg"]  = agg.carries / g
    agg["carries_pg"]   = agg.carries / g
    agg["targets_pg"]   = agg.targets / g
    agg["rz_touch_pg"]  = agg.rz_touches / g
    agg["i10_touch_pg"] = agg.i10_touches / g
    agg["rz_target_pg"] = agg.rz_targets / g
    agg["rz_pass_pg"]   = agg.team_rz_pass / 17.0
    for c in set(sum(FEATURES.values(), [])):
        agg[c] = pd.to_numeric(agg[c], errors="coerce").fillna(0)

    agg["role_pg"] = np.nan
    FIT_MIN_GAMES = 6
    for pos, feats in FEATURES.items():
        m = agg.position == pos
        fit = m & (agg.games >= FIT_MIN_GAMES)
        if fit.sum() < len(feats) + 3:
            agg.loc[m, "role_pg"] = agg.loc[m, "pts_xtd_pg"]
            continue
        X = np.column_stack([agg.loc[fit, f].values for f in feats] + [np.ones(fit.sum())])
        y = agg.loc[fit, "pts_xtd_pg"].values
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        Xall = np.column_stack([agg.loc[m, f].values for f in feats] + [np.ones(m.sum())])
        pred = Xall @ beta

        # LEAVE-ONE-OUT. A player in the fit would otherwise be predicted partly
        # by coefficients his own scoring helped set. The effect is small at these
        # sample sizes (measured: ~0.5% of the prediction for RB/WR/TE, ~1.7% for
        # QB where n is only ~43) but it costs nothing to remove entirely, and it
        # makes the reported R2 an out-of-sample number instead of an in-sample
        # one that would overstate how much this really explains.
        idx = np.flatnonzero(fit.values)
        pos_rows = np.flatnonzero(m.values)
        where = {r: i for i, r in enumerate(pos_rows)}
        loo = pred.copy()
        for i, row in enumerate(idx):
            keep = np.ones(len(idx), bool); keep[i] = False
            bi, *_ = np.linalg.lstsq(X[keep], y[keep], rcond=None)
            loo[where[row]] = X[i] @ bi
        agg.loc[m, "role_pg"] = loo

        yhat_loo = np.array([loo[where[r]] for r in idx])
        ss = max(((y - y.mean()) ** 2).sum(), 1e-9)
        r2_loo = 1 - ((y - yhat_loo) ** 2).sum() / ss
        r2_in  = 1 - ((y - X @ beta) ** 2).sum() / ss
        print(f"  role model {pos}: n={int(fit.sum())}  R2(leave-one-out)={r2_loo:.2f} "
              f"(in-sample {r2_in:.2f})")
    agg["role_pg"] = agg.role_pg.fillna(agg.pts_xtd_pg).clip(lower=0)

    W_ROLE = 0.55                      # opportunity weighted OVER raw production
    agg["proj_pg"] = W_ROLE * agg.role_pg + (1 - W_ROLE) * agg.pts_xtd_pg
    # a player who barely played has an unreliable rate; shrink him toward his
    # position's replacement level rather than trusting a 2-game sample
    agg["reliability"] = (agg.games / 12.0).clip(upper=1.0)

    # ============================================================
    # VALUE OVER REPLACEMENT — this league's real roster shape
    # ============================================================
    # 12 teams x 8 starters (QB/RB/RB/WR/WR/TE/FLEX/DEF). Replacement level is
    # set by how many of a position START league-wide, plus that position's share
    # of the 12 flex spots. Only 12 rounds and 4 bench, so the draftable pool is
    # 144 players, not the 180 a 15-round league drafts -- documented per position
    # below so the number is auditable rather than asserted.
    REPL_RANK = {}
    for pos in ["QB", "RB", "WR", "TE"]:
        base = STARTERS.get(pos, 0) * TEAMS
        flex = round(FLEX_SPLIT.get(pos, 0) * FLEX * TEAMS)
        REPL_RANK[pos] = int(base + flex) + 1
    print(f"  replacement ranks: {REPL_RANK}   (draftable pool {TEAMS*ROUNDS} players)")

    agg["vor_pg"] = np.nan
    repl_pts = {}
    for pos, rk in REPL_RANK.items():
        m = agg.position == pos
        pool = agg.loc[m & (agg.games >= 4)].sort_values("proj_pg", ascending=False)
        if len(pool) >= rk:
            base = float(pool.iloc[rk - 1].proj_pg)
            who  = pool.iloc[rk - 1].player_display_name
        else:
            base = float(pool.proj_pg.min()) if len(pool) else 0.0
            who  = "(pool short)"
        repl_pts[pos] = base
        agg.loc[m, "vor_pg"] = agg.loc[m, "proj_pg"] - base
        print(f"    {pos}{rk:>3} replacement = {base:5.2f} pts/g  ({who})")
    # shrink unreliable samples toward replacement (vor -> 0)
    agg["vor_pg"] = agg.vor_pg * agg.reliability
    agg["vor_season"] = agg.vor_pg * 17.0

    # ---- quantify the 6-point thesis honestly -------------------------------
    # The naive claim "6-pt TDs make QBs more valuable" is wrong on its own: the
    # rule lifts EVERY QB, replacement included. What actually changes is the
    # SPREAD between an elite QB and a replacement QB. Measure exactly that.
    def qb_spread(frame, rk, n_top=6):
        """Elite-QB advantage over replacement, at 4-pt vs 6-pt passing TDs.

        n_top=6 is the headline (a top-6 QB). n_top=1 answers the different and
        narrower question 'what does the single best QB gain', which moves around
        far more because it rides one player's passing-TD total."""
        q = frame[frame.games >= 8]
        if len(q) < rk:
            return None
        q4 = q.sort_values("pts_pub4_pg", ascending=False)
        q6 = q.sort_values("pts_league_pg", ascending=False)
        r4, r6 = float(q4.iloc[rk-1].pts_pub4_pg), float(q6.iloc[rk-1].pts_league_pg)
        t4 = float(q4.head(n_top).pts_pub4_pg.mean())
        t6 = float(q6.head(n_top).pts_league_pg.mean())
        return dict(repl4=r4, repl6=r6, top4=t4, top6=t6,
                    spread4=t4-r4, spread6=t6-r6, gain=(t6-r6)-(t4-r4))

    # Replicate on 2024. If the result only holds in one season at one
    # replacement rank, it is noise and must be reported as such.
    REPL_YEARS, QB1_YEARS = {}, {}
    for yr in (2024, 2025):
        f = os.path.join(RAW, f"stats_player_week_{yr}.parquet")
        if not os.path.exists(f):
            continue
        y = pd.read_parquet(f)
        y = y[(y.season_type == "REG") & (y.position == "QB")].copy()
        y["pl"] = score(y, LEAGUE); y["pp"] = score(y, PUBLIC4)
        ya = y.groupby("player_display_name", as_index=False).agg(
            games=("week", "nunique"), pl=("pl", "sum"), pp=("pp", "sum"))
        ya["pts_league_pg"] = ya.pl / ya.games
        ya["pts_pub4_pg"]   = ya.pp / ya.games
        REPL_YEARS[yr] = {rk: qb_spread(ya, rk) for rk in (11, 13, 15)}
        QB1_YEARS[yr]  = {rk: qb_spread(ya, rk, n_top=1) for rk in (11, 13, 15)}
    gains = [v["gain"] * 17 for yr in REPL_YEARS for v in REPL_YEARS[yr].values() if v]
    gains1 = [v["gain"] * 17 for yr in QB1_YEARS for v in QB1_YEARS[yr].values() if v]

    qb = agg[(agg.position == "QB") & (agg.games >= 8)].copy()
    qb_rk = REPL_RANK["QB"]
    qb4 = qb.sort_values("pts_pub4_pg", ascending=False)
    qb6 = qb.sort_values("pts_league_pg", ascending=False)
    if len(qb) >= qb_rk:
        r4 = float(qb4.iloc[qb_rk - 1].pts_pub4_pg)
        r6 = float(qb6.iloc[qb_rk - 1].pts_league_pg)
        top4 = qb4.head(6).pts_pub4_pg.mean()
        top6 = qb6.head(6).pts_league_pg.mean()
        THESIS = {
            "replacement_qb_4pt_pg": round(r4, 2),
            "replacement_qb_6pt_pg": round(r6, 2),
            "top6_qb_4pt_pg": round(float(top4), 2),
            "top6_qb_6pt_pg": round(float(top6), 2),
            "spread_4pt_pg": round(float(top4 - r4), 2),
            "spread_6pt_pg": round(float(top6 - r6), 2),
            "spread_gain_pg": round(float((top6 - r6) - (top4 - r4)), 2),
            "spread_gain_season": round(float(((top6 - r6) - (top4 - r4)) * 17), 1),
            "replacement_qb_name": str(qb6.iloc[qb_rk - 1].player_display_name),
            # the honest version: a RANGE across 2 seasons x 3 replacement ranks,
            # not one point estimate dressed up as the answer
            "gain_season_lo": round(min(gains), 1) if gains else None,
            "gain_season_hi": round(max(gains), 1) if gains else None,
            "gain_season_mid": round(float(np.median(gains)), 1) if gains else None,
            "replications": len(gains),
            # The single best QB is a DIFFERENT and much noisier question than a
            # top-6 QB: it rides one player's passing-TD total, so it swings hard
            # between seasons. Reported as its own range rather than folded in.
            "qb1_gain_lo": round(min(gains1), 1) if gains1 else None,
            "qb1_gain_hi": round(max(gains1), 1) if gains1 else None,
            "qb1_gain_mid": round(float(np.median(gains1)), 1) if gains1 else None,
        }
    else:
        THESIS = {}

    agg.to_parquet(os.path.join(OUT,"player_2025.parquet"), index=False)
    keep = ["player_id","player_display_name","position","team_2025","games","snap_pct",
            "proj_pg","role_pg","vor_pg","vor_season","reliability",
            "targets","target_share","air_yards_share","wopr","carries","rz_carries",
            "rz_targets","i10_touches","rz_share","actual_td","xtd","td_oe",
            "passing_tds","pts_league","pts_pub4","sixpt_gap","pts_xtd",
            "pts_league_pg","pts_xtd_pg","sixpt_gap_pg"]
    agg[keep].sort_values("pts_league", ascending=False) \
       .to_csv(os.path.join(OUT,"player_2025.csv"), index=False, float_format="%.3f")
    print(f"  data/player_2025.parquet + .csv   {len(agg)} players")
    return agg, THESIS, REPL_RANK, repl_pts





# ============================================================================
# EDGE — my rank vs the board's ADP rank. The delta is the whole point.
# ============================================================================
ALIAS = {          # board spelling -> 2025 nflverse spelling, where they differ
    "james cook":"james cook", "kenneth walker":"kenneth walker",
    "marvin harrison":"marvin harrison", "brian thomas":"brian thomas",
    "michael pittman":"michael pittman", "travis etienne":"travis etienne",
    "chris godwin":"chris godwin", "harold fannin":"harold fannin",
    "kyle pitts":"kyle pitts", "deebo samuel":"deebo samuel",
    "tank bigsby":"tank bigsby", "hollywood brown":"marquise brown",
    "cam ward":"cameron ward", "chig okonkwo":"chigoziem okonkwo",
    "gabe davis":"gabriel davis", "josh palmer":"joshua palmer",
}

def build_edge_table(agg, thesis, repl_rank, repl_pts, board_path="ranks.json"):
    board = json.load(open(os.path.join(HERE, board_path)))["ranks"]
    agg = agg.copy()
    agg["key"] = agg.player_display_name.map(norm)
    # one row per name: keep the highest-volume season row if duplicated
    agg = agg.sort_values("proj_pg", ascending=False).drop_duplicates("key")
    idx = agg.set_index("key")

    rows, unmatched = [], []
    for b in board:
        if b["pos"] == "DST":
            continue
        k = norm(b["name"])
        k = norm(ALIAS.get(k, k)) if ALIAS.get(k) else k
        if k not in idx.index:
            unmatched.append(b)
            continue
        r = idx.loc[k]
        moved = bool(str(r.team_2025).upper() != str(b["team"]).upper())
        games = int(r.games)
        # Confidence is about whether 2025 says anything about 2026 — not about
        # how good the player is. A 2025 backup who is a 2026 starter has data
        # that describes a role he no longer has; that is not evidence he is bad.
        snap = float(r.snap_pct)
        if games >= 14:   conf = "high"
        elif games >= 9:  conf = "med"
        elif games >= 5:  conf = "low"
        else:             conf = "vlow"
        role_risk = bool(snap < 0.55 or games < 9)
        if moved and conf in ("high", "med"):
            conf = "med" if conf == "high" else "low"
        if role_risk:
            conf = "vlow"
        rows.append(dict(
            name=b["name"], pos=b["pos"], team=b["team"], bye=b["bye"],
            board_rank=b["rank"], adp=b["adp"], tier=b["tier"],
            team_2025=str(r.team_2025), moved=moved, games=games,
            snap_pct=round(float(r.snap_pct), 3),
            target_share=round(float(r.target_share), 3),
            rz_touches=int(r.rz_touches), i10_touches=int(r.i10_touches),
            actual_td=int(r.actual_td), xtd=round(float(r.xtd), 1),
            td_oe=round(float(r.td_oe), 1),
            passing_tds=int(r.passing_tds),
            sixpt_gap=round(float(r.sixpt_gap), 1),
            pts_league_pg=round(float(r.pts_league_pg), 2),
            proj_pg=round(float(r.proj_pg), 2),
            vor_pg=round(float(r.vor_pg), 2),
            vor_season=round(float(r.vor_season), 1),
            confidence=conf, role_risk=role_risk,
        ))

    df = pd.DataFrame(rows)
    # my rank = ordering of the SAME board players by value over replacement
    df = df.sort_values("vor_season", ascending=False).reset_index(drop=True)
    df["edge_rank"] = df.index + 1
    df["edge"] = df.board_rank - df.edge_rank      # + = I like him more than ADP does
    df = df.sort_values("board_rank").reset_index(drop=True)
    # An edge is only CLAIMED where 2025 describes a role the player still has.
    # Everyone else keeps their numbers but is explicitly marked unreliable, so
    # the console can show the delta without asserting it means anything.
    df["edge_trusted"] = (~df.role_risk) & df.confidence.isin(["high", "med"])

    def reason(r):
        """One line a human can evaluate at the table. Facts, not scores."""
        bits = []
        if r.pos == "QB" and r.passing_tds:
            bits.append(f"{r.passing_tds} pass TD = +{r.sixpt_gap:.0f} pts in 6-pt scoring")
        if r.td_oe <= -2.0:
            bits.append(f"{r.actual_td} TD on {r.xtd:.1f} expected — positive regression")
        elif r.td_oe >= 2.5:
            bits.append(f"{r.actual_td} TD on only {r.xtd:.1f} expected — TD luck won't repeat")
        if r.pos in ("WR", "TE") and r.target_share >= 0.24:
            bits.append(f"{r.target_share*100:.0f}% target share")
        if r.pos == "RB" and r.rz_touches >= 40:
            bits.append(f"{int(r.rz_touches)} red-zone touches")
        if r.i10_touches >= 18:
            bits.append(f"{int(r.i10_touches)} inside-the-10 touches")
        if r.snap_pct >= 0.80 and r.pos != "QB":
            bits.append(f"{r.snap_pct*100:.0f}% snap share")
        if r.moved:
            bits.append(f"changed teams ({r.team_2025}->{r.team})")
        if r.games <= 10:
            bits.append(f"only {r.games} games in 2025")
        if r.role_risk:
            # role_risk is an OR of two independent tests; say which one fired,
            # so a 17-game rotational player is not reported as "only 17 games".
            if r.games < 9 and r.snap_pct < 0.55:
                what = f"only {r.games} games and {r.snap_pct*100:.0f}% of snaps"
            elif r.games < 9:
                what = f"only {r.games} games"
            else:
                what = f"just {r.snap_pct*100:.0f}% of snaps over {r.games} games"
            bits = [f"{what} in 2025 — that describes a role he no longer has, "
                    f"not his 2026 value"]
        if not bits:
            bits.append(f"{r.proj_pg:.1f} proj pts/g vs {r.pos} replacement")
        return "; ".join(bits[:3])

    df["why"] = df.apply(reason, axis=1)
    return df, unmatched


def main_with_edge():
    agg, thesis, repl_rank, repl_pts = main()
    df, unmatched = build_edge_table(agg, thesis, repl_rank, repl_pts)
    df.to_csv(os.path.join(OUT, "edge_2025.csv"), index=False, float_format="%.3f")

    payload = {
        "generated_from": "nflverse 2025 regular season",
        "scoring": {"half_ppr": 0.5, "pass_td": 6, "pass_int": -2,
                    "note": "verified live against Sleeper league scoring_settings"},
        "replacement": {"ranks": repl_rank,
                        "pts_per_game": {k: round(v, 2) for k, v in repl_pts.items()}},
        "thesis": thesis,
        # Lean payload: the browser renders these fields and nothing else.
        # Full per-player detail (snaps, target share, xTD, red-zone splits) stays
        # in data/edge_2025.csv — the browser never needs it and never models.
        "players": [
            {"name": r["name"], "pos": r["pos"], "rank": int(r["board_rank"]),
             "erank": int(r["edge_rank"]), "edge": int(r["edge"]),
             "vor": round(float(r["vor_season"]), 1), "conf": r["confidence"],
             "ok": bool(r["edge_trusted"]), "why": r["why"],
             # season points a QB gains purely from the 6-pt rule (= 2 x pass TD).
             # Kept per-player because pocket passers gain far more than rushers.
             "sixpt": round(float(r["sixpt_gap"]), 0) if r["pos"] == "QB" else 0,
             "ptd": int(r["passing_tds"]) if r["pos"] == "QB" else 0}
            for r in json.loads(df.to_json(orient="records"))
        ],
        "unmatched": [{"name": u["name"], "pos": u["pos"], "rank": u["rank"]} for u in unmatched],
    }
    with open(os.path.join(HERE, "edge.json"), "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"  edge.json  {len(df)} matched, {len(unmatched)} unmatched (no 2025 NFL data)")
    return df, unmatched, thesis


if __name__ == "__main__":
    # main() alone writes only the data/ layer; edge.json comes from
    # main_with_edge(). Running this file directly must produce both.
    main_with_edge()
