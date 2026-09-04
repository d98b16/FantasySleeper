const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 1150 } });

  const errors = [];
  page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('CONSOLE: ' + m.text()); });

  await page.goto('file://' + path.resolve('index.html'));
  await page.waitForTimeout(400);

  // --- unit-check the snake math against the known truth from the spreadsheet
  const snake = await page.evaluate(() => {
    const { CONFIG } = window.DRAFT;
    CONFIG.teams = 12; CONFIG.mySlot = 3; CONFIG.rounds = 12;
    const out = [];
    for (let rd = 1; rd <= CONFIG.rounds; rd++)
      out.push((rd % 2) ? 12*(rd-1)+3 : 12*rd-3+1);
    return out;
  });
  const expected = [3,22,27,46,51,70,75,94,99,118,123,142];  // CONTEXT.md, 12 rounds
  const snakeOK = JSON.stringify(snake) === JSON.stringify(expected);
  console.log('snake picks:', snake.join(','));
  console.log('snake math matches spreadsheet:', snakeOK);

  // --- name matching sanity
  const match = await page.evaluate(() => {
    const t = (f,l) => {
      const n = (f+' '+l).toLowerCase().replace(/[.'’-]/g,' ')
        .replace(/\b(jr|sr|ii|iii|iv|v)\b/g,' ').replace(/[^a-z0-9]/g,'');
      return n;
    };
    const D = JSON.parse(document.getElementById('ranksData').textContent);
    const set = new Set(D.ranks.filter(p=>p.pos!=='DST').map(p =>
      p.name.toLowerCase().replace(/[.'’-]/g,' ').replace(/\b(jr|sr|ii|iii|iv|v)\b/g,' ').replace(/[^a-z0-9]/g,'')));
    const cases = [["Ja'Marr","Chase"],["Jaxon","Smith-Njigba"],["Amon-Ra","St. Brown"],
                   ["Kenneth","Walker III"],["Michael","Pittman Jr."],["Travis","Etienne Jr."],
                   ["Deebo","Samuel Sr."],["Brock","Bowers"],["Jahmyr","Gibbs"]];
    return cases.map(([f,l]) => [f+' '+l, set.has(t(f,l))]);
  });
  const allMatch = match.every(m => m[1]);
  console.log('name matching:', match.map(m => `${m[0]}=${m[1]?'OK':'FAIL'}`).join(' | '));

  // --- run the demo draft
  await page.click('#demoBtn');
  await page.waitForTimeout(1000);
  await page.evaluate(() => {                      // fast-forward: 34 picks
    for (let i = 0; i < 34; i++) window.DRAFT && demoStep();
  }).catch(async () => {
    await page.evaluate(() => { for (let i=0;i<34;i++) window.dispatchEvent(new Event('x')); });
  });
  await page.waitForTimeout(1200);

  const state = await page.evaluate(() => {
    const v = window.DRAFT.derive();
    return {
      picks: window.DRAFT.S.picks.length,
      curPick: v.curPick, round: v.rd, until: v.until, myNext: v.myNext,
      mine: v.mine.map(p => `R${p.round} ${p.pos} ${p.name}`),
      have: v.have, need: v.need,
      avail: v.avail.length,
      boardSize: JSON.parse(document.getElementById('ranksData').textContent).ranks.length,
      top3: v.scored.slice(0,3).map(p => `${p.name} (${p.pos}, score ${Math.round(p.score)})`),
      supplyRB: v.supply.RB, supplyWR: v.supply.WR,
      feedCount: document.querySelectorAll('.fitem').length,
      baRows: document.querySelectorAll('#baBody tr').length,
      alerts: Array.from(document.querySelectorAll('.alert')).map(a => a.textContent.trim()),
    };
  });

  console.log('\n--- STATE AFTER SIMULATED PICKS ---');
  console.log('picks made:', state.picks, '| current pick:', state.curPick, '| round:', state.round);
  console.log('my roster:', state.mine.length ? state.mine.join(' | ') : '(none)');
  console.log('have:', JSON.stringify(state.have), 'need:', JSON.stringify(state.need));
  console.log('board left:', state.avail, '| next my pick:', state.myNext, '| until:', state.until);
  console.log('top recommendations:', state.top3.join('  //  '));
  console.log('RB supply:', JSON.stringify(state.supplyRB));
  console.log('alerts:', state.alerts.length ? state.alerts.join(' ~ ') : '(none)');
  console.log('rendered rows — feed:', state.feedCount, 'bestAvail:', state.baRows);

  await page.screenshot({ path: 'console_shot.png', fullPage: false });

  // --- assertions
  const checks = {
    'snake math correct': snakeOK,
    'all name variants match': allMatch,
    'picks were made': state.picks >= 30,
    'board shrank by picks made': state.avail === state.boardSize - state.picks,
    'my roster populated': state.mine.length >= 2,
    'recommendations present': state.top3.length === 3,
    'feed rendered': state.feedCount > 0,
    'best-available rendered': state.baRows === 8,
    'no JS errors': errors.length === 0,
  };
  console.log('\n--- CHECKS ---');
  let fail = 0;
  for (const [k,v] of Object.entries(checks)){ console.log((v?'PASS':'FAIL') + '  ' + k); if(!v) fail++; }
  if (errors.length) console.log('\nERRORS:\n' + errors.join('\n'));
  await browser.close();
  process.exit(fail ? 1 : 0);
})();
