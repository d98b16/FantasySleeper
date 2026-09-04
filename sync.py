#!/usr/bin/env python3
"""
sync.py — the ONLY supported way to rebuild the draft artifacts.

build_sheet.py's `board` is the single source of truth for rankings. Four things
derive from it and every one of them must agree:

    build_sheet.py  ->  fantasy_draft_2026.xlsx      (the workbook)
                    ->  draft_sheet.csv              (the Google Sheets import)
    gen_ranks.py    ->  ranks.json                   (the web board)
    build_edge.py   ->  edge.json                    (the 2025 edge model)
    this script     ->  index.html                   (both JSONs inlined)

Running those by hand is how ranks.json and index.html silently drift apart --
which has now happened twice. Run this instead. It rebuilds everything in
dependency order, re-inlines both payloads, and then VERIFIES that what ended up
inside index.html is byte-identical to the files on disk. Non-zero exit = drift.

    python3 sync.py            rebuild + inline + verify
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


def main():
    if "--check" in sys.argv:
        print("checking inlined payloads...")
        check()
        print("in sync.")
        return

    print("1/4  build_sheet.py  -> xlsx + csv")
    print("     " + sh("build_sheet.py").strip().replace("\n", "\n     "))
    print("2/4  gen_ranks.py    -> ranks.json")
    print("     " + sh("gen_ranks.py").strip().replace("\n", "\n     "))
    print("3/4  build_edge.py   -> data/ + edge.json")
    sh("-c", "import build_edge,io,contextlib;"
             "b=io.StringIO();"
             "contextlib.redirect_stdout(b).__enter__();"
             "build_edge.main_with_edge()")
    print("     edge.json rebuilt from cached nflverse pulls")

    print("4/4  inline into index.html")
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
    print("in sync.  board %d players %s | edge %d matched, %d unmatched"
          % (len(board["ranks"]), pos, len(edge["players"]), len(edge["unmatched"])))


if __name__ == "__main__":
    main()
