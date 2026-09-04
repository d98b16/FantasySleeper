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
1. **6-pt passing TDs** — public ADP assumes 4-pt. Every QB is structurally
   underpriced in this league relative to the market. This is a real, exploitable gap.
2. **12 rounds / 4 bench / DEF required** — only 12 roster spots total. There is no
   room for dead weight, and a defense must be taken (round 12).

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
  for rankings. CSV row offsets are computed dynamically — do not hardcode them.
- `gen_ranks.py` — runs build_sheet.py, emits `ranks.json` for the web app.
- `ranks.json` — generated. Re-inline into index.html's ranksData block after regen.
- `test_console.js` / `test_def.js` — Playwright. Snake math, name matching,
  DEF gating, render checks. **Run these before shipping anything.**

## Known limitations (honest)

- Board is 120 players deep; a 12x12 draft is 144 picks. Late rounds run past it.
- Rankings snapshot is from FantasyFootballCalculator half-PPR ADP, refreshed Aug 27
  and again on draft morning. ADP past ~#60 is expert-consensus, not live market.
- Position-relative tier bands: QB/TE "elite" = T5/T6 because those positions have no
  T1-T4 players on this board. Absolute tier comparisons across positions are wrong.
