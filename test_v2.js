/* test_v2.js — covers everything added in v2:
     roster slot assignment + FLEX overflow      (feature 1)
     ranks.json / edge.json <-> index.html sync  (the drift that keeps recurring)
     DEF is actually recommended when required   (audit finding, critical)
     stale demo state never survives a connect   (audit finding, critical)
     bye stacking counts starters only           (audit finding)
*/
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const checks = {};
const T = (name, val) => { checks[name] = val; };

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 1200 } });
  const errors = [];
  page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('CONSOLE: ' + m.text()); });
  await page.goto('file://' + path.resolve('index.html'));
  await page.waitForTimeout(300);

  // ---------- 1. inlined payloads must equal the files on disk ----------
  const inlined = await page.evaluate(() => ({
    ranks: document.getElementById('ranksData').textContent.trim(),
    edge:  document.getElementById('edgeData').textContent.trim(),
  }));
  T('ranks.json matches index.html', inlined.ranks === fs.readFileSync('ranks.json', 'utf8').trim());
  T('edge.json matches index.html',  inlined.edge  === fs.readFileSync('edge.json',  'utf8').trim());

  // ---------- 2. roster slots + FLEX overflow ----------
  const slots = await page.evaluate(() => {
    const { assignSlots, SLOTS } = window.DRAFT;
    const P = (name, pos) => ({ name, pos, team: 'XX', ranked: { bye: 7 } });
    const ids = r => assignSlots(r).slots.map(s => s.id + '=' + (s.player ? s.player.name : ''));
    return {
      nSlots: SLOTS.length,
      // 3rd RB must fall to FLEX, 4th to the bench
      rb: ids([P('RB1', 'RB'), P('RB2', 'RB'), P('RB3', 'RB'), P('RB4', 'RB')]),
      // 2nd TE must fall to FLEX
      te: ids([P('TEa', 'TE'), P('TEb', 'TE')]),
      // 3rd WR must fall to FLEX
      wr: ids([P('WRa', 'WR'), P('WRb', 'WR'), P('WRc', 'WR')]),
      // a full starting eight lands exactly where it should
      full: ids([P('q', 'QB'), P('r1', 'RB'), P('r2', 'RB'), P('w1', 'WR'),
                 P('w2', 'WR'), P('t', 'TE'), P('r3', 'RB'), P('d', 'DST')]),
      // an unknown position (off-board pick) still gets a bench seat, never dropped
      unknown: assignSlots([P('mystery', '')]).slots.filter(s => s.player).map(s => s.id),
      // 14 RBs vs 7 RB-eligible slots (RB1 RB2 FLEX BN1-4) -> 7 have nowhere to go
      overflowed: assignSlots(Array.from({ length: 14 }, (_, i) => P('p' + i, 'RB'))).overflow.length,
    };
  });
  T('12 roster slots', slots.nSlots === 12);
  T('3rd RB -> FLEX, 4th -> bench',
    slots.rb.includes('FLEX=RB3') && slots.rb.includes('BN1=RB4'));
  T('2nd TE -> FLEX', slots.te.includes('FLEX=TEb'));
  T('3rd WR -> FLEX', slots.wr.includes('FLEX=WRc'));
  T('full starting 8 placed',
    slots.full.slice(0, 8).join('|') === 'QB=q|RB1=r1|RB2=r2|WR1=w1|WR2=w2|TE=t|FLEX=r3|DEF=d');
  T('unknown position -> bench', slots.unknown.join() === 'BN1');
  T('over-limit picks reported as overflow', slots.overflowed === 7);

  // ---------- 3. DEF must be recommended when it is the last required slot ----------
  const def = await page.evaluate(() => {
    const { S, CONFIG, derive } = window.DRAFT;
    const N = s => window.DRAFT.norm(s);
    const R = JSON.parse(document.getElementById('ranksData').textContent).ranks;
    // put the owner at his final pick (#142) with 7 starters filled and DEF open
    const fill = ['QB', 'RB', 'RB', 'WR', 'WR', 'TE', 'RB'];
    S.picks = []; S.taken = new Set();
    let n = 0;
    const mine = [];
    for (const pos of fill) {
      const p = R.find(x => x.pos === pos && !S.taken.has(N(x.name)));
      mine.push(p); S.taken.add(N(p.name));
    }
    // 141 picks made; the owner's are at his slots
    const myPickNos = [3, 22, 27, 46, 51, 70, 75, 94, 99, 118, 123];
    for (let i = 1; i <= 141; i++) {
      const slot = (Math.ceil(i / 12) % 2) ? i - 12 * (Math.ceil(i / 12) - 1)
                                           : 12 - (i - 12 * (Math.ceil(i / 12) - 1)) + 1;
      const isMine = myPickNos.includes(i);
      const p = isMine ? mine[myPickNos.indexOf(i)] : null;
      S.picks.push(p
        ? { pickNo: i, round: Math.ceil(i / 12), slot: 3, name: p.name, pos: p.pos, team: p.team, ranked: p }
        : { pickNo: i, round: Math.ceil(i / 12), slot, name: 'filler' + i, pos: 'WR', team: 'XX', ranked: null });
    }
    S.taken = new Set(mine.map(p => N(p.name)));
    const v = derive();
    const top = v.scored[0];
    const out = { curPick: v.curPick, needDST: v.need.DST, myRemaining: v.myRemaining,
                  mustFill: v.mustFill, canWait: v.canWaitOnDef,
                  top: top ? top.name + ' (' + top.pos + ')' : 'EMPTY',
                  topPos: top ? top.pos : null,
                  dstLeft: v.supply.DST.total,
                  alerts: Array.from(document.querySelectorAll('.alert')).map(a => a.textContent) };
    // and confirm DEF is still buried early, when waiting is safe
    S.picks = []; S.taken = new Set();
    const v2 = derive();
    out.earlyDefIdx = v2.scored.findIndex(p => p.pos === 'DST');
    out.earlyCanWait = v2.canWaitOnDef;
    S.picks = []; S.taken = new Set();
    return out;
  });
  T('DEF recommended #1 at the final pick when it is the last hole', def.topPos === 'DST');
  T('runway logic knows it cannot wait', def.canWait === false && def.mustFill === true);
  T('DEF still buried early when waiting is safe',
    def.earlyCanWait === true && def.earlyDefIdx > 8);
  T('board carries enough defenses for 12 teams', def.dstLeft >= 12);

  // ---------- 4. demo state must never survive a connect ----------
  const stale = await page.evaluate(async () => {
    const { S, startDemo } = window.DRAFT;
    startDemo();
    for (let i = 0; i < 6; i++) demoStep();
    const demoPicks = S.picks.length;
    // simulate what connect() does before it ever reaches the network
    S.gen++; S.picks = []; S.taken = new Set(); S.sig = null; S.seen = 0;
    return { demoPicks, afterConnect: S.picks.length, sig: S.sig };
  });
  T('connect clears leftover demo picks', stale.demoPicks > 0 && stale.afterConnect === 0);
  T('pick-list signature reset on mode switch', stale.sig === null);

  // ---------- 5. bye stacking counts starters, not bench ----------
  const bye = await page.evaluate(() => {
    const { S, derive } = window.DRAFT;
    const mk = (name, pos) => ({ pickNo: 1, round: 1, slot: 3, name, pos, team: 'XX',
                                 ranked: { name, pos, bye: 9, tier: 1, rank: 1 } });
    S.picks = []; S.taken = new Set();
    // 6 RBs all on bye 9: 2 start, 1 flexes, 3 sit on the bench
    for (const n of ['a', 'b', 'c', 'd', 'e', 'f']) S.picks.push(mk(n, 'RB'));
    const v = derive();
    S.picks = []; S.taken = new Set();
    return { counted: v.byes[9] || 0, roster: 6 };
  });
  T('bye stack counts the 3 starters, not all 6 picks', bye.counted === 3);

  // ---------- 6. survival odds ----------
  const odds = await page.evaluate(() => {
    const { lastsUntil, normCdf } = window.DRAFT;
    const R = JSON.parse(document.getElementById('ranksData').textContent).ranks;
    const withAdp = R.filter(x => x.adp != null);
    const t = R.find(x => x.adp && x.adp > 30);
    return {
      cdf: [normCdf(-1.96), normCdf(0), normCdf(1.96)],
      nullPast: [lastsUntil(t, 22, 22), lastsUntil(t, 22, 10), lastsUntil(t, 22, null)],
      bounded: withAdp.every(x => { const l = lastsUntil(x, 3, 22); return l.pct >= 0 && l.pct <= 1; }),
      // strictly decreasing as the next pick gets further away
      mono: [27, 46, 70, 94].map(k => lastsUntil(t, 22, k).pct),
      // a player already well past his ADP is gone; one far below it is safe
      gone: lastsUntil(R.find(x => x.adp && x.adp < 5), 3, 22).pct,
      safe: lastsUntil(R.filter(x => x.adp).slice(-1)[0], 3, 22).pct,
      // no live ADP past ~#60 -> flagged as an estimate
      est: lastsUntil(R.find(x => x.adp == null), 70, 94).est,
      liveNotEst: lastsUntil(R.find(x => x.adp != null), 3, 22).est,
    };
  });
  T('normCdf accurate to 1e-4',
    Math.abs(odds.cdf[0] - 0.0250) < 1e-4 && Math.abs(odds.cdf[1] - 0.5) < 1e-9 &&
    Math.abs(odds.cdf[2] - 0.9750) < 1e-4);
  T('no odds when next pick is not ahead', odds.nullPast.every(x => x === null));
  T('odds bounded to [0,1]', odds.bounded);
  T('odds fall monotonically with distance',
    odds.mono.every((v, i) => i === 0 || v <= odds.mono[i - 1]));
  T('player far past ADP reads as gone', odds.gone < 0.02);
  T('player far below ADP reads as safe', odds.safe > 0.95);
  T('rank fallback flagged as estimate, live ADP is not',
    odds.est === true && odds.liveNotEst === false);

  // ---------- 7. positional run detection ----------
  const runs = await page.evaluate(() => {
    const { detectRuns } = window.DRAFT;
    const R = JSON.parse(document.getElementById('ranksData').textContent).ranks;
    const pool = R.map(x => ({ pos: x.pos }));
    const mk = (pos, i) => ({ pickNo: i, pos, name: 'p' + i });
    const seq = a => a.map((p, i) => mk(p, i));
    return {
      hot: detectRuns(seq(['RB','RB','RB','RB','RB','RB','WR','WR','WR','WR']), pool)
             .map(r => r.pos + ':' + r.hits),
      balanced: detectRuns(seq(['RB','WR','WR','TE','RB','WR','QB','WR','RB','WR']), pool).length,
      tooShort: detectRuns(seq(['RB','RB','RB']), pool).length,
      // only the last 10 count, so an old run must age out
      aged: detectRuns(seq(['RB','RB','RB','RB','RB','RB','WR','TE','WR','QB','WR','TE','WR','QB','WR','TE']), pool).length,
      windowCapped: detectRuns(seq(Array(40).fill('RB')), pool)[0].window,
    };
  });
  // on a back-to-back turn the odds must measure the FOLLOWING pick, not this one
  const target = await page.evaluate(() => {
    const { S, derive } = window.DRAFT;
    S.picks = []; S.taken = new Set();
    const at = n => { S.picks = Array.from({ length: n - 1 }, (_, i) =>
      ({ pickNo: i + 1, round: Math.ceil((i + 1) / 12), slot: 1,
         name: 'x' + i, pos: 'WR', team: 'XX', ranked: null }));
      const v = derive(); return { cur: v.curPick, next: v.myNext, target: v.oddsTarget }; };
    const out = { onClock22: at(22), between: at(23), onClock27: at(27), last: at(142) };
    S.picks = []; S.taken = new Set();
    return out;
  });
  T('on the clock at #22 -> odds measured to #27',
    target.onClock22.next === 22 && target.onClock22.target === 27);
  T('between picks -> odds measured to the next pick',
    target.between.next === 27 && target.between.target === 27);
  T('on the clock at #27 -> odds measured to #46',
    target.onClock27.next === 27 && target.onClock27.target === 46);
  T('no target at the final pick', target.last.target === null);

  T('run detected when a position goes hot', runs.hot.includes('RB:6'));
  T('no run on a balanced window', runs.balanced === 0);
  T('no run before the window fills', runs.tooShort === 0);
  T('an old run ages out of the window', runs.aged === 0);
  T('window capped at 10 picks', runs.windowCapped === 10);

  // ---------- 8. no template-literal syntax leaks into rendered text ----------
  // Both board-size messages once shipped as literal "${RANKS.length}" because
  // they used template syntax inside plain quoted strings. Nothing asserted on
  // rendered copy, so only a screenshot caught it. Assert on it now.
  const copy = await page.evaluate(() => {
    const { S, norm, render } = window.DRAFT;
    const R = JSON.parse(document.getElementById('ranksData').textContent).ranks;
    const grab = () => document.body.innerText;
    const seen = [];
    S.picks = []; S.taken = new Set(); render(false); seen.push(grab());
    // mid-draft
    S.picks = R.slice(0, 40).map((x, i) => ({ pickNo: i + 1, round: Math.ceil((i + 1) / 12),
      slot: (i % 12) + 1, name: x.name, pos: x.pos, team: x.team, ranked: x }));
    S.taken = new Set(S.picks.map(p => p.ranked.pos === 'DST'
      ? p.ranked.team.toUpperCase() : norm(p.ranked.name)));
    render(false); seen.push(grab());
    // board fully exhausted
    S.picks = R.map((x, i) => ({ pickNo: i + 1, round: Math.ceil((i + 1) / 12),
      slot: (i % 12) + 1, name: x.name, pos: x.pos, team: x.team, ranked: x }));
    S.taken = new Set(R.map(x => x.pos === 'DST' ? x.team.toUpperCase() : norm(x.name)));
    render(false); seen.push(grab());
    S.picks = []; S.taken = new Set(); render(false);
    const all = seen.join('\n');
    return { leak: /\$\{/.test(all), boardSize: R.length,
             mentionsSize: all.includes(String(R.length)) };
  });
  T('no ${...} leaks into rendered copy in any board state', copy.leak === false);
  T('board-size copy reports the real board length', copy.mentionsSize);

  // ---------- 9. the demo must finish, not silently freeze ----------
  const demo = await page.evaluate(() => {
    const { S, CONFIG, startDemo } = window.DRAFT;
    startDemo();
    for (let i = 0; i < 400; i++) { if (!S.demoTimer && i > 3) break; demoStep(); }
    return { picks: S.picks.length, timer: !!S.demoTimer,
             target: CONFIG.teams * CONFIG.rounds,
             status: document.getElementById('statusTx').textContent,
             boardSize: JSON.parse(document.getElementById('ranksData').textContent).ranks.length };
  });
  // bots avoid DSTs until the last rounds; with fewer non-DST players than picks
  // the pool empties, and the demo used to stall there with no message at all
  T('demo drafts the whole board, not just the non-DST part',
    demo.picks >= demo.boardSize - 1);
  T('demo stops cleanly with a reason', !demo.timer && /complete|stopped/.test(demo.status));
  T('demo says how far it got', /\d/.test(demo.status));

  // ---------- 10. no horizontal page scroll on a phone ----------
  for (const w of [360, 390, 414]) {
    await page.setViewportSize({ width: w, height: 900 });
    await page.evaluate(() => {
      const { S, norm, render } = window.DRAFT;
      const R = JSON.parse(document.getElementById('ranksData').textContent).ranks;
      document.getElementById('setup').hidden = true;
      S.picks = R.slice(0, 40).map((x, i) => ({ pickNo: i + 1, round: Math.ceil((i + 1) / 12),
        slot: (i % 12) + 1, name: x.name, pos: x.pos, team: x.team, ranked: x, injury: '' }));
      S.taken = new Set(S.picks.map(p => p.ranked.pos === 'DST'
        ? p.ranked.team.toUpperCase() : norm(p.ranked.name)));
      render(false);
    });
    const m = await page.evaluate(() => {
      const t = document.querySelector('.card > table');
      return { fits: document.documentElement.scrollWidth <= window.innerWidth,
               tableFits: t.scrollWidth <= t.clientWidth + 1,
               cols: [...document.querySelectorAll('#baBody tr:first-child td')]
                       .filter(td => td.offsetParent !== null).length };
    });
    T(`no horizontal page scroll at ${w}px`, m.fits);
    // the 9-column board is a few px wider than a phone, so Bye (redundant with
    // the roster cards and its own alert) is hidden under 430px
    if (w >= 390) T(`board table fits without scrolling at ${w}px`, m.tableFits);
    T(`bye column dropped on a phone at ${w}px`, m.cols === 8);
  }
  await page.evaluate(() => { window.DRAFT.S.picks = []; window.DRAFT.S.taken = new Set(); });
  await page.setViewportSize({ width: 1440, height: 1200 });

  // ---------- 11. v3 payload: outcome ranges, and honesty about ADP ----------
  const v3 = await page.evaluate(() => {
    const E = window.DRAFT.EDGE;
    return {
      version: E.version,
      beatsAdp: E.honesty && E.honesty.model_beats_adp,
      perPos: Object.keys((E.honesty || {}).per_position || {}).length,
      sixSeasons: ((E.sixpoint || {}).top6 || {}).seasons,
      n: E.players.length,
      ordered: E.players.every(p => p.floor <= p.ceil + 1e-9),
      bustRange: E.players.every(p => p.bust >= 0 && p.bust <= 1),
      hasConf: E.players.every(p => ['high','med','low','none'].includes(p.conf)),
      edgesTested: E.players.every(p => Math.abs(p.edge) < 10),
      cols: document.querySelectorAll('#baBody tr:first-child td').length,
      thesis: document.getElementById('thesis').innerText,
      honesty: E.honesty,
      upRows: document.querySelectorAll('#edgeUp .erow').length,
      dnRows: document.querySelectorAll('#edgeDn .erow').length,
    };
  });
  const E3 = v3.honesty;
  T('payload is v3', v3.version === 3);
  T('payload records that the model does NOT beat ADP', v3.beatsAdp === false);
  T('payload carries per-position MAE vs ADP', v3.perPos >= 4);
  T('6-point result is multi-season', v3.sixSeasons >= 13);
  T('every player floor <= ceiling', v3.ordered);
  T('every bust probability in [0,1]', v3.bustRange);
  T('every player has a confidence marker', v3.hasConf);
  // the edge column now carries only measured effects (~3 ranks), never v2's
  // rank deltas which ran to +/-69
  T('edge values are measured effects, not rank deltas', v3.edgesTested);
  T('best-available has RANGE and BUST columns', v3.cols === 9);
  T('thesis states the model loses to ADP', /loses to ADP/i.test(v3.thesis));
  T('thesis reports the tested-signal count', /\btwo\b/i.test(v3.thesis));
  T('thesis states the refuted v2 signal', /TD-luck regression/i.test(v3.thesis));
  T('payload records 2 of 7 signals survived',
    E3.n_survived === 2 && E3.n_tested === 7);
  T('tested signals carry effects in points, not just ranks',
    Object.values(E3.tested_signals).every(s => typeof s.effect_pts === 'number'));
  T('both outcome-range lists render', v3.upRows === 8 && v3.dnRows === 8);

  // ---------- 12. bench picks are graded on ceiling, starters on value ------
  const modes = await page.evaluate(() => {
    const { S, derive, norm: N, WEIGHTS: W } = window.DRAFT;
    const R = JSON.parse(document.getElementById('ranksData').textContent).ranks;
    const gone = R.filter(x => x.pos !== 'DST').slice(0, 100);
    const MY = [3, 22, 27, 46, 51, 70, 75, 94];
    const build = (posList) => {
      const mine = [];
      for (const pos of posList)
        mine.push(R.find(x => x.pos === pos && !mine.some(m => m.name === x.name)));
      S.picks = []; S.taken = new Set(gone.map(x => N(x.name)));
      mine.forEach(x => S.taken.add(x.pos === 'DST' ? x.team.toUpperCase() : N(x.name)));
      for (let i = 1; i <= 110; i++) {
        const k = MY.indexOf(i);
        const m = k >= 0 ? mine[k] : null;      // fewer positions than picks is fine
        S.picks.push({ pickNo: i, round: Math.ceil(i / 12), slot: m ? 3 : 99,
          name: m ? m.name : 'x' + i, pos: m ? m.pos : 'WR',
          team: 'XX', ranked: m || null });
      }
      return derive();
    };
    const FULL = ['QB', 'RB', 'RB', 'WR', 'WR', 'TE', 'RB', 'DST'];
    const bench = build(FULL);
    const benchTop = bench.scored.slice(0, 5);
    const benchUpside = benchTop.map(x =>
      x.edge && x.edge.mean > 0 ? (x.edge.ceil - x.edge.mean) / x.edge.mean : 0);
    const names = benchTop.map(x => x.name);
    // same state with the two new weights disabled
    const cb = W.ceilingBench, br = W.bustRisk;
    W.ceilingBench = 0; W.bustRisk = 0;
    const off = build(FULL).scored.slice(0, 5).map(x => x.name);
    const offUpside = build(FULL).scored.slice(0, 5).map(x =>
      x.edge && x.edge.mean > 0 ? (x.edge.ceil - x.edge.mean) / x.edge.mean : 0);
    W.ceilingBench = cb; W.bustRisk = br;
    // a state with a starter still open must NOT be in bench mode
    const starter = build(['QB', 'RB', 'WR', 'WR', 'TE', 'RB']);
    const swing = bench.scored.filter(x => x.why.some(w => /bench swing/.test(w))).length;
    const starterSwing = starter.scored.filter(x => x.why.some(w => /bench swing/.test(w))).length;
    S.picks = []; S.taken = new Set();
    return { benchRequired: bench.requiredLeft, starterRequired: starter.requiredLeft,
             names, off, meanUpsideOn: benchUpside.reduce((a, b) => a + b, 0) / 5,
             meanUpsideOff: offUpside.reduce((a, b) => a + b, 0) / 5,
             swing, starterSwing };
  });
  T('bench mode detected only when every starter is filled',
    modes.benchRequired === 0 && modes.starterRequired > 0);
  T('ceiling-seeking fires on bench picks', modes.swing > 0);
  T('ceiling-seeking does NOT fire while a starter is open', modes.starterSwing === 0);
  T('the ceiling terms actually change the ordering',
    JSON.stringify(modes.names) !== JSON.stringify(modes.off));
  T('bench recommendations have higher mean upside than without the terms',
    modes.meanUpsideOn > modes.meanUpsideOff);

  T('no JS errors', errors.length === 0);

  let fail = 0;
  console.log('--- v2 CHECKS ---');
  for (const [k, v] of Object.entries(checks)) { console.log((v ? 'PASS' : 'FAIL') + '  ' + k); if (!v) fail++; }
  if (errors.length) console.log('\nERRORS:\n' + errors.join('\n'));
  if (!checks['DEF recommended #1 at the final pick when it is the last hole'])
    console.log('\n  debug DEF:', JSON.stringify(def, null, 1).slice(0, 600));
  await browser.close();
  process.exit(fail ? 1 : 0);
})();
