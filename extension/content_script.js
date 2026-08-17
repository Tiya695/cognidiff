/* CogniDiff — content script (privacy-safe keystroke dynamics capture)
 *
 * HARD RULE, enforced by this file:
 *   The actual character a user types is never read, never stored and never
 *   leaves this function scope. We read `event.key` for exactly one purpose —
 *   to bucket it into a category — and the character itself is discarded on the
 *   next line. No variable in this file ever holds typed text.
 *
 * What we measure is *rhythm*: how long keys are held, how long the gaps
 * between them are, how often the user deletes and retypes. That is the
 * cognitive signal. The content is not.
 */

(() => {
  'use strict';

  const BATCH_MS = 60_000;         // one batch per minute
  const PAUSE_MS = 2_000;          // gap that counts as a "pause"
  const LONG_PAUSE_MS = 3_000;     // gap that counts as a "long pause"

  // ---------------------------------------------------------------------------
  // 1. Sensitive-context exclusion. This runs BEFORE anything is recorded.
  //    A hard requirement, not an enhancement.
  // ---------------------------------------------------------------------------

  const BLOCKED_URL_PATTERNS = [
    // path fragments
    /\/login/i, /\/signin/i, /\/sign-in/i, /\/log-in/i, /\/auth/i,
    /\/checkout/i, /\/payment/i, /\/billing/i, /\/reset-password/i,
    /\/forgot-password/i, /\/verify/i, /\/otp/i, /\/2fa/i,
    // host fragments — banking, payment, health portals
    /bank/i, /paypal/i, /stripe\.com/i, /razorpay/i, /paytm/i, /upi/i,
    /netbanking/i, /insurance/i, /patient/i, /medical/i, /health.*portal/i,
    /aadhaar/i, /uidai/i, /incometax/i,
  ];

  const SENSITIVE_LABEL = /(password|passcode|pin|cvv|cvc|otp|secret|token|ssn|aadhaar|card\s*number|security\s*code)/i;

  /** True when the whole page is off-limits. */
  function pageIsSensitive() {
    // Incognito: chrome.extension.inIncognitoContext is readable from a content
    // script and is the most reliable signal available to us here.
    try {
      if (chrome.extension && chrome.extension.inIncognitoContext) return true;
    } catch (_) { /* API unavailable — fall through to URL checks */ }

    const url = location.href;
    return BLOCKED_URL_PATTERNS.some((re) => re.test(url));
  }

  /** True when the focused element is off-limits. */
  function elementIsSensitive(el) {
    if (!el || el.nodeType !== 1) return true;   // fail closed

    const tag = (el.tagName || '').toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();

    if (tag === 'input' && type === 'password') return true;
    if (['tel', 'email'].includes(type) && SENSITIVE_LABEL.test(el.name || '')) return true;

    const auto = (el.getAttribute('autocomplete') || '').toLowerCase();
    if (auto.includes('cc-') || auto.includes('one-time-code') ||
        auto.includes('current-password') || auto.includes('new-password')) return true;

    if (el.hasAttribute('data-sensitive')) return true;

    const label = [el.getAttribute('aria-label'), el.getAttribute('placeholder'),
                   el.getAttribute('name'), el.id].filter(Boolean).join(' ');
    if (SENSITIVE_LABEL.test(label)) return true;

    // Any form that contains a password field is treated as an auth form in
    // its entirety — the username box next to a password box is still auth.
    const form = el.closest && el.closest('form');
    if (form && form.querySelector('input[type="password"]')) return true;

    return false;
  }

  // ---------------------------------------------------------------------------
  // 2. Key categorisation. The only place event.key is ever touched.
  // ---------------------------------------------------------------------------

  /**
   * Maps a keyboard event to a single-character category code.
   * Returns null for keys we do not count (modifiers, arrows, function keys).
   *
   *   l = letter   d = digit   s = space   b = backspace/delete   p = punctuation
   *
   * The character itself is NOT returned, NOT logged and NOT retained.
   */
  function categorise(event) {
    const k = event.key;
    if (k === undefined || k === null) return null;
    if (k === 'Backspace' || k === 'Delete') return 'b';
    if (k === ' ' || k === 'Spacebar' || k === 'Enter' || k === 'Tab') return 's';
    if (k.length !== 1) return null;             // Shift, Control, ArrowLeft, F5 …
    if (k >= 'a' && k <= 'z') return 'l';
    if (k >= 'A' && k <= 'Z') return 'l';
    if (k >= '0' && k <= '9') return 'd';
    return 'p';
  }

  // ---------------------------------------------------------------------------
  // 3. Buffer
  // ---------------------------------------------------------------------------

  let monitoring = false;
  let sessionMinute = 0;
  let buffer = newBuffer();
  const holdOpen = new Map();     // event.code -> keydown timestamp

  function newBuffer() {
    return {
      startedAt: Date.now(),
      categories: [],     // array of 'l' | 'd' | 's' | 'b' | 'p'
      offsets: [],        // ms since buffer start, parallel to categories
      holds: [],          // keyup-minus-keydown durations, ms
      lastDownAt: null,
      intervals: [],      // inter-key intervals, ms
      tainted: false,     // touched a sensitive context — discard, never send
    };
  }

  /** Drop everything collected so far. Used when a sensitive context appears. */
  function discardBuffer(reason) {
    if (buffer.categories.length > 0) {
      console.debug('[CogniDiff] buffer discarded —', reason);
    }
    buffer = newBuffer();
    holdOpen.clear();
  }

  // ---------------------------------------------------------------------------
  // 4. Capture
  // ---------------------------------------------------------------------------

  function onKeyDown(event) {
    if (!monitoring) return;

    if (pageIsSensitive() || elementIsSensitive(event.target)) {
      // A batch that started on a normal page and continued into a checkout
      // form must never leave the browser. Delete it — do not flush it.
      discardBuffer('sensitive context entered');
      return;
    }

    const cat = categorise(event);
    if (!cat) return;

    const now = event.timeStamp ? performance.timeOrigin + event.timeStamp : Date.now();

    if (buffer.lastDownAt !== null) {
      buffer.intervals.push(now - buffer.lastDownAt);
    }
    buffer.lastDownAt = now;

    buffer.categories.push(cat);
    buffer.offsets.push(Math.round(now - buffer.startedAt));
    holdOpen.set(event.code || cat, now);
  }

  function onKeyUp(event) {
    if (!monitoring) return;
    const key = event.code || categorise(event);
    if (!key || !holdOpen.has(key)) return;

    const down = holdOpen.get(key);
    holdOpen.delete(key);
    const now = event.timeStamp ? performance.timeOrigin + event.timeStamp : Date.now();
    const hold = now - down;
    if (hold >= 0 && hold < 5_000) buffer.holds.push(hold);
  }

  /** Fires when focus moves — catches tabbing INTO a password field. */
  function onFocusIn(event) {
    if (!monitoring) return;
    if (elementIsSensitive(event.target)) discardBuffer('focus moved to sensitive field');
  }

  // ---------------------------------------------------------------------------
  // 5. Batching
  // ---------------------------------------------------------------------------

  const mean = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);

  function buildBatch(buf) {
    const total = buf.categories.length;
    if (total === 0) return null;

    const elapsedMs = Date.now() - buf.startedAt;
    const elapsedMin = Math.max(elapsedMs / 60_000, 1 / 60);

    const backspaces = buf.categories.filter((c) => c === 'b').length;
    const pauses = buf.intervals.filter((i) => i > PAUSE_MS).length;
    const longPauses = buf.intervals.filter((i) => i > LONG_PAUSE_MS).length;

    // Standard WPM convention: 5 keystrokes = 1 word.
    const wpm = (total / 5) / elapsedMin;

    return {
      // --- headline features -------------------------------------------------
      wpm_estimate: round2(wpm),
      avg_inter_key_interval_ms: round2(mean(buf.intervals)),
      avg_hold_duration_ms: round2(mean(buf.holds)),
      backspace_count: backspaces,
      total_keystrokes: total,
      pause_count: pauses,
      long_pause_count: longPauses,
      session_minute: sessionMinute,
      duration_ms: elapsedMs,

      // --- raw category/timing sequence -------------------------------------
      // Needed server-side for correction-event detection and rhythm variance.
      // Contains NO characters: only the five category codes above.
      key_categories: buf.categories.join(''),
      offsets_ms: buf.offsets,
      intervals_ms: buf.intervals.map(round2),

      // --- non-identifying device fingerprint (Phase 2 quality gate) ---------
      device_fingerprint: deviceFingerprint(),

      captured_at: new Date().toISOString(),
      complete: elapsedMs >= BATCH_MS * 0.9,
    };
  }

  const round2 = (n) => Math.round(n * 100) / 100;

  /**
   * Coarse, non-identifying device signature. Deliberately bucketed: a new
   * keyboard changes typing rhythm far more than a mild cognitive change does,
   * so we need to know the setup changed — but we never want a hardware serial
   * or anything that could single out a person.
   */
  function deviceFingerprint() {
    const w = window.screen ? window.screen.width : 0;
    const bucket = w < 1000 ? 'sm' : w < 1600 ? 'md' : w < 2200 ? 'lg' : 'xl';
    const platform = (navigator.userAgentData && navigator.userAgentData.platform) ||
                     (navigator.platform || 'unknown');
    const lang = (navigator.language || 'unknown').split('-')[0];
    return `${platform}|${bucket}|${lang}`;
  }

  function flush() {
    if (!monitoring) return;

    const buf = buffer;
    buffer = newBuffer();
    holdOpen.clear();

    if (buf.tainted) return;                       // never send a tainted buffer
    if (pageIsSensitive()) return;

    const batch = buildBatch(buf);
    if (!batch) return;                            // nothing typed this minute

    sessionMinute += 1;
    chrome.runtime.sendMessage({ type: 'keystroke_batch', batch }, () => {
      if (chrome.runtime.lastError) {
        console.debug('[CogniDiff] background unavailable:', chrome.runtime.lastError.message);
      }
    });
  }

  // ---------------------------------------------------------------------------
  // 6. Lifecycle
  // ---------------------------------------------------------------------------

  let timer = null;

  function start() {
    if (timer) return;
    document.addEventListener('keydown', onKeyDown, true);
    document.addEventListener('keyup', onKeyUp, true);
    document.addEventListener('focusin', onFocusIn, true);
    timer = setInterval(flush, BATCH_MS);
    console.info('[CogniDiff] monitoring active on this page.');
  }

  function stop() {
    if (!timer) return;
    document.removeEventListener('keydown', onKeyDown, true);
    document.removeEventListener('keyup', onKeyUp, true);
    document.removeEventListener('focusin', onFocusIn, true);
    clearInterval(timer);
    timer = null;
    discardBuffer('monitoring turned off');
    console.info('[CogniDiff] monitoring stopped.');
  }

  async function isAllowlisted() {
    const { site_allowlist = [] } = await chrome.storage.local.get('site_allowlist');
    if (site_allowlist.length === 0) return true;   // manifest already scopes us
    return site_allowlist.some((host) => location.hostname.endsWith(host));
  }

  async function sync() {
    const { monitoring_active = false } = await chrome.storage.local.get('monitoring_active');
    const allowed = monitoring_active && !pageIsSensitive() && (await isAllowlisted());

    if (allowed && !monitoring) { monitoring = true; start(); }
    else if (!allowed && monitoring) { monitoring = false; stop(); }
  }

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === 'local' && ('monitoring_active' in changes || 'site_allowlist' in changes)) sync();
  });

  // Flush whatever is pending when the tab goes away, so a real minute of
  // typing is not silently lost — unless the page is sensitive.
  window.addEventListener('pagehide', () => { if (monitoring) flush(); });

  sync();
})();
