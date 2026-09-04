#!/usr/bin/env python3
"""
build_panel.py — raw nflverse -> one tidy player-season panel.

Output: data/player_seasons.parquet, one row per (gsis_id, season), carrying
production, opportunity, efficiency, team context, age, draft capital and
availability. Everything downstream (features, model, backtest) reads this and
never touches data/raw/ again.

SCHEMA NOTES (normalisation applied here, per the mission's "write down what
changed" requirement):
  stats_player / snap_counts / pbp   identical 150 / 16 / 372 columns across all
                                     14 seasons. No normalisation needed.
  injuries                           `season_type` absent 2012-2015; filled REG.
  depth_charts                       two eras. 2012-2024 uses depth_team /
                                     depth_position / position; 2025 switched to
                                     pos_rank / pos_grp / pos_abb. Both carry
                                     gsis_id, so both are mapped onto
                                     (gsis_id, season, depth_rank, pos_grp).
  participation                      2016+ only. offense_players (gsis ids) is
                                     present every year; the name/number columns
                                     that appear in 2023 are not used.
  advstats (yards after contact)     2018+ only.
Feature blocks that start late are left NULL before their first season and the
model is told which rows are missing -- never zero-filled, which would read as
"zero routes" rather than "unknown".

    python3 build_panel.py            # build (skips seasons already done)
    python3 build_panel.py --force    # rebuild every season
"""
import argparse, os, sys, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
import league

HERE = os.path.dirname(os.path.abspath(__file__))
RAW  = os.path.join(HERE, "data", "raw")
OUT  = os.path.join(HERE, "data")
FIRST, LAST = 2012, 2025
PART_FIRST, ADV_FIRST = 2016, 2018


def rp(name):
    return pd.read_parquet(os.path.join(RAW, name))


# ---------------------------------------------------------------- weekly stats
def weekly(season):
    w = rp(f"stats_player_week_{season}.parquet")
    w = w[w.season_type == "REG"].copy()
    w = w[w.position.isin(league.SKILL)].copy()
    w["pts"]  = league.score_frame(w, league.LEAGUE)
    w["pts4"] = league.score_frame(w, league.PUBLIC4)
    return w


SUM_COLS = ["completions", "attempts", "passing_yards", "passing_tds",
            "passing_interceptions", "passing_air_yards", "carries",
            "rushing_yards", "rushing_tds", "receptions", "targets",
            "receiving_yards", "receiving_tds", "receiving_air_yards",
            "receiving_yards_after_catch", "fumbles_lost_total",
            "passing_first_downs", "rushing_first_downs", "receiving_first_downs",
            "pts", "pts4"]
MEAN_COLS = ["target_share", "air_yards_share", "wopr", "racr",
             "receiving_epa", "rushing_epa", "passing_epa"]


def agg_weekly(w):
    for c in SUM_COLS:
        if c not in w:
            w[c] = 0
        w[c] = pd.to_numeric(w[c], errors="coerce").fillna(0)
    g = w.groupby(["player_id", "player_display_name", "position"], as_index=False)
    a = g.agg(games=("week", "nunique"),
              **{c: (c, "sum") for c in SUM_COLS},
              **{c: (c, "mean") for c in MEAN_COLS if c in w})
    last = w.sort_values("week").groupby("player_id").tail(1)[["player_id", "team"]]
    a = a.merge(last.rename(columns={"team": "team"}), on="player_id", how="left")
    n_teams = w.groupby("player_id").team.nunique().rename("teams_played")
    a = a.merge(n_teams.reset_index(), on="player_id", how="left")
    return a


# ------------------------------------------------------------------ snap share
_PFR_BRIDGE = None


def pfr_bridge():
    """pfr_id -> gsis_id, from the static players file (89.7% complete) rather
    than roster_weekly, whose pfr_id is only 29% filled in 2012 and 75% in 2025.
    Cached: it does not vary by season."""
    global _PFR_BRIDGE
    if _PFR_BRIDGE is None:
        pl = rp("players.parquet")
        b = pl.dropna(subset=["gsis_id", "pfr_id"])[["gsis_id", "pfr_id", "display_name"]]
        _PFR_BRIDGE = b.drop_duplicates("pfr_id")
    return _PFR_BRIDGE


def snaps(season, names=None):
    """Do NOT filter on snap_counts.position: PFR codes RBs as HB and fullbacks
    as FB, which silently drops real players. Join on id, falling back to a
    normalised name match for the ~10% of players with no pfr_id on file, and
    let the stats table's position govern.

    snap_counts_2012 contains no REG rows at all, so 2012 has no snap share and
    is left NULL rather than zero-filled."""
    sn = rp(f"snap_counts_{season}.parquet")
    sn = sn[sn.game_type == "REG"]
    if sn.empty:
        return pd.DataFrame(columns=["player_id", "snap_pct", "snap_games", "snaps_total"])
    b = pfr_bridge()
    sn = sn.merge(b[["gsis_id", "pfr_id"]], left_on="pfr_player_id",
                  right_on="pfr_id", how="left")
    if names is not None:                      # name fallback for the remainder
        miss = sn.gsis_id.isna()
        if miss.any():
            key = sn.loc[miss, "player"].map(league.norm)
            sn.loc[miss, "gsis_id"] = key.map(names).values
    sn = sn.dropna(subset=["gsis_id"])
    return sn.groupby("gsis_id", as_index=False).agg(
        snap_pct=("offense_pct", "mean"),
        snap_games=("offense_pct", "size"),
        snaps_total=("offense_snaps", "sum")).rename(columns={"gsis_id": "player_id"})


# ------------------------------------------------------- pbp: zones + team ctx
PBP_COLS = ["season", "week", "season_type", "posteam", "play_type", "yardline_100",
            "rush_attempt", "pass_attempt", "complete_pass", "rusher_player_id",
            "receiver_player_id", "passer_player_id", "rush_touchdown",
            "pass_touchdown", "air_yards", "two_point_attempt", "game_id",
            "play_id", "epa", "down", "qtr", "half_seconds_remaining"]


def pbp_features(season):
    p = rp(f"play_by_play_{season}.parquet")[PBP_COLS]
    p = p[(p.season_type == "REG") & (p.two_point_attempt != 1)].copy()

    def zone(lo, hi):
        return p[(p.yardline_100 > lo) & (p.yardline_100 <= hi)]

    def touches(fr, tag):
        """Opportunities AND touchdowns per zone. The TD counts are what let the
        expected-TD model use directly measured conversion rates per zone and
        position instead of solving for them, which was numerically fragile."""
        r  = fr[fr.rush_attempt == 1].groupby("rusher_player_id").size().rename(f"{tag}_car")
        t  = fr[fr.pass_attempt == 1].groupby("receiver_player_id").size().rename(f"{tag}_tgt")
        rd = (fr[(fr.rush_attempt == 1) & (fr.rush_touchdown == 1)]
              .groupby("rusher_player_id").size().rename(f"{tag}_car_td"))
        td = (fr[(fr.pass_attempt == 1) & (fr.pass_touchdown == 1)]
              .groupby("receiver_player_id").size().rename(f"{tag}_tgt_td"))
        return pd.concat([r, t, rd, td], axis=1).fillna(0)

    # three disjoint bands so opportunities are never double counted
    i5   = touches(zone(0, 5),    "i5")
    ring = touches(zone(5, 10),   "ring")     # 6-10 yard line
    mid  = touches(zone(10, 20),  "mid")      # 11-20
    out  = touches(zone(20, 100), "out")
    opp = (i5.join(ring, how="outer").join(mid, how="outer")
             .join(out, how="outer").fillna(0))
    # convenience roll-ups used everywhere downstream
    opp["i10_car"] = opp.i5_car + opp.ring_car
    opp["i10_tgt"] = opp.i5_tgt + opp.ring_tgt
    opp["rz_car"]  = opp.i10_car + opp.mid_car
    opp["rz_tgt"]  = opp.i10_tgt + opp.mid_tgt
    opp.index.name = "player_id"
    opp = opp.reset_index()

    # air yards / aDOT on targets
    tg = p[(p.pass_attempt == 1) & p.receiver_player_id.notna()]
    adot = tg.groupby("receiver_player_id").agg(
        tgt_pbp=("air_yards", "size"), air_yards=("air_yards", "sum"),
        adot=("air_yards", "mean")).reset_index().rename(
        columns={"receiver_player_id": "player_id"})
    opp = opp.merge(adot, on="player_id", how="outer").fillna(0)

    # team context: pace and pass rate, from plays not from box scores
    off = p[p.play_type.isin(["run", "pass"])]
    gp = off.groupby("posteam").game_id.nunique().rename("tm_games")
    tm = off.groupby("posteam").agg(tm_plays=("play_id", "size"),
                                    tm_pass=("pass_attempt", "sum"),
                                    tm_epa=("epa", "mean")).join(gp)
    tm["tm_plays_pg"] = tm.tm_plays / tm.tm_games
    tm["tm_pass_rate"] = tm.tm_pass / tm.tm_plays
    rzp = p[p.yardline_100 <= 20].groupby("posteam").size().rename("tm_rz_plays")
    tm = tm.join(rzp).fillna({"tm_rz_plays": 0})
    tm["tm_rz_pg"] = tm.tm_rz_plays / tm.tm_games
    tm = tm.reset_index().rename(columns={"posteam": "team"})
    return opp, tm[["team", "tm_plays_pg", "tm_pass_rate", "tm_epa", "tm_rz_pg"]]


# ------------------------------------------------- routes run (participation)
def routes(season):
    """Pass plays with the player on the field. A proxy for routes run -- it
    includes snaps where an RB or TE stayed in to block, so it overstates routes
    for those two positions. Used as a denominator for YPRR with that caveat."""
    if season < PART_FIRST:
        return None
    pa = rp(f"pbp_participation_{season}.parquet")[
        ["nflverse_game_id", "play_id", "offense_players"]]
    p = rp(f"play_by_play_{season}.parquet")[
        ["game_id", "play_id", "season_type", "pass_attempt"]]
    p = p[(p.season_type == "REG") & (p.pass_attempt == 1)]
    m = pa.merge(p, left_on=["nflverse_game_id", "play_id"],
                 right_on=["game_id", "play_id"], how="inner")
    ids = m.offense_players.dropna().str.split(";")
    flat = pd.Series([i for sub in ids for i in sub if i])
    r = flat.value_counts().rename("routes").reset_index()
    r.columns = ["player_id", "routes"]
    return r


# ------------------------------------------------------------- yards after contact
def advstats(season):
    if season < ADV_FIRST:
        return None
    try:
        rush = rp(f"advstats_week_rush_{season}.parquet")
        rec  = rp(f"advstats_week_rec_{season}.parquet")
    except Exception:
        return None
    ro = rp(f"roster_weekly_{season}.parquet")[["gsis_id", "pfr_id", "week"]]
    br = (ro.dropna(subset=["gsis_id", "pfr_id"]).sort_values("week")
            .groupby("pfr_id", as_index=False).tail(1)[["gsis_id", "pfr_id"]])
    b = pfr_bridge()[["gsis_id", "pfr_id"]]
    WANT = {"rushing_yards_after_contact": "ruy_ac",
            "rushing_yards_before_contact": "ruy_bc",
            "rushing_broken_tackles": "brk_tkl_ru",
            "receiving_broken_tackles": "brk_tkl_re",
            "receiving_drop": "drops"}
    out = []
    for df in (rush, rec):
        keep = [c for c in WANT if c in df.columns]
        if not keep or "pfr_player_id" not in df.columns:
            continue
        d = df.merge(b, left_on="pfr_player_id", right_on="pfr_id", how="left")
        d = d.dropna(subset=["gsis_id"])
        out.append(d.groupby("gsis_id", as_index=False)[keep].sum()
                    .rename(columns=WANT))
    if not out:
        return None
    a = out[0]
    for extra in out[1:]:
        shared = [c for c in extra.columns if c != "gsis_id" and c in a.columns]
        extra = extra.drop(columns=shared)
        a = a.merge(extra, on="gsis_id", how="outer")
    return a.rename(columns={"gsis_id": "player_id"})


# ------------------------------------------------------------------- injuries
def injuries(season):
    inj = rp(f"injuries_{season}.parquet")
    if "season_type" in inj.columns:          # absent 2012-2015
        inj = inj[inj.season_type == "REG"]
    idc = "gsis_id" if "gsis_id" in inj.columns else "player_id"
    if idc not in inj.columns:
        return None
    st = inj.get("report_status", inj.get("game_status"))
    if st is None:
        return None
    inj = inj.assign(_st=st.astype(str).str.lower())
    return inj.groupby(idc, as_index=False).agg(
        inj_reports=("_st", "size"),
        inj_out=("_st", lambda s: (s == "out").sum()),
        inj_dnp=("_st", lambda s: s.str.contains("doubt").sum()),
    ).rename(columns={idc: "player_id"})


# ------------------------------------------------------------------ depth chart
def depth(season):
    d = rp(f"depth_charts_{season}.parquet")
    if "pos_rank" in d.columns:                       # 2025+ schema
        d = d.rename(columns={"gsis_id": "player_id", "pos_rank": "rank_raw",
                              "pos_grp": "pos_grp"})
    else:                                             # 2012-2024 schema
        d = d.rename(columns={"gsis_id": "player_id", "depth_team": "rank_raw",
                              "position": "pos_grp"})
    if "player_id" not in d.columns or "rank_raw" not in d.columns:
        return None
    d["rank_raw"] = pd.to_numeric(d.rank_raw, errors="coerce")
    d = d.dropna(subset=["player_id", "rank_raw"])
    return d.groupby("player_id", as_index=False).agg(depth_rank=("rank_raw", "min"))


# --------------------------------------------------------------------- build
def build_season(season):
    w = weekly(season)
    a = agg_weekly(w).rename(columns={"player_id": "player_id"})
    a["season"] = season
    a["sched_games"] = league.season_games(season)

    names = dict(zip(a.player_display_name.map(league.norm), a.player_id))
    a = a.merge(snaps(season, names), on="player_id", how="left")
    opp, tm = pbp_features(season)
    a = a.merge(opp, on="player_id", how="left")
    a = a.merge(tm, on="team", how="left")

    r = routes(season)
    a = a.merge(r, on="player_id", how="left") if r is not None else a.assign(routes=np.nan)
    adv = advstats(season)
    if adv is not None:
        a = a.merge(adv, on="player_id", how="left")
    else:
        for c in ("ruy_ac", "ruy_bc", "brk_tkl_ru", "brk_tkl_re", "drops"):
            a[c] = np.nan
    ij = injuries(season)
    a = a.merge(ij, on="player_id", how="left") if ij is not None else a.assign(
        inj_reports=np.nan, inj_out=np.nan, inj_dnp=np.nan)
    dp = depth(season)
    a = a.merge(dp, on="player_id", how="left") if dp is not None else a.assign(depth_rank=np.nan)
    return a


def finalize(panel):
    """Per-game rates, age, draft capital, availability. Rates are the model's
    unit: season totals conflate how good a player is with how often he played."""
    players = rp("players.parquet")
    idc = "gsis_id" if "gsis_id" in players.columns else "player_id"
    keep = [c for c in [idc, "birth_date", "draft_year", "draft_round",
                        "draft_pick", "rookie_year", "entry_year"]
            if c in players.columns]
    pl = players[keep].rename(columns={idc: "player_id"}).drop_duplicates("player_id")
    panel = panel.merge(pl, on="player_id", how="left")

    dp = rp("draft_picks.parquet")
    if "gsis_id" in dp.columns:
        d = dp[["gsis_id", "round", "pick", "season"]].rename(
            columns={"gsis_id": "player_id", "round": "dr_round",
                     "pick": "dr_pick", "season": "dr_year"}).drop_duplicates("player_id")
        panel = panel.merge(d, on="player_id", how="left")
    else:
        panel["dr_round"] = panel["dr_pick"] = panel["dr_year"] = np.nan

    bd = pd.to_datetime(panel.get("birth_date"), errors="coerce")
    panel["age"] = panel.season - bd.dt.year + (bd.dt.month > 8).astype(float) * -1
    # Experience: prefer the explicit rookie/entry year; fall back to draft year;
    # last resort, the first season we observe him in the panel. players.parquet
    # does not always carry rookie_year, and a 100%-null feature is worse than a
    # noisy one because it silently drops out of the model.
    entry = None
    for c in ("rookie_year", "entry_year", "draft_year"):
        col = panel.get(c)
        if col is not None and pd.to_numeric(col, errors="coerce").notna().any():
            entry = pd.to_numeric(col, errors="coerce") if entry is None else \
                    entry.fillna(pd.to_numeric(col, errors="coerce"))
    first_seen = panel.groupby("player_id").season.transform("min")
    entry = first_seen if entry is None else entry.fillna(first_seen)
    panel["exp"] = panel.season - entry
    panel["draft_round"] = panel.dr_round.fillna(panel.get("draft_round"))
    panel["draft_pick"]  = panel.dr_pick.fillna(panel.get("draft_pick"))
    panel["undrafted"] = panel.draft_pick.isna().astype(int)

    g = panel.games.replace(0, np.nan)
    for c in ["pts", "pts4", "carries", "targets", "receptions", "receiving_yards",
              "rushing_yards", "passing_yards", "attempts", "rz_car", "rz_tgt",
              "i10_car", "i10_tgt", "i5_car", "i5_tgt", "air_yards", "routes"]:
        if c in panel:
            panel[f"{c}_pg"] = panel[c] / g
    panel["rz_touch_pg"]  = (panel.rz_car.fillna(0)  + panel.rz_tgt.fillna(0))  / g
    panel["i10_touch_pg"] = (panel.i10_car.fillna(0) + panel.i10_tgt.fillna(0)) / g
    panel["i5_touch_pg"]  = (panel.i5_car.fillna(0)  + panel.i5_tgt.fillna(0))  / g
    panel["touch_pg"]     = (panel.carries.fillna(0) + panel.targets.fillna(0)) / g

    panel["ypc"]        = panel.rushing_yards / panel.carries.replace(0, np.nan)
    panel["ypr"]        = panel.receiving_yards / panel.receptions.replace(0, np.nan)
    panel["catch_rate"] = panel.receptions / panel.targets.replace(0, np.nan)
    panel["yprr"]       = panel.receiving_yards / panel.routes.replace(0, np.nan)
    panel["td_total"]   = panel.rushing_tds.fillna(0) + panel.receiving_tds.fillna(0)
    panel["td_pg"]      = panel.td_total / g
    panel["yac_per_rec"] = panel.receiving_yards_after_catch / panel.receptions.replace(0, np.nan)
    panel["yac_per_carry"] = panel.ruy_ac / panel.carries.replace(0, np.nan)
    panel["games_missed"] = (panel.sched_games - panel.games).clip(lower=0)
    # A player traded mid-season can appear in MORE game-weeks than one team's
    # schedule, because his old and new teams bye in different weeks: Rashid
    # Shaheed played 18 in 2025, Emmanuel Sanders 17 in 2019. That is real, not a
    # data error, but availability is a rate and cannot exceed 1.
    panel["avail"] = (panel.games / panel.sched_games).clip(upper=1.0)
    panel["traded_midseason"] = (panel.teams_played.fillna(1) > 1).astype(int)
    panel["sixpt_gap"] = panel.pts - panel.pts4
    return panel


def main(force=False):
    dest = os.path.join(OUT, "player_seasons.parquet")
    frames = []
    for y in range(FIRST, LAST + 1):
        print(f"  {y} ...", end="", flush=True)
        f = build_season(y)
        print(f" {len(f):>5} players")
        frames.append(f)
    panel = finalize(pd.concat(frames, ignore_index=True))
    panel = panel.sort_values(["season", "pts"], ascending=[True, False])
    panel.to_parquet(dest, index=False)
    print(f"\ndata/player_seasons.parquet  {len(panel)} player-seasons, "
          f"{panel.season.min()}-{panel.season.max()}, {panel.shape[1]} columns")
    cov = panel.groupby("season").agg(n=("player_id", "size"),
                                      snap=("snap_pct", lambda s: s.notna().mean()),
                                      routes=("routes", lambda s: s.notna().mean()),
                                      yac=("ruy_ac", lambda s: s.notna().mean()),
                                      age=("age", lambda s: s.notna().mean()))
    print("\ncoverage by season (fraction non-null):")
    print(cov.round(2).to_string())
    return panel


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    main(force=ap.parse_args().force)
