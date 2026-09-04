const { chromium } = require('playwright');
const path = require('path');
(async () => {
  const b = await chromium.launch(); const page = await b.newPage();
  await page.goto('file://' + path.resolve('draft_console.html'));
  await page.waitForTimeout(250);
  const r = await page.evaluate(() => {
    const {S, CONFIG, derive} = window.DRAFT;
    const N = (s)=>s.toLowerCase().replace(/[.'’-]/g,' ').replace(/\b(jr|sr|ii|iii|iv|v)\b/g,' ').replace(/[^a-z0-9]/g,'');
    const at = (picksMade) => {
      S.picks=[]; S.taken=new Set();
      const pool = derive().scored.filter(p=>p.pos!=='DST');
      for(let i=0;i<picksMade && i<pool.length;i++){
        const p=pool[i];
        S.picks.push({pickNo:i+1,round:Math.ceil((i+1)/CONFIG.teams),slot:1,name:p.name,pos:p.pos,team:p.team,ranked:p});
        S.taken.add(N(p.name));
      }
      const v=derive(), sc=v.scored;
      return {round:v.rd, made:S.picks.length, boardLeft:v.avail.length,
              defIdx:sc.findIndex(p=>p.pos==='DST'), top:sc[0]?`${sc[0].name} (${sc[0].pos})`:'EMPTY'};
    };
    const out=[at(12),at(60),at(108),at(117)];
    S.picks=[];S.taken=new Set();
    return out;
  });
  console.log('picksMade  round  boardLeft  DEFindex  topRec');
  r.forEach(x=>console.log(String(x.made).padStart(9),String(x.round).padStart(6),String(x.boardLeft).padStart(10),String(x.defIdx).padStart(9),'  '+x.top));
  const gated = r.filter(x=>x.round<12 && x.boardLeft>3).every(x=>x.defIdx>3);
  console.log('\nDEF correctly buried while board has depth:', gated);
  console.log('NOTE board depth: 120 ranked players vs 144 total picks in a 12x12 draft.');
  await b.close(); process.exit(gated?0:1);
})();
