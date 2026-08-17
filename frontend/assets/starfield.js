/* CogniDiff, the drifting star field behind everything.
 *
 * Three parallax layers so the background has depth without pulling attention:
 * distant stars barely move, near ones drift and twinkle. Plus a handful of
 * slow "dust" motes that catch the blue bloom.
 *
 * Honours prefers-reduced-motion by rendering one static frame.
 */

(function (global) {
  'use strict';

  function startStarfield(canvas, options = {}) {
    if (!canvas) return null;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;

    const reduce = global.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const dpr = Math.min(global.devicePixelRatio || 1, 2);
    const density = options.density ?? 1;

    let w = 0, h = 0, layers = [], motes = [], galaxies = [], raf = null;

    const LAYERS = [
      { n: 260, speed: 0.0030, size: [0.35, 0.95], alpha: [0.20, 0.52] },
      { n: 140, speed: 0.0075, size: [0.55, 1.35], alpha: [0.34, 0.78] },
      { n: 52,  speed: 0.0150, size: [0.90, 1.95], alpha: [0.50, 1.00] },
    ];

    function seed() {
      layers = LAYERS.map((cfg) => ({
        ...cfg,
        stars: Array.from({ length: Math.round(cfg.n * density) }, () => ({
          x: Math.random(),
          y: Math.random(),
          r: cfg.size[0] + Math.random() * (cfg.size[1] - cfg.size[0]),
          a: cfg.alpha[0] + Math.random() * (cfg.alpha[1] - cfg.alpha[0]),
          phase: Math.random() * Math.PI * 2,
          tw: 0.35 + Math.random() * 1.1,
        })),
      }));

      // Distant galaxies: small tilted spirals drifting slowly across the
      // field. They are what stops the background reading as a flat sheet of
      // dots, and they are deliberately dim enough to sit behind the scan
      // rather than compete with it.
      galaxies = Array.from({ length: Math.round(7 * density) }, () => ({
        x: Math.random(),
        y: Math.random(),
        r: 26 + Math.random() * 54,
        tilt: Math.random() * Math.PI,
        squash: 0.22 + Math.random() * 0.35,
        a: 0.05 + Math.random() * 0.07,
        spin: (Math.random() - 0.5) * 0.00006,
        hue: Math.random() < 0.5 ? [150, 200, 255] : [190, 175, 255],
        vx: (Math.random() - 0.5) * 0.000075,
        vy: -0.00002 - Math.random() * 0.00005,
        arms: 2 + Math.floor(Math.random() * 2),
      }));

      motes = Array.from({ length: Math.round(9 * density) }, () => ({
        x: Math.random(),
        y: Math.random(),
        r: 20 + Math.random() * 60,
        a: 0.02 + Math.random() * 0.045,
        vx: (Math.random() - 0.5) * 0.00016,
        vy: -0.00006 - Math.random() * 0.00012,
      }));
    }

    /** One faint spiral: a glowing core plus a couple of sparse arms. */
    function drawGalaxy(g, t) {
      const cx = g.x * w, cy = g.y * h;
      const rot = g.tilt + (reduce ? 0 : t * g.spin);

      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(rot);
      ctx.scale(1, g.squash);

      const core = ctx.createRadialGradient(0, 0, 0, 0, 0, g.r);
      const [r0, g0, b0] = g.hue;
      core.addColorStop(0, `rgba(${r0}, ${g0}, ${b0}, ${g.a * 1.5})`);
      core.addColorStop(0.35, `rgba(${r0}, ${g0}, ${b0}, ${g.a * 0.55})`);
      core.addColorStop(1, `rgba(${r0}, ${g0}, ${b0}, 0)`);
      ctx.fillStyle = core;
      ctx.beginPath();
      ctx.arc(0, 0, g.r, 0, Math.PI * 2);
      ctx.fill();

      // logarithmic arms, stippled rather than stroked so they read as stars
      for (let arm = 0; arm < g.arms; arm++) {
        const offset = (arm / g.arms) * Math.PI * 2;
        for (let i = 0; i < 26; i++) {
          const f = i / 26;
          const ang = offset + f * 3.0;
          const rad = g.r * 0.18 + f * g.r * 0.92;
          const px = Math.cos(ang) * rad;
          const py = Math.sin(ang) * rad;
          ctx.beginPath();
          ctx.arc(px, py, 0.55 + (1 - f) * 0.5, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(${r0}, ${g0}, ${b0}, ${g.a * (1 - f) * 2.4})`;
          ctx.fill();
        }
      }
      ctx.restore();
    }

    function resize() {
      w = canvas.clientWidth || global.innerWidth;
      h = canvas.clientHeight || global.innerHeight;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function draw(t) {
      ctx.clearRect(0, 0, w, h);

      // distant galaxies sit furthest back
      for (const g of galaxies) {
        if (!reduce) {
          g.x += g.vx; g.y += g.vy;
          if (g.y < -0.25) { g.y = 1.25; g.x = Math.random(); }
          if (g.x < -0.25) g.x = 1.25;
          if (g.x > 1.25) g.x = -0.25;
        }
        drawGalaxy(g, t);
      }

      // soft blue dust catching the background bloom
      for (const m of motes) {
        if (!reduce) {
          m.x += m.vx; m.y += m.vy;
          if (m.y < -0.15) { m.y = 1.15; m.x = Math.random(); }
          if (m.x < -0.15) m.x = 1.15;
          if (m.x > 1.15) m.x = -0.15;
        }
        const g = ctx.createRadialGradient(m.x * w, m.y * h, 0, m.x * w, m.y * h, m.r);
        g.addColorStop(0, `rgba(120, 190, 255, ${m.a})`);
        g.addColorStop(1, 'rgba(120, 190, 255, 0)');
        ctx.fillStyle = g;
        ctx.fillRect(m.x * w - m.r, m.y * h - m.r, m.r * 2, m.r * 2);
      }

      for (const layer of layers) {
        for (const s of layer.stars) {
          if (!reduce) {
            s.y -= layer.speed * 0.016;
            if (s.y < -0.02) { s.y = 1.02; s.x = Math.random(); }
          }
          const twinkle = reduce ? 1 : 0.62 + 0.38 * Math.sin(s.phase + t * 0.001 * s.tw);
          ctx.beginPath();
          ctx.arc(s.x * w, s.y * h, s.r, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(214, 236, 255, ${s.a * twinkle})`;
          ctx.fill();
        }
      }
    }

    function frame(t) {
      draw(t);
      raf = requestAnimationFrame(frame);
    }

    resize();
    seed();

    if (reduce) {
      draw(0);
    } else {
      raf = requestAnimationFrame(frame);
    }

    const onResize = () => { resize(); if (reduce) draw(0); };
    global.addEventListener('resize', onResize);

    return {
      stop() {
        if (raf) cancelAnimationFrame(raf);
        global.removeEventListener('resize', onResize);
      },
    };
  }

  global.startStarfield = startStarfield;

  // Auto-start when a #starfield canvas is present.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      startStarfield(document.getElementById('starfield'));
    });
  } else {
    startStarfield(document.getElementById('starfield'));
  }
})(window);
