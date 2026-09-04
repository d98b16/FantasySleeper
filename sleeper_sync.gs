/**
 * sleeper_sync.gs — live Sleeper draft sync for the Google Sheet
 * =============================================================================
 * READ THIS BEFORE YOU BOTHER INSTALLING IT.
 *
 * A static .xlsx cannot poll an API. Nothing you can put in a cell will do it —
 * no IMPORTDATA trick, no custom function (custom functions are cached and are
 * not allowed to fetch on a timer). The ONLY way to make the SHEET itself update
 * live is server-side Apps Script on a time-driven trigger, which is this file.
 *
 * HONEST RECOMMENDATION: for YOU, during the draft, use the web console instead.
 *   - Apps Script time triggers have a HARD FLOOR OF 1 MINUTE. Your pick timer is
 *     90 seconds. A one-minute-stale board is worse than useless on the clock —
 *     the console polls every 1-2s and already shows more than the sheet can.
 *   - Installing this costs 5-10 minutes of OAuth fiddling you do not have the
 *     night before a draft.
 *
 * WHERE IT IS ACTUALLY WORTH IT: your co-owner. If mwhitten204@gmail.com is
 * watching the shared Sheet rather than the console, this keeps his view honest
 * without him needing anything but the tab he already has open. It is a
 * second-screen convenience, not a drafting tool.
 *
 * INSTALL
 *   1. Open the Sheet -> Extensions -> Apps Script.
 *   2. Delete the stub, paste this whole file, Save.
 *   3. Run `setup` once. Google will ask you to authorize (external fetch +
 *      spreadsheet write). Approve it.
 *   4. A "Draft Sync" menu appears on the Sheet after a reload.
 *
 * UNINSTALL: Draft Sync -> Stop live sync (or delete the trigger in the editor).
 */

var LEAGUE_ID = '1389326749023608832';   // GovSmart Gridiron (verified)
var DRAFT_ID  = '1389326749023608833';
var MY_SLOT   = 3;
var TEAMS     = 12;
var ROUNDS    = 12;

var BOARD_SHEET = 'Sheet1';   // the tab holding the imported draft_sheet.csv
var LIVE_SHEET  = 'Live';     // created automatically

// Board column letters, matching build_sheet.py's CSV layout exactly.
var COL = { rank:1, tier:2, player:3, pos:4, team:5, bye:6, adp:7, notes:8,
            drafted:9, mine:10 };

/** Mirrors norm() in index.html and build_edge.py. Keep all three identical. */
function norm(s) {
  return String(s || '').toLowerCase()
    .replace(/[.'’-]/g, ' ')
    .replace(/\b(jr|sr|ii|iii|iv|v)\b/g, ' ')
    .replace(/[^a-z0-9]/g, '');
}

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Draft Sync')
    .addItem('Sync once now', 'syncNow')
    .addItem('Start live sync (1 min)', 'startLiveSync')
    .addItem('Stop live sync', 'stopLiveSync')
    .addToUi();
}

function setup() {
  syncNow();
  SpreadsheetApp.getActiveSpreadsheet().toast(
    'Draft Sync installed. Use the Draft Sync menu to start the 1-minute timer.', 'Ready', 8);
}

function startLiveSync() {
  stopLiveSync();
  ScriptApp.newTrigger('syncNow').timeBased().everyMinutes(1).create();
  SpreadsheetApp.getActiveSpreadsheet().toast(
    'Live sync on — refreshes every 60s. Remember: your pick timer is 90s, so the ' +
    'console is still the thing to draft from.', 'Draft Sync', 8);
}

function stopLiveSync() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'syncNow') ScriptApp.deleteTrigger(t);
  });
}

/** Snake: which draft slot owns overall pick n. */
function slotOfPick(n) {
  var rd = Math.ceil(n / TEAMS), i = n - TEAMS * (rd - 1);
  return (rd % 2) ? i : (TEAMS - i + 1);
}

function fetchPicks() {
  var url = 'https://api.sleeper.app/v1/draft/' + DRAFT_ID + '/picks';
  var res = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  if (res.getResponseCode() !== 200) {
    throw new Error('Sleeper returned HTTP ' + res.getResponseCode());
  }
  return JSON.parse(res.getContentText());
}

function syncNow() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var picks;
  try {
    picks = fetchPicks();
  } catch (e) {
    writeStatus(ss, 'ERROR: ' + e.message);
    return;
  }
  picks.sort(function (a, b) { return a.pick_no - b.pick_no; });

  // ---- 1. the Live tab: a plain readable pick log ------------------------
  var live = ss.getSheetByName(LIVE_SHEET) || ss.insertSheet(LIVE_SHEET);
  live.clear();
  var out = [['Pick', 'Rd', 'Slot', 'Player', 'Pos', 'Team', 'Yours?']];
  var takenByMe = {}, taken = {};
  picks.forEach(function (p) {
    var m = p.metadata || {};
    var name = [m.first_name, m.last_name].filter(String).join(' ').trim();
    var pos = String(m.position || '').toUpperCase();
    var team = String(m.team || '').toUpperCase();
    var slot = p.draft_slot || slotOfPick(p.pick_no);
    var key = (pos === 'DEF' || pos === 'DST') ? team : norm(name);
    taken[key] = true;
    if (slot === MY_SLOT) takenByMe[key] = true;
    out.push([p.pick_no, p.round, slot, name, pos, team, slot === MY_SLOT ? 'YOU' : '']);
  });
  live.getRange(1, 1, out.length, out[0].length).setValues(out);
  live.getRange(1, 1, 1, out[0].length).setFontWeight('bold');
  live.setFrozenRows(1);

  // ---- 2. mark the Big Board's Drafted? / MINE? columns -------------------
  var board = ss.getSheetByName(BOARD_SHEET);
  if (board) {
    var found = findBoardRows(board);
    if (found) {
      var n = found.last - found.first + 1;
      var names = board.getRange(found.first, COL.player, n, 1).getValues();
      var poss  = board.getRange(found.first, COL.pos,    n, 1).getValues();
      var teams = board.getRange(found.first, COL.team,   n, 1).getValues();
      var dr = [], mi = [];
      for (var i = 0; i < n; i++) {
        var pos = String(poss[i][0]).toUpperCase();
        var key = (pos === 'DST' || pos === 'DEF')
          ? String(teams[i][0]).toUpperCase() : norm(names[i][0]);
        dr.push([taken[key] ? 'x' : '']);
        mi.push([takenByMe[key] ? 'x' : '']);
      }
      board.getRange(found.first, COL.drafted, n, 1).setValues(dr);
      board.getRange(found.first, COL.mine,    n, 1).setValues(mi);
    }
  }

  var next = picks.length + 1;
  writeStatus(ss, 'pick #' + next + ' · round ' + Math.ceil(next / TEAMS) +
    ' · on the clock: slot ' + slotOfPick(next) +
    (slotOfPick(next) === MY_SLOT ? ' — THAT IS YOU' : '') +
    ' · ' + picks.length + ' picks in · updated ' +
    Utilities.formatDate(new Date(), ss.getSpreadsheetTimeZone(), 'HH:mm:ss'));
}

/**
 * Locate the board block by CONTENT, not by a hardcoded row number. The CSV's
 * layout shifts whenever the plan or scenario text changes length; anchoring on
 * the literal header row is what keeps this from silently writing 'x' into the
 * wrong rows -- the same failure the Python side guards against.
 */
function findBoardRows(sheet) {
  var col = sheet.getRange(1, 1, sheet.getLastRow(), 1).getValues();
  var header = -1;
  for (var i = 0; i < col.length; i++) {
    if (String(col[i][0]).trim() === 'Rank') { header = i + 1; break; }
  }
  if (header < 0) return null;
  var first = header + 1, lastRow = first;
  for (var r = first; r <= col.length; r++) {
    if (String(col[r - 1][0]).trim() === '') break;
    lastRow = r;
  }
  return { first: first, last: lastRow };
}

function writeStatus(ss, msg) {
  var live = ss.getSheetByName(LIVE_SHEET) || ss.insertSheet(LIVE_SHEET);
  live.getRange('I1').setValue(msg).setFontWeight('bold');
}
