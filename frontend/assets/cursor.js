/* CogniDiff cursor: a light source, not a shape.
 *
 * Two stacked radial washes follow the pointer at different rates, so the light
 * has a bright heart that keeps up and a broad halo that lags. Nothing is
 * outlined. The earlier version drew a ring, which reads as a widget glued to
 * the screen rather than as illumination.
 *
 * On the landing page the same position is handed to the particle shader, so
 * the scan itself brightens where the light falls. That is the part that sells
 * it: the light appears to fall *on* the brain rather than float in front of it.
 *
 * The native cursor stays visible. Hiding it is a common flourish and a bad
 * idea: it breaks text-selection affordances and makes the page feel broken to
 * anyone whose pointer needs to be findable.
 */

(function (global) {
  'use strict';

  function startCursor() {
    const reduce = global.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const coarse = global.matchMedia('(pointer: coarse)').matches;
    if (reduce || coarse) return null;

    const beam = document.createElement('div');
    beam.className = 'cursor-beam';
    beam.setAttribute('aria-hidden', 'true');

    const core = document.createElement('div');
    core.className = 'cursor-core';
    core.setAttribute('aria-hidden', 'true');

    document.body.appendChild(beam);
    document.body.appendChild(core);

    let tx = global.innerWidth / 2, ty = global.innerHeight / 2;
    let bx = tx, by = ty, cx = tx, cy = ty;
    let visible = false, raf = null;

    function onMove(e) {
      tx = e.clientX; ty = e.clientY;
      if (!visible) {
        visible = true;
        bx = cx = tx; by = cy = ty;
        beam.classList.add('is-on');
        core.classList.add('is-on');
      }
    }

    const INTERACTIVE =
      'a, button, input, select, textarea, label, [role="button"], [tabindex]:not([tabindex="-1"])';

    function onOver(e) {
      const hot = Boolean(e.target.closest?.(INTERACTIVE));
      beam.classList.toggle('is-hot', hot);
      core.classList.toggle('is-hot', hot);
    }

    function onLeave() {
      visible = false;
      beam.classList.remove('is-on');
      core.classList.remove('is-on');
      if (global.CogniDiffScan) global.CogniDiffScan.setCursor(null);
    }

    function frame() {
      cx += (tx - cx) * 0.22;  cy += (ty - cy) * 0.22;   // heart keeps up
      bx += (tx - bx) * 0.075; by += (ty - by) * 0.075;  // halo lags

      core.style.transform = `translate3d(${cx}px, ${cy}px, 0) translate(-50%, -50%)`;
      beam.style.transform = `translate3d(${bx}px, ${by}px, 0) translate(-50%, -50%)`;

      // Hand the light to the scan so the particles react to it.
      const scan = global.CogniDiffScan;
      if (scan && scan.setCursor) {
        scan.setCursor(visible ? [cx, cy] : null);
      }

      raf = requestAnimationFrame(frame);
    }

    global.addEventListener('pointermove', onMove, { passive: true });
    global.addEventListener('pointerover', onOver, { passive: true });
    document.addEventListener('mouseleave', onLeave);
    global.addEventListener('blur', onLeave);

    raf = requestAnimationFrame(frame);

    return {
      stop() {
        if (raf) cancelAnimationFrame(raf);
        global.removeEventListener('pointermove', onMove);
        global.removeEventListener('pointerover', onOver);
        document.removeEventListener('mouseleave', onLeave);
        beam.remove();
        core.remove();
      },
    };
  }

  global.startCursor = startCursor;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', startCursor);
  } else {
    startCursor();
  }
})(window);
