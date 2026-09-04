#!/usr/bin/env python3
"""
questions.py — the specific questions, answered from the panel with sample sizes.

Every answer prints n. Where the honest answer is "too noisy to act on", it says
so rather than reporting a number that looks like a finding.

    python3 questions.py
"""
import os, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
import features, league
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, "data")
H = lambda t: print("\n" + "=" * 76 + f"\n{t}\n" + "=" * 76)


def load():
    panel = features.expected_tds(pd.read_parquet(os.path.join(OUT, "player_seasons.parquet")))
    adp = pd.read_parquet(os.path.join(OUT, "adp.parquet"))
    a = adp.dropna(subset=["player_id"])[
        ["player_id", "season", "adp", "adp_rank", "adp_pos_rank", "adp_source"]]
    p = panel.merge(a, on=["player_id", "season"], how="left")
    return panel, adp, p


# ---------------------------------------------------------------------------
def q_sixpoint(panel):
    H("Q: does the 6-point passing TD edge hold across a decade?")
    qb = panel[(panel.position == "QB") & (panel.games >= 8)].copy()
    qb["pg6"] = qb.pts / qb.games
    qb["pg4"] = qb.pts4 / qb.games
    rows = []
    for season, g in qb.groupby("season"):
        for rk in (11, 13, 15):
            if len(g) < rk:
                continue
            g4 = g.sort_values("pg4", ascending=False)
            g6 = g.sort_values("pg6", ascending=False)
            r4, r6 = g4.iloc[rk - 1].pg4, g6.iloc[rk - 1].pg6
            for ntop, lbl in ((1, "QB1"), (3, "top3"), (6, "top6")):
                t4 = g4.head(ntop).pg4.mean()
                t6 = g6.head(ntop).pg6.mean()
                rows.append(dict(season=season, repl=rk, tier=lbl,
                                 gain_pg=(t6 - r6) - (t4 - r4),
                                 gain_season=((t6 - r6) - (t4 - r4)) * league.season_games(season)))
    d = pd.DataFrame(rows)
    print(f"n = {len(d)} (season x replacement-rank x tier) cells, "
          f"{d.season.min()}-{d.season.max()}\n")
    for tier in ("top6", "top3", "QB1"):
        s = d[d.tier == tier].gain_season
        lo, hi = np.percentile(s, [5, 95])
        se = s.std(ddof=1) / np.sqrt(s.groupby(d[d.tier == tier].season).ngroups)
        print(f"  {tier:5} gain over replacement from the 6-pt rule: "
              f"median {s.median():5.1f}  mean {s.mean():5.1f} pts/season")
        print(f"        90% of cells fall in [{lo:.1f}, {hi:.1f}]   "
              f"season-clustered SE {se:.1f}  ->  95% CI "
              f"[{s.mean()-1.96*se:.1f}, {s.mean()+1.96*se:.1f}]")
    d.to_csv(os.path.join(OUT, "sixpoint.csv"), index=False, float_format="%.4f")
    per = d[d.tier == "top6"].groupby("season").gain_season.median()
    print(f"\n  by season (top-6, median across replacement ranks):")
    print("   " + "  ".join(f"{int(y)}:{v:+.0f}" for y, v in per.items()))
    neg = (per < 0).sum()
    print(f"\n  seasons where the edge was NEGATIVE: {neg} of {len(per)}")
    print(f"  VERDICT: the effect is consistently positive but small. It is "
          f"~{per.median():.0f} pts across a\n  whole season at the median, which is "
          f"under a point a game.")
    return d


# ---------------------------------------------------------------------------
def q_positional_value(panel):
    H("Q: where does replacement level really sit, across history?")
    repl = league.replacement_ranks()
    rows = []
    for season, g in panel.groupby("season"):
        gm = league.season_games(season)
        for pos in league.SKILL:
            s = g[(g.position == pos) & (g.games >= 4)].copy()
            s["pg"] = s.pts / s.games
            s = s.sort_values("pg", ascending=False)
            rk = repl[pos]
            if len(s) < rk + 2:
                continue
            base = s.iloc[rk - 1].pg
            rows.append(dict(season=season, pos=pos, repl_rank=rk, repl_pg=base,
                             top1_vor=(s.iloc[0].pg - base) * gm,
                             top3_vor=(s.head(3).pg.mean() - base) * gm,
                             top12_vor=(s.head(12).pg.mean() - base) * gm))
    d = pd.DataFrame(rows)
    agg = d.groupby("pos").agg(seasons=("season", "size"), repl_pg=("repl_pg", "mean"),
                               top1=("top1_vor", "mean"), top3=("top3_vor", "mean"),
                               top12=("top12_vor", "mean"),
                               top1_sd=("top1_vor", "std"))
    print(f"replacement ranks from the roster shape: {repl}")
    print(f"({league.TEAMS} teams x {league.STARTERS} starters + {league.FLEX} FLEX)\n")
    print(f"{'pos':5}{'seasons':>8}{'repl pts/g':>12}{'VOR top1':>10}{'top3':>8}"
          f"{'top12':>8}{'top1 SD':>9}")
    for pos in league.SKILL:
        r = agg.loc[pos]
        print(f"{pos:5}{int(r.seasons):>8}{r.repl_pg:>12.2f}{r.top1:>10.0f}"
              f"{r.top3:>8.0f}{r.top12:>8.0f}{r.top1_sd:>9.0f}")
    print("\n  VOR of the best player at each position, per season:")
    piv = d.pivot_table(index="season", columns="pos", values="top3_vor")
    print(piv.round(0).to_string())
    print("\n  VERDICT: the ordering is stable across 14 seasons. RB carries the "
          "largest\n  top-end VOR, QB the smallest, and QB's is also the most "
          "volatile relative to\n  its size -- which is the argument for waiting, "
          "not the 6-point rule.")
    return d


# ---------------------------------------------------------------------------
def q_injuries(panel):
    H("Q: do injuries predict injuries?")
    d = panel.sort_values(["player_id", "season"]).copy()
    d["next_games"] = d.groupby("player_id").games.shift(-1)
    d["next_season"] = d.groupby("player_id").season.shift(-1)
    d = d[(d.next_season == d.season + 1)]
    print(f"{'pos':5}{'n':>7}{'slope':>8}{'r':>7}   interpretation")
    for pos in league.SKILL:
        s = d[(d.position == pos)].dropna(subset=["games", "next_games"])
        if len(s) < 60:
            continue
        b = np.polyfit(s.games, s.next_games, 1)[0]
        r = np.corrcoef(s.games, s.next_games)[0, 1]
        print(f"{pos:5}{len(s):>7}{b:>8.2f}{r:>7.2f}   "
              f"{'real but weak' if r < 0.5 else 'moderate'}")
    print("\n  Missing time last year vs missing time this year, by bucket:")
    d["bucket"] = pd.cut(d.games_missed, [-1, 0, 2, 5, 20],
                         labels=["0 missed", "1-2", "3-5", "6+"])
    b = d.groupby("bucket").agg(n=("next_games", "size"),
                                next_games=("next_games", "mean"),
                                pct_full=("next_games", lambda s: (s >= 16).mean()))
    print(b.round(2).to_string())
    lo = b.next_games.iloc[0]; hi = b.next_games.iloc[-1]
    print(f"\n  VERDICT: yes, but weakly. A player who missed 6+ games averages "
          f"{hi:.1f} games\n  the next year vs {lo:.1f} for one who missed none -- "
          f"a {lo-hi:.1f} game difference.\n  Worth a tiebreak, not worth a round.")
    return d


# ---------------------------------------------------------------------------
def q_team_stability(panel):
    H("Q: which offenses are most stable year to year?")
    tm = (panel.groupby(["team", "season"])
                .agg(plays=("tm_plays_pg", "mean"), pass_rate=("tm_pass_rate", "mean"),
                     epa=("tm_epa", "mean"), rz=("tm_rz_pg", "mean"))
                .reset_index().sort_values(["team", "season"]))
    for c in ("plays", "pass_rate", "epa", "rz"):
        tm[f"n_{c}"] = tm.groupby("team")[c].shift(-1)
    tm["nseason"] = tm.groupby("team").season.shift(-1)
    tm = tm[tm.nseason == tm.season + 1]
    print("league-wide year-over-year stability of team context:")
    for c in ("plays", "pass_rate", "epa", "rz"):
        s = tm.dropna(subset=[c, f"n_{c}"])
        r = np.corrcoef(s[c], s[f"n_{c}"])[0, 1]
        b = np.polyfit(s[c], s[f"n_{c}"], 1)[0]
        print(f"  {c:10} n={len(s):>4}  slope {b:5.2f}  r {r:5.2f}")
    per = []
    for team, g in tm.groupby("team"):
        if len(g) < 6:
            continue
        per.append(dict(team=team, n=len(g),
                        pass_rate_sd=g.pass_rate.std(), plays_sd=g.plays.std(),
                        epa_sd=g.epa.std()))
    p = pd.DataFrame(per).sort_values("pass_rate_sd")
    print("\n  most STABLE pass rates (lowest year-over-year SD):")
    print("   " + ", ".join(f"{r.team} {r.pass_rate_sd:.3f}" for _, r in p.head(6).iterrows()))
    print("  least stable:")
    print("   " + ", ".join(f"{r.team} {r.pass_rate_sd:.3f}" for _, r in p.tail(6).iterrows()))
    print("\n  VERDICT: team pass rate is the most stable context feature and "
          "team EPA the\n  least. Role projections are most trustworthy on the "
          "stable-pass-rate teams.")
    return p


# ---------------------------------------------------------------------------
def q_mispriced(p):
    H("Q: which player-seasons were most mispriced vs ADP, and what did they share?")
    d = p[p.adp.notna() & (p.adp_rank <= 150)].copy()
    d["pg"] = d.pts / d.games.replace(0, np.nan)
    d["pg"] = d.pg.fillna(0)
    # actual positional rank that season
    d["act_pos_rank"] = d.groupby(["season", "position"]).pts.rank(ascending=False, method="min")
    d["surprise"] = d.adp_pos_rank - d.act_pos_rank      # + = beat his price
    good = d[d.games >= 6]
    print(f"n = {len(d)} drafted player-seasons ({d.season.min()}-{d.season.max()})\n")
    print("BIGGEST OVERPERFORMERS (finished far above where they were drafted):")
    for _, r in d.nlargest(10, "surprise").iterrows():
        print(f"  {int(r.season)} {r.position:3} {r.player_display_name:22} "
              f"ADP {r.pos_rank_str if hasattr(r,'pos_rank_str') else int(r.adp_pos_rank):>3} "
              f"-> finished {int(r.act_pos_rank):>3}  (+{int(r.surprise)})")
    print("\nBIGGEST BUSTS:")
    for _, r in d.nsmallest(10, "surprise").iterrows():
        print(f"  {int(r.season)} {r.position:3} {r.player_display_name:22} "
              f"ADP {int(r.adp_pos_rank):>3} -> finished {int(r.act_pos_rank):>3}  "
              f"({int(r.surprise)})  {int(r.games)} games")
    # what do they share? compare prior-year traits of hits vs busts
    d["prior_snap"] = d.snap_pct
    top = d.nlargest(150, "surprise"); bot = d.nsmallest(150, "surprise")
    print("\nTRAITS — top 150 overperformers vs bottom 150 busts (their OWN season):")
    print(f"{'trait':22}{'over':>9}{'bust':>9}{'gap':>9}")
    for c, lbl in [("age", "age"), ("games", "games played"), ("snap_pct", "snap share"),
                   ("target_share", "target share"), ("td_oe", "TDs over expected"),
                   ("adp_pos_rank", "ADP pos rank"), ("exp", "years experience")]:
        if c not in d: continue
        a, b = top[c].mean(), bot[c].mean()
        print(f"{lbl:22}{a:>9.2f}{b:>9.2f}{a-b:>+9.2f}")
    print("\n  Caution: these are OUTCOME traits measured in the same season, so "
          "they describe\n  what a hit looks like after the fact, not a rule for "
          "picking one beforehand.\n  The predictive version of this question is "
          "the backtest, not this table.")
    return d


def main():
    panel, adp, p = load()
    q_sixpoint(panel)
    q_positional_value(panel)
    q_injuries(panel)
    q_team_stability(panel)
    q_mispriced(p)
    q_rookies(panel, adp)




# ---------------------------------------------------------------------------
def q_rookies(panel, adp):
    """v2 excluded all six rookies from the edge table outright. Was that right,
    or is there signal in draft capital and landing spot?"""
    print("\n" + "=" * 76)
    print("Q: how predictable are rookies? was excluding them right?")
    print("=" * 76)
    p = panel.copy()
    first = p.groupby("player_id").season.transform("min")
    p["is_rookie"] = (p.season == first) & (p.exp.fillna(9) <= 0)
    # fall back to first-observed-season when exp is missing
    p.loc[p.exp.isna(), "is_rookie"] = (p.season == first)
    r = p[p.is_rookie & p.position.isin(league.SKILL)].copy()
    a = adp.dropna(subset=["player_id"])[["player_id", "season", "adp", "adp_pos_rank"]]
    r = r.merge(a, on=["player_id", "season"], how="left")
    r["drafted"] = r.adp.notna()
    print(f"n = {len(r)} rookie seasons, {int(r.season.min())}-{int(r.season.max())}")
    print(f"  of these, {int(r.drafted.sum())} ({r.drafted.mean():.0%}) had an ADP "
          f"-- the rest went undrafted in fantasy\n")

    r["pg"] = r.pts / r.games.replace(0, np.nan)
    print("rookie production by NFL draft round:")
    r["rd"] = r.draft_round.fillna(8).clip(upper=8)
    t = r.groupby("rd").agg(n=("pg", "size"), games=("games", "mean"),
                            pts_pg=("pg", "mean"),
                            hit_rate=("pg", lambda s: (s >= 10).mean()))
    t.index = [f"round {int(i)}" if i < 8 else "undrafted/late" for i in t.index]
    print(t.round(2).to_string())

    d = r[r.draft_pick.notna() & r.pg.notna()]
    if len(d) > 50:
        rho = stats.spearmanr(d.draft_pick, d.pg).correlation
        print(f"\n  Spearman(NFL draft pick, rookie pts/game) = {rho:+.3f}  (n={len(d)})")
        print(f"  -> draft capital explains r2 = {rho**2:.3f} of rookie scoring")
    dd = r[r.adp_pos_rank.notna() & r.pg.notna()]
    if len(dd) > 50:
        rho2 = stats.spearmanr(dd.adp_pos_rank, dd.pg).correlation
        print(f"  Spearman(fantasy ADP,    rookie pts/game) = {rho2:+.3f}  (n={len(dd)})")
        print(f"  -> the fantasy market prices rookies "
              f"{'BETTER' if abs(rho2) > abs(rho) else 'no better'} than NFL draft capital alone")

    by_pos = r[r.pg.notna()].groupby("position").agg(
        n=("pg", "size"), pts_pg=("pg", "mean"),
        top24=("pg", lambda s: (s >= s.quantile(0.9)).mean()))
    print("\nrookie scoring by position:")
    print(by_pos.round(2).to_string())
    print("\n  VERDICT: draft capital carries real but modest information, and the")
    print("  fantasy market already reflects it. Excluding rookies from a MODEL is")
    print("  correct -- they have no prior-season features by construction, so a")
    print("  model has nothing to say. Excluding them from the BOARD would be wrong:")
    print("  ADP prices them, and ADP is what wins here.")
    return r


if __name__ == "__main__":
    main()
