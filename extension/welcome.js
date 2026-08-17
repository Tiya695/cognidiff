/* CogniDiff first-run consent page.
 *
 * Shown once, on install, before the extension has access to any site. It does
 * not ask for a permission or capture anything: it exists so the consent the
 * user gives afterwards, in Chrome's own prompt, is informed rather than
 * reflexive.
 */

(function () {
  'use strict';

  // --- starfield, matching the popup and the web app -----------------------

  (function starfield() {
    const canvas = document.getElementById('stars');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let w = 0, h = 0, stars = [];

    function size() {
      w = window.innerWidth; h = window.innerHeight;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      stars = Array.from({ length: 160 }, () => ({
        x: Math.random(), y: Math.random(),
        r: Math.random() * 1.1 + 0.3,
        a: Math.random() * 0.5 + 0.15,
        sp: 0.002 + Math.random() * 0.012,
        ph: Math.random() * Math.PI * 2,
      }));
    }

    function frame(t) {
      ctx.clearRect(0, 0, w, h);
      for (const s of stars) {
        if (!reduce) {
          s.y -= s.sp * 0.016;
          if (s.y < -0.02) { s.y = 1.02; s.x = Math.random(); }
        }
        const tw = reduce ? 1 : 0.6 + 0.4 * Math.sin(s.ph + t * 0.0011);
        ctx.beginPath();
        ctx.arc(s.x * w, s.y * h, s.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(214, 236, 255, ${s.a * tw})`;
        ctx.fill();
      }
      if (!reduce) requestAnimationFrame(frame);
    }

    size();
    window.addEventListener('resize', size);
    requestAnimationFrame(frame);
  })();

  // --- accept --------------------------------------------------------------

  document.getElementById('accept').addEventListener('click', async () => {
    await chrome.storage.local.set({ consent_seen: true });

    // Chrome gives no API to open the extension's own popup, so point at it
    // rather than pretending we can.
    const btn = document.getElementById('accept');
    btn.disabled = true;
    btn.textContent = 'Open the CogniDiff icon in your toolbar';

    const note = document.querySelector('.cta-note');
    note.textContent =
      'Click the CogniDiff icon (top right of Chrome, you may need the puzzle-piece menu) '
      + 'to choose your sites and switch monitoring on.';
  });
})();
