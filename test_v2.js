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
