#!/usr/bin/env python3
"""
fetch_adp_2026.py — cache the live 2026 half-PPR ADP board.

Writes data/adp_2026.json and nothing else. Touches no part of the draft
pipeline: not ranks.json, not build_sheet.py, not index.html.

Why it exists: ranks.json carries an ADP for only 60 of its 129 players, so a
"market" column built from it would be blank for more than half the board. The
live FantasyFootballCalculator board has 228, which makes the comparison real.

    python3 fetch_adp_2026.py            # cached; --refresh to re-pull
"""
import json, os, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(HERE, "data", "adp_2026.json")
URL = ("https://fantasyfootballcalculator.com/api/v1/adp/half-ppr"
       "?teams=12&year=2026&position=all")
POS_FIX = {"DEF": "DST", "PK": "K", "D/ST": "DST"}


def main(refresh=False):
    if os.path.exists(DEST) and not refresh:
        d = json.load(open(DEST))
        print(f"cached  data/adp_2026.json  {len(d['players'])} players")
        return d
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (research)"})
    raw = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
    players = []
    for p in raw.get("players", []):
        pos = POS_FIX.get(str(p.get("position", "")).upper(), str(p.get("position", "")).upper())
        players.append(dict(name=p.get("name"), pos=pos, team=p.get("team"),
                            adp=p.get("adp"), sd=p.get("stdev"),
                            hi=p.get("high"), lo=p.get("low"), bye=p.get("bye")))
    players.sort(key=lambda x: (x["adp"] is None, x["adp"]))
    for i, p in enumerate(players, 1):
        p["mkt_rank"] = i
    out = dict(source="FantasyFootballCalculator half-PPR, 12-team, 2026",
               fetched_utc=None, n=len(players), players=players)
    os.makedirs(os.path.dirname(DEST), exist_ok=True)
    json.dump(out, open(DEST, "w"), separators=(",", ":"))
    print(f"fetched data/adp_2026.json  {len(players)} players, "
          f"deepest ADP {players[-1]['adp']}")
    return out


if __name__ == "__main__":
    main(refresh="--refresh" in sys.argv)
