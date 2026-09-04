# FantasySleeper — project context

Single-page draft console for one specific Sleeper league. No backend, no build step,
no API key. `index.html` is fully self-contained and is what GitHub Pages serves.

Live: https://d98b16.github.io/FantasySleeper/

## THE LEAGUE — verified against Sleeper's API, do not re-assume

| Fact | Value |
|---|---|
| Sleeper league ID | `1389326749023608832` |
| Draft ID | `1389326749023608833` |
| League name | GovSmart Gridiron |
| Format | 12-team **snake** |
| Scoring | **0.5 PPR** (half), **6-point passing TDs** |
| Waivers | $100 FAAB |
| Owner's draft slot | **3** |
| Draft time | Fri Sep 4 2026, 5:30 PM ET, 90-second pick timer |
| Rounds | **12** (not 15) |
| Starters (8) | QB, RB, RB, WR, WR, TE, FLEX(RB/WR/TE), **DEF** |
| Bench | 4 |
| IR slots | 2 |
| Kicker | **NONE — there is no K slot. Never draft one.** |
| Owner's 12 picks | 3, 22, 27, 46, 51, 70, 75, 94, 99, 118, 123, 142 |

DeAndre is the **co-owner** on Matt Whitten's roster (Sleeper user `MWhitten204`,
team "Urine Trouble", roster_id 8). The user_id that actually holds the draft slot is
`738922049573097472`; DeAndre's own user_id is `1401418036652556288`.

Two consequences that drive strategy:
1. **6-pt passing TDs** — public ADP assumes 4-pt, so QBs *are* mispriced here.
   But the gap is much smaller than it looks, and it points at different QBs than
   you would guess. See "The 6-point thesis, measured" below before acting on it.
2. **12 rounds / 4 bench / DEF required** — only 12 roster spots total. There is no
   room for dead weight, and a defense must be taken.

## The 6-point thesis, measured (2025 nflverse, `build_edge.py`)

The original claim here was "every QB is structurally underpriced — take a top-6 QB
by rounds 5-8". The data does not support the second half of that.

The rule lifts **every** QB, the streamer included:

| | 4-pt (public ADP) | 6-pt (this league) |
|---|---|---|
| Replacement QB (QB13) | 17.42 pts/g | 20.87 pts/g |
| Top-6 QB average | 20.67 pts/g | 24.54 pts/g |
| **Elite QB's advantage** | **3.26 pts/g** | **3.67 pts/g** |

So the elite QB's edge over a streamer grows by **0.41 pts/game — about 7 points
across a whole season**. That is one good WR game. It is not worth a 5th-round pick.
Checked at every plausible replacement rank (QB9 through QB18) the gain stays in the
5-16 pts/season band; measured against QB1 specifically it is ~0 or negative.

For scale, value over replacement across a season: best QB ~60 pts, best TE ~113,
best WR ~117, best RB ~227. **Wait on QB until round 9.**

Second, counterintuitive result: **rushing TDs are already 6 points in every format**,
so dual-threat QBs gain the *least* from this rule, not the most. 2025 season gain:

    Stafford +92   Goff +68   Maye +62   Prescott +60   |   Allen +50   Lamar +42

Prefer high-volume pocket passers. The previous note in this file said the opposite.

**Confidence:** the structural argument (the rule lifts replacement as much as elite;
rushing TDs are format-neutral) is arithmetic and does not depend on the sample. The
specific per-player numbers are one season and will not repeat exactly.

## Sleeper API — public, read-only, no auth, no key

Rate limit ~1000 req/min. The console polls at 2000ms, 1000ms when the pick is near
(~3-6% of budget). **CORS is confirmed working from GitHub Pages** — tested live.

- `GET /v1/league/<league_id>` — settings, scoring, roster_positions
- `GET /v1/league/<league_id>/drafts` — → draft_id
- `GET /v1/draft/<draft_id>` — settings, draft_order, slot_to_roster_id, status
- `GET /v1/draft/<draft_id>/picks` — **the poll target.** Each pick carries a full
  `metadata` object (first_name, last_name, position, team, injury_status), which is
  why we never need Sleeper's ~5MB `/v1/players/nfl` file. Keep it that way.
- `GET /v1/league/<id>/users` and `/rosters` — owner ↔ roster mapping
- `GET /v1/state/nfl` — current season/week

## Files

- `index.html` — the whole app. Rankings are embedded in `<script id="ranksData">`.
  Tunables live at the top of the script block: `ROSTER_NEED`, `FLEX_SLOTS`,
  `WEIGHTS`, `CONFIG`. `window.DRAFT` exposes state for console poking.
- `build_sheet.py` — builds `fantasy_draft_2026.xlsx` (6 tabs) AND `draft_sheet.csv`
  (the Google Sheets import). The `board` list in here is the single source of truth
  for rankings. Row offsets in BOTH outputs are computed dynamically — do not
  hardcode them. Assertions parse every generated formula back out and prove its
  ranges and criteria cells land on the computed rows.
- `gen_ranks.py` — runs build_sheet.py, emits `ranks.json` for the web app.
- `build_edge.py` — 2025 nflverse -> `data/` + `edge.json`. Raw pulls cached in
  `data/raw/` (gitignored); `--refresh` re-downloads.
- **`sync.py` — run this, not the scripts above.** It rebuilds sheet -> ranks ->
  edge, re-inlines both JSONs into index.html, and verifies they match byte for
  byte. `sync.py --check` verifies without changing anything. Running the
  generators by hand is how ranks.json and index.html drifted apart twice.
- `sleeper_sync.gs` — optional Apps Script that live-syncs the shared Google
  Sheet. Read the header before installing: the 1-minute trigger floor makes it a
  second-screen convenience for the co-owner, not a drafting tool.
- `test_console.js` / `test_def.js` / `test_v2.js` — Playwright. Snake math, name
  matching, DEF gating both directions, roster slots, payload drift.
  **Run all three before shipping anything.**

## Known limitations (honest)

- Board is 129 players deep (117 skill + 12 defenses); a 12x12 draft is 144 picks,
  so the deepest rounds can still run past it.
- The edge model is one season. 6 board players are 2026 rookies with no NFL data
  and are excluded outright; 25 more had a 2025 role too small to describe their
  2026 one (low snaps or few games) and are shown but explicitly not claimed as
  edges. Only 86 of 129 carry a trusted edge.
- In-sample R^2 on the role models is high (0.85-0.99) because opportunity really
  does explain scoring *within* a season. That is not the same as predictive
  accuracy for 2026, and should not be read as such.
- Rankings snapshot is from FantasyFootballCalculator half-PPR ADP, refreshed Aug 27
  and again on draft morning. ADP past ~#60 is expert-consensus, not live market.
- Position-relative tier bands: QB/TE "elite" = T5/T6 because those positions have no
  T1-T4 players on this board. Absolute tier comparisons across positions are wrong.
