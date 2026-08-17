/* CogniDiff, background service worker.
 *
 * Receives 60-second feature batches from content scripts, stamps them with a
 * date and hour, keeps a local copy in chrome.storage.local, and forwards them
 * to the backend when it is reachable. If the backend is down the batch stays
 * local and is retried later, typing data is never dropped just because a
 * server is offline, and it is never sent anywhere else.
 */

const API_BASE = 'http://localhost:8000';
const MAX_LOCAL_SESSIONS = 5000;      // ring buffer, keeps storage bounded
const MAX_QUEUE = 500;

// ---------------------------------------------------------------------------
// storage helpers
// ---------------------------------------------------------------------------

async function get(key, fallback) {
  const out = await chrome.storage.local.get(key);
  return key in out ? out[key] : fallback;
}

const set = (obj) => chrome.storage.local.set(obj);

// ---------------------------------------------------------------------------
// batch handling
// ---------------------------------------------------------------------------

function stamp(batch) {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return {
    ...batch,
    date: `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`,
    hour: now.getHours(),
    received_at: now.toISOString(),
  };
}

async function storeLocally(batch) {
  const sessions = await get('session_data', []);
  sessions.push(batch);
  if (sessions.length > MAX_LOCAL_SESSIONS) {
    sessions.splice(0, sessions.length - MAX_LOCAL_SESSIONS);
  }
  await set({ session_data: sessions });
  return sessions.length;
}

/**
 * POST a batch to the backend. The auth token is issued by the dashboard login
 * and stored here by the popup, the extension never holds a password.
 */
async function sendToBackend(batch) {
  const token = await get('auth_token', null);
  if (!token) return { ok: false, reason: 'not_signed_in' };

  try {
    const res = await fetch(`${API_BASE}/api/session`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(batch),
    });

    if (res.status === 401) {
      await set({ auth_token: null });
      return { ok: false, reason: 'token_expired' };
    }
    if (!res.ok) return { ok: false, reason: `http_${res.status}` };

    return { ok: true, body: await res.json() };
  } catch (err) {
    return { ok: false, reason: 'offline' };
  }
}

async function enqueue(batch) {
  const queue = await get('pending_queue', []);
  queue.push(batch);
  if (queue.length > MAX_QUEUE) queue.splice(0, queue.length - MAX_QUEUE);
  await set({ pending_queue: queue });
}

/** Retry anything the backend missed while it was down. */
//: Reasons worth retrying later. Everything else is a 4xx that rejected the
//: batch on its merits, where retrying cannot help.
const RETRYABLE = new Set(['offline', 'http_429', 'not_signed_in', 'token_expired']);

async function drainQueue() {
  const queue = await get('pending_queue', []);
  if (queue.length === 0) return { sent: 0, remaining: 0 };

  const remaining = [];
  let sent = 0;
  for (const batch of queue) {
    const result = await sendToBackend(batch);
    if (result.ok) sent += 1;
    else if (RETRYABLE.has(result.reason) || result.reason.startsWith('http_5')) remaining.push(batch);
    // 4xx other than 401 means the server rejected the batch on its merits
    // (quality gate, validation). Retrying will not help, drop it.
  }
  await set({ pending_queue: remaining });
  return { sent, remaining: remaining.length };
}

async function handleBatch(batch) {
  const stamped = stamp(batch);
  await storeLocally(stamped);

  const result = await sendToBackend(stamped);
  if (!result.ok) {
    await enqueue(stamped);
    console.warn('[CogniDiff] batch queued locally ,', result.reason);
    return { stored: true, synced: false, reason: result.reason };
  }
  return { stored: true, synced: true, server: result.body };
}

// ---------------------------------------------------------------------------
// daily roll-up
//
// The point of the product is a score per day, not a score when somebody
// happens to open the dashboard. The backend derives the CogniScore server-side
// from stored sessions; this just makes sure that derivation is actually asked
// for once a day, so the trend line has a point on it even if the user never
// visits the site.
//
// It is a nudge, not a calculation: nothing here computes or supplies a score,
// which is what keeps the score unforgeable from the client.
// ---------------------------------------------------------------------------

async function rollUpToday(force = false) {
  const token = await get('auth_token', null);
  if (!token) return { scored: false, reason: 'not_signed_in' };

  const today = new Date().toISOString().slice(0, 10);
  const last = await get('last_rollup_date', null);
  if (!force && last === today) return { scored: false, reason: 'already_done_today' };

  // Nothing captured today means nothing to score, and asking anyway would put
  // a meaningless point on the trend.
  const sessions = await get('session_data', []);
  if (!sessions.some((s) => s.date === today)) {
    return { scored: false, reason: 'no_sessions_today' };
  }

  await drainQueue();   // score the day only once its sessions have landed

  try {
    const res = await fetch(`${API_BASE}/api/score`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ recompute: true }),
    });
    if (res.status === 401) { await set({ auth_token: null }); return { scored: false, reason: 'token_expired' }; }
    if (!res.ok) return { scored: false, reason: `http_${res.status}` };

    const body = await res.json();
    await set({
      last_rollup_date: today,
      last_score: body.cogni_score ?? null,
      last_score_band: body.confidence_band ?? null,
      last_alert: body.alert?.status_code ?? null,
    });
    return { scored: true, score: body.cogni_score, alert: body.alert?.status_code };
  } catch {
    return { scored: false, reason: 'offline' };
  }
}

// ---------------------------------------------------------------------------
// monitored sites
//
// This is the consent mechanism, and it is deliberately built on Chrome's own
// permission system rather than on a list we keep to ourselves.
//
// The earlier version hardcoded three domains into manifest content_scripts and
// kept a "site allowlist" in the popup. That list was decorative: adding a site
// changed a stored array but Chrome never injected the content script there, so
// the answer to "which sites am I monitoring" was whatever the manifest said,
// not what the user chose.
//
// Now the extension ships with no site access at all. Each site is requested at
// runtime, Chrome shows its own prompt, and the content script is registered
// dynamically only once the permission is actually held. The upshot is that the
// user can verify and revoke everything from chrome://extensions without
// trusting our UI, which is the correct place for that trust to live.
// ---------------------------------------------------------------------------

/** A host like "docs.google.com" becomes the two patterns Chrome needs. */
function patternsFor(host) {
  return [`https://${host}/*`, `http://${host}/*`];
}

function scriptIdFor(host) {
  return `cognidiff-${host}`;
}

async function grantedHosts() {
  const perms = await chrome.permissions.getAll();
  const hosts = new Set();
  for (const origin of perms.origins || []) {
    const m = origin.match(/^https?:\/\/([^/*]+)\/?\*?$/);
    if (m && m[1] && m[1] !== 'localhost:8000') hosts.add(m[1]);
  }
  return hosts;
}

/** Register the content script for one host. Assumes permission is held. */
async function registerSite(host) {
  const id = scriptIdFor(host);
  try {
    const existing = await chrome.scripting.getRegisteredContentScripts({ ids: [id] });
    if (existing.length) return { registered: true, already: true };
  } catch { /* not registered yet */ }

  await chrome.scripting.registerContentScripts([{
    id,
    matches: patternsFor(host),
    js: ['content_script.js'],
    runAt: 'document_idle',
    allFrames: false,
    persistAcrossSessions: true,
  }]);
  return { registered: true };
}

async function unregisterSite(host) {
  try {
    await chrome.scripting.unregisterContentScripts({ ids: [scriptIdFor(host)] });
  } catch { /* was not registered */ }
}

async function addSite(host) {
  const granted = await grantedHosts();
  if (!granted.has(host)) {
    // The popup asks for the permission, because chrome.permissions.request
    // needs a user gesture. If we get here without it, something is wrong.
    return { added: false, reason: 'permission_not_granted' };
  }
  await registerSite(host);

  const sites = await get('monitored_sites', []);
  if (!sites.includes(host)) {
    sites.push(host);
    await set({ monitored_sites: sites });
  }
  return { added: true, host, sites };
}

async function removeSite(host) {
  await unregisterSite(host);
  try {
    await chrome.permissions.remove({ origins: patternsFor(host) });
  } catch { /* already gone */ }

  const sites = (await get('monitored_sites', [])).filter((h) => h !== host);
  await set({ monitored_sites: sites });
  return { removed: true, host, sites };
}

/**
 * Make the registrations match the permissions actually held.
 *
 * Chrome permissions can be revoked from chrome://extensions without telling
 * us, so the stored list is a cache and the permission set is the truth. Any
 * disagreement is resolved in favour of the permissions.
 */
async function syncSites() {
  const granted = await grantedHosts();
  const stored = await get('monitored_sites', []);

  const live = [];
  for (const host of granted) {
    await registerSite(host);
    live.push(host);
  }
  for (const host of stored) {
    if (!granted.has(host)) await unregisterSite(host);
  }

  live.sort();
  await set({ monitored_sites: live });
  return live;
}

// Keep in step when the user changes permissions outside our UI.
chrome.permissions.onAdded.addListener(() => syncSites());
chrome.permissions.onRemoved.addListener(() => syncSites());

// ---------------------------------------------------------------------------
// message router
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    switch (msg.type) {
      case 'keystroke_batch':
        sendResponse(await handleBatch(msg.batch));
        break;

      case 'get_all_data': {
        const sessions = await get('session_data', []);
        const queue = await get('pending_queue', []);
        sendResponse({ sessions, pending: queue.length, count: sessions.length });
        break;
      }

      case 'get_summary': {
        const sessions = await get('session_data', []);
        const today = new Date().toISOString().slice(0, 10);
        const todays = sessions.filter((s) => s.date === today);
        const avg = (arr, k) => (arr.length
          ? Math.round((arr.reduce((a, s) => a + (s[k] || 0), 0) / arr.length) * 10) / 10
          : 0);
        sendResponse({
          today_sessions: todays.length,
          total_sessions: sessions.length,
          avg_wpm: avg(todays, 'wpm_estimate'),
          avg_iki_ms: avg(todays, 'avg_inter_key_interval_ms'),
          pending: (await get('pending_queue', [])).length,
        });
        break;
      }

      case 'clear_all_data':
        await chrome.storage.local.remove(['session_data', 'pending_queue']);
        sendResponse({ cleared: true, message: 'All locally stored data deleted.' });
        break;

      case 'flush_queue':
        sendResponse(await drainQueue());
        break;

      case 'add_site':
        sendResponse(await addSite(msg.host));
        break;

      case 'remove_site':
        sendResponse(await removeSite(msg.host));
        break;

      case 'sync_sites':
        sendResponse({ sites: await syncSites() });
        break;

      case 'get_sites': {
        const sites = await syncSites();
        sendResponse({ sites });
        break;
      }

      case 'roll_up_today':
        sendResponse(await rollUpToday(true));
        break;

      default:
        sendResponse({ error: 'unknown_message_type' });
    }
  })();

  return true;   // keep the message channel open for the async response
});

// ---------------------------------------------------------------------------
// install defaults + periodic retry
// ---------------------------------------------------------------------------

chrome.runtime.onInstalled.addListener(async (details) => {
  const existing = await get('monitoring_active', null);
  if (existing === null) {
    // Opt-in by default OFF. The user turns monitoring on from the popup after
    // reading the privacy notice, consent before capture, always.
    await set({
      monitoring_active: false,
      monitored_sites: [],     // no site access until the user grants it
      session_data: [],
      pending_queue: [],
      consent_seen: false,
    });
  }

  // Show the consent page once, on first install only.
  if (details && details.reason === 'install') {
    chrome.tabs.create({ url: chrome.runtime.getURL('welcome.html') });
  }
  chrome.alarms.create('cognidiff_drain', { periodInMinutes: 5 });
  // Hourly, but rollUpToday() no-ops once the day is already scored. Checking
  // often is how a laptop that is asleep at midnight still gets its day.
  chrome.alarms.create('cognidiff_rollup', { periodInMinutes: 60 });
  syncSites();
});

chrome.runtime.onStartup.addListener(() => {
  syncSites();
  drainQueue();
  rollUpToday();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'cognidiff_drain') drainQueue();
  if (alarm.name === 'cognidiff_rollup') rollUpToday();
});
