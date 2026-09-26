"""Build docs/data-review.html — a self-contained review of the engine's data.

Manual-only tool: run `python -m src.build_data_review` (or `python src/build_data_review.py`).
NEVER called by run_weekly.py, never scheduled — it only READS data/ and docs/ and
writes one static HTML file with the data embedded inline (opens offline via file://).

Shows ONLY what the poll-matrix engine consumes (owner decision 2026-09-22:
MCMC/CPI retired from the run path):
  docs/polls.json (poll log + seeds), data/poll_matrix.csv (observation matrix),
  data/raw/week_*/polls_snapshot.json (raw poll fetches), data/raw/manual_notes.csv,
  config/poll_engine.json (aggregation params), config/housemates.json + twist.json
  (eligibility layer), docs/track_record.json.

Bayesian/MCMC/CPI analysis is NOT engine input anymore and is excluded here
(kept in git history; data/predictions.json MCMC file stays as rollback artifact).
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "data-review.html"
MATRIX = ROOT / "data" / "poll_matrix.csv"
SNAP_DIR = ROOT / "data" / "raw"
ENGINE_CFG = ROOT / "config" / "poll_engine.json"


def read_json(p: Path):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def week_start(premiere: str, week: int) -> str:
    d = date.fromisoformat(premiere) + timedelta(days=7 * (week - 1))
    return d.isoformat()


def collect_poll_snapshots(premiere: str) -> dict:
    """Per-week poll-snapshot content: source states + entries + archived files."""
    weeks = {}
    for wd in sorted(SNAP_DIR.glob("week_*"), key=lambda p: int(p.name.split("_")[1])):
        wk = int(wd.name.split("_")[1])
        snap_path = wd / "polls_snapshot.json"
        weeks[str(wk)] = {
            "week": wk,
            "week_start": week_start(premiere, wk),
            "snapshot": read_json(snap_path) if snap_path.exists() else None,
            "files": sorted(p.name for p in wd.iterdir() if p.is_file()),
        }
    return weeks


def collect_matrix() -> list[dict]:
    if not MATRIX.exists():
        return []
    with open(MATRIX, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_flags(polls, matrix, snaps, house_cfg) -> list[dict]:
    flags = []
    n_rows = len(matrix)
    if n_rows < 3:
        flags.append({
            "level": "warn",
            "title": f"Thin window: only {n_rows} poll observation row(s) in the matrix",
            "detail": "The Sep-26 run aggregates seeds + transcriptions + momentum. THIN-WINDOW warning "
                      "is the expected shape (engine-runbook section 2/4). Transcribing wk6/wk7 result "
                      "images takes the window from 1 seed week to 3.",
        })
    pend = [e["week"] for e in snaps.values()
            if e["snapshot"] and any(s.get("state") == "needs-transcription"
                                     for s in e["snapshot"].get("sources", []))]
    if pend:
        flags.append({
            "level": "warn",
            "title": "Result images awaiting transcription: weeks " + ", ".join(str(w) for w in pend),
            "detail": "data/raw/week_0X/polls_result_image.png -> docs/polls.json (runbook section 5). "
                      "Canonical names only; never guess unclear numbers.",
        })
    valid: set[str] = set()
    for h in house_cfg:
        valid.update(h["aliases"])
    unknown = []
    for w in polls["weeks"]:
        for p in w.get("poll", []):
            if p["name"] not in valid:
                unknown.append(f"wk{w['week']}: {p['name']}")
    if unknown:
        flags.append({
            "level": "warn",
            "title": "Poll rows with non-canonical housemate names",
            "detail": "; ".join(unknown) + " — fix in docs/polls.json before aggregation.",
        })
    flags.append({
        "level": "info",
        "title": "Rank-only sources (ngnews247) are constraint rows — never shares",
        "detail": "Grade C rows enter the aggregate only as top_N/bottom_N ordering constraints with "
                  "soften-on-conflict; every application is logged in the products' polls.constraint_log.",
    })
    return flags


def main() -> int:
    season = read_json(ROOT / "config/season.json")
    twist = read_json(ROOT / "config/twist.json")
    house = read_json(ROOT / "config/housemates.json")
    polls = read_json(ROOT / "docs/polls.json")
    engine_cfg = read_json(ENGINE_CFG)
    track = read_json(ROOT / "docs/track_record.json")
    with open(ROOT / "data/raw/manual_notes.csv", encoding="utf-8") as f:
        manual = list(csv.DictReader(f))

    snaps = collect_poll_snapshots(season["premiere_date"])
    matrix = collect_matrix()

    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "season": season,
        "twist": twist,
        "roster_note": house.get("note_on_walked", ""),
        "housemates": house["housemates"],
        "engine_cfg": engine_cfg,
        "polls": polls,
        "track": track,
        "manual_notes": manual,
        "snaps": snaps,
        "matrix": matrix,
        "flags": build_flags(polls, matrix, snaps, house["housemates"]),
    }

    html = TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")
    return 0


TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BBNaija 2026 — Poll & Ranking Data Review</title>
<style>
:root{
  --bg:#0b0d12; --panel:#131722; --panel-2:#0f131d; --line:#232a3a;
  --ink:#ece9e1; --muted:#8b93a7; --faint:#5a6175;
  --gold:#f5b301; --gold-dim:#8a6a10; --red:#e5484d; --teal:#3dd6c3; --bronze:#c98a5e;
  --mono:ui-monospace,'Cascadia Mono',Consolas,monospace; --disp:'Archivo Black','Arial Black',sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font-family:'Segoe UI',system-ui,sans-serif;
  min-height:100vh;padding:clamp(12px,3vw,36px)}
.wrap{max-width:1280px;margin:0 auto}
a{color:var(--teal);word-break:break-all}
h1{font-family:var(--disp);font-size:clamp(20px,3.5vw,34px);text-transform:uppercase;letter-spacing:.5px}
h1 .yr{color:var(--gold)}
.sub{color:var(--muted);font-size:12px;letter-spacing:.16em;text-transform:uppercase}
.badges{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.badge{font-family:var(--mono);font-size:11px;padding:3px 9px;border:1px solid var(--line);
  border-radius:3px;color:var(--muted);background:var(--panel-2);text-transform:uppercase}
.badge.ok{border-color:var(--teal);color:var(--teal)} .badge.warn{border-color:var(--gold);color:var(--gold)}
.badge.demo{border-color:var(--red);color:var(--red)}
.panel{border:1px solid var(--line);border-radius:6px;background:var(--panel);padding:14px 16px;margin-top:14px;min-width:0}
.panel h2{font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:var(--muted);margin-bottom:10px;
  display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.tag{font-size:9px;padding:2px 6px;border:1px solid var(--gold-dim);color:var(--gold);border-radius:2px;letter-spacing:.1em}
.tag.sec{border-color:var(--line);color:var(--faint)}
.note{font-size:11.5px;color:var(--faint);line-height:1.6;margin-top:8px}
.note b{color:var(--muted)}
table{border-collapse:collapse;width:100%;font-size:12px}
th,td{border:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
th{background:var(--panel-2);color:var(--muted);font-weight:600;font-size:10.5px;
  text-transform:uppercase;letter-spacing:.08em}
td.num,th.num{text-align:right;font-family:var(--mono)}
.mono{font-family:var(--mono);font-size:11.5px}
.tblwrap{overflow:auto;max-height:520px;border:1px solid var(--line)}
.chip{display:inline-block;font-family:var(--mono);font-size:10px;padding:1px 6px;border-radius:3px;
  border:1px solid var(--line);background:var(--panel-2);margin:1px}
.flag{border-left:3px solid var(--gold);background:rgba(245,179,1,.06);padding:9px 12px;margin:8px 0;border-radius:3px;font-size:12.5px;line-height:1.55}
.flag.warn{border-left-color:var(--gold)} .flag.info{border-left-color:var(--teal);background:rgba(61,214,195,.05)}
.flag .ft{font-weight:700}
.flag .fd{color:var(--muted);margin-top:2px}
details{border:1px solid var(--line);border-radius:5px;background:var(--panel-2);margin:8px 0}
details summary{cursor:pointer;padding:9px 12px;font-size:12px;color:var(--muted);letter-spacing:.06em}
details[open] summary{border-bottom:1px solid var(--line);color:var(--ink)}
details .inner{padding:10px 12px;max-height:420px;overflow:auto}
.item{padding:6px 0;border-bottom:1px dashed var(--line);font-size:12px;line-height:1.5}
.item:last-child{border-bottom:none}
.item .t{font-weight:600}
.item .m{font-family:var(--mono);font-size:10.5px;color:var(--faint)}
.bar{height:6px;border-radius:2px;background:var(--gold);min-width:1px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:900px){.grid2{grid-template-columns:1fr}}
footer{margin-top:22px;padding-top:12px;border-top:1px solid var(--line);font-size:12px;color:var(--muted);line-height:1.7}
code{font-family:var(--mono);background:var(--panel-2);border:1px solid var(--line);border-radius:3px;padding:0 5px;font-size:11px}
</style>
</head>
<body>
<div class="wrap">
  <div class="sub">Season 11 · Show Ya Sef · engine-input data review · MCMC/CPI excluded (retired 2026-09-22)</div>
  <h1>BBNaija <span class="yr">2026</span> — Poll &amp; Ranking Data</h1>
  <div class="badges" id="badges"></div>
  <div class="note" id="genAt"></div>

  <section class="panel">
    <h2>Data-quality flags <span class="tag sec">computed at build time</span></h2>
    <div id="flags"></div>
  </section>

  <section class="panel">
    <h2>Aggregation config <span class="tag sec">config/poll_engine.json — how poll rows become win shares</span></h2>
    <div class="grid2">
      <div><table id="cfgTbl"></table></div>
      <div id="cfgGrades"></div>
    </div>
  </section>

  <section class="panel">
    <h2>The poll observation matrix <span class="tag sec">data/poll_matrix.csv — rebuilt idempotently every run; cache only, never a source</span></h2>
    <div id="matrixSummary"></div>
    <div class="tblwrap" style="max-height:none"><table id="matrixTbl"></table></div>
    <div class="note" id="matrixNote"></div>
  </section>

  <section class="panel">
    <h2>Poll log &amp; seed rows <span class="tag sec">docs/polls.json — transcribed finals + hand-logged rows</span></h2>
    <div id="pollStates"></div>
    <div class="grid2" style="margin-top:10px">
      <div>
        <h2 style="font-size:10px;letter-spacing:.14em">Week-8 vote-to-save poll (grade-A seed row)</h2>
        <div id="w8poll"></div>
      </div>
      <div>
        <h2 style="font-size:10px;letter-spacing:.14em">Concordance at snapshot (review telemetry)</h2>
        <div id="concord"></div>
      </div>
    </div>
    <div class="note" id="pollNote"></div>
  </section>

  <section class="panel">
    <h2>Raw poll fetches per week <span class="tag sec">data/raw/week_XX/polls_snapshot.json + archived HTML/images</span></h2>
    <div class="tblwrap" style="max-height:none"><table id="snapTbl"></table></div>
    <div id="snapDetails"></div>
    <div class="note" id="snapNote"></div>
  </section>

  <section class="panel">
    <h2>Manual notes <span class="tag sec">data/raw/manual_notes.csv — exit ledger + nomination blocks</span></h2>
    <div id="manualTbl"></div>
  </section>

  <section class="panel">
    <h2>Roster (eligibility layer) <span class="tag sec">config/housemates.json + config/twist.json — who can enter the matrix</span></h2>
    <div class="tblwrap"><table id="rosterTbl"></table></div>
    <div class="note" id="rosterNote"></div>
  </section>

  <section class="panel">
    <h2>Track record <span class="tag sec">docs/track_record.json — grows weekly from Sunday results</span></h2>
    <div id="trackPanel"></div>
  </section>

  <footer id="foot"></footer>
</div>

<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = id => document.getElementById(id);
const esc = s => String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pct = v => v==null?'—':(100*v).toFixed(2)+'%';
const f3 = v => v==null?'—':Number(v).toFixed(3);

function wStart(w){ const d=new Date(D.season.premiere_date+'T00:00:00Z'); d.setUTCDate(d.getUTCDate()+7*(w-1)); return d.toISOString().slice(0,10); }

// ---- header
const nRows = D.matrix.length;
const nPoll = D.polls.weeks.filter(w=>w.poll&&w.poll.length).reduce((a,w)=>a+w.poll.length,0);
const pend = Object.values(D.snaps).filter(e=>e.snapshot&&(e.snapshot.sources||[]).some(s=>s.state==='needs-transcription')).map(e=>e.week);
$('badges').innerHTML =
  '<span class="badge ok">'+nRows+' matrix rows</span>'+
  '<span class="badge">'+D.polls.weeks.length+' weeks logged</span>'+
  '<span class="badge ok">'+nPoll+' seed poll rows</span>'+
  '<span class="badge warn">'+pend.length+' images to transcribe</span>'+
  '<span class="badge demo">MCMC/CPI excluded · retired</span>';
$('genAt').innerHTML = 'Built <code>'+esc(D.generated_at)+'</code> by <code>src/build_data_review.py</code> — shows only what the poll-matrix engine consumes.';

// ---- flags
$('flags').innerHTML = D.flags.map(f=>'<div class="flag '+f.level+'"><div class="ft">'+esc(f.title)+'</div><div class="fd">'+esc(f.detail)+'</div></div>').join('');

// ---- config
const C = D.engine_cfg;
$('cfgTbl').innerHTML = '<tr><th>key</th><th>value</th></tr>' +
  ['window_weeks','cap','lambda_decay','epsilon_constraint'].map(k=>'<tr><td class="mono">'+k+'</td><td class="num">'+C[k]+'</td></tr>').join('')+
  '<tr><td class="mono">halfway_factor</td><td class="num">'+C.constraint_rules.halfway_factor+'</td></tr>';
$('cfgGrades').innerHTML = '<table><tr><th>source</th><th class="num">grade q</th><th class="num">pseudo-n</th></tr>'+
  Object.keys(C.grades).map(k=>'<tr><td class="mono">'+esc(k)+'</td><td class="num">'+C.grades[k]+'</td><td class="num">'+(C.pseudo_n[k]!=null?C.pseudo_n[k]:'—')+'</td></tr>').join('')+'</table>'+
  '<div class="note">'+esc(C.grades_note)+'</div>'+
  '<div class="note"><b>Weight formula:</b> w = q · min(n, cap) · λ^(Δt) — grade × capped sample size × recency decay over a '+C.window_weeks+'-week window. '+
  'The aggregated share IS the win probability; bootstrap replicates give the 89% bands.</div>';

// ---- matrix
if(nRows){
  const metaKeys = ['obs_id','source_name','source_grade','obs_type','sample_size','timestamp','week','active_set','poll_url','collection_method','snapshot_id','n_collapsed','provenance','carried'];
  const names = Object.keys(D.matrix[0]).filter(k=>metaKeys.indexOf(k)<0);
  $('matrixSummary').innerHTML = '<span class="chip">obs rows: '+nRows+'</span>'+
    D.matrix.map(r=>'<span class="chip">wk'+r.week+' · '+esc(r.source_name)+' · grade '+Number(r.source_grade).toFixed(2)+' · '+esc(r.obs_type)+' · n='+r.sample_size+(r.carried==='True'?' · carried':'')+'</span>').join('');
  $('matrixTbl').innerHTML = '<tr><th>obs_id</th><th>wk</th><th>source</th><th class="num">q</th><th>type</th><th class="num">n</th><th class="num">date</th><th>carried</th>'+
    names.map(n=>'<th class="num">'+esc(n.replace(/_/g,' '))+'</th>').join('')+'</tr>'+
    D.matrix.map(r=>'<tr><td class="mono" style="font-size:10px">'+esc(r.obs_id)+'</td><td class="num">'+r.week+'</td>'+
      '<td class="mono" style="font-size:10.5px">'+esc(r.source_name)+'</td><td class="num">'+f3(+r.source_grade)+'</td>'+
      '<td class="mono" style="font-size:10.5px">'+esc(r.obs_type)+'</td><td class="num">'+r.sample_size+'</td>'+
      '<td class="num" style="font-size:10.5px">'+esc(r.timestamp)+'</td>'+
      '<td>'+(r.carried==='True'?'<span style="color:var(--gold)">carried</span>':'—')+'</td>'+
      names.map(n=>'<td class="num">'+(r[n]?pct(+r[n]):'·')+'</td>').join('')+'</tr>').join('');
  $('matrixNote').innerHTML = '<b>One row = one poll observation.</b> Rebuilt every run from data/raw/week_XX/ snapshots + docs/polls.json seeds — the CSV is a derived cache, never a source. '+
    'Latest-wins dedupe per (source, week); same-week rerun replaces that week\'s row; bootstrap replicates keep all eligible names before carry-forward.';
}

// ---- polls log
const stateChip = s => {
  const colors = {ok:'var(--teal)',empty:'var(--faint)',skipped:'var(--faint)',unreachable:'var(--red)','needs-transcription':'var(--gold)','not-in-feed':'var(--faint)'};
  const c = colors[s.state]||'var(--muted)';
  return '<span class="chip" style="color:'+c+';border-color:'+c+'">'+esc(s.source)+': '+esc(s.state)+'</span>';
};
$('pollStates').innerHTML = D.polls.weeks.slice().sort((a,b)=>a.week-b.week).map(w=>{
  const st = w.sources ? w.sources.map(stateChip).join(' ') : '<span class="chip" style="color:var(--gold)">'+esc((w.source||'').split(' ')[0])+' full poll · '+w.poll.length+' rows</span>';
  return '<div style="margin:6px 0;font-size:12px"><b>wk'+w.week+'</b> '+(w.recorded_at?'<span class="mono" style="color:var(--faint);font-size:10.5px">'+esc(String(w.recorded_at).slice(0,16))+'</span>':'')+' '+st+'</div>';
}).join('');
const w8 = D.polls.weeks.find(w=>w.poll&&w.poll.length);
if(w8){
  const maxP = Math.max.apply(null, w8.poll.map(p=>p.pct));
  $('w8poll').innerHTML = '<table><tr><th>#</th><th>Housemate</th><th class="num">save %</th><th class="num">votes</th><th></th></tr>'+
    w8.poll.map((p,i)=>'<tr><td class="num">'+(i+1)+'</td><td><b>'+esc(p.name)+'</b></td><td class="num">'+p.pct.toFixed(2)+'</td><td class="num">'+p.votes.toLocaleString()+'</td>'+
      '<td style="width:35%"><div class="bar" style="width:'+(100*p.pct/maxP).toFixed(1)+'%"></div></td></tr>').join('')+'</table>'+
    '<div class="note">'+esc(w8.source)+'</div>';
  const mc = w8.model_at_snapshot;
  if(mc){
    $('concord').innerHTML =
      '<div class="note">hazard concordance <b class="mono">'+mc.hazard_concordance.agree+'/'+mc.hazard_concordance.pairs+' = '+mc.hazard_concordance.score.toFixed(3)+'</b> (0.5 = coin flip; vs the retired MCMC — review telemetry only)</div>'+
      '<table><tr><th>Housemate</th><th class="num">poll %</th><th class="num">P(#1)</th><th class="num">rel hazard</th></tr>'+
      w8.poll.map(p=>{const m=mc.per_housemate[p.name];return '<tr><td>'+esc(p.name)+'</td><td class="num">'+p.pct+'</td><td class="num">'+f3(m.p_rank_1)+'</td><td class="num">'+f3(m.rel_hazard)+'</td></tr>';}).join('')+'</table>'+
      '<div class="note">poll top-3 ['+mc.poll_top3.map(esc).join(', ')+'] vs model top-3 ['+mc.model_p_rank_1_top3.map(esc).join(', ')+'] — the documented coverage-vs-vote-intensity gap.</div>';
  }
}
$('pollNote').innerHTML = '<b>Seeds &amp; manual rows</b> enter as full_share observations graded by origin (widget transcription = A, FB groups = B, rank-only = C). '+
  'Weeks 1–7 and 9 currently have <b>no poll numbers</b> — the engine is gap-tolerant; missing weeks are no-ops, never fabricated. '+
  'Wk-9\'s in-window "empty" is by design: the widget shows a voting form (no percentages) until Sat 21:00 close. '+
  'Backfilled FINAL snapshots never anchor shares (outcome-leakage rule).';

// ---- snapshots
const srcCols = ['bbnaijadaily','bbnaijadaily-result-image','ngnews247','manual'];
const stateColor = s => ({ok:'var(--teal)',empty:'var(--faint)',skipped:'var(--faint)',unreachable:'var(--red)','needs-transcription':'var(--gold)','not-in-feed':'var(--faint)'})[s]||'var(--muted)';
$('snapTbl').innerHTML = '<tr><th>wk</th><th>week of</th><th>type</th><th>captured</th>'+
  srcCols.map(c=>'<th>'+esc(c.replace(/-/g,' '))+'</th>').join('')+'<th>archived files</th></tr>'+
  Object.values(D.snaps).map(e=>{
    const s=e.snapshot||{};
    const bysrc={}; (s.sources||[]).forEach(x=>{bysrc[x.source]=x;});
    return '<tr><td><b>wk'+e.week+'</b></td><td class="mono">'+esc(e.week_start)+'</td>'+
      '<td class="mono" style="font-size:10.5px">'+esc(s.snapshot_type||'—')+'</td>'+
      '<td class="mono" style="font-size:10.5px">'+(s.captured_at?esc(s.captured_at.slice(0,16)):'—')+'</td>'+
      srcCols.map(c=>{
        const x=bysrc[c];
        if(!x) return '<td style="color:var(--faint)">·</td>';
        const col=stateColor(x.state);
        const n=(x.entries||[]).length;
        return '<td><span class="chip" style="color:'+col+';border-color:'+col+'">'+esc(x.state)+(n?' · '+n:'')+'</span></td>';
      }).join('')+
      '<td class="mono" style="font-size:10px;color:var(--faint)">'+esc(e.files.join(', '))+'</td></tr>';
  }).join('');
$('snapDetails').innerHTML = Object.values(D.snaps).map(e=>{
  const s=e.snapshot||{};
  const entries=(s.sources||[]).reduce((acc,src)=>acc.concat((src.entries||[]).map(en=>({src:src.source,name:en.name,pct:en.pct,votes:en.votes}))),[]);
  return '<details><summary>wk'+e.week+' — '+(s.sources||[]).length+' sources, '+entries.length+' entries — click to inspect</summary>'+
    '<div class="inner">'+
    (entries.length?entries.map(en=>'<div class="item"><div class="t">'+esc(en.name)+'</div><div class="m">'+esc(en.src)+' · '+pct(en.pct)+(en.votes?' · '+en.votes.toLocaleString()+' votes':'')+'</div></div>').join(''):'<div class="note">no entries (empty / skipped / needs-transcription)</div>')+
    '</div></details>';
}).join('');
$('snapNote').innerHTML = '<b>Widget timing model (verified 2026-09-23):</b> Mon 20:00→Sat 21:00 = voting form, no percentages (snapshot <i>empty</i> by design). '+
  'After close = results view with percentages (grade-A capture). Post-show = final chart is an image → archived for human transcription. '+
  'Each week\'s final shares feed the NEXT week\'s window — the engine is a last-final-plus-momentum predictor on Saturdays.';

// ---- manual notes
$('manualTbl').innerHTML = '<table><tr><th>date</th><th>wk</th><th>housemate</th><th>type</th><th>value</th><th>notes</th></tr>'+
  D.manual_notes.map(r=>'<tr><td class="mono">'+esc(r.date)+'</td><td class="num">'+esc(r.week)+'</td><td>'+(esc(r.housemate)||'—')+'</td>'+
    '<td class="mono">'+esc(r.note_type)+'</td><td style="max-width:340px">'+esc(r.value)+'</td><td style="max-width:420px;font-size:11px">'+esc(r.notes)+'</td></tr>').join('')+'</table>';

// ---- roster
$('rosterTbl').innerHTML = '<tr><th>Name</th><th>Sex</th><th>Status</th><th class="num">Exit wk</th><th>Enters matrix?</th><th>Gambit</th></tr>'+
  D.housemates.map(h=>{
    const inM = h.status==='active';
    const gambitNote = (h.name==='Flora'||h.name==='Aikou') ? 'wk1–5 (released wk6)' : '—';
    return '<tr><td><b>'+esc(h.name)+'</b></td><td>'+esc(h.sex)+'</td>'+
      '<td>'+esc(h.status)+'</td><td class="num">'+(h.exit_week!=null?h.exit_week:'—')+'</td>'+
      '<td>'+(inM?'<span style="color:var(--teal)">yes</span>':'<span style="color:var(--faint)">no (exited)</span>')+'</td>'+
      '<td class="mono" style="font-size:10.5px">'+gambitNote+'</td></tr>';
  }).join('');
$('rosterNote').innerHTML = '<b>Eligibility:</b> exited housemates never enter the matrix; active Gambit members never enter (excluded from shares, keep runner-up eligibility). '+
  esc(D.roster_note)+' <b style="color:var(--gold)">Abi &amp; Araga still marked active in config although evicted wk7 — fix before the next run.</b>';

// ---- track record
const T = D.track;
$('trackPanel').innerHTML = '<table><tr><th>wk</th><th>scored</th><th>reason</th></tr>'+
  T.weeks.map(w=>'<tr><td class="num">'+w.week+'</td><td class="mono" style="color:'+(w.scored?'var(--teal)':'var(--gold)')+'">'+w.scored+'</td><td style="font-size:11px">'+esc(w.reason||'')+'</td></tr>').join('')+'</table>'+
  '<div class="note">'+T.summary.weeks_scored+' weeks scored · hits '+T.summary.winner_survived_hits+' · mean Brier '+(T.summary.mean_brier!=null?T.summary.mean_brier:'—')+'</div>';

$('foot').innerHTML =
  '<b>Engine-input files shown:</b> <code>docs/polls.json</code> · <code>data/poll_matrix.csv</code> · <code>data/raw/week_XX/polls_snapshot.json</code> · '+
  '<code>data/raw/manual_notes.csv</code> · <code>config/poll_engine.json</code> · <code>config/housemates.json</code> · <code>config/twist.json</code> · <code>docs/track_record.json</code>.<br>'+
  'Regenerate any time: <code>python src/build_data_review.py</code>. Static, offline, $0 — no network calls on this page.';
</script>
</body>
</html>
"""

if __name__ == "__main__":
    sys.exit(main())
