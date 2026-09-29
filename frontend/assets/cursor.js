/* CogniDiff cursor: passes pointer coordinates directly to the 3D neural brain scan.
 *
 * No DOM beam/core elements are created, guaranteeing that zero shine
 * or glare is visible outside the brain anywhere on the website.
 */

(function (global) {
  'use strict';

  function startCursor() {
    let tx = global.innerWidth / 2, ty = global.innerHeight / 2;
    let cx = tx, cy = ty;
    let visible = false, raf = null;

    function onMove(e) {
      tx = e.clientX;
      ty = e.clientY;
      visible = true;
    }

    function onLeave() {
      visible = false;
      if (global.CogniDiffScan && global.CogniDiffScan.setCursor) {
        global.CogniDiffScan.setCursor(null);
      }
    }

    function frame() {
      cx += (tx - cx) * 0.35;
      cy += (ty - cy) * 0.35;

      const scan = global.CogniDiffScan;
      if (scan && scan.setCursor) {
        scan.setCursor(visible ? [cx, cy] : null);
      }

      raf = requestAnimationFrame(frame);
    }

    global.addEventListener('pointermove', onMove, { passive: true });
    document.addEventListener('mouseleave', onLeave);
    global.addEventListener('blur', onLeave);

    raf = requestAnimationFrame(frame);

    return {
      stop() {
        if (raf) cancelAnimationFrame(raf);
        global.removeEventListener('pointermove', onMove);
        document.removeEventListener('mouseleave', onLeave);
        global.removeEventListener('blur', onLeave);
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
