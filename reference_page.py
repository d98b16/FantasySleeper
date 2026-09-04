#!/usr/bin/env python3
"""
reference_page.py — the standalone reference page's CSS, JS and HTML shell.

Kept separate from build_reference.py so the data layer and the page template do
not have to live in one file. The page is fully self-contained: no build step, no
network, no CDN, no framework. The data is inlined as JSON and every bit of
filtering happens client-side over it.
"""
import json

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0d1117;--panel:#161b22;--panel2:#1c2430;--line:#2d3947;--tx:#e6edf3;
--dim:#93a1b0;--faint:#6b7a8a;--rb:#3fb950;--wr:#58a6ff;--qb:#f0883e;--te:#bc8cff;
--dst:#8b98a5;--bad:#f85149;--warn:#e3b341;--good:#3fb950}
body{background:var(--bg);color:var(--tx);font:16px/1.45 ui-sans-serif,system-ui,
-apple-system,"Segoe UI",Roboto,Arial,sans-serif;padding:0 14px 40px;max-width:1150px;margin:0 auto}
h1{font-size:19px;letter-spacing:-.02em}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.1em;color:var(--faint);
margin:24px 0 9px;font-weight:800;border-bottom:1px solid var(--line);padding-bottom:6px}
.sub{font-size:12px;color:var(--faint);font-weight:500;letter-spacing:0;text-transform:none}
header{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;padding-top:14px}
.meta{font-size:11.5px;color:var(--faint)}
#bar{position:sticky;top:0;z-index:20;background:rgba(13,17,23,.97);
border-bottom:1px solid var(--line);padding:9px 14px 8px;margin:10px -14px 0}
.row1{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
#q{flex:1;min-width:150px;font:inherit;font-size:15px;color:var(--tx);
background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:8px 11px}
#q:focus{outline:none;border-color:var(--wr)}
.chips{display:flex;gap:5px;flex-wrap:wrap}
.chip{font-size:12.5px;font-weight:800;padding:6px 11px;border-radius:99px;cursor:pointer;
border:1px solid var(--line);background:var(--panel);color:var(--dim);user-select:none;white-space:nowrap}
.chip:hover{border-color:var(--faint)}
.chip.on{background:var(--panel2);color:var(--tx);border-color:var(--wr)}
.chip.on.QB{border-color:var(--qb);color:var(--qb)}
.chip.on.RB{border-color:var(--rb);color:var(--rb)}
.chip.on.WR{border-color:var(--wr);color:var(--wr)}
.chip.on.TE{border-color:var(--te);color:var(--te)}
.chip.on.DST{border-color:var(--dst);color:var(--tx)}
.chip .c{opacity:.6;font-weight:600;margin-left:4px}
.row2{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:7px}
select,label.ck{font:inherit;font-size:12.5px;color:var(--dim);background:var(--panel);
border:1px solid var(--line);border-radius:7px;padding:6px 9px;cursor:pointer}
label.ck{display:flex;align-items:center;gap:6px;user-select:none}
label.ck.on{color:var(--tx);border-color:var(--wr)}
.seg{display:flex;border:1px solid var(--line);border-radius:8px;overflow:hidden}
.seg b{font-size:12px;font-weight:800;padding:6px 13px;cursor:pointer;color:var(--dim);
background:var(--panel);user-select:none;letter-spacing:.04em}
.seg b.on{background:var(--wr);color:#06121f}
.hint{font-size:11px;color:var(--faint);margin-left:auto}
#note{font-size:11.5px;color:var(--faint);margin-top:6px;line-height:1.45}
#note b{color:var(--warn)}
.dnd{background:rgba(248,81,73,.16);border:2px solid var(--bad);border-radius:10px;
padding:14px 16px;margin:14px 0 4px}
.dnd .hdr{font-size:12px;font-weight:900;letter-spacing:.14em;color:var(--bad);margin-bottom:8px}
.dnd .nm{font-size:30px;font-weight:900;line-height:1.1;letter-spacing:-.02em}
.dnd .why{font-size:15px;color:#ffb3ae;margin-top:5px;font-weight:600}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th{font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:var(--faint);
text-align:left;padding:5px 7px;font-weight:800}
td{padding:6px 7px;border-top:1px solid var(--line);font-size:14px}
tr.hot td{background:rgba(248,81,73,.10)} tr.warm td{background:rgba(227,179,65,.08)}
.pos{font-size:10px;font-weight:900;padding:1px 5px;border-radius:4px;margin-right:5px}
.pos.RB{color:var(--rb);background:rgba(63,185,80,.15)}
.pos.WR{color:var(--wr);background:rgba(88,166,255,.15)}
.pos.QB{color:var(--qb);background:rgba(240,136,62,.15)}
.pos.TE{color:var(--te);background:rgba(188,140,255,.15)}
.pos.DST{color:var(--dst);background:rgba(139,152,165,.15)}
.nmc{font-size:15px;font-weight:800}
.dim{color:var(--faint)} .num{text-align:right}
.d{font-weight:900;font-size:14px}
.d.up{color:var(--good)} .d.dn{color:var(--bad)} .d.nu{color:var(--faint)}
.tag{font-size:9.5px;font-weight:800;letter-spacing:.04em;padding:1px 5px;border-radius:4px;
background:var(--panel2);color:var(--faint);border:1px solid var(--line);margin-left:5px;
white-space:nowrap}
.tag.nb{color:var(--warn);border-color:rgba(227,179,65,.4)}
.tag.rk{color:var(--good);border-color:rgba(63,185,80,.4)}
.tag.dn{color:var(--bad);border-color:rgba(248,81,73,.5)}
.empty{padding:16px;color:var(--faint);font-size:14px;text-align:center}
.tier{margin-bottom:12px;border-left:5px solid var(--line);padding-left:12px}
.tier.t0{border-left-color:var(--good)} .tier.t1{border-left-color:var(--warn)}
.tier.t2{border-left-color:#c9822f} .tier.t3{border-left-color:var(--faint)}
.tier .tn{font-size:14px;font-weight:900;letter-spacing:.05em}
.tier.t0 .tn{color:var(--good)} .tier.t1 .tn{color:var(--warn)}
.tier.t2 .tn{color:#c9822f} .tier.t3 .tn{color:var(--faint)}
.tier .tm{font-size:11.5px;color:var(--faint);margin-bottom:5px}
.plist{display:flex;flex-wrap:wrap;gap:7px}
.pl{background:var(--panel);border:1px solid var(--line);border-radius:7px;padding:7px 11px}
.pl .n{font-size:16px;font-weight:800;line-height:1.15}
.pl .dd{font-size:11.5px;color:var(--dim);margin-top:1px}
.hc{display:grid;grid-template-columns:repeat(auto-fill,minmax(255px,1fr));gap:7px}
.hcp{background:var(--panel);border:1px solid var(--line);border-radius:7px;padding:8px 11px}
.hcp .a{font-size:15px;font-weight:800}
.hcp .b{font-size:14px;font-weight:700;color:var(--good);margin-top:2px}
.hcp .c{font-size:11px;color:var(--faint);margin-top:2px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--line);
border:1px solid var(--line);border-radius:8px;overflow:hidden}
.cols>div{background:var(--panel);padding:0 0 6px}
.cols h3{font-size:10.5px;text-transform:uppercase;letter-spacing:.08em;padding:8px 11px;font-weight:800}
.cols .up h3{color:var(--good)} .cols .dn h3{color:var(--bad)}
.drow{display:flex;gap:9px;padding:5px 11px;border-top:1px solid rgba(45,57,71,.5);align-items:baseline}
.drow .dv{font-size:15px;font-weight:900;min-width:38px}
.up .dv{color:var(--good)} .dn .dv{color:var(--bad)}
.note{font-size:12px;color:var(--faint);line-height:1.55;margin-top:8px;background:var(--panel);
border-left:3px solid var(--line);padding:9px 12px;border-radius:0 6px 6px 0}
.note b{color:var(--dim)}
footer{margin-top:30px;font-size:11px;color:var(--faint);text-align:center;line-height:1.7;
border-top:1px solid var(--line);padding-top:12px}
@media(max-width:620px){
  body{padding:0 10px 40px} #bar{margin:10px -10px 0;padding-left:10px;padding-right:10px}
  .dnd .nm{font-size:24px} .hc{grid-template-columns:1fr} .cols{grid-template-columns:1fr}
  td{font-size:13px} .hint{display:none} .nmc{font-size:14px}
}
"""

JS = r"""
var D = window.__REF__;
var POS = ['QB','RB','WR','TE','DST'];

/* Same normalisation the console and the Python side use, byte for byte:
   lowercase, strip dots / apostrophes / hyphens, drop Jr Sr II III IV V, keep
   alphanumerics. So "Ja'Marr Chase", "Smith-Njigba", "Amon-Ra St. Brown",
   "Kenneth Walker III" and "Deebo Samuel Sr." all match what you would type. */
var SUFFIX = /\b(jr|sr|ii|iii|iv|v)\b/g;
function norm(s){
  return String(s||'').toLowerCase().replace(/[.'’-]/g,' ')
    .replace(SUFFIX,' ').replace(/[^a-z0-9]/g,'');
}

var S = { q:'', pos:new Set(), bye:'', rookies:false, view:'both' };

function readHash(){
  var h = (location.hash||'').replace(/^#/,'');
  if(!h) return;
  h.split('&').forEach(function(kv){
    var i = kv.indexOf('='); if(i<0) return;
    var k = decodeURIComponent(kv.slice(0,i)), v = decodeURIComponent(kv.slice(i+1));
    if(k==='q') S.q=v;
    else if(k==='pos'&&v) v.split(',').forEach(function(p){ if(POS.indexOf(p)>=0) S.pos.add(p); });
    else if(k==='bye') S.bye=v;
    else if(k==='rk') S.rookies = v==='1';
    else if(k==='view'&&['ours','market','both'].indexOf(v)>=0) S.view=v;
  });
}
function writeHash(){
  var p=[];
  if(S.q) p.push('q='+encodeURIComponent(S.q));
  if(S.pos.size) p.push('pos='+POS.filter(function(x){return S.pos.has(x);}).join(','));
  if(S.bye) p.push('bye='+S.bye);
  if(S.rookies) p.push('rk=1');
  if(S.view!=='both') p.push('view='+S.view);
  var h = p.length ? '#'+p.join('&') : '';
  if(h !== location.hash)
    history.replaceState(null,'',location.pathname+location.search+h);
}

function matchQuery(p, q){
  if(!q) return true;
  return norm(p.n).indexOf(q)>=0 || norm(p.t||'').indexOf(q)>=0 ||
         norm(p.cl||'').indexOf(q)>=0;
}
function matches(p, override){
  var pos = override && override.pos ? override.pos : S.pos;
  if(pos.size && !pos.has(p.p)) return false;
  if(S.bye && String(p.by||'') !== S.bye) return false;
  if(S.rookies && !p.rt) return false;
  return matchQuery(p, norm(S.q));
}
function shown(){ return D.players.filter(function(p){ return matches(p); }); }

function esc(s){ return String(s==null?'':s)
  .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function posTag(p){ return '<span class="pos '+esc(p)+'">'+esc(p)+'</span>'; }
function dCell(d){
  if(d==null) return '<span class="d nu">&mdash;</span>';
  var cls = Math.abs(d)<=5 ? 'nu' : (d>0 ? 'up' : 'dn');
  return '<span class="d '+cls+'">'+(d>0?'+':'')+d+'</span>';
}

function renderBoard(list){
  var v = S.view, rows = list.slice();
  rows.sort(function(a,b){
    if(v==='market') return (a.mkt==null)-(b.mkt==null) || (a.mkt||1e9)-(b.mkt||1e9);
    if(v==='ours')   return (a.our==null)-(b.our==null) || (a.our||1e9)-(b.our||1e9);
    var ax = a.our==null ? (a.mkt||1e9) : a.our, bx = b.our==null ? (b.mkt||1e9) : b.our;
    return ax-bx;
  });
  var head = '<tr><th>Player</th><th>Pos</th><th>Tm</th><th>Bye</th>';
  if(v!=='market') head += '<th class=num>Ours</th><th class=num>Tier</th>';
  if(v!=='ours')   head += '<th class=num>ADP</th><th class=num>Mkt</th>';
  if(v==='both')   head += '<th class=num>Delta</th>';
  head += '</tr>';
  if(!rows.length)
    return '<table>'+head+'</table><div class=empty>No players match.</div>';
  var body = rows.slice(0,300).map(function(p){
    var tags = '';
    if(p.dnd) tags += '<span class="tag dn">DO NOT DRAFT</span>';
    if(p.our==null) tags += '<span class="tag nb">NOT ON BOARD</span>';
    if(p.mkt==null) tags += '<span class="tag nb">NOT ON MARKET</span>';
    if(p.rt) tags += '<span class="tag rk">ROOKIE</span>';
    var r = '<tr><td class=nmc>'+esc(p.n)+tags+'</td><td>'+posTag(p.p)+'</td>'+
            '<td class=dim>'+esc(p.t||'—')+'</td><td class=dim>'+(p.by||'—')+'</td>';
    if(v!=='market') r += '<td class=num>'+(p.our==null?'<span class=dim>&mdash;</span>':'#'+p.our)+'</td>'+
                          '<td class="num dim">'+(p.ti==null?'&mdash;':'T'+p.ti)+'</td>';
    if(v!=='ours')   r += '<td class=num>'+(p.adp==null?'<span class=dim>&mdash;</span>':p.adp.toFixed(1))+'</td>'+
                          '<td class="num dim">'+(p.mkt==null?'&mdash;':'#'+p.mkt)+'</td>';
    if(v==='both')   r += '<td class=num>'+dCell(p.d)+'</td>';
    return r+'</tr>';
  }).join('');
  var more = rows.length>300
    ? '<div class=empty>'+(rows.length-300)+' more match &mdash; narrow the filter.</div>' : '';
  return '<table>'+head+body+'</table>'+more;
}

function renderDisagree(list){
  /* Defenses are excluded. Our board deliberately stacks all twelve at the
     bottom because DEF is a required starter you take in the last round or two;
     the market spreads them from #84 to #222. That produces deltas up to +98
     which are a difference in ROSTER STRATEGY, not a disagreement about how good
     the defense is, and they would otherwise crowd out every real name. */
  var both = list.filter(function(p){ return p.d!=null && !p.dnd && p.p!=='DST'; });
  var up = both.slice().sort(function(a,b){ return b.d-a.d; }).slice(0,15);
  var dn = both.slice().sort(function(a,b){ return a.d-b.d; }).slice(0,15);
  function col(arr,cls,title){
    if(!arr.length) return '<div class="'+cls+'"><h3>'+title+'</h3>'+
      '<div class=empty>No players match.</div></div>';
    return '<div class="'+cls+'"><h3>'+title+'</h3>'+arr.map(function(p){
      return '<div class=drow><span class=dv>'+(p.d>0?'+':'')+p.d+'</span>'+
        '<span><b>'+esc(p.n)+'</b> '+posTag(p.p)+
        '<span class=dim style="font-size:11.5px"> ours #'+p.our+
        ' · market #'+p.mkt+'</span></span></div>';
    }).join('')+'</div>';
  }
  return '<div class=cols>'+col(up,'up','We like — market is lower on him')+
         col(dn,'dn','Market likes — we are lower on him')+'</div>';
}

function renderRookies(list){
  var keys = {}; list.forEach(function(p){ keys[norm(p.n)]=1; });
  var order = ['REAL WEEK-1 ROLE','STARTER-ADJACENT','DART THROW','BENCH FLYER'];
  var out = '', any = false;
  order.forEach(function(t,i){
    var g = D.rookies.filter(function(r){ return r.tier===t && keys[norm(r.name)]; });
    if(!g.length) return;
    any = true;
    out += '<div class="tier t'+Math.min(i,3)+'"><div class=tn>'+esc(t)+'</div>'+
      '<div class=tm>'+esc(g[0].note)+' · historically '+g[0].mean_pg.toFixed(1)+
      ' pts/g</div><div class=plist>';
    g.forEach(function(r){
      out += '<div class=pl><div class=n>'+posTag(r.pos)+esc(r.name)+'</div>'+
        '<div class=dd>'+esc(r.team)+' · board #'+r.board_rank+
        ' · NFL pick '+r.pick+' · '+esc(r.college)+'</div></div>';
    });
    out += '</div></div>';
  });
  return any ? out : '<div class=empty>No rookies match.</div>';
}

function renderOffBoard(){
  var q = norm(S.q);
  var g = D.off_board_rookies.filter(function(r){
    if(S.pos.size && !S.pos.has(r.pos)) return false;
    if(S.bye) return false;
    return matchQuery({n:r.name, t:r.team, cl:r.college}, q);
  });
  if(!g.length) return '<div class=empty>No off-board rookies match.</div>';
  return '<div class=plist>'+g.map(function(r){
    return '<div class=pl><div class=n>'+posTag(r.pos)+esc(r.name)+'</div>'+
      '<div class=dd>'+esc(r.team)+' · NFL pick '+r.pick+' · '+
      Math.round(r.hit*100)+'% hit rate · '+esc(r.college)+'</div></div>';
  }).join('')+'</div>';
}

function renderByes(list){
  var wk = {};
  list.forEach(function(p){
    if(!p.by || p.our==null || p.our>60) return;
    (wk[p.by] = wk[p.by] || []).push(p);
  });
  var weeks = Object.keys(wk).map(Number).sort(function(a,b){ return wk[b].length-wk[a].length; });
  var head = '<tr><th>Wk</th><th>Top-60 out</th><th>By position</th><th>Who</th></tr>';
  if(!weeks.length)
    return '<table>'+head+'</table><div class=empty>No players match.</div>';
  var rows = weeks.map(function(w){
    var g = wk[w], cls = g.length>=10?'hot':g.length>=8?'warm':'';
    var by = POS.map(function(x){
      var c = g.filter(function(p){ return p.p===x; }).length;
      return c ? x+c : ''; }).filter(Boolean).join(' ');
    var who = g.slice().sort(function(a,b){ return a.our-b.our; }).slice(0,7)
      .map(function(p){ return p.n; }).join(', ');
    return '<tr class="'+cls+'"><td style="font-size:20px;font-weight:900">'+w+'</td>'+
      '<td style="font-size:17px;font-weight:800">'+g.length+'</td>'+
      '<td class=dim>'+esc(by)+'</td>'+
      '<td class=dim style="font-size:11.5px">'+esc(who)+'</td></tr>';
  }).join('');
  return '<table>'+head+rows+'</table>';
}

function renderHandcuffs(list){
  var keys = {}; list.forEach(function(p){ keys[norm(p.n)]=1; });
  var g = D.handcuffs.filter(function(h){ return keys[norm(h.lead)] || keys[norm(h.back)]; });
  if(!g.length) return '<div class=empty>No handcuff pairs match.</div>';
  return '<div class=hc>'+g.slice(0,30).map(function(h){
    var br = h.back_board_rank ? 'board #'+h.back_board_rank : 'off board';
    var as = h.assumed_same_team ? ' · assumed still there' : '';
    return '<div class=hcp><div class=a>'+esc(h.lead)+
      ' <span style="color:var(--faint);font-size:12px">#'+h.lead_rank+
      ' '+esc(h.team)+'</span></div>'+
      '<div class=b>&rarr; '+esc(h.back)+'</div>'+
      '<div class=c>'+h.back_carries+' carries in 2025 · '+esc(br)+esc(as)+'</div></div>';
  }).join('')+'</div>';
}

function renderChips(){
  var all = document.getElementById('chipAll');
  all.className = 'chip'+(S.pos.size?'':' on');
  all.innerHTML = 'ALL<span class=c>'+D.players.length+'</span>';
  POS.forEach(function(p){
    var el = document.getElementById('chip'+p);
    var n = D.players.filter(function(x){
      return matches(x, {pos:new Set([p])}); }).length;
    el.className = 'chip '+p+(S.pos.has(p)?' on':'');
    el.innerHTML = p+'<span class=c>'+n+'</span>';
  });
}

function render(){
  var list = shown();
  renderChips();
  ['ours','market','both'].forEach(function(v){
    var el = document.getElementById('v_'+v);
    if(S.view===v) el.classList.add('on'); else el.classList.remove('on');
  });
  document.getElementById('count').textContent = list.length+' shown';
  document.getElementById('board').innerHTML = renderBoard(list);
  document.getElementById('disagree').innerHTML = renderDisagree(list);
  document.getElementById('secDisagree').style.display = S.view==='both' ? '' : 'none';
  document.getElementById('rookies').innerHTML = renderRookies(list);
  document.getElementById('offboard').innerHTML = renderOffBoard();
  document.getElementById('byes').innerHTML = renderByes(list);
  document.getElementById('handcuffs').innerHTML = renderHandcuffs(list);
  writeHash();
}

function boot(){
  readHash();
  var q = document.getElementById('q');
  q.value = S.q;
  q.addEventListener('input', function(){ S.q = q.value; render(); });
  document.getElementById('chipAll').onclick = function(){ S.pos.clear(); render(); };
  POS.forEach(function(p){
    document.getElementById('chip'+p).onclick = function(){
      if(S.pos.has(p)) S.pos['delete'](p); else S.pos.add(p);
      render();
    };
  });
  var bs = document.getElementById('byeSel');
  bs.value = S.bye;
  bs.addEventListener('change', function(){ S.bye = bs.value; render(); });
  var rk = document.getElementById('rkChk');
  rk.checked = S.rookies;
  rk.addEventListener('change', function(){
    S.rookies = rk.checked;
    document.getElementById('rkLbl').classList.toggle('on', rk.checked);
    render();
  });
  document.getElementById('rkLbl').classList.toggle('on', S.rookies);
  ['ours','market','both'].forEach(function(v){
    document.getElementById('v_'+v).onclick = function(){ S.view = v; render(); };
  });
  document.addEventListener('keydown', function(e){
    if(e.key==='/' && document.activeElement!==q){ e.preventDefault(); q.focus(); q.select(); }
    else if(e.key==='Escape'){ q.value=''; S.q=''; q.blur(); render(); }
  });
  render();
}
/* Re-read the hash on hash-only navigation. Without this a link or a back
   button that only changes the fragment leaves the page showing the previous
   filter while the URL claims otherwise. */
function applyHash(){
  S.q=''; S.pos.clear(); S.bye=''; S.rookies=false; S.view='both';
  readHash();
  document.getElementById('q').value = S.q;
  document.getElementById('byeSel').value = S.bye;
  document.getElementById('rkChk').checked = S.rookies;
  document.getElementById('rkLbl').classList.toggle('on', S.rookies);
  render();
}
window.addEventListener('hashchange', applyHash);

window.__REFAPI__ = { norm:norm, matches:matches, shown:shown, state:S,
                      render:render, dCell:dCell, readHash:readHash,
                      writeHash:writeHash, applyHash:applyHash };
if(document.readyState==='loading') document.addEventListener('DOMContentLoaded', boot);
else boot();
"""


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def render(p):
    L, A = [], None
    out = []
    A = out.append
    byes_avail = sorted({r["by"] for r in p["players"] if r.get("by")})
    A("<!DOCTYPE html><html lang=en><head><meta charset=utf-8>")
    A('<meta name="viewport" content="width=device-width,initial-scale=1">')
    A("<title>Draft Reference</title><style>" + CSS + "</style></head><body>")
    A('<header><h1>Draft Reference</h1>'
      '<span class=sub>' + esc(p["generated_for"]) + '</span></header>')
    A('<div class=meta>Second-tab companion. Static &mdash; nothing here updates '
      'during the draft. The live board is the other tab.</div>')

    A('<div id=bar><div class=row1>'
      '<input id=q type=search placeholder="Search name, team, college…   ( / )" '
      'autocomplete=off spellcheck=false>'
      '<div class=chips><span class=chip id=chipAll>ALL</span>')
    for pos in ["QB", "RB", "WR", "TE", "DST"]:
        A('<span class="chip ' + pos + '" id=chip' + pos + '>' + pos + '</span>')
    A('</div></div><div class=row2><div class=seg>'
      '<b id=v_ours>OURS</b><b id=v_market>MARKET</b><b id=v_both>BOTH</b></div>'
      '<select id=byeSel><option value="">All byes</option>')
    for b in byes_avail:
        A('<option value="' + str(b) + '">Bye ' + str(b) + '</option>')
    A('</select>'
      '<label class=ck id=rkLbl><input type=checkbox id=rkChk> Rookies only</label>'
      '<span class=hint id=count></span></div>'
      '<div id=note><b>Delta is a disagreement flag, not an edge.</b> '
      'Out-of-sample across 2016&ndash;2025 nothing beat ADP &mdash; not our board, '
      'not the model. Delta = market rank &minus; our rank, so positive means we are '
      'higher on him. Read it as "one of us is wrong", never as "we are right".</div></div>')

    for d in p["do_not_draft"]:
        A('<div class=dnd><div class=hdr>DO NOT DRAFT</div>'
          '<div class=nm>' + esc(d["name"]) +
          ' <span class="pos ' + esc(d["pos"]) + '">' + esc(d["pos"]) + '</span>'
          ' <span style="font-size:16px;color:var(--faint)">' + esc(d["team"]) +
          ' · board #' + str(d["board_rank"]) + '</span></div>'
          '<div class=why>' + esc(d["reason"]) + '</div>')
        for h in p.get("inherits", []):
            if h["out"] != d["name"]:
                continue
            br = ("board #" + str(h["board_rank"])) if h["board_rank"] else "not on the board"
            A('<div class=why style="color:var(--warn);margin-top:9px">&rarr; '
              + esc(h["heir"]) + ' inherits the ' + esc(h["team"]) + ' backfield ('
              + str(h["carries"]) + ' carries in 2025, ' + esc(br)
              + ') &mdash; that is the pick this frees up.</div>')
        A("</div>")

    A('<h2>Board <span class=sub>ours vs the market · '
      + esc(p.get("market_source") or "ADP") + '</span></h2><div id=board></div>')
    A('<div id=secDisagree><h2>Biggest disagreements '
      '<span class=sub>top 15 each way by absolute delta</span></h2>'
      '<div id=disagree></div>'
      '<div class=note>These are the players where our board and the public board '
      'most disagree. That is <b>not</b> a claim that we are right — the '
      'backtest says the market wins out of sample. It is a list of picks worth '
      'ten extra seconds of thought.<br><br>'
      'Two things before you read it. <b>Our top 30 basically IS the market</b> '
      '&mdash; median disagreement is 1 slot and the largest is 5, because the '
      'board was built from this same half-PPR ADP. Real divergence only starts '
      'past our #60 where the board switches to expert consensus (median 12 slots '
      'out there). And <b>defenses are excluded</b>: our board stacks all twelve '
      'at the bottom because DEF is a last-round required starter, which creates '
      'deltas up to +98 that are a roster-strategy difference, not a judgement '
      'about the defense.</div></div>')

    m = p["rookie_method"]
    A('<h2>Rookies <span class=sub>tiered by the one trait that predicts</span></h2>'
      '<div id=rookies></div>')
    A('<div class=note><b>Method.</b> Tested on ' + str(m["n"]) + ' rookie seasons, '
      + esc(m["span"]) + '. <b>Predicts:</b> ' + esc(m["predicts"]) + '. <b>Weak:</b> '
      + esc(m["weak"]) + '. <b>No signal:</b> ' + esc(m["no_signal"])
      + '. <b>Untested:</b> ' + esc(m["untested"]) + '.</div>')
    A('<h2>Round-1 and 2 rookies your board does NOT list</h2><div id=offboard></div>')
    A('<h2>Bye weeks <span class=sub>where the board is thin — 4 bench spots</span>'
      '</h2><div id=byes></div>')
    A('<div class=note><b>The rule for this roster:</b> two <i>starters</i> on the '
      'same bye is a real problem with only four bench spots. Two bench players is '
      'not. Red rows take 10+ of the top 60 off the field at once.</div>')
    A('<h2>Handcuffs <span class=sub>who backs up the RB you just took</span></h2>'
      '<div id=handcuffs></div>')
    A('<div class=note>Backups are the 2025 second-most-used back on that player’s '
      '<b>2026</b> team. Pairs marked <i>assumed still there</i> are not on the '
      '129-player board.</div>')
    A('<footer>Generated by build_reference.py · static, no network, no '
      'modelling in the page<br>Rookie tiers from 825 rookie seasons 2013-2025 '
      '· press / to search, Esc to clear</footer>')

    blob = json.dumps(p, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    A('<script id=refData type="application/json">' + blob + "</script>")
    A('<script>window.__REF__=JSON.parse('
      'document.getElementById("refData").textContent);</script>')
    A("<script>" + JS + "</script>")
    A("</body></html>")
    return "\n".join(out)
