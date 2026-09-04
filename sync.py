#!/usr/bin/env python3
"""
sync.py — the ONLY supported way to rebuild the draft artifacts.

build_sheet.py's `board` is the single source of truth for rankings. Four things
derive from it and every one of them must agree:

    data_pull.py    ->  data/raw/                    (cached nflverse + ADP; run once)
    build_sheet.py  ->  fantasy_draft_2026.xlsx      (the workbook)
                    ->  draft_sheet.csv              (the Google Sheets import)
    gen_ranks.py    ->  ranks.json                   (the web board)
    build_panel.py  ->  data/player_seasons.parquet  (14 seasons, tidy)
    build_adp.py    ->  data/adp.parquet             (16 seasons of ADP)
    features.py     ->  data/features.parquet        (supervised, no leakage)
    project.py      ->  data/projections_2026.*      (mean/floor/ceiling/bust)
    build_edge.py   ->  edge.json                    (the console payload)
    this script     ->  index.html                   (both JSONs inlined)

Running those by hand is how ranks.json and index.html silently drift apart --
which has now happened twice. Run this instead. It rebuilds everything in
dependency order, re-inlines both payloads, and then VERIFIES that what ended up
inside index.html is byte-identical to the files on disk. Non-zero exit = drift.

    python3 sync.py            rebuild the fast path + inline + verify
    python3 sync.py --full     also rerun stickiness, edge tests and the ~20 min
                               walk-forward backtest, and regenerate BACKTEST.md
    python3 sync.py --check    verify only, change nothing (use in CI / pre-commit)
"""
import json, re, subprocess, sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX = os.path.join(HERE, "index.html")
BLOCKS = {                       # script tag id -> file it must mirror
    "ranksData": "ranks.json",
    "edgeData":  "edge.json",
}


def sh(*cmd):
    r = subprocess.run([sys.executable, *cmd], cwd=HERE,
                       capture_output=True, text=True)
    if r.returncode:
        print(r.stdout); print(r.stderr, file=sys.stderr)
        sys.exit("FAILED: %s" % " ".join(cmd))
    return r.stdout


def block_re(tag):
    return re.compile(r'(<script id="%s" type="application/json">)(.*?)(</script>)' % tag, re.S)


def read_block(html, tag):
    m = block_re(tag).search(html)
    if not m:
        sys.exit("index.html has no <script id=%r> block" % tag)
    return m.group(2)


def check(quiet=False):
    html = open(INDEX).read()
    bad = []
    for tag, fn in BLOCKS.items():
        disk = open(os.path.join(HERE, fn)).read().strip()
        inline = read_block(html, tag).strip()
        if disk != inline:
            try:
                a, b = json.loads(disk), json.loads(inline)
                detail = "%d vs %d ranked players" % (
                    len(a.get("ranks", a.get("players", []))),
                    len(b.get("ranks", b.get("players", []))))
            except Exception:
                detail = "%d vs %d bytes" % (len(disk), len(inline))
            bad.append("%s does not match #%s in index.html (%s)" % (fn, tag, detail))
        elif not quiet:
            print("  OK  %-11s == #%s (%d bytes)" % (fn, tag, len(disk)))
    if bad:
        for b in bad:
            print("  DRIFT  " + b, file=sys.stderr)
        sys.exit("index.html is out of sync — run: python3 sync.py")
    return True


# The model layer, in dependency order. The expensive stages are skipped unless
# --full is passed, because the walk-forward backtest is ~20 minutes and its
# outputs only change when the model or the data change.
FAST = [
    ("build_sheet.py", "xlsx + csv"),
    ("gen_ranks.py",   "ranks.json"),
    ("build_panel.py", "data/player_seasons.parquet"),
    ("build_adp.py",   "data/adp.parquet"),
    ("features.py",    "data/features.parquet"),
    ("project.py",     "data/projections_2026.parquet"),
    ("build_edge.py",  "edge.json"),
]
FULL = [
    ("stickiness.py",   "data/stickiness.csv"),
    ("edge_tests.py",   "data/edge_tests.csv"),
    ("questions.py",    "data/sixpoint.csv"),
    ("backtest.py",     "data/backtest_results.csv   (~20 min)"),
    ("make_reports.py", "BACKTEST.md"),
]


def main():
    if "--check" in sys.argv:
        print("checking inlined payloads...")
        check()
        print("in sync.")
        return

    full = "--full" in sys.argv
    stages = list(FAST)
    if full:
        # order matters: stickiness/tests/questions feed build_edge and the report
        stages = (FAST[:5] + FULL[:3] + FAST[5:] + FULL[3:])
    n = len(stages) + 1
    for i, (script, what) in enumerate(stages, 1):
        print(f"{i}/{n}  {script:16} -> {what}")
        out = sh(script).strip()
        tail = [l for l in out.splitlines() if l.strip()][-2:]
        for l in tail:
            print("     " + l)
    if not full:
        print("     (skipped stickiness / edge_tests / backtest — pass --full to rerun,"
              " ~20 min)")

    print(f"{n}/{n}  inline into index.html")
    html = open(INDEX).read()
    for tag, fn in BLOCKS.items():
        payload = open(os.path.join(HERE, fn)).read().strip()
        json.loads(payload)                      # never inline invalid JSON
        html = block_re(tag).sub(
            lambda m, p=payload: m.group(1) + p + m.group(3), html, count=1)
    open(INDEX, "w").write(html)
    check()

    board = json.loads(open(os.path.join(HERE, "ranks.json")).read())
    edge = json.loads(open(os.path.join(HERE, "edge.json")).read())
    pos = {}
    for r in board["ranks"]:
        pos[r["pos"]] = pos.get(r["pos"], 0) + 1
    print("in sync.  board %d players %s | edge payload v%s, %d players"
          % (len(board["ranks"]), pos, edge.get("version", "?"), len(edge["players"])))
    h = edge.get("honesty", {})
    if h:
        print("          model beats ADP: %s" % h.get("model_beats_adp"))


if __name__ == "__main__":
    main()
