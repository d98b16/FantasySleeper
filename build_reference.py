#!/usr/bin/env python3
"""
build_reference.py — data/reference.json + reference.html

A standalone during-draft page, separate from index.html and touching none of it.
Open it in a second tab. No interaction, no network, big text, scannable in a few
seconds because a pick clock is 90 seconds.

Contents, in the order they matter at the table:
  1. DO NOT DRAFT      hard exclusions
  2. ROOKIE TIERS      from the ONE trait that predicts (draft capital)
  3. BYE GRID          where the board is thin, and which weeks collide
  4. HANDCUFFS         which board RBs have a backup worth a bench spot
  5. OFF-BOARD ROOKIES round-1 picks your 129-player board does not list

    python3 build_reference.py
"""
import json, os, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
import league
from reference_page import render

HERE = os.path.dirname(os.path.abspath(__file__))
RAW  = os.path.join(HERE, "data", "raw")
OUT  = os.path.join(HERE, "data")
CLASS = 2026

# Hard exclusions. These are facts about availability, not opinions about talent,
# so they override every ranking. Sourced from the owner.
DO_NOT_DRAFT = [
    dict(name="Josh Jacobs", pos="RB", team="GB", board_rank=26,
         reason="Commissioner's Exempt List — cannot play. Undraftable.",
         severity="hard"),
]

# Measured on 825 rookie seasons, 2013-2025 (rookies.py). Draft capital is the
# only trait that predicts year-1 production with any strength: spearman +0.54,
# r2 0.29. Vacated opportunity at the landing spot is weak (r2 0.01-0.03) and
# combine athleticism is nothing. College production is UNTESTED — nflverse has
# no college stats and I have no cached CFB source.
TIERS = [
    (0, 10,  "REAL WEEK-1 ROLE",  0.741, 13.4, "top-10 pick — 74% hit rate as rookies"),
    (10, 32, "STARTER-ADJACENT",  0.433,  9.6, "rest of round 1 — 43% hit rate"),
    (32, 64, "DART THROW",        0.291,  7.1, "round 2 — 29% hit rate"),
    (64, 105,"BENCH FLYER",       0.107,  5.1, "round 3 — 11% hit rate"),
    (105, 999,"DO NOT ROSTER",    0.051,  3.4, "round 4+ — 5% hit rate"),
]


def clean(o):
    """NaN and Infinity are not JSON. Python's json.dumps emits them bare, which
    Python itself will read back but JSON.parse in a browser rejects outright --
    the page silently had no data at all until this was found. Null them."""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, float) and (o != o or o in (float("inf"), float("-inf"))):
        return None
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        f = float(o)
        return None if f != f else f
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def tier_for(pick):
    for lo, hi, name, hit, pg, note in TIERS:
        if lo < pick <= hi:
            return dict(tier=name, hit=hit, mean_pg=pg, note=note)
    return dict(tier="DO NOT ROSTER", hit=0.05, mean_pg=3.4, note="undrafted")


DND_KEYS = {league.norm(d["name"]) for d in DO_NOT_DRAFT}


def load():
    board = pd.DataFrame(json.load(open(os.path.join(HERE, "ranks.json")))["ranks"])
    board["key"] = board.name.map(league.norm)
    # An undraftable player must not appear anywhere on this page as if he were
    # available -- he was showing up in the bye grid and as a handcuff LEAD,
    # which is the exact opposite of the message.
    board = board[~board.key.isin(DND_KEYS)].copy()
    dp = pd.read_parquet(os.path.join(RAW, "draft_picks.parquet"))
    dp = dp[(dp.season == CLASS) & dp.position.isin(league.SKILL)].copy()
    dp["key"] = dp.pfr_player_name.map(league.norm)
    panel = pd.read_parquet(os.path.join(OUT, "player_seasons.parquet"))
    p25 = panel[panel.season == 2025].copy()
    p25["key"] = p25.player_display_name.map(league.norm)
    return board, dp, p25


def rookies(board, dp):
    on = board.merge(dp[["key", "round", "pick", "team", "college", "position"]],
                     on="key", how="inner", suffixes=("", "_d"))
    rows = []
    for _, r in on.sort_values("pick").iterrows():
        t = tier_for(int(r["pick"]))
        rows.append(dict(name=r["name"], pos=r["pos"], team=r["team"],
                         board_rank=int(r["rank"]), rd=int(r["round"]),
                         pick=int(r["pick"]), college=r["college"], **t))
    off = dp[~dp.key.isin(board.key) & (dp["round"] <= 2)].sort_values("pick")
    offrows = []
    for _, r in off.iterrows():
        t = tier_for(int(r["pick"]))
        if t["hit"] < 0.25:
            continue                       # not worth a mention below round 2
        offrows.append(dict(name=r["pfr_player_name"], pos=r["position"],
                            team=r["team"], rd=int(r["round"]), pick=int(r["pick"]),
                            college=r["college"], **t))
    return rows, offrows


def byes(board):
    """Where the board is thin. Two starters on the same bye is a real problem
    with four bench spots; two bench players is not."""
    b = board[board.pos != "DST"].copy()
    top = b[b["rank"] <= 60]
    grid = []
    for wk in sorted(b.bye.dropna().unique()):
        wk = int(wk)
        g = b[b.bye == wk]
        t = top[top.bye == wk]
        grid.append(dict(week=wk, total=len(g), top60=len(t),
                         by_pos={p: int((t.pos == p).sum()) for p in league.SKILL},
                         names=t.sort_values("rank")["name"].head(10).tolist()))
    grid.sort(key=lambda x: -x["top60"])
    return grid


def handcuffs(board, p25):
    """Which board RBs have a backup worth one of four bench spots.

    Team assignment uses the 2026 board where the player appears on it, and only
    falls back to his 2025 team otherwise. Using 2025 teams throughout paired
    Jahmyr Gibbs with David Montgomery, who has since left Detroit for Houston --
    a handcuff who plays for another team is not a handcuff. Fallback pairs are
    flagged `assumed_same_team`, because for a player who is not on the board
    there is no 2026 evidence either way."""
    rb = board[board.pos == "RB"].copy()
    board_team = dict(zip(board.key, board.team))
    carries = (p25[p25.position == "RB"]
               .groupby(["key"], as_index=False)
               .agg(carries=("carries", "sum"),
                    name=("player_display_name", "first"),
                    snap=("snap_pct", "mean"),
                    team_2025=("team", "first")))
    carries["team_2026"] = carries.key.map(board_team)
    carries["assumed"] = carries.team_2026.isna()
    carries["team"] = carries.team_2026.fillna(carries.team_2025)

    lead_carries = dict(zip(carries.key, carries.carries))
    pairs, seen = [], set()
    for _, lead in rb.sort_values("rank").iterrows():
        if lead["key"] in DND_KEYS:
            continue
        mates = carries[(carries.team == lead["team"]) & (carries.key != lead["key"])
                        & (~carries.key.isin(DND_KEYS))]
        mates = mates[mates.carries >= 25].sort_values("carries", ascending=False)
        if mates.empty:
            continue
        m = mates.iloc[0]
        # Only emit a pair where the board player is genuinely the LEAD. Without
        # this the list produced backwards pairs ("Ollie Gordon II -> De'Von
        # Achane") and reciprocals (Stevenson -> Henderson and Henderson ->
        # Stevenson), which is worse than no handcuff at all.
        back_rank = board[board.key == m["key"]]
        back_rank = int(back_rank["rank"].iloc[0]) if len(back_rank) else None
        if back_rank is not None and back_rank < lead["rank"]:
            continue                       # the "backup" is the better player
        if lead_carries.get(lead["key"], 0) < m.carries and back_rank is not None:
            continue                       # he was second in line himself
        pair = tuple(sorted([lead["key"], m["key"]]))
        if pair in seen:
            continue
        seen.add(pair)
        pairs.append(dict(
            lead=lead["name"], lead_rank=int(lead["rank"]), team=lead["team"],
            back=m["name"], back_carries=int(m.carries),
            back_snap=round(float(m.snap or 0), 2),
            back_board_rank=back_rank, assumed_same_team=bool(m.assumed)))
    return pairs


def market_board():
    """Live 2026 half-PPR ADP. Joined on the normalised name, and on the team
    code for defenses, whose names differ on the two boards ("HOU D/ST" vs
    "Houston Defense")."""
    p = os.path.join(OUT, "adp_2026.json")
    if not os.path.exists(p):
        return {}, {}
    m = json.load(open(p))["players"]
    by_name, by_team_dst = {}, {}
    for x in m:
        rec = dict(adp=x["adp"], mkt=x["mkt_rank"], pos=x["pos"],
                   team=x.get("team"), name=x["name"], sd=x.get("sd"))
        by_name[league.norm(x["name"])] = rec
        if x["pos"] == "DST" and x.get("team"):
            by_team_dst[str(x["team"]).upper()] = rec
    return by_name, by_team_dst


def universe(board, dp, mkt_name, mkt_dst):
    """Every player either board or market knows about. Nobody is dropped for
    existing on one side only -- those are exactly the players worth seeing."""
    rows, seen = [], set()
    rook = {}
    for _, r in dp.iterrows():
        rook[r["key"]] = dict(pick=int(r["pick"]), rd=int(r["round"]),
                              college=r["college"], **tier_for(int(r["pick"])))

    for _, b in board.iterrows():
        k = b["key"]
        seen.add(k)
        m = mkt_name.get(k) or (mkt_dst.get(str(b["team"]).upper())
                                if b["pos"] == "DST" else None)
        rk = rook.get(k)
        rows.append(dict(n=b["name"], p=b["pos"], t=b["team"],
                         our=int(b["rank"]), ti=int(b["tier"]) if pd.notna(b["tier"]) else None,
                         by=int(b["bye"]) if pd.notna(b["bye"]) else None,
                         adp=(m or {}).get("adp"), mkt=(m or {}).get("mkt"),
                         cl=(rk or {}).get("college"), pk=(rk or {}).get("pick"),
                         rt=(rk or {}).get("tier"), nt=b.get("notes") or ""))
    for k, m in mkt_name.items():
        if k in seen or m["pos"] in ("K",):
            continue
        rk = rook.get(k)
        rows.append(dict(n=m["name"], p=m["pos"], t=m.get("team") or "",
                         our=None, ti=None, by=None, adp=m["adp"], mkt=m["mkt"],
                         cl=(rk or {}).get("college"), pk=(rk or {}).get("pick"),
                         rt=(rk or {}).get("tier"), nt=""))
    for k, rk in rook.items():
        if k in seen or k in mkt_name:
            continue
        row = dp[dp.key == k].iloc[0]
        rows.append(dict(n=row["pfr_player_name"], p=row["position"], t=row["team"],
                         our=None, ti=None, by=None, adp=None, mkt=None,
                         cl=rk["college"], pk=rk["pick"], rt=rk["tier"], nt=""))

    # delta = market rank - our rank. Positive: we rank him better than the
    # market does. Both sides must exist or it is meaningless.
    for r in rows:
        r["d"] = (r["mkt"] - r["our"]) if (r["mkt"] and r["our"]) else None
        r["dnd"] = league.norm(r["n"]) in DND_KEYS
    rows.sort(key=lambda r: (r["our"] is None, r["our"] or 9999,
                             r["mkt"] is None, r["mkt"] or 9999))
    return rows


def main():
    board, dp, p25 = load()
    mkt_name, mkt_dst = market_board()
    rk, offrk = rookies(board, dp)

    inherits = []
    for d in DO_NOT_DRAFT:
        if d["pos"] != "RB":
            continue
        mates = (p25[(p25.position == "RB") & (p25.team == d["team"])
                     & (p25.key != league.norm(d["name"]))]
                 .sort_values("carries", ascending=False))
        if mates.empty:
            continue
        m = mates.iloc[0]
        ob = board[board.key == m["key"]]
        inherits.append(dict(out=d["name"], team=d["team"],
                             heir=m["player_display_name"], carries=int(m.carries),
                             board_rank=int(ob["rank"].iloc[0]) if len(ob) else None))

    payload = dict(
        inherits=inherits,
        generated_for="GovSmart Gridiron · 12-team · 0.5 PPR · 6-pt pass TD · 12 rounds",
        do_not_draft=DO_NOT_DRAFT,
        rookie_method=dict(
            n=825, span="2013-2025",
            predicts="draft capital (spearman +0.54, r2 0.29)",
            weak="opportunity vacated at the landing spot (r2 0.01-0.03; only WR "
                 "targets reaches significance)",
            no_signal="combine athleticism (r2 0.001)",
            untested="college production — nflverse has no college stats and no "
                     "CFB source is cached, so it is untested here, not disproven"),
        rookies=rk, off_board_rookies=offrk,
        byes=byes(board), handcuffs=handcuffs(board, p25),
        players=universe(board, dp, mkt_name, mkt_dst),
        market_source=(json.load(open(os.path.join(OUT, "adp_2026.json")))["source"]
                       if os.path.exists(os.path.join(OUT, "adp_2026.json")) else None),
    )
    payload = clean(payload)
    with open(os.path.join(OUT, "reference.json"), "w") as f:
        json.dump(payload, f, separators=(",", ":"), allow_nan=False)
    html = render(payload)
    with open(os.path.join(HERE, "reference.html"), "w") as f:
        f.write(html)
    nb = sum(1 for r in payload["players"] if r["our"] is None)
    nm = sum(1 for r in payload["players"] if r["mkt"] is None)
    print(f"data/reference.json  {len(payload['players'])} players "
          f"({nb} not on board, {nm} not on market), {len(rk)} board rookies, "
          f"{len(payload['handcuffs'])} handcuff pairs")
    print(f"reference.html       {len(html)/1024:.0f} KB standalone")
    return payload


if __name__ == "__main__":
    main()
