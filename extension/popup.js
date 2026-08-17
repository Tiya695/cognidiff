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
// monitored sites
//
// Adding a site means asking Chrome for the host permission. That call must
// happen here, in the popup, because chrome.permissions.request() only works
// from a user gesture; the service worker then registers the content script
// once the permission is actually held.
// ---------------------------------------------------------------------------

const patternsFor = (host) => [`https://${host}/*`, `http://${host}/*`];

function renderSites(list) {
  const ul = $('allowlist');
  ul.textContent = '';

  if (!list || list.length === 0) {
    const li = document.createElement('li');
    li.className = 'empty';
    li.textContent = 'No sites approved yet. Nothing is being captured.';
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
      const res = await send({ type: 'remove_site', host });
      renderSites(res.sites);
      await refreshCurrentSite();
      say(`Stopped monitoring ${host}. Chrome access revoked.`);
    });
    li.appendChild(rm);

    ul.appendChild(li);
  }
}

/** Ask Chrome for the host, then have the worker register the script. */
async function requestSite(host) {
  let granted = false;
  try {
    granted = await chrome.permissions.request({ origins: patternsFor(host) });
  } catch (err) {
    say('Chrome refused that site pattern.', true);
    return false;
  }
  if (!granted) { say('Permission declined, nothing changed.', true); return false; }

  const res = await send({ type: 'add_site', host });
  if (!res.added) { say('Could not enable that site.', true); return false; }

  renderSites(res.sites);
  say(`Now monitoring ${host}. Reload that tab to start capturing.`);
  return true;
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
  if (await requestSite(host)) input.value = '';
});

// --- the site you are actually on ------------------------------------------

let currentHost = null;

async function refreshCurrentSite() {
  const box = $('currentSite');
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !tab.url || !/^https?:/.test(tab.url)) { box.hidden = true; return; }

    currentHost = new URL(tab.url).hostname;
    const { monitored_sites = [] } = await chrome.storage.local.get('monitored_sites');
    const already = monitored_sites.includes(currentHost);

    $('curHost').textContent = currentHost;
    $('enableHere').textContent = already ? 'ALREADY MONITORED' : 'MONITOR THIS SITE';
    $('enableHere').disabled = already;
    box.hidden = false;
  } catch {
    box.hidden = true;
  }
}

$('enableHere').addEventListener('click', async () => {
  if (!currentHost) return;
  if (await requestSite(currentHost)) await refreshCurrentSite();
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
// account
//
// The missing link that made the extension local-only: batches are sent with a
// Bearer token, but nothing ever put a token into chrome.storage. Signing in
// here stores the token, and the pending queue is flushed immediately so
// sessions captured while signed out reach the account too.
// ---------------------------------------------------------------------------

async function refreshAccount() {
  const { auth_token = null, account_name = null } =
    await chrome.storage.local.get(['auth_token', 'account_name']);
  const signedIn = Boolean(auth_token);
  $('signedOut').hidden = signedIn;
  $('signedIn').hidden = !signedIn;
  if (signedIn) $('acctName').textContent = account_name || 'you';
}

$('loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const username = $('acctUser').value.trim();
  const password = $('acctPass').value;
  if (!username || !password) { say('Enter your username and password.', true); return; }

  say('Signing in…');
  try {
    const res = await fetch('http://localhost:8000/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) { say(body.detail || 'Sign in failed.', true); return; }

    await chrome.storage.local.set({
      auth_token: body.access_token,
      account_name: body.first_name || body.username,
    });
    $('acctPass').value = '';

    const drained = await send({ type: 'flush_queue' });
    say(drained && drained.sent
      ? `Signed in. ${drained.sent} queued session(s) uploaded.`
      : 'Signed in. Syncing is on.');

    await refreshAccount();
    await refreshStats();
    await refreshLink();
  } catch {
    say('Cannot reach the API on port 8000. Is the backend running?', true);
  }
});

$('signOutBtn').addEventListener('click', async () => {
  await chrome.storage.local.remove(['auth_token', 'account_name']);
  say('Signed out. Capture continues, sessions stay on this device.');
  await refreshAccount();
});

// ---------------------------------------------------------------------------
// boot
// ---------------------------------------------------------------------------

(async function init() {
  starfield();

  const { monitoring_active = false } =
    await chrome.storage.local.get('monitoring_active');

  paintToggle(monitoring_active);

  // syncSites() reconciles against the permissions actually held, so a site
  // revoked from chrome://extensions disappears here too.
  const { sites } = await send({ type: 'get_sites' });
  renderSites(sites);
  await refreshCurrentSite();
  await refreshAccount();
  await refreshStats();
  await refreshLink();
})();
