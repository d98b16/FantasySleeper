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

So the elite QB's edge over a streamer grows by **0.41 pts/game**. Repeating the whole
measurement across **two seasons (2024 and 2025) x three replacement ranks (QB11/13/15)**
puts the gain at **7-19 points across a full season, median 12.5** — under a point a
game. Measured against QB1 specifically it is ~0 or negative. It is not worth a
5th-round pick.

For scale, value over replacement across a season: best QB ~60 pts, best TE ~113,
best WR ~117, best RB ~227. **Wait on QB until round 9.**

Second: **rushing TDs are already 6 points in every format**, so the rule rewards
*passing-TD volume* and nothing else. The gain is exactly `2 x passing TDs`.

    2025:  Stafford +92  Goff +68  Maye +62  Prescott +60  |  Allen +50  Hurts +50  Lamar +42
    2024:  Burrow  +86  Mayfield +82  Jackson +82  Goff +74  |  Allen +56  Daniels +50  Hurts +36

The obvious reading — "so fade the dual-threats" — is **too strong, and I am not
claiming it**. The correlation between rushing-TD share and 6-pt gain among the top 20
gainers is only -0.23 (2024) and -0.18 (2025), and Lamar Jackson was the *third* biggest
gainer of 2024 on 41 passing TDs. The label is a bad proxy. **Look at the QB's actual
passing-TD total, not his rushing reputation.** The previous note in this file said
dual-threats gain the most, which is backwards.

**Confidence.** High on the structure: that the rule lifts replacement as much as elite,
and that the gain equals 2 x passing TDs, is arithmetic and cannot fail to hold. Medium
on the magnitude: 7-19 pts/season is a real range, not a point estimate, and the spread
comes from which replacement rank you believe. Low on any individual 2026 projection —
these are 2025 and 2024 totals and QBs do not repeat TD counts.

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
