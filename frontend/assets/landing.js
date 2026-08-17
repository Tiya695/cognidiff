/* CogniDiff landing, scroll choreography for the seven scan states.
 *
 * GSAP ScrollTrigger drives one thing per state: a set of numbers on the
 * NeuralBrain instance (camera position, rotation, morph, pulse, focus). The
 * brain itself knows nothing about scrolling, it just renders whatever those
 * numbers currently say, which keeps the animation and the geometry separable.
 */

(function () {
  'use strict';

  document.documentElement.classList.add('js');

  const canvas = document.getElementById('brain');
  const sections = Array.from(document.querySelectorAll('.state'));
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---------------------------------------------------------------------
  // state table, camera, orientation and shader uniforms per section
  // ---------------------------------------------------------------------

  const STATES = {
    // 01 ARRIVAL, full front view, slow continuous rotation
    1: { cam: [0, 0.02, 4.25], target: [0, 0.04, 0], spin: 0.055,
         morph: 0, pulse: false, focus: null, lines: 0 },

    // 02 THE BASELINE, tilt up and push in on the cortical surface
    2: { cam: [0.35, 1.15, 2.30], target: [0, 0.34, 0], spin: 0.030,
         morph: 0, pulse: false, focus: null, lines: 0 },

    // 03 SIGNALS, centred, pulse waves travelling through the cloud
    3: { cam: [0, 0.02, 3.05], target: [0, 0.02, 0], spin: 0.018,
         morph: 0, pulse: true, focus: null, lines: 0 },

    // 04 THE NETWORK, disperse into a constellation of nodes and links
    4: { cam: [0, 0, 8.20], target: [0, 0, 0], spin: 0.012,
         morph: 1, pulse: false, focus: null, lines: 0.42 },

    // 05 INSIGHT, regather, swing behind to the occipital pole
    5: { cam: [0.55, 0.18, 3.55], target: [0, 0.02, 0], spin: 0, rotY: Math.PI,
         morph: 0, pulse: false, focus: [0, -0.02, -1.02, 0.60], lines: 0 },

    // 06 BALANCE, pan down onto the cerebellum
    6: { cam: [0.15, -0.72, 2.95], target: [0, -0.52, -0.35], spin: 0.022,
         rotY: Math.PI * 0.82,
         morph: 0, pulse: false, focus: [0, -0.58, -0.72, 0.44], lines: 0 },

    // 07 SUMMARY, pull back out to the full view, steady rotation
    7: { cam: [0, 0.02, 4.75], target: [0, 0.02, 0], spin: 0.052,
         morph: 0, pulse: false, focus: null, lines: 0 },
  };

  // ---------------------------------------------------------------------
  // live telemetry, the numbers in the metadata rows tick like instruments
  // ---------------------------------------------------------------------

  function startTelemetry() {
    const rateEls = document.querySelectorAll('[data-live="rate"]');
    const statusEl = document.querySelector('[data-live="status"]');
    const phases = ['MAPPING', 'SAMPLING', 'RESOLVING', 'MAPPING'];
    let phase = 0;

    if (reduceMotion) return;

    setInterval(() => {
      const rate = (3.6 + Math.random() * 1.3).toFixed(2);
      rateEls.forEach((el) => { el.textContent = `${rate} M/S`; });
    }, 900);

    if (statusEl) {
      setInterval(() => {
        phase = (phase + 1) % phases.length;
        statusEl.textContent = phases[phase];
      }, 3400);
    }
  }

  // ---------------------------------------------------------------------
  // boot
  // ---------------------------------------------------------------------

  function boot() {
    startTelemetry();

    // Reveal copy with IntersectionObserver, independent of the WebGL layer,
    // so the page still animates its text if the GPU path bails out.
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) e.target.classList.add('is-in');
      });
    }, { threshold: 0.28 });
    document.querySelectorAll('.state__copy').forEach((el) => io.observe(el));

    let brain = null;
    try {
      brain = new window.NeuralBrain(canvas, { seed: 20260817 });
    } catch (err) {
      // No WebGL, or three.js failed to load. The page is fully readable
      // without it, hide the dead canvas and carry on.
      console.warn('[CogniDiff] neural scan unavailable:', err.message);
      canvas.style.display = 'none';
    }

    if (brain) {
      // Exposed so the scan can be inspected and captured from the console.
      window.CogniDiffScan = brain;
      window.CogniDiffStates = STATES;

      const s = STATES[1];
      brain.camX = s.cam[0]; brain.camY = s.cam[1]; brain.camZ = s.cam[2];
      brain.cameraTarget.set(...s.target);
      brain.autoSpin = s.spin;
      brain.start();

      // Pause the render loop when the tab is hidden, no point burning a GPU
      // on a page nobody is looking at.
      document.addEventListener('visibilitychange', () => {
        if (document.hidden) brain.stop(); else brain.start();
      });
    }

    setupScroll(brain);
  }

  // ---------------------------------------------------------------------
  // scroll triggers
  // ---------------------------------------------------------------------

  function setupScroll(brain) {
    const hasGsap = typeof window.gsap !== 'undefined'
                 && typeof window.ScrollTrigger !== 'undefined';

    if (hasGsap) window.gsap.registerPlugin(window.ScrollTrigger);

    let pulseTween = null;

    /** Rotate to a specific facing, taking the shortest way round. */
    function targetRotation(current, wanted) {
      const turns = Math.round((current - wanted) / (Math.PI * 2));
      return wanted + turns * Math.PI * 2;
    }

    function applyState(n) {
      if (!brain) return;

      const s = STATES[n];
      if (!s) return;

      const dur = reduceMotion ? 0 : 1.5;
      const ease = 'power2.inOut';

      if (hasGsap && !reduceMotion) {
        const gsap = window.gsap;

        gsap.to(brain, {
          camX: s.cam[0], camY: s.cam[1], camZ: s.cam[2],
          duration: dur, ease, overwrite: 'auto',
        });
        gsap.to(brain.cameraTarget, {
          x: s.target[0], y: s.target[1], z: s.target[2],
          duration: dur, ease, overwrite: 'auto',
        });
        gsap.to(brain.uniforms.uMorph, {
          value: s.morph, duration: dur * 1.15, ease: 'power2.inOut',
          overwrite: 'auto',
        });
        gsap.to(brain.lineMaterial, {
          opacity: s.lines, duration: dur, ease, overwrite: 'auto',
        });

        // Focus highlight: fade the radius rather than snapping it, so the
        // glow blooms into the region instead of appearing on it.
        if (s.focus) {
          brain.uniforms.uFocus.value.set(s.focus[0], s.focus[1], s.focus[2]);
          gsap.to(brain.uniforms.uFocusRadius, {
            value: s.focus[3], duration: dur, ease, overwrite: 'auto',
          });
        } else {
          gsap.to(brain.uniforms.uFocusRadius, {
            value: 0, duration: dur * 0.7, ease, overwrite: 'auto',
          });
        }

        brain.autoSpin = s.spin;
        if (typeof s.rotY === 'number') {
          gsap.to(brain.group.rotation, {
            y: targetRotation(brain.group.rotation.y, s.rotY),
            duration: dur * 1.2, ease, overwrite: 'auto',
          });
        }

        // pulse waves
        if (pulseTween) { pulseTween.kill(); pulseTween = null; }
        if (s.pulse) {
          brain.uniforms.uPulse.value = 0;
          pulseTween = gsap.fromTo(
            brain.uniforms.uPulse,
            { value: -0.15 },
            { value: 1.15, duration: 2.1, ease: 'none',
              repeat: -1, repeatDelay: 0.25 }
          );
        } else {
          brain.uniforms.uPulse.value = -1;
        }
      } else {
        // No GSAP or reduced motion, jump straight to the state.
        brain.camX = s.cam[0]; brain.camY = s.cam[1]; brain.camZ = s.cam[2];
        brain.cameraTarget.set(...s.target);
        brain.uniforms.uMorph.value = s.morph;
        brain.lineMaterial.opacity = s.lines;
        brain.uniforms.uPulse.value = s.pulse ? 0.5 : -1;
        brain.autoSpin = reduceMotion ? 0 : s.spin;
        if (s.focus) brain.setFocus(s.focus[0], s.focus[1], s.focus[2], s.focus[3]);
        else brain.setFocus(0, 0, 0, 0);
        if (typeof s.rotY === 'number') brain.group.rotation.y = s.rotY;
      }
    }

    if (hasGsap) {
      sections.forEach((section) => {
        const n = Number(section.dataset.state);
        window.ScrollTrigger.create({
          trigger: section,
          start: 'top 62%',
          end: 'bottom 38%',
          onEnter: () => applyState(n),
          onEnterBack: () => applyState(n),
        });
      });
    } else {
      // Fallback: drive the same states from an IntersectionObserver.
      const io = new IntersectionObserver((entries) => {
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
        if (visible) applyState(Number(visible.target.dataset.state));
      }, { threshold: [0.35, 0.6] });
      sections.forEach((s) => io.observe(s));
    }

    applyState(1);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
