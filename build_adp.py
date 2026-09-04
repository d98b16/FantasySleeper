#!/usr/bin/env python3
"""
build_adp.py — historical ADP -> data/adp.parquet, joined to nflverse player ids.

WHY THIS IS THE HARDEST PIECE
    ADP is the benchmark the model has to beat, so any sloppiness here flatters
    or unfairly punishes it. Two problems have to be solved honestly:

    1. FORMAT. The league is 0.5 PPR. FantasyFootballCalculator serves half-PPR
       only from 2018. For 2012-2017 we build a proxy from the standard and PPR
       boards, which bracket half-PPR by construction. The proxy is VALIDATED on
       2018-2025 where all three exist -- see validate() -- rather than assumed.

    2. IDENTITY. ADP carries a name, a team and a position; nflverse carries
       gsis ids. Matching is done on normalised name + season, with position as a
       tiebreak, and the match rate is reported per season. Unmatched ADP rows
       are kept and flagged, never silently dropped, because dropping them would
       quietly remove exactly the players the market was most wrong about
       (rookies and journeymen).

    python3 build_adp.py
"""
import glob, json, os, sys, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
import league

HERE = os.path.dirname(os.path.abspath(__file__))
RAW  = os.path.join(HERE, "data", "raw", "adp")
OUT  = os.path.join(HERE, "data")

POS_FIX = {"PK": "K", "DEF": "DST", "D/ST": "DST"}


def load_raw():
    rows = []
    for fp in sorted(glob.glob(os.path.join(RAW, "adp_*.json"))):
        base = os.path.basename(fp)[4:-5]           # <fmt>_<year>
        fmt, yr = base.rsplit("_", 1)
        try:
            payload = json.load(open(fp))
        except Exception:
            continue
        for p in payload.get("players", []):
            rows.append(dict(
                fmt=fmt, season=int(yr), name=p.get("name"),
                pos=POS_FIX.get(str(p.get("position")).upper(), str(p.get("position")).upper()),
                team=p.get("team"), adp=p.get("adp"), adp_sd=p.get("stdev"),
                adp_hi=p.get("high"), adp_lo=p.get("low"),
                times_drafted=p.get("times_drafted"), bye=p.get("bye")))
    df = pd.DataFrame(rows)
    df["key"] = df.name.map(league.norm)
    for c in ("adp", "adp_sd", "adp_hi", "adp_lo", "times_drafted"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # rank within (format, season) -- ranks compare across formats, raw ADP does not
    df["adp_rank"] = df.groupby(["fmt", "season"]).adp.rank(method="min")
    return df


def validate(df):
    """Is mean(standard, ppr) a usable stand-in for half-PPR? Measured on the
    2018-2025 overlap, reported, and only then used for 2012-2017."""
    piv = df.pivot_table(index=["season", "key"], columns="fmt",
                         values="adp", aggfunc="first")
    piv = piv.dropna(subset=["standard", "ppr", "half-ppr"])
    piv["proxy"] = piv[["standard", "ppr"]].mean(axis=1)
    out = []
    for season, g in piv.groupby(level=0):
        err = g.proxy - g["half-ppr"]
        rho = g.proxy.rank().corr(g["half-ppr"].rank(), method="spearman")
        out.append(dict(season=season, n=len(g), mae=err.abs().mean(),
                        bias=err.mean(), spearman=rho,
                        p90=err.abs().quantile(0.90)))
    v = pd.DataFrame(out)
    print("\nPROXY VALIDATION — mean(standard, PPR) vs true half-PPR ADP")
    print(v.round(3).to_string(index=False))
    print(f"  pooled: n={len(piv)}  MAE={abs(piv.proxy-piv['half-ppr']).mean():.2f} picks"
          f"  bias={(piv.proxy-piv['half-ppr']).mean():+.2f}"
          f"  spearman={piv.proxy.rank().corr(piv['half-ppr'].rank(), method='spearman'):.4f}")
    return v


def blend(df):
    """One ADP per (season, player): true half-PPR where it exists, else the
    validated standard/PPR proxy. `adp_source` records which, always."""
    wide = df.pivot_table(index=["season", "key", "pos"],
                          values=["adp", "adp_sd", "adp_hi", "adp_lo", "times_drafted"],
                          columns="fmt", aggfunc="first")
    wide.columns = [f"{a}__{b}" for a, b in wide.columns]
    wide = wide.reset_index()

    half = wide.get("adp__half-ppr")
    std, ppr = wide.get("adp__standard"), wide.get("adp__ppr")
    proxy = pd.concat([std, ppr], axis=1).mean(axis=1)
    wide["adp"] = half.where(half.notna(), proxy)
    wide["adp_source"] = np.where(half.notna(), "half-ppr",
                          np.where(std.notna() & ppr.notna(), "proxy(std+ppr)",
                          np.where(ppr.notna(), "ppr-only",
                          np.where(std.notna(), "standard-only", "none"))))
    sd_half = wide.get("adp_sd__half-ppr")
    sd_proxy = pd.concat([wide.get("adp_sd__standard"), wide.get("adp_sd__ppr")],
                         axis=1).mean(axis=1)
    wide["adp_sd"] = sd_half.where(sd_half.notna(), sd_proxy)
    td = pd.concat([wide.get(f"times_drafted__{f}") for f in
                    ("half-ppr", "ppr", "standard")], axis=1).max(axis=1)
    wide["times_drafted"] = td
    wide = wide.dropna(subset=["adp"])
    wide["adp_rank"] = wide.groupby("season").adp.rank(method="min")
    wide["adp_pos_rank"] = wide.groupby(["season", "pos"]).adp.rank(method="min")
    return wide[["season", "key", "pos", "adp", "adp_sd", "adp_rank",
                 "adp_pos_rank", "adp_source", "times_drafted"]]


# Name variants the ADP board uses that nflverse does not. Kept explicit and
# small: a fuzzy matcher here would silently mis-link players, which is worse
# than a handful of misses.
ALIAS = {
    # ADP-board spelling -> nflverse spelling. Every entry below was verified
    # against the panel (name resolves, in the right season, at the right
    # position). An earlier version of this map was written from memory and was
    # mostly WRONG -- several entries broke matches that already worked, e.g.
    # mapping "willfuller" to "willfullerv" when nflverse says "Will Fuller".
    # Do not add an entry here without checking it against player_seasons.
    "michaelvick": "mikevick",            # nflverse: "Mike Vick"
    "beaniewells": "chriswells",          # nflverse: "Chris Wells"
    "hollywoodbrown": "marquisebrown",    # nflverse: "Marquise Brown"
    "joshuapalmer": "joshpalmer",         # fuzzy-verified, 2024-2025
    "charlesjohnson": "charlesdjohnson",  # fuzzy-verified, 2015
}


def attach_ids(adp):
    """Match ADP rows to gsis ids via the panel. Unmatched rows are KEPT and
    flagged: dropping them would remove the journeymen and rookies the market
    was most wrong about, which is the population we care about most."""
    panel = pd.read_parquet(os.path.join(OUT, "player_seasons.parquet"),
                            columns=["player_id", "player_display_name",
                                     "position", "season", "games", "pts"])
    panel["key"] = panel.player_display_name.map(league.norm)
    adp = adp.copy()
    adp["key"] = adp.key.replace(ALIAS)
    # a player's ADP for season S should match his season-S nflverse row
    m = adp.merge(panel[["key", "season", "player_id", "position", "games", "pts"]],
                  on=["key", "season"], how="left")
    # if the name matched more than one id in a season, prefer the one whose
    # position agrees with the ADP board
    m["pos_ok"] = (m.position == m.pos).fillna(False)
    m = (m.sort_values(["season", "key", "pos_ok", "games"], ascending=[True, True, False, False])
           .drop_duplicates(["season", "key"], keep="first"))
    m["matched"] = m.player_id.notna()
    panel_first = int(panel.season.min())
    m["in_panel_era"] = m.season >= panel_first
    # A DST or K on the ADP board can never match a skill-position panel row, and
    # neither can a season before the panel starts. Report the rate on the
    # population where a match is actually possible, and show the rest separately
    # so the number is not quietly flattered.
    live = m[m.in_panel_era & m.pos.isin(league.SKILL)]
    print(f"\nID MATCH RATE (skill positions, {panel_first}+ where a match is possible)")
    r = live.groupby("season").agg(rows=("key", "size"), matched=("matched", "sum"))
    r["rate"] = (r.matched / r.rows).round(3)
    print(r.to_string())
    print(f"  pooled: {live.matched.mean():.1%} of {len(live)} rows")
    top = live[live.adp_rank <= 120]
    print(f"  top-120 by ADP: {top.matched.mean():.1%} ({(~top.matched).sum()} unmatched)")
    print(f"\n  excluded from the rate (a match is impossible, not a failure):")
    print(f"    {(~m.in_panel_era).sum():>5} rows from {m.season.min()}-{panel_first-1}, "
          f"before the panel starts")
    print(f"    {(m.in_panel_era & ~m.pos.isin(league.SKILL)).sum():>5} DST/K rows "
          f"({sorted(set(m[m.in_panel_era & ~m.pos.isin(league.SKILL)].pos))})")
    # A drafted player who never took a regular-season snap is not a missing row
    # to be dropped -- he is the market's worst outcome, and dropping him would
    # quietly make ADP look better than it was. If he exists in the panel in ANY
    # season, record the ADP season as 0 games / 0 points.
    ever = set(panel.player_id.dropna())
    key2id = (panel.sort_values(["season"]).drop_duplicates("key", keep="last")
                   .set_index("key").player_id.to_dict())
    zero = m.matched.eq(False) & m.in_panel_era & m.pos.isin(league.SKILL) & m.key.isin(key2id)
    m.loc[zero, "player_id"] = m.loc[zero, "key"].map(key2id)
    m.loc[zero, ["games", "pts"]] = 0.0
    m.loc[zero, "matched"] = True
    m["zero_season"] = zero
    print(f"\n  {int(zero.sum())} drafted players with no regular-season snap that year "
          f"recorded as 0 games / 0 points rather than dropped")
    for _, x in m[zero & (m.adp_rank <= 80)].sort_values("adp").head(6).iterrows():
        print(f"    {int(x.season)}  ADP {x.adp:6.1f}  {x.pos:3}  {x['key']}")

    live = m[m.in_panel_era & m.pos.isin(league.SKILL)]
    print(f"  match rate after zero-fill: {live.matched.mean():.1%}")

    miss = live[~live.matched & (live.adp_rank <= 100)]
    if len(miss):
        print(f"\n  genuine misses inside the top 100 ({len(miss)}):")
        for _, x in miss.sort_values("adp").head(10).iterrows():
            print(f"    {int(x.season)}  ADP {x.adp:6.1f}  {x.pos:3}  {x['key']}")
        print("    (a player drafted but who never took a regular-season skill snap "
              "has no panel row by construction)")
    return m


def main():
    raw = load_raw()
    print(f"loaded {len(raw)} ADP rows  "
          f"{raw.season.min()}-{raw.season.max()}  formats={sorted(raw.fmt.unique())}")
    print(raw.groupby(["fmt"]).season.agg(["min", "max", "count"]).to_string())
    v = validate(raw)
    adp = blend(raw)
    print(f"\nblended: {len(adp)} player-seasons")
    print(adp.groupby("adp_source").size().to_string())
    m = attach_ids(adp)
    m.to_parquet(os.path.join(OUT, "adp.parquet"), index=False)
    v.to_csv(os.path.join(OUT, "adp_proxy_validation.csv"), index=False)
    print(f"\ndata/adp.parquet  {len(m)} rows")
    return m


if __name__ == "__main__":
    main()
