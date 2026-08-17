/* CogniDiff — the drifting star field behind everything.
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

    let w = 0, h = 0, layers = [], motes = [], raf = null;

    const LAYERS = [
      { n: 130, speed: 0.0022, size: [0.35, 0.9],  alpha: [0.14, 0.42] },
      { n: 70,  speed: 0.0060, size: [0.55, 1.25], alpha: [0.26, 0.66] },
      { n: 26,  speed: 0.0125, size: [0.85, 1.75], alpha: [0.42, 0.95] },
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

      motes = Array.from({ length: Math.round(9 * density) }, () => ({
        x: Math.random(),
        y: Math.random(),
        r: 20 + Math.random() * 60,
        a: 0.02 + Math.random() * 0.045,
        vx: (Math.random() - 0.5) * 0.00016,
        vy: -0.00006 - Math.random() * 0.00012,
      }));
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
