/* test_def.js — DEF gating.
   DEF is a REQUIRED starter in this league but there are only 12 rounds, so the
   board must do two opposite things correctly:
     (a) bury DEF while the owner still has enough picks left to fill every hole
         AND take a defense  -- otherwise it burns a real pick on a streamer;
     (b) surface DEF the moment that runway is gone -- otherwise the owner ends
         the draft with an empty required slot, which is the worse failure.
   The old version of this test drove an owner who had drafted NOTHING through
   108 picks, which is permanent panic mode, and so only ever tested (a). */
const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const b = await chromium.launch();
  const page = await b.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('file://' + path.resolve('index.html'));
  await page.waitForTimeout(250);

  const rows = await page.evaluate(() => {
    const { S, CONFIG, derive, norm } = window.DRAFT;
    const MY = [3, 22, 27, 46, 51, 70, 75, 94, 99, 118, 123, 142];
    const slotOf = n => { const rd = Math.ceil(n / 12), i = n - 12 * (rd - 1);
                          return (rd % 2) ? i : (12 - i + 1); };

    /* Replay a realistic draft: everyone (the owner included) takes the board's
       own top recommendation, so the owner's roster fills at a normal rate. */
    const upTo = made => {
      S.picks = []; S.taken = new Set();
      for (let n = 1; n <= made; n++) {
        const v = derive();
        const pick = v.scored[0];
        if (!pick) break;
        S.picks.push({ pickNo: n, round: Math.ceil(n / 12), slot: slotOf(n),
                       name: pick.name, pos: pick.pos, team: pick.team, ranked: pick });
        S.taken.add(pick.pos === 'DST' ? pick.team.toUpperCase() : norm(pick.name));
      }
      const v = derive();
      return { made, round: v.rd, boardLeft: v.avail.length,
               myPicks: v.mine.length, myRemaining: v.myRemaining,
               requiredLeft: v.requiredLeft, canWait: v.canWaitOnDef,
               defIdx: v.scored.findIndex(p => p.pos === 'DST'),
               dstLeft: v.supply.DST.total,
               nonDstLeft: v.avail.filter(p => p.pos !== 'DST').length,
               top: v.scored[0] ? `${v.scored[0].name} (${v.scored[0].pos})` : 'EMPTY' };
    };
    // stop just before each of the owner's picks
    const out = [2, 21, 45, 69, 98, 117, 122].map(n => upTo(n));

    /* The final-pick case cannot come from this replay: 12 teams x 12 rounds is
       144 picks against a 129-player board, so a replay where everyone follows
       our board runs the board dry before pick 142. Build that state directly. */
    S.picks = []; S.taken = new Set();
    const R = JSON.parse(document.getElementById('ranksData').textContent).ranks;
    const mine = [];
    for (const pos of ['QB','RB','RB','WR','WR','TE','RB'])
      mine.push(R.find(x => x.pos === pos && !mine.includes(x)));
    const MYNOS = [3,22,27,46,51,70,75,94,99,118,123];
    for (let n = 1; n <= 141; n++) {
      const i = MYNOS.indexOf(n), p = i >= 0 && i < mine.length ? mine[i] : null;
      S.picks.push(p
        ? { pickNo:n, round:Math.ceil(n/12), slot:3, name:p.name, pos:p.pos, team:p.team, ranked:p }
        : { pickNo:n, round:Math.ceil(n/12), slot:slotOf(n), name:'x'+n, pos:'WR', team:'XX', ranked:null });
    }
    S.taken = new Set(mine.map(p => norm(p.name)));
    const vf = derive();
    out.push({ made:141, round:vf.rd, boardLeft:vf.avail.length, myPicks:vf.mine.length,
               myRemaining:vf.myRemaining, requiredLeft:vf.requiredLeft, canWait:vf.canWaitOnDef,
               defIdx:vf.scored.findIndex(p=>p.pos==='DST'), dstLeft:vf.supply.DST.total,
               nonDstLeft:vf.avail.filter(p=>p.pos!=='DST').length,
               top:vf.scored[0] ? `${vf.scored[0].name} (${vf.scored[0].pos})` : 'EMPTY', built:true });
    S.picks = []; S.taken = new Set();
    return out;
  });

  console.log(' made  rd  left  nonDST  mine  myRem  reqLeft  canWait  DEFidx  top');
  rows.forEach(r => console.log(
    String(r.made).padStart(5), String(r.round).padStart(3), String(r.boardLeft).padStart(5),
    String(r.nonDstLeft).padStart(7), String(r.myPicks).padStart(5), String(r.myRemaining).padStart(6),
    String(r.requiredLeft).padStart(8), String(r.canWait).padStart(8),
    String(r.defIdx).padStart(7), '  ' + r.top + (r.built ? '   [constructed]' : '')));

  // (a) while there is genuine runway AND real players remain, DEF stays buried.
  //     Checkpoints where only defenses are left prove nothing about gating.
  const early = rows.filter(r => r.canWait && r.nonDstLeft > 5);
  const buriedEarly = early.length >= 4 && early.every(r => r.defIdx > 5);
  // (b) at the owner's final pick, DEF is the only hole left and must lead
  const last = rows[rows.length - 1];
  const surfacesLate = !last.canWait && last.defIdx === 0;
  // the board must hold enough defenses that 12 teams can all draft one
  const enoughDefenses = rows[0].dstLeft >= 12;

  console.log('\nDEF buried while runway exists and real players remain ('
    + early.length + ' checkpoints):', buriedEarly);
  console.log('DEF surfaces at the final pick:', surfacesLate, '| top there:', last.top);
  console.log('board carries >=12 defenses:', enoughDefenses, '(' + rows[0].dstLeft + ')');
  console.log('no JS errors:', errors.length === 0);

  const ok = buriedEarly && surfacesLate && enoughDefenses && !errors.length;
  if (!ok && errors.length) console.log('ERRORS:', errors.join('\n'));
  await b.close();
  process.exit(ok ? 0 : 1);
})();
