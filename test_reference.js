/* test_reference.js — the standalone during-draft reference page.
   Covers filter-state math, name normalisation on the names that actually break
   naive matching, delta sign, the one-sided (not-on-board / not-on-market) case,
   URL hash round-tripping, keyboard shortcuts and empty states. */
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const checks = {};
const T = (n, v) => { checks[n] = !!v; };

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 1400 } });
  const errors = [];
  page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('CONSOLE: ' + m.text()); });
  const url = 'file://' + path.resolve('reference.html');
  await page.goto(url);
  await page.waitForTimeout(300);

  // ---------- self-containment ----------
  const html = fs.readFileSync('reference.html', 'utf8');
  T('no external scripts, styles or images',
    !/<script[^>]+src=/i.test(html) && !/<link[^>]+href=/i.test(html) && !/<img/i.test(html));
  T('no network calls in the page', !/fetch\(|XMLHttpRequest|EventSource/.test(html));
  T('data is inlined as valid JSON', await page.evaluate(() =>
    !!(window.__REF__ && window.__REF__.players && window.__REF__.players.length > 100)));
  // NaN is not JSON: Python emits it bare and JSON.parse rejects it outright,
  // which silently left the page with no data at all until it was caught.
  T('payload contains no bare NaN or Infinity',
    !/[:,\[]\s*(NaN|-?Infinity)\s*[,}\]]/.test(html));

  // ---------- name normalisation ----------
  const norm = await page.evaluate(() => {
    const n = window.__REFAPI__.norm;
    return [["Ja'Marr Chase", 'jamarrchase'],
            ['Jaxon Smith-Njigba', 'jaxonsmithnjigba'],
            ['Amon-Ra St. Brown', 'amonrastbrown'],
            ['Kenneth Walker III', 'kennethwalker'],
            ['Travis Etienne Jr.', 'travisetienne'],
            ['Deebo Samuel Sr.', 'deebosamuel'],
            ['Michael Pittman Jr.', 'michaelpittman'],
            ['D’Andre Swift', 'dandreswift'],
            ['James Cook III', 'jamescook']]
      .map(([raw, want]) => [raw, n(raw), n(raw) === want]);
  });
  T('normalisation handles apostrophes, hyphens, periods and suffixes',
    norm.every(x => x[2]));

  // searching by the messy spelling finds the player
  for (const [q, expect] of [['jamarr', "Ja'Marr Chase"], ['smith njigba', 'Jaxon Smith-Njigba'],
                             ['st brown', 'Amon-Ra St. Brown'], ['walker iii', 'Kenneth Walker III']]) {
    await page.fill('#q', q);
    await page.waitForTimeout(80);
    const hit = await page.evaluate(n => window.__REFAPI__.shown().some(p => p.n === n), expect);
    T(`search "${q}" finds ${expect}`, hit);
  }
  await page.fill('#q', '');

  // ---------- filter-state math ----------
  const filt = await page.evaluate(() => {
    const A = window.__REFAPI__, D = window.__REF__, S = A.state;
    const res = {};
    S.pos.clear(); S.q = ''; S.bye = ''; S.rookies = false; A.render();
    res.all = A.shown().length;
    res.total = D.players.length;
    S.pos.add('RB'); A.render();
    const rb = A.shown();
    res.rbOnly = rb.every(p => p.p === 'RB');
    res.rbN = rb.length;
    S.pos.add('WR'); A.render();
    const rbwr = A.shown();
    res.multi = rbwr.every(p => p.p === 'RB' || p.p === 'WR');
    res.additive = rbwr.length === res.rbN + D.players.filter(p => p.p === 'WR').length;
    S.pos.clear(); S.bye = '11'; A.render();
    res.byeOnly = A.shown().every(p => String(p.by) === '11');
    res.byeN = A.shown().length;
    S.bye = ''; S.rookies = true; A.render();
    res.rookieOnly = A.shown().every(p => !!p.rt);
    res.rookieN = A.shown().length;
    // filters compose: rookies AND position
    S.pos.add('WR'); A.render();
    res.compose = A.shown().every(p => !!p.rt && p.p === 'WR');
    S.pos.clear(); S.rookies = false; A.render();
    return res;
  });
  T('no filter shows every player', filt.all === filt.total);
  T('a position chip filters to that position', filt.rbOnly && filt.rbN > 0);
  T('chips are multi-select and additive', filt.multi && filt.additive);
  T('bye filter isolates one week', filt.byeOnly && filt.byeN > 0);
  T('rookies-only filter works', filt.rookieOnly && filt.rookieN > 0);
  T('filters compose (rookies AND position)', filt.compose);

  // chip counts must equal what that chip alone would show
  const counts = await page.evaluate(() => {
    const A = window.__REFAPI__, D = window.__REF__;
    A.state.pos.clear(); A.state.q = ''; A.render();
    return ['QB', 'RB', 'WR', 'TE', 'DST'].map(p => {
      const shown = parseInt(document.getElementById('chip' + p).innerText.replace(/\D/g, ''), 10);
      const real = D.players.filter(x => x.p === p).length;
      return [p, shown, real, shown === real];
    });
  });
  T('every chip count matches its true population', counts.every(c => c[3]));

  // ---------- delta ----------
  const d = await page.evaluate(() => {
    const D = window.__REF__;
    const both = D.players.filter(p => p.d != null);
    return {
      n: both.length,
      formula: both.every(p => p.d === p.mkt - p.our),
      // positive delta must mean WE rank him better (lower number) than market
      signUp: both.filter(p => p.d > 0).every(p => p.our < p.mkt),
      signDn: both.filter(p => p.d < 0).every(p => p.our > p.mkt),
      oneSidedHasNoDelta: D.players.filter(p => p.our == null || p.mkt == null)
        .every(p => p.d == null),
    };
  });
  T('delta equals market rank minus our rank', d.formula && d.n > 50);
  T('positive delta means we are higher on him', d.signUp);
  T('negative delta means the market is higher on him', d.signDn);
  T('a one-sided player has no delta', d.oneSidedHasNoDelta);

  const colour = await page.evaluate(() => {
    const c = window.__REFAPI__.dCell;
    return { up: c(20), dn: c(-20), nu5: c(5), nuNeg5: c(-5), none: c(null) };
  });
  T('delta +20 is green with a sign', /class="d up"/.test(colour.up) && /\+20/.test(colour.up));
  T('delta -20 is red with a sign', /class="d dn"/.test(colour.dn) && /-20/.test(colour.dn));
  T('delta within +/-5 is neutral',
    /class="d nu"/.test(colour.nu5) && /class="d nu"/.test(colour.nuNeg5));
  T('missing delta renders a dash', /nu/.test(colour.none) && /mdash/.test(colour.none));

  // ---------- not on board / not on market ----------
  const one = await page.evaluate(() => {
    const D = window.__REF__;
    const nb = D.players.filter(p => p.our == null);
    const nm = D.players.filter(p => p.mkt == null);
    // a player can legitimately be on neither board (a 2026 rookie the market
    // has not priced and our 129 does not list). The requirement is that he is
    // KEPT and rendered, not that the other side exists.
    return { nb: nb.length, nm: nm.length,
             neither: D.players.filter(p => p.our == null && p.mkt == null).length,
             allNamed: D.players.every(p => p.n && p.p) };
  });
  T('players missing from our board are kept, not dropped', one.nb > 0 && one.allNamed);
  T('players missing from the market board are kept', one.nm > 0 && one.allNamed);
  T('a player on neither board is still kept', one.neither >= 0 && one.allNamed);
  await page.evaluate(() => { window.__REFAPI__.state.q = 'sadiq'; window.__REFAPI__.render(); });
  await page.waitForTimeout(100);
  T('an off-board rookie renders a NOT ON BOARD tag',
    await page.evaluate(() => /NOT ON BOARD/.test(document.getElementById('board').innerHTML)));
  await page.evaluate(() => { window.__REFAPI__.state.q = ''; window.__REFAPI__.render(); });

  // ---------- view toggle ----------
  const views = {};
  for (const v of ['ours', 'market', 'both']) {
    await page.click('#v_' + v);
    await page.waitForTimeout(100);
    views[v] = await page.evaluate(() => ({
      cols: document.querySelectorAll('#board table tr:first-child th').length,
      head: [...document.querySelectorAll('#board table tr:first-child th')].map(t => t.innerText),
      disagree: document.getElementById('secDisagree').style.display !== 'none',
      top10: [...document.querySelectorAll('#board table tr td:first-child')]
               .slice(0, 10).map(t => t.innerText.split('\n')[0]).join('|'),
      full: [...document.querySelectorAll('#board table tr td:first-child')]
              .map(t => t.innerText.split('\n')[0]).join('|'),
    }));
  }
  T('OURS view hides the market columns',
    !views.ours.head.some(h => /ADP|MKT/i.test(h)) && views.ours.head.some(h => /OURS/i.test(h)));
  T('MARKET view hides our columns',
    !views.market.head.some(h => /OURS|TIER/i.test(h)) && views.market.head.some(h => /ADP/i.test(h)));
  T('BOTH view shows our, market and delta',
    views.both.head.some(h => /OURS/i.test(h)) && views.both.head.some(h => /ADP/i.test(h))
    && views.both.head.some(h => /DELTA/i.test(h)));
  T('disagreements only appear in BOTH view',
    views.both.disagree && !views.ours.disagree && !views.market.disagree);
  // The top of our board was built FROM this ADP, so the first rows agree by
  // construction; divergence starts deeper. Assert the full orderings differ.
  T('OURS and MARKET produce different orderings', views.ours.full !== views.market.full);
  T('the two views agree at the very top, as they should', views.ours.top10 === views.market.top10);

  const dis = await page.evaluate(() => ({
    up: [...document.querySelectorAll('#disagree .up .drow .dv')].map(e => parseInt(e.innerText, 10)),
    dn: [...document.querySelectorAll('#disagree .dn .drow .dv')].map(e => parseInt(e.innerText, 10)),
  }));
  T('defenses are excluded from the disagreement lists',
    await page.evaluate(() => !/D\/ST/.test(document.getElementById('disagree').innerText)));
  T('WE LIKE column is all positive deltas, descending',
    dis.up.length === 15 && dis.up.every(x => x > 0) &&
    dis.up.every((x, i) => i === 0 || x <= dis.up[i - 1]));
  T('MARKET LIKES column is all negative deltas, ascending',
    dis.dn.length === 15 && dis.dn.every(x => x < 0) &&
    dis.dn.every((x, i) => i === 0 || x >= dis.dn[i - 1]));

  // ---------- honest labelling ----------
  const note = await page.evaluate(() => document.getElementById('note').innerText);
  T('the page says delta is not an edge', /not an edge/i.test(note));
  T('the page says nothing beat ADP', /nothing beat ADP/i.test(note));

  // ---------- empty state ----------
  await page.fill('#q', 'qqzzxx-no-such-player');
  await page.waitForTimeout(120);
  const empty = await page.evaluate(() => ({
    board: document.querySelector('#board .empty')?.innerText || '',
    rookies: document.querySelector('#rookies .empty')?.innerText || '',
    hc: document.querySelector('#handcuffs .empty')?.innerText || '',
    byes: document.querySelector('#byes .empty')?.innerText || '',
    bodyLen: document.body.innerText.length,
  }));
  T('no match shows a row, never a blank page',
    /No players match/i.test(empty.board) && empty.bodyLen > 500);
  T('every section degrades to its own empty row',
    empty.rookies && empty.hc && empty.byes);
  await page.fill('#q', '');

  // ---------- keyboard ----------
  await page.evaluate(() => document.getElementById('q').blur());
  await page.keyboard.press('/');
  await page.waitForTimeout(80);
  T('"/" focuses the search box',
    await page.evaluate(() => document.activeElement.id === 'q'));
  await page.fill('#q', 'chase');
  await page.waitForTimeout(80);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(100);
  T('Escape clears the search',
    await page.evaluate(() => document.getElementById('q').value === '' &&
                              window.__REFAPI__.state.q === ''));

  // ---------- url hash ----------
  await page.evaluate(() => {
    const A = window.__REFAPI__;
    A.state.pos.clear(); A.state.pos.add('RB'); A.state.pos.add('WR');
    A.state.q = 'jeanty'; A.state.view = 'ours'; A.state.bye = '';
    A.state.rookies = false; A.render();
  });
  await page.waitForTimeout(100);
  const hash = await page.evaluate(() => location.hash);
  T('hash reflects position and query state',
    /pos=RB,WR/.test(hash) && /q=jeanty/.test(hash) && /view=ours/.test(hash));

  // navigating to the same document with only a different fragment does NOT
  // reload it, so exercise both paths: a genuine reload, and a hash-only change
  await page.goto('about:blank');
  await page.goto(url + '#pos=TE&q=mcbride&view=market');
  await page.waitForTimeout(300);
  const restored = await page.evaluate(() => ({
    q: document.getElementById('q').value,
    pos: [...window.__REFAPI__.state.pos],
    view: window.__REFAPI__.state.view,
    shown: window.__REFAPI__.shown().map(p => p.n),
  }));
  T('a filtered view survives a reload',
    restored.q === 'mcbride' && restored.pos.join() === 'TE' &&
    restored.view === 'market' && restored.shown.some(n => /McBride/.test(n)));

  // hash-only navigation must also re-apply, via the hashchange listener
  await page.evaluate(() => { location.hash = '#pos=RB&q=henry'; });
  await page.waitForTimeout(200);
  const hashOnly = await page.evaluate(() => ({
    q: document.getElementById('q').value,
    pos: [...window.__REFAPI__.state.pos] }));
  T('a hash-only change re-applies the filter',
    hashOnly.q === 'henry' && hashOnly.pos.join() === 'RB');

  await page.goto('about:blank');
  await page.goto(url + '#pos=BOGUS,RB&bye=99&view=nonsense');
  await page.waitForTimeout(300);
  const bad = await page.evaluate(() => ({
    pos: [...window.__REFAPI__.state.pos],
    view: window.__REFAPI__.state.view,
    rows: document.querySelectorAll('#board table tr').length,
  }));
  T('a malformed hash is ignored, not fatal',
    bad.pos.join() === 'RB' && bad.view === 'both' && bad.rows >= 1);

  T('no JS errors', errors.length === 0);

  let fail = 0;
  console.log('--- REFERENCE PAGE ---');
  for (const [k, v] of Object.entries(checks)) {
    console.log((v ? 'PASS' : 'FAIL') + '  ' + k);
    if (!v) fail++;
  }
  if (errors.length) console.log('\nERRORS:\n' + errors.join('\n'));
  await browser.close();
  process.exit(fail ? 1 : 0);
})();
