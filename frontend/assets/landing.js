/* CogniDiff landing, scroll choreography for the seven neural scan states.
 *
 * GSAP ScrollTrigger drives camera position, rotation, morph, pulse wave,
 * and regional focus highlights matching the reference scan video.
 */

(function () {
  'use strict';

  document.documentElement.classList.add('js');

  const canvas = document.getElementById('brain');
  const sections = Array.from(document.querySelectorAll('.state'));
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---------------------------------------------------------------------
  // State Table: Camera, Orientation & Shader Uniforms per Section
  // Exactly matching the video transitions:
  // ---------------------------------------------------------------------

  const STATES = {
    // 01 ARRIVAL: Frontal anatomical view, scaled to fill area (~78% height, balanced padding)
    1: {
      cam: [0, 0.10, 2.95],
      target: [0, 0.145, 0],
      shiftX: 0.215,
      spin: 0,
      rotY: 0,
      morph: 0,
      pulse: false,
      focus: null,
      lines: 0,
    },

    // 02 THE CORTEX: Shifted to left blank space with 180° rotation
    2: {
      cam: [0, 0.10, 2.95],
      target: [0, 0.145, 0],
      shiftX: -0.24,
      spin: 0,
      rotY: Math.PI,
      rotX: 0.14,
      morph: 0,
      pulse: false,
      focus: null,
      lines: 0,
    },

    // 03 SIGNALS: Centred, brain morphs into sparse glowing particles in deep space
    3: {
      cam: [0, 0.10, 2.95],
      target: [0, 0.08, 0],
      shiftX: 0,
      spin: 0,
      rotY: 0,
      morph: 1,
      pulse: false,
      focus: null,
      lines: 0, // NO geometrical lines
      brainOpacity: 1.0, // Render the sparse scattered particles
      bgOpacity: 0.0, // Starfield & cosmos fade out into deep space
    },

    // 04 THE NETWORK: Lateral profile (cerebellum left, frontal pole right) — shifted right with equal vertical margins
    4: {
      cam: [0, 0.10, 2.95],
      target: [0, 0.135, 0],
      shiftX: 0.210,
      spin: 0,
      rotY: Math.PI * 0.50 - 0.08, // Lateral side angle (cerebellum on left, frontal pole on right)
      rotX: 0.06,                  // Subtle tilt showing 3D cortical gyri depth
      morph: 0,                    // Solid anatomical brain (zero scatter)
      pulse: false,
      focus: null,
      lines: 0,
    },

    // 05 VISION: Posterior view of occipital pole (brain centered, equal vertical margins)
    5: {
      cam: [0, 0.10, 2.95],
      target: [0, 0.135, 0],
      shiftX: 0,                   // Centered, exactly matching reference video f_188
      spin: 0,
      rotY: Math.PI,               // 180° posterior view of occipital pole
      rotX: -0.04,
      morph: 0,
      pulse: false,
      focus: null,                 // Regional glow removed per user request
      lines: 0,
    },

    // 06 BALANCE: Posterior-inferior view highlighting cerebellum (centered, equal vertical margins)
    6: {
      cam: [0, 0.10, 2.95],
      target: [0, 0.133, -0.20],
      shiftX: 0,                   // Centered
      spin: 0,
      rotY: Math.PI * 0.94,
      rotX: -0.10,
      morph: 0,
      pulse: false,
      focus: null,                 // Regional glow removed per user request
      lines: 0,
    },

    // 07 SUMMARY: Pull back out to full frontal anatomical overview (centered)
    7: {
      cam: [0, 0.10, 3.45],
      target: [0, 0.08, 0],
      shiftX: 0,
      spin: 0,
      rotY: Math.PI * 2,
      rotX: 0.14,
      morph: 0,
      pulse: false,
      focus: null,
      lines: 0,
    },
  };

  // ---------------------------------------------------------------------
  // Live Telemetry Readout
  // ---------------------------------------------------------------------

  function startTelemetry() {
    const rateEls = document.querySelectorAll('[data-live="rate"]');
    const statusEl = document.querySelector('[data-live="status"]');
    const phases = ['MONITORING', 'BASELINE', 'ACTIVE', 'CALIBRATING'];
    let phase = 0;

    if (reduceMotion) return;

    setInterval(() => {
      const wpm = Math.floor(62 + Math.random() * 7);
      rateEls.forEach((el) => { el.textContent = `${wpm} WPM`; });
    }, 1200);

    if (statusEl) {
      setInterval(() => {
        phase = (phase + 1) % phases.length;
        statusEl.textContent = phases[phase];
      }, 3400);
    }
  }

  // ---------------------------------------------------------------------
  // Boot & Initialization
  // ---------------------------------------------------------------------

  function boot() {
    startTelemetry();

    // IntersectionObserver for text entrance animations
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
      console.warn('[CogniDiff] neural scan unavailable:', err.message);
      canvas.style.display = 'none';
    }

    if (brain) {
      window.CogniDiffScan = brain;
      window.CogniDiffStates = STATES;

      const s = STATES[1];
      brain.camX = s.cam[0];
      brain.camY = s.cam[1];
      brain.camZ = s.cam[2];
      brain.cameraTarget.set(...s.target);
      brain.viewOffsetX = (window.innerWidth > 900) ? (s.shiftX || 0) : 0;
      brain.autoSpin = s.spin;
      brain.start();

      document.addEventListener('visibilitychange', () => {
        if (document.hidden) brain.stop(); else brain.start();
      });
    }

    setupScroll(brain);
  }

  // ---------------------------------------------------------------------
  // Scroll Choreography
  // ---------------------------------------------------------------------

  function setupScroll(brain) {
    const hasGsap = typeof window.gsap !== 'undefined'
                 && typeof window.ScrollTrigger !== 'undefined';

    if (hasGsap) window.gsap.registerPlugin(window.ScrollTrigger);

    let pulseTween = null;
    let currentState = 1;

    function targetRotation(current, wanted) {
      const diff = (current - wanted) / (Math.PI * 2);
      const turns = Math.abs(diff % 1) === 0.5 ? Math.trunc(diff) : Math.round(diff);
      return wanted + turns * Math.PI * 2;
    }

    function applyState(n) {
      if (!brain) return;

      const s = STATES[n];
      if (!s) return;

      const prevState = currentState;
      currentState = n;

      let dur = reduceMotion ? 0 : 1.6;
      if (n === 3) dur = 3.4; // State 2 -> 3: particles scatter & screen darkens (slow & spacious)
      if (n === 4 && prevState === 3) dur = 3.4; // State 3 -> 4: particles come together to form brain (slow & graceful)
      if (n === 5) dur = 3.8; // State 4 -> 5: slow cinematic macro zoom & turn to posterior view
      if (prevState === 5 && n === 4) dur = 3.8; // State 5 -> 4: reverse transition (slow & smooth)

      const ease = 'power2.inOut';
      const targetShift = (window.innerWidth > 900) ? (s.shiftX || 0) : 0;

      // -----------------------------------------------------------------
      // Specialized Transition 04 -> 05 (Matching Video 0:05 to 0:06)
      // Slow, majestic camera dolly, sweeping rotation to posterior view,
      // and uniform anatomical shading (zero sudden rush, zero black circles).
      // -----------------------------------------------------------------
      if (hasGsap && !reduceMotion && prevState === 4 && n === 5) {
        const gsap = window.gsap;

        // 1. Rotation to posterior view (Math.PI) — gentle sinusoidal easing
        gsap.to(brain.group.rotation, {
          y: targetRotation(brain.group.rotation.y, s.rotY),
          duration: dur,
          ease: 'sine.inOut',
          overwrite: 'auto',
        });
        gsap.to(brain.group.rotation, {
          x: s.rotX,
          duration: dur,
          ease: 'sine.inOut',
          overwrite: 'auto',
        });

        // 2. Smooth centering
        gsap.to(brain, {
          viewOffsetX: targetShift,
          duration: dur,
          ease: 'sine.inOut',
          overwrite: 'auto',
        });

        // 3. Dynamic camera dolly in & out (gentle cinematic push-in)
        const zoomTl = gsap.timeline();
        zoomTl
          .to(brain, {
            camZ: 2.05,
            duration: dur * 0.48,
            ease: 'sine.in',
          })
          .to(brain, {
            camZ: s.cam[2],
            duration: dur * 0.52,
            ease: 'sine.out',
          });

        // 4. Camera target swoops smoothly into curving occipital pole, then centers
        const targetTl = gsap.timeline();
        targetTl
          .to(brain.cameraTarget, {
            x: -0.04,
            y: 0.12,
            z: -0.10,
            duration: dur * 0.48,
            ease: 'sine.in',
          })
          .to(brain.cameraTarget, {
            x: s.target[0],
            y: s.target[1],
            z: s.target[2],
            duration: dur * 0.52,
            ease: 'sine.out',
          });

        // 5. Regional focus glow removed per user request: ensure uFocusRadius stays 0
        brain.uniforms.uFocusRadius.value = 0.0;

        gsap.to(brain.uniforms.uMorph, { value: 0, duration: 0.3, overwrite: 'auto' });
        gsap.to(brain.lineMaterial, { opacity: 0, duration: 0.3, overwrite: 'auto' });
        gsap.to(brain.uniforms.uOpacity, { value: 1.0, duration: 0.3, overwrite: 'auto' });
        brain.autoSpin = 0;
        if (pulseTween) { pulseTween.kill(); pulseTween = null; }
        brain.uniforms.uPulse.value = -1;
        return;
      }

      // -----------------------------------------------------------------
      // Reverse Transition 05 -> 04 (Scrolling back up)
      // -----------------------------------------------------------------
      if (hasGsap && !reduceMotion && prevState === 5 && n === 4) {
        const gsap = window.gsap;

        gsap.to(brain.group.rotation, {
          y: targetRotation(brain.group.rotation.y, s.rotY),
          duration: dur,
          ease: 'sine.inOut',
          overwrite: 'auto',
        });
        gsap.to(brain.group.rotation, {
          x: s.rotX,
          duration: dur,
          ease: 'sine.inOut',
          overwrite: 'auto',
        });
        gsap.to(brain, {
          viewOffsetX: targetShift,
          duration: dur,
          ease: 'sine.inOut',
          overwrite: 'auto',
        });

        const revZoomTl = gsap.timeline();
        revZoomTl
          .to(brain, {
            camZ: 2.05,
            duration: dur * 0.48,
            ease: 'sine.in',
          })
          .to(brain, {
            camZ: s.cam[2],
            duration: dur * 0.52,
            ease: 'sine.out',
          });

        const revTargetTl = gsap.timeline();
        revTargetTl
          .to(brain.cameraTarget, {
            x: -0.04,
            y: 0.12,
            z: -0.10,
            duration: dur * 0.48,
            ease: 'sine.in',
          })
          .to(brain.cameraTarget, {
            x: s.target[0],
            y: s.target[1],
            z: s.target[2],
            duration: dur * 0.52,
            ease: 'sine.out',
          });

        gsap.to(brain.uniforms.uFocusRadius, {
          value: 0.0,
          duration: dur * 0.45,
          ease: 'power2.out',
          overwrite: 'auto',
        });

        gsap.to(brain.uniforms.uMorph, { value: 0, duration: 0.3, overwrite: 'auto' });
        gsap.to(brain.lineMaterial, { opacity: 0, duration: 0.3, overwrite: 'auto' });
        gsap.to(brain.uniforms.uOpacity, { value: 1.0, duration: 0.3, overwrite: 'auto' });
        brain.autoSpin = 0;
        if (pulseTween) { pulseTween.kill(); pulseTween = null; }
        brain.uniforms.uPulse.value = -1;
        return;
      }

      if (hasGsap && !reduceMotion) {
        const gsap = window.gsap;

        // Smooth horizontal shift (zero rotation / zero perspective skew)
        gsap.to(brain, {
          viewOffsetX: targetShift,
          duration: dur,
          ease,
          overwrite: 'auto',
        });

        // Smooth camera translation
        gsap.to(brain, {
          camX: s.cam[0],
          camY: s.cam[1],
          camZ: s.cam[2],
          duration: dur,
          ease,
          overwrite: 'auto',
        });
        gsap.to(brain.cameraTarget, {
          x: s.target[0],
          y: s.target[1],
          z: s.target[2],
          duration: dur,
          ease,
          overwrite: 'auto',
        });

        // Smooth morph into constellation network
        gsap.to(brain.uniforms.uMorph, {
          value: s.morph,
          duration: dur * 1.15,
          ease: 'power2.inOut',
          overwrite: 'auto',
        });

        // Constellation lines opacity
        gsap.to(brain.lineMaterial, {
          opacity: s.lines,
          duration: dur,
          ease,
          overwrite: 'auto',
        });

        // Smooth brain particle cloud opacity transition
        const brainOpacity = typeof s.brainOpacity === 'number' ? s.brainOpacity : 1.0;
        gsap.to(brain.uniforms.uOpacity, {
          value: brainOpacity,
          duration: dur,
          ease,
          overwrite: 'auto',
        });

        // Smooth background fade (starfield & cosmos)
        const bgOpacity = typeof s.bgOpacity === 'number' ? s.bgOpacity : 1.0;
        const starfield = document.getElementById('starfield');
        const cosmos = document.querySelector('.cosmos');
        if (starfield) {
          gsap.to(starfield, {
            opacity: bgOpacity,
            duration: dur,
            ease,
            overwrite: 'auto',
          });
        }
        if (cosmos) {
          gsap.to(cosmos, {
            opacity: bgOpacity,
            duration: dur,
            ease,
            overwrite: 'auto',
          });
        }

        // Focus highlight bloom
        if (s.focus) {
          brain.uniforms.uFocus.value.set(s.focus[0], s.focus[1], s.focus[2]);
          gsap.to(brain.uniforms.uFocusRadius, {
            value: s.focus[3],
            duration: dur,
            ease,
            overwrite: 'auto',
          });
        } else {
          gsap.to(brain.uniforms.uFocusRadius, {
            value: 0,
            duration: dur * 0.7,
            ease,
            overwrite: 'auto',
          });
        }

        brain.autoSpin = s.spin;

        // Controlled rotation around Y and tilt around X
        if (typeof s.rotY === 'number') {
          gsap.to(brain.group.rotation, {
            y: targetRotation(brain.group.rotation.y, s.rotY),
            duration: dur,
            ease,
            overwrite: 'auto',
          });
        }
        const wantedRotX = typeof s.rotX === 'number' ? s.rotX : 0.14;
        gsap.to(brain.group.rotation, {
          x: wantedRotX,
          duration: dur,
          ease,
          overwrite: 'auto',
        });

        // Pulse wave
        if (pulseTween) { pulseTween.kill(); pulseTween = null; }
        if (s.pulse) {
          brain.uniforms.uPulse.value = 0;
          pulseTween = gsap.fromTo(
            brain.uniforms.uPulse,
            { value: -0.15 },
            {
              value: 1.15,
              duration: 2.2,
              ease: 'none',
              repeat: -1,
              repeatDelay: 0.25,
            }
          );
        } else {
          brain.uniforms.uPulse.value = -1;
        }
      } else {
        brain.camX = s.cam[0];
        brain.camY = s.cam[1];
        brain.camZ = s.cam[2];
        brain.cameraTarget.set(...s.target);
        brain.viewOffsetX = targetShift;
        brain.uniforms.uMorph.value = s.morph;
        brain.lineMaterial.opacity = s.lines;
        const brainOpacity = typeof s.brainOpacity === 'number' ? s.brainOpacity : 1.0;
        const bgOpacity = typeof s.bgOpacity === 'number' ? s.bgOpacity : 1.0;
        brain.uniforms.uOpacity.value = brainOpacity;
        const starfield = document.getElementById('starfield');
        const cosmos = document.querySelector('.cosmos');
        if (starfield) starfield.style.opacity = String(bgOpacity);
        if (cosmos) cosmos.style.opacity = String(bgOpacity);
        brain.uniforms.uPulse.value = s.pulse ? 0.5 : -1;
        brain.autoSpin = reduceMotion ? 0 : s.spin;
        if (s.focus) brain.setFocus(s.focus[0], s.focus[1], s.focus[2], s.focus[3]);
        else brain.setFocus(0, 0, 0, 0);
        if (typeof s.rotY === 'number') brain.group.rotation.y = s.rotY;
        brain.group.rotation.x = typeof s.rotX === 'number' ? s.rotX : 0.14;
      }
    }

    window.CogniDiffApplyState = applyState;

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
