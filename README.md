# FantasySleeper

Live Sleeper draft board + draft-day console for one 12-team league.
**Live: https://d98b16.github.io/FantasySleeper/**

`index.html` is the whole app: one self-contained static file, no build step, no
backend, no npm needed to run it. Open it from a URL on a phone and it works.
Its only network call is to Sleeper's public read-only API.

## Draft-day use

Open the page, hit **Connect**. It polls the draft every 2s (1s when your pick is
close) and shows:

- **Your roster** — all 12 slots as cards with FLEX overflow handled, plus the 2
  IR slots. Empty *starters* are styled loud, empty bench muted, because an
  unfilled starter is the actual problem.
- **Best available** — scored against your open slots, tier scarcity, bye
  collisions, and how far a player has fallen past ADP.
- **`to #N`** — the chance each player is still there at your *next* pick. On a
  back-to-back turn this is the whole decision.
- **Edge** — where the 2025 model disagrees with the board's ADP.
- **Run chips** — when a position is going materially faster than its supply.

`Run demo draft` rehearses the whole thing with no league connection.

## Rebuilding

```bash
python3 sync.py            # rebuild everything, re-inline, verify
python3 sync.py --check    # verify only; non-zero exit on drift
```

**Always use `sync.py`.** `build_sheet.py`'s `board` list is the single source of
truth for rankings, and four artifacts derive from it:

```
build_sheet.py ──┬──> fantasy_draft_2026.xlsx     workbook, 6 tabs
                 └──> draft_sheet.csv             Google Sheets import
gen_ranks.py ───────> ranks.json ────┐
build_edge.py ──────> edge.json ─────┴──> inlined into index.html
```

Running those generators by hand is how `ranks.json` and `index.html` silently
drifted apart twice — once shipping a 15-round plan with a kicker into a
12-round league that has no kicker slot. `sync.py` rebuilds in dependency order
and then proves the inlined payloads are byte-identical to the files on disk.

## The model

`sync.py` runs the chain. `data_pull.py` caches 14 seasons of nflverse and 16 of
historical ADP into `data/raw/` (gitignored, ~357MB, never re-downloaded).

The honest summary is in **[FINDINGS.md](FINDINGS.md)**; the numbers are in
**[BACKTEST.md](BACKTEST.md)**, generated from the results files rather than typed.

**The model does not beat ADP.** Walk-forward across 2016-2025, six model families,
four positions: the market wins every time, and the best a model manages is a tie by
learning to predict a residual of zero. Seven edge hypotheses were pre-registered and
tested with draft price controlled; one survived (heavy games-missed last season,
worth ~3 positional ranks). The TD-regression signal this tool shipped last year is
worth +0.2 ranks at p=0.80 once price is controlled — the market had already priced
it, and it has been removed.

So the console keeps ADP's board order and adds what ADP cannot give you: a floor, a
ceiling, and a bust probability per player, plus a confidence marker. Everything is
precomputed offline into a static `edge.json`. **The browser does no modelling.**

The most useful by-product is `data/stickiness.csv` — what actually repeats year to
year. Volume does (carries/game 0.76, targets/game 0.79). Efficiency mostly does not
(YPC 0.17, catch rate 0.14). Touchdowns over expected do not repeat at all
(0.09-0.15).

## Tests

```bash
npm install playwright && npx playwright install chromium   # first time only
node test_console.js && node test_def.js && node test_v2.js && python3 test_pipeline.py
```

95 checks: snake math, name matching, DEF gating in *both* directions, roster
slot assignment and FLEX overflow, survival-odds math, run detection, and a guard
that fails if `ranks.json`/`edge.json` ever drift from what is inlined in
`index.html`, and — in `test_pipeline.py` — explicit leakage tests proving no
feature row contains information from its own target season. Run all four before
shipping.

## Optional: live-syncing the Google Sheet

`sleeper_sync.gs` is Apps Script that syncs the shared Sheet from the Sleeper API.
Read its header before installing — Apps Script triggers have a hard **1-minute**
floor against a 90-second pick timer, so it is a second-screen convenience for a
co-owner watching the Sheet, not something to draft from. Use the console.
