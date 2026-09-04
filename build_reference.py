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


def main():
    board, dp, p25 = load()
    rk, offrk = rookies(board, dp)
    # If a top-30 back is unavailable, the man behind him is the story.
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
                             heir=m["player_display_name"],
                             carries=int(m.carries),
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
    )
    with open(os.path.join(OUT, "reference.json"), "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    html = render(payload)
    with open(os.path.join(HERE, "reference.html"), "w") as f:
        f.write(html)
    print(f"data/reference.json  {len(rk)} board rookies, {len(offrk)} off-board, "
          f"{len(payload['handcuffs'])} handcuff pairs, {len(payload['byes'])} bye weeks")
    print(f"reference.html       {len(html)/1024:.0f} KB standalone")
    return payload




# ============================================================================
# THE PAGE
# ============================================================================
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0d1117;--panel:#161b22;--panel2:#1c2430;--line:#2d3947;--tx:#e6edf3;
--dim:#93a1b0;--faint:#6b7a8a;--rb:#3fb950;--wr:#58a6ff;--qb:#f0883e;--te:#bc8cff;
--bad:#f85149;--warn:#e3b341;--good:#3fb950}
body{background:var(--bg);color:var(--tx);font:16px/1.45 ui-sans-serif,system-ui,
-apple-system,"Segoe UI",Roboto,Arial,sans-serif;padding:14px;max-width:1100px;margin:0 auto}
h1{font-size:19px;letter-spacing:-.02em}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.1em;color:var(--faint);
margin:26px 0 9px;font-weight:800;border-bottom:1px solid var(--line);padding-bottom:6px}
.sub{font-size:12px;color:var(--faint);font-weight:500;letter-spacing:0;text-transform:none}
header{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:4px}
.meta{font-size:11.5px;color:var(--faint);margin-bottom:2px}
/* --- do not draft --- */
.dnd{background:rgba(248,81,73,.16);border:2px solid var(--bad);border-radius:10px;
padding:14px 16px;margin:14px 0 4px}
.dnd .hdr{font-size:12px;font-weight:900;letter-spacing:.14em;color:var(--bad);margin-bottom:8px}
.dnd .nm{font-size:30px;font-weight:900;line-height:1.1;letter-spacing:-.02em}
.dnd .why{font-size:15px;color:#ffb3ae;margin-top:5px;font-weight:600}
/* --- tiers --- */
.tier{margin-bottom:12px;border-left:5px solid var(--line);padding-left:12px}
.tier.t0{border-left-color:var(--good)} .tier.t1{border-left-color:var(--warn)}
.tier.t2{border-left-color:#c9822f} .tier.t3{border-left-color:var(--faint)}
.tier .tn{font-size:14px;font-weight:900;letter-spacing:.05em}
.tier.t0 .tn{color:var(--good)} .tier.t1 .tn{color:var(--warn)}
.tier.t2 .tn{color:#c9822f} .tier.t3 .tn{color:var(--faint)}
.tier .tm{font-size:11.5px;color:var(--faint);margin-bottom:5px}
.plist{display:flex;flex-wrap:wrap;gap:7px}
.pl{background:var(--panel);border:1px solid var(--line);border-radius:7px;
padding:7px 11px;min-width:0}
.pl .n{font-size:17px;font-weight:800;line-height:1.15}
.pl .d{font-size:11.5px;color:var(--dim);margin-top:1px}
.pos{font-size:10px;font-weight:900;padding:1px 5px;border-radius:4px;margin-right:4px}
.pos.RB{color:var(--rb);background:rgba(63,185,80,.15)}
.pos.WR{color:var(--wr);background:rgba(88,166,255,.15)}
.pos.QB{color:var(--qb);background:rgba(240,136,62,.15)}
.pos.TE{color:var(--te);background:rgba(188,140,255,.15)}
/* --- bye grid --- */
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--faint);
text-align:left;padding:5px 7px;font-weight:800}
td{padding:7px;border-top:1px solid var(--line);font-size:14px}
tr.hot td{background:rgba(248,81,73,.10)}
tr.warm td{background:rgba(227,179,65,.08)}
.wk{font-size:21px;font-weight:900}
.cnt{font-size:17px;font-weight:800}
.pc{font-size:12px;color:var(--dim)}
.nm{font-size:11.5px;color:var(--faint);line-height:1.35}
/* --- handcuffs --- */
.hc{display:grid;grid-template-columns:repeat(auto-fill,minmax(255px,1fr));gap:7px}
.hcp{background:var(--panel);border:1px solid var(--line);border-radius:7px;padding:8px 11px}
.hcp .a{font-size:15px;font-weight:800}
.hcp .b{font-size:14px;font-weight:700;color:var(--good);margin-top:2px}
.hcp .c{font-size:11px;color:var(--faint);margin-top:2px}
.note{font-size:12px;color:var(--faint);line-height:1.55;margin-top:8px;
background:var(--panel);border-left:3px solid var(--line);padding:9px 12px;border-radius:0 6px 6px 0}
.note b{color:var(--dim)}
footer{margin-top:30px;font-size:11px;color:var(--faint);text-align:center;line-height:1.7;
border-top:1px solid var(--line);padding-top:12px}
@media(max-width:560px){
  body{padding:10px} .pl .n{font-size:16px} .dnd .nm{font-size:25px}
  .hc{grid-template-columns:1fr} td{font-size:13px} .wk{font-size:19px}
}
"""


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render(p):
    L = []
    A = L.append
    A(f"<!DOCTYPE html><html lang=en><head><meta charset=utf-8>")
    A('<meta name="viewport" content="width=device-width,initial-scale=1">')
    A("<title>Draft Reference</title><style>" + CSS + "</style></head><body>")
    A('<header><h1>Draft Reference</h1>'
      f'<span class=sub>{esc(p["generated_for"])}</span></header>')
    A('<div class=meta>Second-tab companion. Static — nothing here updates during '
      'the draft. The live board is the other tab.</div>')

    # 1 --- do not draft
    for d in p["do_not_draft"]:
        A('<div class=dnd><div class=hdr>DO NOT DRAFT</div>'
          f'<div class=nm>{esc(d["name"])} '
          f'<span class="pos {esc(d["pos"])}">{esc(d["pos"])}</span> '
          f'<span style="font-size:16px;color:var(--faint)">{esc(d["team"])} · '
          f'board #{d["board_rank"]}</span></div>'
          f'<div class=why>{esc(d["reason"])}</div>')
        for h in p.get("inherits", []):
            if h["out"] != d["name"]:
                continue
            br = f'board #{h["board_rank"]}' if h["board_rank"] else "not on the board"
            A(f'<div class=why style="color:var(--warn);margin-top:9px">'
              f'&rarr; {esc(h["heir"])} inherits the {esc(h["team"])} backfield '
              f'({h["carries"]} carries in 2025, {esc(br)}) — that is the pick '
              f'this frees up.</div>')
        A("</div>")

    # 2 --- rookies
    m = p["rookie_method"]
    A('<h2>Rookies <span class=sub>tiered by the one trait that predicts</span></h2>')
    order = ["REAL WEEK-1 ROLE", "STARTER-ADJACENT", "DART THROW", "BENCH FLYER"]
    for i, tname in enumerate(order):
        grp = [r for r in p["rookies"] if r["tier"] == tname]
        if not grp:
            continue
        note = grp[0]["note"]
        A(f'<div class="tier t{min(i,3)}"><div class=tn>{esc(tname)}</div>'
          f'<div class=tm>{esc(note)} · historically {grp[0]["mean_pg"]:.1f} pts/g</div>'
          '<div class=plist>')
        for r in grp:
            A(f'<div class=pl><div class=n><span class="pos {esc(r["pos"])}">'
              f'{esc(r["pos"])}</span>{esc(r["name"])}</div>'
              f'<div class=d>{esc(r["team"])} · board #{r["board_rank"]} · '
              f'NFL pick {r["pick"]} · {esc(r["college"])}</div></div>')
        A("</div></div>")
    A(f'<div class=note><b>Method.</b> Tested on {m["n"]} rookie seasons, '
      f'{esc(m["span"])}. <b>Predicts:</b> {esc(m["predicts"])}. '
      f'<b>Weak:</b> {esc(m["weak"])}. <b>No signal:</b> {esc(m["no_signal"])}. '
      f'<b>Untested:</b> {esc(m["untested"])}. Tiers are draft capital and nothing '
      'else, because nothing else earned a place in them.</div>')

    if p["off_board_rookies"]:
        A('<h2>Round-1 and 2 rookies your board does NOT list '
          '<span class=sub>the board stops at 129 players</span></h2><div class=plist>')
        for r in p["off_board_rookies"]:
            A(f'<div class=pl><div class=n><span class="pos {esc(r["pos"])}">'
              f'{esc(r["pos"])}</span>{esc(r["name"])}</div>'
              f'<div class=d>{esc(r["team"])} · NFL pick {r["pick"]} · '
              f'{int(r["hit"]*100)}% hit rate · {esc(r["college"])}</div></div>')
        A('</div><div class=note>These are not on the 129-player board at all. '
          'A round-1 rookie hits about 43% of the time; that is a better late-round '
          'swing than most names left in round 12. Check they are actually in '
          "Sleeper's pool before you plan on one.</div>")

    # 3 --- byes
    A('<h2>Bye weeks <span class=sub>where the board is thin — '
      'you have 4 bench spots</span></h2>')
    A('<table><tr><th>Wk</th><th>Top-60 out</th><th>By position</th>'
      '<th>Who</th></tr>')
    for b in p["byes"]:
        cls = "hot" if b["top60"] >= 10 else "warm" if b["top60"] >= 8 else ""
        bp = " ".join(f'{k}{v}' for k, v in b["by_pos"].items() if v)
        A(f'<tr class="{cls}"><td class=wk>{b["week"]}</td>'
          f'<td class=cnt>{b["top60"]}</td><td class=pc>{esc(bp)}</td>'
          f'<td class=nm>{esc(", ".join(b["names"][:7]))}</td></tr>')
    A("</table>")
    A('<div class=note><b>The rule for this roster:</b> two <i>starters</i> on the '
      'same bye is a real problem with only four bench spots — you start a hole. '
      'Two bench players on the same bye is not. Weeks shaded red take 10+ of the '
      'top 60 off the field at once; if you already hold two starters on one of '
      'those weeks, break the tie toward a different bye.</div>')

    # 4 --- handcuffs
    A('<h2>Handcuffs <span class=sub>who backs up the RB you just took</span></h2>'
      '<div class=hc>')
    for h in p["handcuffs"][:24]:
        br = f'board #{h["back_board_rank"]}' if h["back_board_rank"] else "off board"
        asu = " · assumed still there" if h.get("assumed_same_team") else ""
        A(f'<div class=hcp><div class=a>{esc(h["lead"])} '
          f'<span style="color:var(--faint);font-size:12px">#{h["lead_rank"]} '
          f'{esc(h["team"])}</span></div>'
          f'<div class=b>&rarr; {esc(h["back"])}</div>'
          f'<div class=c>{h["back_carries"]} carries in 2025 · {esc(br)}{esc(asu)}</div></div>')
    A("</div>")
    A('<div class=note>Backups are the 2025 second-most-used back on that player\'s '
      '<b>2026</b> team. Pairs marked <i>assumed still there</i> are not on the '
      '129-player board, so there is no 2026 evidence about them either way — '
      'check the roster before spending a pick.</div>')

    A('<footer>Generated by build_reference.py · '
      'static, no network, no modelling in the page<br>'
      'Rookie tiers from 825 rookie seasons 2013-2025 · '
      'handcuffs from 2025 carries on 2026 teams</footer>')
    A("</body></html>")
    return "\n".join(L)


if __name__ == "__main__":
    main()
