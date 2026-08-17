/* CogniDiff cursor.
 *
 * A soft cyan bloom and a thin ring that trail the pointer, easing toward it
 * rather than snapping. The ring lags slightly behind the bloom, which is what
 * reads as weight instead of as a sticker glued to the cursor.
 *
 * The native cursor stays visible. Hiding it in favour of a custom dot is a
 * common flourish and a bad idea here: it breaks text selection affordances and
 * makes the page feel broken to anyone whose pointer needs to be findable.
 *
 * Disabled entirely on touch devices and under prefers-reduced-motion.
 */

(function (global) {
  'use strict';

  function startCursor() {
    const reduce = global.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const coarse = global.matchMedia('(pointer: coarse)').matches;
    if (reduce || coarse) return null;

    const glow = document.createElement('div');
    glow.className = 'cursor-glow';
    glow.setAttribute('aria-hidden', 'true');

    const ring = document.createElement('div');
    ring.className = 'cursor-ring';
    ring.setAttribute('aria-hidden', 'true');

    document.body.appendChild(glow);
    document.body.appendChild(ring);

    let tx = global.innerWidth / 2, ty = global.innerHeight / 2;
    let gx = tx, gy = ty, rx = tx, ry = ty;
    let visible = false;
    let raf = null;

    function onMove(e) {
      tx = e.clientX;
      ty = e.clientY;
      if (!visible) {
        visible = true;
        gx = rx = tx; gy = ry = ty;
        glow.classList.add('is-on');
        ring.classList.add('is-on');
      }
    }

    // Grow the ring over anything clickable, so the cursor doubles as an
    // affordance rather than pure decoration.
    function onOver(e) {
      const hit = e.target.closest?.(
        'a, button, input, select, textarea, label, [role="button"], [tabindex]:not([tabindex="-1"])'
      );
      ring.classList.toggle('is-hot', Boolean(hit));
    }

    function onLeave() {
      visible = false;
      glow.classList.remove('is-on');
      ring.classList.remove('is-on');
    }

    function frame() {
      // Two different easing rates are what create the lag between the two.
      gx += (tx - gx) * 0.18;  gy += (ty - gy) * 0.18;
      rx += (tx - rx) * 0.085; ry += (ty - ry) * 0.085;

      glow.style.transform = `translate3d(${gx}px, ${gy}px, 0) translate(-50%, -50%)`;
      ring.style.transform = `translate3d(${rx}px, ${ry}px, 0) translate(-50%, -50%)`;

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
        glow.remove();
        ring.remove();
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
