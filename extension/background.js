/* CogniDiff — background service worker.
 *
 * Receives 60-second feature batches from content scripts, stamps them with a
 * date and hour, keeps a local copy in chrome.storage.local, and forwards them
 * to the backend when it is reachable. If the backend is down the batch stays
 * local and is retried later — typing data is never dropped just because a
 * server is offline, and it is never sent anywhere else.
 */

const API_BASE = 'http://localhost:8000';
const MAX_LOCAL_SESSIONS = 5000;      // ring buffer — keeps storage bounded
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
 * and stored here by the popup — the extension never holds a password.
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
async function drainQueue() {
  const queue = await get('pending_queue', []);
  if (queue.length === 0) return { sent: 0, remaining: 0 };

  const remaining = [];
  let sent = 0;
  for (const batch of queue) {
    const result = await sendToBackend(batch);
    if (result.ok) sent += 1;
    else if (result.reason === 'offline' || result.reason.startsWith('http_5')) remaining.push(batch);
    // 4xx other than 401 means the server rejected the batch on its merits
    // (quality gate, validation). Retrying will not help — drop it.
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
    console.warn('[CogniDiff] batch queued locally —', result.reason);
    return { stored: true, synced: false, reason: result.reason };
  }
  return { stored: true, synced: true, server: result.body };
}

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

      default:
        sendResponse({ error: 'unknown_message_type' });
    }
  })();

  return true;   // keep the message channel open for the async response
});

// ---------------------------------------------------------------------------
// install defaults + periodic retry
// ---------------------------------------------------------------------------

chrome.runtime.onInstalled.addListener(async () => {
  const existing = await get('monitoring_active', null);
  if (existing === null) {
    // Opt-in by default OFF. The user turns monitoring on from the popup after
    // reading the privacy notice — consent before capture, always.
    await set({
      monitoring_active: false,
      site_allowlist: ['docs.google.com', 'mail.google.com', 'keep.google.com'],
      session_data: [],
      pending_queue: [],
    });
  }
  chrome.alarms.create('cognidiff_drain', { periodInMinutes: 5 });
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'cognidiff_drain') drainQueue();
});
