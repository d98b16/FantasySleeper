#!/usr/bin/env python3
"""
data_pull.py — pull and cache every raw input the projection model needs.

Everything lands in data/raw/ (gitignored) and is NEVER re-downloaded unless the
file is missing, zero-length, or --refresh is passed. This is the only script
that touches the network.

    python3 data_pull.py              # fill any gaps
    python3 data_pull.py --refresh    # re-download everything
    python3 data_pull.py --manifest   # print what is cached, no network

SPAN
    2012-2025 (14 seasons). The binding constraint is snap_counts, which starts
    in 2012; pbp and weekly stats go back to 1999 but snap share is too central
    to the model to give up for the extra years. Coverage that starts later is
    recorded per-source in the manifest and handled as a feature block that
    simply is not available before its start year -- never silently zero-filled.

SOURCES
    nflverse-data releases (public, no auth)   github.com/nflverse/nflverse-data
    FantasyFootballCalculator ADP API          fantasyfootballcalculator.com
"""
import argparse, io, json, os, sys, time
import urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
RAW  = os.path.join(HERE, "data", "raw")
NFLV = "https://github.com/nflverse/nflverse-data/releases/download"
FFC  = "https://fantasyfootballcalculator.com/api/v1/adp"

FIRST, LAST = 2012, 2025

# name -> (release tag, filename template, first season available)
PER_SEASON = {
    "stats_player":      ("stats_player",      "stats_player_week_{y}.parquet", 1999),
    "stats_team":        ("stats_team",        "stats_team_week_{y}.parquet",   1999),
    "pbp":               ("pbp",               "play_by_play_{y}.parquet",      1999),
    "snap_counts":       ("snap_counts",       "snap_counts_{y}.parquet",       2012),
    "weekly_rosters":    ("weekly_rosters",    "roster_weekly_{y}.parquet",     2002),
    "depth_charts":      ("depth_charts",      "depth_charts_{y}.parquet",      2001),
    "injuries":          ("injuries",          "injuries_{y}.parquet",          2009),
    "participation":     ("pbp_participation", "pbp_participation_{y}.parquet", 2016),
    "advstats_rec":      ("pfr_advstats",      "advstats_week_rec_{y}.parquet", 2018),
    "advstats_rush":     ("pfr_advstats",      "advstats_week_rush_{y}.parquet",2018),
    "advstats_pass":     ("pfr_advstats",      "advstats_week_pass_{y}.parquet",2018),
}

# name -> (release tag, filename)   -- single files covering all seasons
STATIC = {
    "players":      ("players_components", "players.parquet"),
    "draft_picks":  ("draft_picks",        "draft_picks.parquet"),
    "schedules":    ("schedules",          "games.parquet"),
    "combine":      ("combine",            "combine.parquet"),
    "ngs_passing":  ("nextgen_stats",      "ngs_passing.parquet"),
    "ngs_rushing":  ("nextgen_stats",      "ngs_rushing.parquet"),
    "ngs_receiving":("nextgen_stats",      "ngs_receiving.parquet"),
    "teams":        ("teams",              "teams_colors_logos.parquet"),
}

# FFC serves half-PPR only from 2018. standard and ppr go back to 2010, and
# half-PPR sits exactly between them, so the earlier years get a proxy built
# from both -- validated against the overlap in build_adp.py, never assumed.
ADP_FORMATS = ["half-ppr", "ppr", "standard"]
ADP_FIRST   = 2010


def _get(url, dest, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "nflverse-pull/1.0"})
            with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as f:
                f.write(r.read())
            return os.path.getsize(dest)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None                      # genuinely absent, not an error
            if i == tries - 1:
                raise
        except Exception:
            if i == tries - 1:
                raise
        time.sleep(2 * (i + 1))
    return None


def pull(refresh=False):
    os.makedirs(RAW, exist_ok=True)
    manifest = {"span": [FIRST, LAST], "sources": {}, "adp": {}, "missing": []}
    got = skipped = 0

    for name, (tag, tmpl, first) in PER_SEASON.items():
        years, sizes = [], 0
        for y in range(FIRST, LAST + 1):
            if y < first:
                continue
            fn = tmpl.format(y=y)
            dest = os.path.join(RAW, fn)
            if os.path.exists(dest) and os.path.getsize(dest) > 0 and not refresh:
                years.append(y); sizes += os.path.getsize(dest); skipped += 1
                continue
            sz = _get(f"{NFLV}/{tag}/{fn}", dest)
            if sz:
                years.append(y); sizes += sz; got += 1
                print(f"  {fn:42} {sz/1e6:7.1f}MB")
            else:
                if os.path.exists(dest):
                    os.remove(dest)
                manifest["missing"].append(fn)
        manifest["sources"][name] = {
            "release": tag, "pattern": tmpl,
            "first_available": first, "years": years, "mb": round(sizes / 1e6, 1),
        }

    for name, (tag, fn) in STATIC.items():
        dest = os.path.join(RAW, fn)
        if os.path.exists(dest) and os.path.getsize(dest) > 0 and not refresh:
            skipped += 1
        else:
            sz = _get(f"{NFLV}/{tag}/{fn}", dest)
            if sz:
                got += 1
                print(f"  {fn:42} {sz/1e6:7.1f}MB")
            else:
                manifest["missing"].append(fn); continue
        manifest["sources"][name] = {"release": tag, "file": fn, "static": True,
                                     "mb": round(os.path.getsize(dest) / 1e6, 2)}

    # ---- historical ADP ----------------------------------------------------
    adp_dir = os.path.join(RAW, "adp")
    os.makedirs(adp_dir, exist_ok=True)
    for fmt in ADP_FORMATS:
        years = []
        for y in range(ADP_FIRST, LAST + 1):
            dest = os.path.join(adp_dir, f"adp_{fmt}_{y}.json")
            if os.path.exists(dest) and os.path.getsize(dest) > 2 and not refresh:
                try:
                    if json.load(open(dest)).get("players"):
                        years.append(y); skipped += 1; continue
                except Exception:
                    pass
            try:
                req = urllib.request.Request(
                    f"{FFC}/{fmt}?teams=12&year={y}&position=all",
                    headers={"User-Agent": "Mozilla/5.0 (research; fantasy backtest)"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    payload = json.loads(r.read().decode())
            except Exception as e:
                print(f"  adp {fmt} {y}: {e}"); continue
            n = len(payload.get("players", []))
            if n:
                json.dump(payload, open(dest, "w"))
                years.append(y); got += 1
                print(f"  adp_{fmt}_{y}.json{'':<24} {n:>4} players")
            time.sleep(0.4)                       # be polite to a free API
        manifest["adp"][fmt] = years

    manifest["fetched"] = got
    manifest["from_cache"] = skipped
    manifest["total_mb"] = round(sum(
        os.path.getsize(os.path.join(dp, f))
        for dp, _, fs in os.walk(RAW) for f in fs) / 1e6, 1)
    with open(os.path.join(HERE, "data", "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest


def show(m):
    print(f"\nspan {m['span'][0]}-{m['span'][1]} | fetched {m['fetched']} | "
          f"cached {m['from_cache']} | {m['total_mb']:.0f}MB on disk")
    for name, s in m["sources"].items():
        if s.get("static"):
            print(f"  {name:16} static           {s['mb']:>7.2f}MB")
        else:
            ys = s["years"]
            span = f"{min(ys)}-{max(ys)}" if ys else "NONE"
            gap = "" if len(ys) == (max(ys) - min(ys) + 1 if ys else 0) else "  GAPS"
            print(f"  {name:16} {span:<16} {s['mb']:>7.1f}MB  ({len(ys)} seasons){gap}")
    for fmt, ys in m["adp"].items():
        print(f"  adp/{fmt:11} {min(ys)}-{max(ys)}      ({len(ys)} seasons)" if ys
              else f"  adp/{fmt:11} NONE")
    if m["missing"]:
        print(f"  missing ({len(m['missing'])}): {', '.join(m['missing'][:6])}"
              + (" ..." if len(m["missing"]) > 6 else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--manifest", action="store_true")
    a = ap.parse_args()
    if a.manifest:
        show(json.load(open(os.path.join(HERE, "data", "manifest.json"))))
    else:
        show(pull(refresh=a.refresh))
