import json, runpy, io, contextlib

ns = {}
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    ns = runpy.run_path("build_sheet.py")

board = ns["board"]
plan  = ns["plan"]
scen  = ns["scenarios"]
faab  = ns["faab"]

ranks = []
for i, (player, pos, team, bye, adp, tier, notes) in enumerate(board, 1):
    ranks.append({
        "rank": i, "name": player, "pos": pos, "team": team,
        "bye": bye, "adp": (float(adp) if adp else None),
        "tier": tier, "notes": notes,
    })

payload = {
    "ranks": ranks,
    "plan": [{"rd": int(p[0]), "pick": int(p[1]), "window": p[2],
              "target": p[3], "fallback": p[4], "note": p[5]} for p in plan],
    "scenarios": scen,
    "faab": [{"rule": h, "detail": d} for (h, d) in faab],
}
with open("ranks.json", "w") as f:
    json.dump(payload, f, separators=(",", ":"))

print("players:", len(ranks))
print("plan rows:", len(payload["plan"]), "| scenarios:", len(scen), "| faab:", len(faab))
print("pos counts:", {p: sum(1 for r in ranks if r["pos"] == p) for p in ("QB","RB","WR","TE","DST")})
print("bytes:", len(json.dumps(payload, separators=(",", ":"))))
