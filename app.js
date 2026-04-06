'use strict';
// ry-web-dashboard v1.4.0 — frontend application

// ── Theme ─────────────────────────────────────────────────────────────────
const THEME_KEY = 'ry-dash-theme';
function getTheme() {
  try { return localStorage.getItem(THEME_KEY); } catch { return null; }
}
function setTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  try { localStorage.setItem(THEME_KEY, t); } catch {}
  const btn = document.getElementById('theme-toggle');
  if (btn) btn.textContent = t === 'light' ? '\u2600' : '\u263E';
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = t === 'light' ? '#ffffff' : '#0a0c10';
}
function initTheme() {
  const saved = getTheme();
  if (saved) { setTheme(saved); }
  else if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) { setTheme('light'); }
  else { setTheme('dark'); }
}
function toggleTheme() {
  setTheme(getTheme() === 'light' ? 'dark' : 'light');
}
initTheme();

// ── Config ────────────────────────────────────────────────────────────────
const TABS = [
  { id: 'monitor',   label: 'Monitor' },
  { id: 'diagnose',  label: 'Diagnose' },
  { id: 'drift',     label: 'Config Drift' },
  { id: 'runtime',   label: 'Runtime' },
  { id: 'logs',      label: 'Logs' },
  { id: 'lint',      label: 'Lint' },
  { id: 'actions',   label: 'Actions' },
  { id: 'changelog', label: 'Changelog' },
];
const HIST = 30;
const hist = { cpu: [], gpu: [] };
let activeTab = 'monitor';
let running = false;
let evtSrc = null;
let filesLoaded = false;

// ── DOM helpers ───────────────────────────────────────────────────────────
const $ = (s, p) => (p || document).querySelector(s);
const $$ = (s, p) => [...(p || document).querySelectorAll(s)];
const h = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };

function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

function colorize(text) {
  return esc(text)
    .replace(/\[OK]/g, '<span class="c-ok">[OK]</span>')
    .replace(/\[FAIL]/g, '<span class="c-err">[FAIL]</span>')
    .replace(/\[WARN]/g, '<span class="c-warn">[WARN]</span>')
    .replace(/\[INFO]/g, '<span class="c-info">[INFO]</span>')
    .replace(/\[DRY]/g, '<span class="c-info">[DRY]</span>')
    .replace(/\[ERR]/g, '<span class="c-err">[ERR]</span>')
    .replace(/^(──.*|══.*|[┌┐└┘│├┤┬┴┼].*)/gm, '<span class="c-dim">$1</span>')
    .replace(/(✓[^\n]*)/g, '<span class="c-ok">$1</span>')
    .replace(/(✗[^\n]*)/g, '<span class="c-err">$1</span>');
}

function toast(msg, type) {
  const el = h('div', 'toast' + (type ? ' toast-' + type : ''), msg);
  $('#toasts').appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

async function api(url, opts) {
  try {
    const r = await fetch(url, opts);
    if (!r.ok) {
      const t = await r.text();
      try { return JSON.parse(t); } catch { toast(`HTTP ${r.status}: ${t.slice(0, 120)}`, 'err'); return null; }
    }
    return await r.json();
  } catch (e) { toast('Request failed: ' + e.message, 'err'); return null; }
}

function setRunning(v) {
  running = v;
  $$('.btn-run').forEach(b => b.disabled = v);
}

function showTerm(id, html) {
  const el = $('#' + id);
  if (!el) return;
  el.innerHTML = html;
  const sec = el.closest('.sec');
  if (sec) sec.classList.remove('hidden');
}

function loadingTerm(id) {
  showTerm(id, '<span class="spin"></span> Running\u2026');
}

// ── Build tabs ────────────────────────────────────────────────────────────
function buildNav() {
  const nav = $('#tabs');
  TABS.forEach(t => {
    const btn = h('button', t.id === activeTab ? 'active' : '', t.label);
    btn.dataset.tab = t.id;
    nav.appendChild(btn);
  });
  nav.addEventListener('click', e => {
    const btn = e.target.closest('button[data-tab]');
    if (!btn) return;
    activeTab = btn.dataset.tab;
    $$('#tabs button').forEach(b => b.classList.toggle('active', b.dataset.tab === activeTab));
    $$('.tab', $('#main')).forEach(p => p.classList.toggle('hidden', p.id !== 'p-' + activeTab));
    if (activeTab === 'actions' && !filesLoaded) { loadFiles(); filesLoaded = true; }
  });
}

// ── Build panels ──────────────────────────────────────────────────────────
function buildPanels() {
  const m = $('#main');
  m.innerHTML = `
<div class="tab" id="p-monitor">
  <div class="sec"><div class="g g4" id="top-row">
    <div class="c"><div class="c-label">CPU Temp</div><div class="val" id="v-ct">\u2014<span class="unit">\u00b0C</span></div><div class="sub" id="v-cg"></div><div class="spark" id="sp-cpu"></div></div>
    <div class="c"><div class="c-label">GPU Temp</div><div class="val" id="v-gt">\u2014<span class="unit">\u00b0C</span></div><div class="sub" id="v-gp"></div><div class="spark" id="sp-gpu"></div></div>
    <div class="c"><div class="c-label">GPU Load</div><div class="val" id="v-gb">\u2014<span class="unit">%</span></div><div class="sub" id="v-vr"></div><div class="bar-track"><div class="bar-fill" id="b-gpu" style="width:0;background:var(--accent)"></div></div></div>
    <div class="c"><div class="c-label">Memory</div><div class="val" id="v-mu">\u2014<span class="unit">GB</span></div><div class="sub" id="v-md"></div><div class="bar-track"><div class="bar-fill" id="b-mem" style="width:0;background:var(--cyan)"></div></div></div>
  </div></div>
  <div class="sec"><div class="g g3">
    <div class="c"><div class="c-label">Power</div><div class="sub" id="v-pw" style="font-size:12px;margin-top:2px">\u2014</div></div>
    <div class="c"><div class="c-label">Swap</div><div class="val val-sm" id="v-sw">\u2014</div><div class="bar-track"><div class="bar-fill" id="b-swap" style="width:0;background:var(--orange)"></div></div></div>
    <div class="c"><div class="c-label">Disk /</div><div class="val val-sm" id="v-dk">\u2014<span class="unit">%</span></div><div class="bar-track"><div class="bar-fill" id="b-disk" style="width:0;background:var(--ok)"></div></div></div>
  </div></div>
  <div class="sec"><div class="g g2">
    <div class="c"><div class="c-label">Network</div><div id="v-net"></div></div>
    <div class="c"><div class="c-label">Services</div><div id="v-svc"></div></div>
  </div></div>
  <div class="sec"><div class="g g3">
    <div class="c"><div class="c-label">ntsync</div><div id="v-nts"></div></div>
    <div class="c"><div class="c-label">ZRAM</div><div class="sub" id="v-zram">\u2014</div></div>
    <div class="c"><div class="c-label">Load Average</div><div class="sub" id="v-load" style="font-size:15px;font-family:var(--mono)">\u2014</div></div>
  </div></div>
</div>
<div class="tab hidden" id="p-diagnose">
  <div class="toolbar"><h2>System Diagnostics</h2><button class="btn btn-p btn-run" id="btn-diag">Run Diagnose</button></div>
  <div class="sec hidden" id="diag-cards-sec"><div class="g g3" id="diag-cards"></div></div>
  <div class="sec hidden" id="diag-out-sec"><div class="sec-label">Output</div><div class="term" id="t-diag"></div></div>
</div>
<div class="tab hidden" id="p-drift">
  <div class="toolbar"><h2>Config Drift</h2>
    <div class="btns"><button class="btn btn-run" id="btn-diff">Diff</button><button class="btn btn-run" id="btn-vs">Verify Static</button></div>
  </div>
  <div class="sec hidden" id="drift-sec"><div class="term" id="t-drift"></div></div>
</div>
<div class="tab hidden" id="p-runtime">
  <div class="toolbar"><h2>Runtime Verification</h2><button class="btn btn-p btn-run" id="btn-vr">Verify Runtime</button></div>
  <div class="sec hidden" id="runtime-sec"><div class="term" id="t-runtime"></div></div>
</div>
<div class="tab hidden" id="p-logs">
  <div class="toolbar"><h2>Log Viewer</h2>
    <select id="log-sel"><option>system</option><option>gpu</option><option>wifi</option><option>boot</option><option>audio</option><option>usb</option><option>kernel</option><option disabled>──────</option><option>last</option><option>list</option><option>all</option><option>analyze</option></select>
    <button class="btn btn-p btn-run" id="btn-logs">Fetch</button>
  </div>
  <div class="sec hidden" id="logs-sec"><div class="term" id="t-logs"></div></div>
</div>
<div class="tab hidden" id="p-lint">
  <div class="toolbar"><h2>Lint</h2><button class="btn btn-p btn-run" id="btn-lint">Run Lint</button></div>
  <div class="sec hidden" id="lint-sec"><div class="term" id="t-lint"></div></div>
</div>
<div class="tab hidden" id="p-actions">
  <div class="sec">
    <div class="sec-label">System Cleanup</div>
    <div class="c">
      <p style="color:var(--text-dim);margin-bottom:10px;font-size:12px">Clean package cache, journal, orphans.</p>
      <div class="btns"><button class="btn btn-run" id="btn-clean-dry">Dry Run</button><button class="btn btn-d btn-run" id="btn-clean">Clean System</button></div>
    </div>
  </div>
  <div class="sec">
    <div class="sec-label">Install / Re-deploy</div>
    <div class="c">
      <p style="color:var(--text-dim);margin-bottom:10px;font-size:12px">Full ry-install deployment \u2014 configs, packages, services.</p>
      <div class="btns"><button class="btn btn-run" id="btn-inst-dry">Dry Run</button><button class="btn btn-d btn-run" id="btn-inst">Install All</button></div>
    </div>
  </div>
  <div class="sec">
    <div class="sec-label">Re-deploy Single File</div>
    <div class="c" id="files-card"><div class="empty">Loading managed files\u2026</div></div>
  </div>
  <div class="sec">
    <div class="sec-label">System Profile</div>
    <div class="c">
      <p style="color:var(--text-dim);margin-bottom:10px;font-size:12px">Capture hardware and configuration snapshot for diagnostics.</p>
      <button class="btn btn-p btn-run" id="btn-profile">Run Profile</button>
    </div>
  </div>
  <div class="sec">
    <div class="sec-label">Stress Test</div>
    <div class="c">
      <p style="color:var(--text-dim);margin-bottom:10px;font-size:12px">CPU/GPU thermal stress test with sensor monitoring.</p>
      <button class="btn btn-d btn-run" id="btn-stress">Run Stress</button>
    </div>
  </div>
  <div class="sec">
    <div class="sec-label">Test Suite</div>
    <div class="c">
      <p style="color:var(--text-dim);margin-bottom:10px;font-size:12px">Run all safe modes, generate NDJSON logs.</p>
      <button class="btn btn-run" id="btn-test">Run Test All</button>
    </div>
  </div>
  <div class="sec hidden" id="action-sec"><div class="sec-label">Output</div><div class="term" id="t-action"></div></div>
</div>
<div class="tab hidden" id="p-changelog">
  <div class="toolbar"><h2>Changelog</h2><button class="btn btn-run" id="btn-clog">Load</button></div>
  <div class="sec hidden" id="clog-sec"><div class="term" id="t-clog"></div></div>
</div>
`;
}

// ── Wire events ───────────────────────────────────────────────────────────
function wireEvents() {
  const on = (id, fn) => { const el = $('#' + id); if (el) el.addEventListener('click', fn); };

  on('theme-toggle', toggleTheme);
  on('btn-diag', runDiagnose);
  on('btn-diff', () => runSimple('/api/diff', 't-drift'));
  on('btn-vs', () => runSimple('/api/verify/static', 't-drift'));
  on('btn-vr', () => runSimple('/api/verify/runtime', 't-runtime'));
  on('btn-lint', () => runSimple('/api/lint', 't-lint'));
  on('btn-logs', () => { const t = $('#log-sel').value; runSimple('/api/logs/' + t, 't-logs'); });
  on('btn-clog', () => runSimple('/api/changelog', 't-clog'));

  on('btn-clean-dry', () => runPost('/api/clean', true));
  on('btn-clean', () => showConfirm('Confirm Cleanup', 'Remove package cache, journal, orphans. Cannot be undone.', () => runPost('/api/clean', false)));
  on('btn-inst-dry', () => runPost('/api/install', true));
  on('btn-inst', () => showConfirm('Confirm Install', 'Deploy all managed configs, packages, and services.', () => runPost('/api/install', false)));
  on('btn-test', () => runPost('/api/test-all', null));
  on('btn-profile', () => runPost('/api/profile', null));
  on('btn-stress', () => showConfirm('Confirm Stress Test', 'Run CPU/GPU thermal stress test. System will be under full load.', () => runPost('/api/stress', null)));

  $('#files-card').addEventListener('click', e => {
    const btn = e.target.closest('button[data-path]');
    if (!btn) return;
    const path = btn.dataset.path;
    const dry = btn.dataset.dry === '1';
    if (dry) {
      runFileInstall(path, true);
    } else {
      showConfirm('Deploy File', 'Re-deploy: ' + path, () => runFileInstall(path, false));
    }
  });
}

// ── API runners ───────────────────────────────────────────────────────────
async function runSimple(url, termId) {
  if (running) return;
  setRunning(true);
  loadingTerm(termId);
  const d = await api(url);
  setRunning(false);
  if (!d) { showTerm(termId, '<span class="c-err">Request failed</span>'); return; }
  let out = colorize(d.output || '(no output)');
  if (d.stderr) out += '\n\n<span class="c-err">' + esc(d.stderr) + '</span>';
  showTerm(termId, out);
}

async function runDiagnose() {
  if (running) return;
  setRunning(true);
  loadingTerm('t-diag');
  $('#diag-cards-sec').classList.add('hidden');
  const d = await api('/api/diagnose');
  setRunning(false);
  if (!d) { showTerm('t-diag', '<span class="c-err">Request failed</span>'); return; }

  if (d.checks != null) {
    const cards = $('#diag-cards');
    cards.innerHTML = '';

    const rc = h('div', 'c');
    const rcl = h('div', 'c-label', 'Result'); rc.appendChild(rcl);
    const badge = h('span', 'badge ' + (d.issues === 0 ? 'badge-ok' : 'badge-warn'));
    badge.textContent = d.issues === 0 ? '\u2713 All clear' : d.issues + ' issue(s)';
    rc.appendChild(badge);
    const sub = h('div', 'sub'); sub.textContent = d.checks + ' checks'; rc.appendChild(sub);
    cards.appendChild(rc);

    const cc = h('div', 'c');
    const ccl = h('div', 'c-label', 'CPU'); cc.appendChild(ccl);
    const gov = d.cpu?.governor ?? d.cpu?.gov ?? '?';
    const epp = d.cpu?.epp ?? '?';
    const ct = d.cpu?.temp_c ?? d.cpu?.temp;
    const cs = h('div', 'sub'); cs.textContent = gov + ' / ' + epp; cc.appendChild(cs);
    if (ct != null) { const ctt = h('div', 'sub'); ctt.textContent = ct + '\u00b0C'; cc.appendChild(ctt); }
    cards.appendChild(cc);

    const gc = h('div', 'c');
    const gcl = h('div', 'c-label', 'GPU'); gc.appendChild(gcl);
    const gp = d.gpu?.perf_level ?? d.gpu?.perf ?? '?';
    const gt = d.gpu?.temp_c ?? d.gpu?.temp;
    const gs = h('div', 'sub'); gs.textContent = gp; gc.appendChild(gs);
    if (gt != null) { const gtt = h('div', 'sub'); gtt.textContent = gt + '\u00b0C'; gc.appendChild(gtt); }
    cards.appendChild(gc);

    $('#diag-cards-sec').classList.remove('hidden');
  }

  const raw = d._raw || d.output || JSON.stringify(d, null, 2);
  showTerm('t-diag', colorize(raw));
  $('#diag-out-sec').classList.remove('hidden');
}

async function runPost(url, dry) {
  if (running) return;
  setRunning(true);
  loadingTerm('t-action');
  const body = dry != null ? { dry_run: dry } : {};
  const d = await api(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  setRunning(false);
  if (!d) { showTerm('t-action', '<span class="c-err">Request failed</span>'); return; }
  const prefix = dry ? '[DRY RUN]\n\n' : '';
  showTerm('t-action', colorize(prefix + (d.output || '(no output)')));
  if (dry === false) toast(d.rc === 0 ? 'Complete' : 'Finished with errors', d.rc === 0 ? 'ok' : 'err');
}

async function runFileInstall(path, dry) {
  if (running) return;
  setRunning(true);
  loadingTerm('t-action');
  const d = await api('/api/install-file', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, dry_run: dry }),
  });
  setRunning(false);
  if (!d) { showTerm('t-action', '<span class="c-err">Request failed</span>'); return; }
  showTerm('t-action', colorize((dry ? '[DRY] ' : '') + path + '\n\n' + (d.output || '(no output)')));
}

async function loadFiles() {
  const d = await api('/api/managed-files');
  const card = $('#files-card');
  if (!d?.files?.length) { card.innerHTML = '<div class="empty">No managed files found</div>'; return; }
  const ul = h('ul', 'flist');
  d.files.forEach(f => {
    const li = document.createElement('li');
    const sp = h('span', '', f);
    const btns = h('div', 'btns');
    const bd = h('button', 'btn btn-sm btn-run', 'dry-run');
    bd.dataset.path = f; bd.dataset.dry = '1';
    const bl = h('button', 'btn btn-sm btn-d btn-run', 'deploy');
    bl.dataset.path = f; bl.dataset.dry = '0';
    btns.append(bd, bl);
    li.append(sp, btns);
    ul.appendChild(li);
  });
  card.innerHTML = '';
  card.appendChild(ul);
}

// ── Confirm dialog ────────────────────────────────────────────────────────
function showConfirm(title, desc, onOk) {
  const ov = $('#overlay');
  ov.innerHTML = '';
  const dlg = h('div', 'dialog');
  dlg.appendChild(h('h3', '', title));
  dlg.appendChild(h('p', '', desc));
  const btns = h('div', 'btns');
  const bc = h('button', 'btn', 'Cancel');
  bc.addEventListener('click', () => ov.classList.add('hidden'));
  const bo = h('button', 'btn btn-d', 'Confirm');
  bo.addEventListener('click', () => { ov.classList.add('hidden'); onOk(); });
  btns.append(bc, bo);
  dlg.appendChild(btns);
  ov.appendChild(dlg);
  ov.classList.remove('hidden');
}

// ── SSE ───────────────────────────────────────────────────────────────────
function connectSSE() {
  if (evtSrc) evtSrc.close();
  evtSrc = new EventSource('/api/telemetry/stream');
  evtSrc.onopen = () => { $('#conn').innerHTML = '<span class="dot dot-ok"></span>live'; };
  evtSrc.onmessage = e => { try { update(JSON.parse(e.data)); } catch {} };
  evtSrc.onerror = () => {
    if (evtSrc) evtSrc.close();
    evtSrc = null;
    $('#conn').innerHTML = '<span class="dot dot-err"></span>reconnecting';
    setTimeout(connectSSE, 5000);
  };
}

function update(d) {
  setVal('v-ct', d.cpu?.temp, '\u00b0C');
  const freq = d.cpu?.freq ? ' \u00b7 ' + d.cpu.freq + ' MHz' : '';
  setTxt('v-cg', (d.cpu?.gov || '?') + ' / ' + (d.cpu?.epp || '?') + freq);
  if (d.cpu?.temp != null) spark('sp-cpu', hist.cpu, d.cpu.temp, 95);

  setVal('v-gt', d.gpu?.temp, '\u00b0C');
  setTxt('v-gp', d.gpu?.perf || '?');
  if (d.gpu?.temp != null) spark('sp-gpu', hist.gpu, d.gpu.temp, 100);
  const gb = d.gpu?.busy ?? 0;
  setVal('v-gb', gb, '%');
  bar('b-gpu', gb, 100);
  const vu = d.gpu?.vram_used ?? 0, vt = d.gpu?.vram_total ?? 0;
  setTxt('v-vr', 'VRAM ' + (vu / 1024).toFixed(1) + 'G / ' + (vt / 1024).toFixed(1) + 'G');

  const mu = d.mem?.used ?? 0, mt = d.mem?.total ?? 1;
  setVal('v-mu', (mu / 1024).toFixed(1), 'GB');
  setTxt('v-md', (mt / 1024).toFixed(0) + 'G total \u00b7 ' + ((d.mem?.avail || 0) / 1024).toFixed(1) + 'G avail');
  bar('b-mem', mu, mt);

  let pw = [];
  if (d.power?.pkg != null) pw.push('Package ' + d.power.pkg + 'W');
  if (d.power?.gpu != null) pw.push('GPU ' + d.power.gpu + 'W');
  setTxt('v-pw', pw.join(' \u00b7 ') || '\u2014');

  const su = d.swap?.used ?? 0, sto = d.swap?.total ?? 0;
  setTxt('v-sw', su + 'M / ' + sto + 'M');
  bar('b-swap', su, Math.max(sto, 1));

  const dp = d.disk ?? 0;
  setVal('v-dk', dp, '%');
  bar('b-disk', dp, 100, dp > 90 ? 'var(--err)' : dp > 75 ? 'var(--warn)' : 'var(--ok)');

  const netEl = $('#v-net');
  netEl.innerHTML = '';
  (d.net || []).forEach(n => {
    const row = h('div', 'row');
    row.appendChild(h('span', '', n.name));
    const r = h('span', '');
    r.style.color = n.state === 'up' ? 'var(--ok)' : 'var(--text-dim)';
    let txt = n.state === 'up' ? '\u25b2' : '\u25bc';
    txt += ' ' + (n.wireless ? 'wifi' : 'eth');
    if (n.speed_mbps) txt += ' \u00b7 ' + (n.speed_mbps >= 1000 ? n.speed_mbps / 1000 + 'G' : n.speed_mbps + 'M');
    r.textContent = txt;
    row.appendChild(r);
    netEl.appendChild(row);
  });

  const svcEl = $('#v-svc');
  svcEl.innerHTML = '';
  if (d.svc) {
    Object.entries(d.svc).forEach(([k, v]) => {
      const row = h('div', 'row');
      row.appendChild(h('span', '', k));
      row.appendChild(h('span', 'badge ' + (v === 'active' ? 'badge-ok' : 'badge-warn'), v));
      svcEl.appendChild(row);
    });
  }

  const ntsEl = $('#v-nts');
  ntsEl.innerHTML = '';
  ntsEl.appendChild(h('span', 'badge ' + (d.ntsync ? 'badge-ok' : 'badge-info'), d.ntsync ? '\u2713 available' : '\u2717 unavailable'));

  const z = d.zram || {};
  setTxt('v-zram', z.active ? 'Active \u00b7 ' + z.algo + ' \u00b7 ' + z.size_gb + 'G' : 'Inactive');
  if (d.load?.length) setTxt('v-load', d.load.join('  '));
  if (d.kernel) setTxt('hdr-kernel', d.kernel);
}

// ── Update helpers ────────────────────────────────────────────────────────
function setVal(id, val, unit) {
  const el = $('#' + id);
  if (!el) return;
  el.textContent = '';
  el.appendChild(document.createTextNode(val != null ? val : '\u2014'));
  if (unit) el.appendChild(h('span', 'unit', unit));
}

function setTxt(id, txt) {
  const el = $('#' + id);
  if (el) el.textContent = txt;
}

function bar(id, val, max, color) {
  const el = $('#' + id);
  if (!el) return;
  el.style.width = Math.min(100, Math.max(0, (val / max) * 100)) + '%';
  if (color) el.style.background = color;
}

function spark(id, arr, val, mx) {
  arr.push(val);
  if (arr.length > HIST) arr.shift();
  const el = $('#' + id);
  if (!el) return;
  while (el.children.length < arr.length)
    el.appendChild(document.createElement('i'));
  while (el.children.length > arr.length)
    el.removeChild(el.lastChild);
  arr.forEach((v, idx) => {
    const s = el.children[idx];
    s.style.height = Math.max(2, (v / mx) * 36) + 'px';
    s.style.background = v > mx * 0.85 ? 'var(--err)' : v > mx * 0.7 ? 'var(--warn)' : 'var(--accent)';
    s.style.opacity = idx === arr.length - 1 ? '1' : '0.6';
  });
}

// ── Init ──────────────────────────────────────────────────────────────────
buildNav();
buildPanels();
wireEvents();
connectSSE();
