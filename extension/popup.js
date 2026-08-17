/* CogniDiff popup, consent toggle, allowlist manager, data controls.
 *
 * Every value that comes back from storage or the network is written with
 * textContent, never innerHTML. A hostile string in the allowlist renders as
 * visible characters; it never executes. (Phase 6, Attack 8.)
 */

const $ = (id) => document.getElementById(id);
const send = (msg) => new Promise((res) => chrome.runtime.sendMessage(msg, res));

const DASHBOARD_URL = 'http://localhost:3000/pages/dashboard.html';

let statusTimer = null;

function say(text, isError = false) {
  const el = $('status');
  el.textContent = text;
  el.classList.toggle('err', isError);
  clearTimeout(statusTimer);
  if (text) statusTimer = setTimeout(() => { el.textContent = ''; el.classList.remove('err'); }, 6000);
}

// ---------------------------------------------------------------------------
// starfield, the same drifting field used across the CogniDiff web app
// ---------------------------------------------------------------------------

function starfield() {
  const canvas = $('stars');
  const ctx = canvas.getContext('2d');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  function size() {
    canvas.width = canvas.offsetWidth * dpr;
    canvas.height = canvas.offsetHeight * dpr;
  }
  size();

  const stars = Array.from({ length: 70 }, () => ({
    x: Math.random(), y: Math.random(),
    r: Math.random() * 1.1 + 0.25,
    a: Math.random() * 0.5 + 0.12,
    tw: Math.random() * 0.02 + 0.004,
    p: Math.random() * Math.PI * 2,
  }));

  function frame(t) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const s of stars) {
      const alpha = reduce ? s.a : s.a * (0.55 + 0.45 * Math.sin(s.p + t * s.tw));
      ctx.beginPath();
      ctx.arc(s.x * canvas.width, s.y * canvas.height, s.r * dpr, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(190, 226, 255, ${alpha})`;
      ctx.fill();
    }
    if (!reduce) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

// ---------------------------------------------------------------------------
// monitoring toggle
// ---------------------------------------------------------------------------

function paintToggle(active) {
  $('toggle').checked = active;
  const label = $('toggleState');
  label.textContent = active ? 'ON' : 'OFF';
  label.classList.toggle('val-on', active);
  label.classList.toggle('val-off', !active);
  $('ftState').textContent = active ? 'CAPTURING' : 'IDLE';
}

$('toggle').addEventListener('change', async (e) => {
  const active = e.target.checked;
  await chrome.storage.local.set({ monitoring_active: active });
  paintToggle(active);
  say(active
    ? 'Monitoring on. Rhythm features only, never your text.'
    : 'Monitoring off. Nothing is being captured.');
});

// ---------------------------------------------------------------------------
// allowlist
// ---------------------------------------------------------------------------

function renderAllowlist(list) {
  const ul = $('allowlist');
  ul.textContent = '';

  if (list.length === 0) {
    const li = document.createElement('li');
    li.className = 'empty';
    li.textContent = 'No sites added, monitoring is inactive.';
    ul.appendChild(li);
    return;
  }

  for (const host of list) {
    const li = document.createElement('li');

    const name = document.createElement('span');
    name.textContent = host;                    // textContent, never innerHTML
    li.appendChild(name);

    const rm = document.createElement('button');
    rm.className = 'rm';
    rm.type = 'button';
    rm.textContent = '×';
    rm.setAttribute('aria-label', `Stop monitoring ${host}`);
    rm.addEventListener('click', async () => {
      const next = list.filter((h) => h !== host);
      await chrome.storage.local.set({ site_allowlist: next });
      renderAllowlist(next);
      say(`Removed ${host}.`);
    });
    li.appendChild(rm);

    ul.appendChild(li);
  }
}

$('addForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const input = $('newSite');
  const host = input.value.trim().toLowerCase()
    .replace(/^https?:\/\//, '')
    .replace(/\/.*$/, '');

  if (!/^[a-z0-9.-]+\.[a-z]{2,}$/.test(host)) {
    say('Enter a valid domain, for example docs.google.com', true);
    return;
  }

  const { site_allowlist = [] } = await chrome.storage.local.get('site_allowlist');
  if (site_allowlist.includes(host)) { say('Already on the list.'); return; }

  const next = [...site_allowlist, host];
  await chrome.storage.local.set({ site_allowlist: next });
  renderAllowlist(next);
  input.value = '';
  say(`Now monitoring ${host}. You may need to reload that tab.`);
});

// ---------------------------------------------------------------------------
// stats
// ---------------------------------------------------------------------------

async function refreshStats() {
  const s = await send({ type: 'get_summary' });
  if (!s) return;
  $('sToday').textContent = s.today_sessions ?? 0;
  $('sWpm').textContent   = s.avg_wpm ? s.avg_wpm : ',';
  $('sIki').textContent   = s.avg_iki_ms ? `${Math.round(s.avg_iki_ms)}ms` : ',';
  $('sQueue').textContent = s.pending ?? 0;
}

async function refreshLink() {
  const pill = $('linkState');
  try {
    const res = await fetch('http://localhost:8000/api/health', { cache: 'no-store' });
    const ok = res.ok;
    pill.textContent = ok ? 'LINKED' : 'DEGRADED';
    pill.className = `pill ${ok ? 'pill-on' : 'pill-off'}`;
  } catch {
    pill.textContent = 'OFFLINE';
    pill.className = 'pill pill-off';
  }
}

// ---------------------------------------------------------------------------
// data controls
// ---------------------------------------------------------------------------

$('viewData').addEventListener('click', async () => {
  const data = await send({ type: 'get_all_data' });
  const dump = $('dump');
  const recent = (data.sessions || []).slice(-5).map((s) => ({
    date: s.date, hour: s.hour,
    wpm: s.wpm_estimate,
    iki_ms: s.avg_inter_key_interval_ms,
    hold_ms: s.avg_hold_duration_ms,
    keystrokes: s.total_keystrokes,
    backspaces: s.backspace_count,
    pauses: s.pause_count,
  }));

  dump.hidden = false;
  dump.textContent =
    `${data.count} session(s) stored locally, ${data.pending} awaiting upload.\n` +
    `Most recent 5 (note: numbers only, no typed text exists anywhere):\n\n` +
    JSON.stringify(recent, null, 2);
  say('Showing your locally stored features.');
});

$('openDash').addEventListener('click', () => {
  chrome.tabs.create({ url: DASHBOARD_URL });
});

$('deleteData').addEventListener('click', async () => {
  const ok = confirm(
    'Delete every locally stored CogniDiff session on this device?\n\n' +
    'This cannot be undone. Data already synced to your account is removed ' +
    'separately from the dashboard.'
  );
  if (!ok) return;

  const res = await send({ type: 'clear_all_data' });
  $('dump').hidden = true;
  await refreshStats();
  say(res.message || 'Deleted.');
});

// ---------------------------------------------------------------------------
// boot
// ---------------------------------------------------------------------------

(async function init() {
  starfield();

  const { monitoring_active = false, site_allowlist = [] } =
    await chrome.storage.local.get(['monitoring_active', 'site_allowlist']);

  paintToggle(monitoring_active);
  renderAllowlist(site_allowlist);
  await refreshStats();
  await refreshLink();
})();
