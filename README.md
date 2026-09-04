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

## The edge model

`build_edge.py` pulls the 2025 nflverse season (weekly stats, snap counts,
play-by-play), caches the raw files in `data/raw/`, and:

1. **Re-scores every player under this league's exact verified rules** — 0.5 PPR,
   6-point passing TDs, −2 INT, confirmed live against the Sleeper API.
2. **Weights opportunity over production.** Realised TDs are replaced with
   expected TDs from red-zone and inside-the-10 opportunity, then blended 55/45
   with a role-implied points-per-game fit (leave-one-out) on snap share, target
   share, air-yards share and red-zone volume. A lucky TD year does not survive.
3. **Values against this league's real roster shape** — 12 teams, 8 starters
   including a DEF, 12 rounds, 4 bench. Replacement is QB13 / RB31 / WR30 / TE14.
4. **Diffs the result against the board's ADP.** That delta is the edge.

Output is a precomputed `edge.json`. **The browser does no modelling.**
Per-player detail lives in `data/edge_2025.csv` and `data/player_2025.csv`.

Honest limits: it is one season. Six board players are 2026 rookies with no NFL
data and are excluded outright; 25 more had a 2025 role too small to describe
their 2026 one and are shown but explicitly not claimed. Only 86 of 129 carry a
trusted edge. See `CONTEXT.md` for the measured 6-point-passing-TD result, which
is real but much smaller than the league's reputation for it suggests.

## Tests

```bash
npm install playwright && npx playwright install chromium   # first time only
node test_console.js && node test_def.js && node test_v2.js
```

45 checks: snake math, name matching, DEF gating in *both* directions, roster
slot assignment and FLEX overflow, survival-odds math, run detection, and a guard
that fails if `ranks.json`/`edge.json` ever drift from what is inlined in
`index.html`. Run all three before shipping.

## Optional: live-syncing the Google Sheet

`sleeper_sync.gs` is Apps Script that syncs the shared Sheet from the Sleeper API.
Read its header before installing — Apps Script triggers have a hard **1-minute**
floor against a 90-second pick timer, so it is a second-screen convenience for a
co-owner watching the Sheet, not something to draft from. Use the console.
