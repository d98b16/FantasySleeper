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

## The 6-point thesis, measured on 14 seasons (`questions.py`)

Measured across 2012-2025, 126 (season x replacement-rank x tier) cells:

| tier | median gain | 95% CI | seasons negative |
|---|---|---|---|
| top-6 QB | **+13.4 pts/season** | 11.2 - 17.7 | 0 of 14 |
| top-3 QB | +19.6 | 15.1 - 24.9 | 0 of 14 |
| QB1 | **+24.8** | 16.4 - 33.3 | 1 of 14 |

The rule lifts **every** QB, replacement included, so what matters is the change in
the elite QB's *advantage* over a streamer. That advantage is real, consistently
positive, and small: under a point a game.

**This corrects the v2 note in two directions.** v2 measured on two seasons and (a)
put the top-6 gain at 7-19 with median 12.5 -- close, and now tightened; (b) called
QB1 "too noisy to plan around" at -3.8 to +34.4. On 14 seasons QB1 is the *largest*
of the three tiers and reliably positive. The two-season sample was too small.

For scale, realised value over replacement at the top of each position over the same
14 seasons: **RB 203, WR 143, QB 140, TE 107**. QB is not worthless -- but you cannot
know in advance which QB finishes first, and QB has the highest variance relative to
its size. **Wait on QB. It is a real edge, not a rounding error.**

## The multi-season model, and what it found (`FINDINGS.md`, `BACKTEST.md`)

Built on 14 seasons of nflverse (2012-2025) and 16 of historical ADP. Walk-forward
validated: train on every season before T, predict T, for T in 2016-2025.

**The model does not beat ADP.** Pooled across positions, points per game:

    ADP (the market)              2.621 MAE      -
    ADP + ridge residual          2.625        -0.14%
    model, with ADP as a feature  2.852        -8.80%
    model, stats only             3.040       -15.99%
    last year's rate              3.280       -25.16%

Six model families, four positions, ten held-out seasons, zero wins. The best result
is a tie, reached by a regularised model learning to predict a residual of ~zero.

**Seven edge hypotheses were pre-registered and tested with draft price controlled.
One survived**: 9 or fewer games last season predicts finishing ~3 positional ranks
below ADP (p=0.0011, survives Bonferroni). Every other raw effect collapsed once
price was controlled -- including **TD-luck regression, which v2 shipped as its edge
column and which is worth +0.2 ranks at p=0.80**. The market had already priced it.

Consequence for the console: the board order stays ADP. What the model contributes
is the **outcome range** -- floor, ceiling, bust probability -- which a single ADP
number cannot provide.

## Stickiness: what repeats year to year (`data/stickiness.csv`)

Slope of next season on this season = the fraction of a player's edge that survives.

    volume      carries/g 0.76 RB   targets/g 0.79 WR   snap share 0.64-0.71
    efficiency  YPC 0.17 RB   catch rate 0.14 RB   yds after contact 0.27 RB
    TD luck     TDs over expected 0.09 WR / 0.11 RB / 0.15 TE   -- noise
    health      games played 0.39 RB / 0.42 WR / 0.49 TE / 0.66 QB

Volume repeats, efficiency mostly does not, TD luck does not repeat at all.

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

**Run `python3 sync.py`, not the individual scripts.** It rebuilds everything in
dependency order, re-inlines both JSON payloads into index.html, and verifies they
match byte for byte. `--full` also reruns the ~20 minute backtest. `--check`
verifies without changing anything.

- `index.html` — the whole app, one self-contained static file. Two inlined payloads:
  `ranksData` (the board) and `edgeData` (projections + honesty block).
- `league.py` — the scoring rules, once, verified live against Sleeper.
- `data_pull.py` — caches nflverse 2012-2025 + FFC ADP 2010-2025 into `data/raw/`
  (gitignored, ~357MB). Never re-downloads. Run once.
- `build_panel.py` — raw -> `data/player_seasons.parquet` (8055 x 104).
- `build_adp.py` — -> `data/adp.parquet`, format-validated and id-matched.
- `features.py` — -> `data/features.parquet` (5524 rows, no leakage).
- `stickiness.py` / `edge_tests.py` / `questions.py` / `backtest.py` — the analyses.
- `project.py` — -> `data/projections_2026.*` (mean/floor/ceiling/bust).
- `build_edge.py` — -> `edge.json`, the console payload (v2 kept as
  `build_edge_v2_archived.py` for reference).
- `make_reports.py` — -> `BACKTEST.md`, generated from the results files.
- `build_sheet.py` / `gen_ranks.py` — the spreadsheet and board, as before.
- `sleeper_sync.gs` — optional Apps Script for the shared Google Sheet.
- **Tests:** `test_console.js` / `test_def.js` / `test_v2.js` (65 checks) and
  `test_pipeline.py` (30 checks, including explicit leakage tests).
  **Run all four before shipping anything.**

## Known limitations (honest)

- Board is 129 players deep (117 skill + 12 defenses); a 12x12 draft is 144 picks,
  so the deepest rounds can still run past it.
- The projections are ADP-anchored by construction, because the model lost to ADP.
  They are not an independent opinion about who is better; they are the market's
  ranking with an uncertainty band attached.
- Out-of-sample MAE is ~2.6 points per game, which is roughly +/-45 points across a
  season. The floor-to-ceiling range is the honest representation; the mean is not.
- Six board players are 2026 rookies with no NFL snaps. The model has nothing to say
  about them and does not pretend to. ADP prices rookies as well as NFL draft capital
  does (Spearman -0.542 vs -0.541), so they stay on the board at their ADP.
- The half-PPR ADP board only exists from 2018. 2012-2017 uses the mean of the
  standard and PPR boards, validated on the overlap at MAE 4.0 picks / Spearman 0.990.
- snap_counts_2012 has no regular-season rows upstream, so 2012 contributes no snap
  share and the first fully-featured training pair is 2013->2014.
- Rankings snapshot is from FantasyFootballCalculator half-PPR ADP, refreshed Aug 27
  and again on draft morning. ADP past ~#60 is expert-consensus, not live market.
- Position-relative tier bands: QB/TE "elite" = T5/T6 because those positions have no
  T1-T4 players on this board. Absolute tier comparisons across positions are wrong.
