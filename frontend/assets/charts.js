/* Chart.js configuration for CogniDiff.
 *
 * One place for the palette and axis styling so every chart in the product
 * reads the same. Each chart is paired with a text summary written into a
 * screen-reader-only element, a <canvas> is completely opaque to assistive
 * technology, so the trend has to exist in words as well.
 */

(function (global) {
  'use strict';

  const CY = '#7fd8ff';
  const GRID = 'rgba(127, 216, 255, .08)';
  const TICK = '#7f95b8';
  const FONT = '"JetBrains Mono", "Cascadia Mono", Consolas, ui-monospace, monospace';

  /** Score bands, used for the ring colour and chart point colours. */
  function bandColor(score) {
    if (score == null) return '#566d92';
    if (score >= 80) return '#5ce6b5';
    if (score >= 60) return '#ffd166';
    if (score >= 40) return '#ff9f5a';
    return '#ff7a8a';
  }

  function baseOptions(extra = {}) {
    return Object.assign({
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(6, 14, 36, .96)',
          borderColor: 'rgba(127, 216, 255, .28)',
          borderWidth: 1,
          titleFont: { family: FONT, size: 11 },
          bodyFont: { family: FONT, size: 12 },
          padding: 10,
          displayColors: false,
          callbacks: {
            label: (ctx) => (ctx.parsed.y == null
              ? 'No reading that day'
              : `CogniScore ${ctx.parsed.y}`),
          },
        },
      },
      scales: {
        x: {
          grid: { color: GRID, drawTicks: false },
          border: { display: false },
          ticks: { color: TICK, font: { family: FONT, size: 9 }, maxRotation: 0, autoSkipPadding: 18 },
        },
        y: {
          min: 0, max: 100,
          grid: { color: GRID, drawTicks: false },
          border: { display: false },
          ticks: { color: TICK, font: { family: FONT, size: 9 }, stepSize: 25 },
        },
      },
    }, extra);
  }

  /**
   * Draw a CogniScore trend line.
   * `rows` is [{date, score}], with null scores for days that have no reading.
   */
  function trendChart(canvas, rows, { summaryEl, label = 'CogniScore' } = {}) {
    if (!canvas || typeof global.Chart === 'undefined') return null;

    const labels = rows.map((r) => (r.date || '').slice(5));   // MM-DD
    const values = rows.map((r) => (r.score == null ? null : Number(r.score)));

    const ctx = canvas.getContext('2d');
    const grad = ctx.createLinearGradient(0, 0, 0, canvas.height || 240);
    grad.addColorStop(0, 'rgba(127, 216, 255, .30)');
    grad.addColorStop(1, 'rgba(127, 216, 255, 0)');

    if (canvas._chart) canvas._chart.destroy();

    canvas._chart = new global.Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label,
          data: values,
          spanGaps: true,               // a missing day is a gap, not a zero
          borderColor: CY,
          borderWidth: 2,
          fill: true,
          backgroundColor: grad,
          tension: 0.34,
          pointRadius: values.map((v) => (v == null ? 0 : 3)),
          pointBackgroundColor: values.map(bandColor),
          pointBorderColor: 'rgba(4, 9, 28, .9)',
          pointBorderWidth: 1.5,
          pointHoverRadius: 6,
        }],
      },
      options: baseOptions(),
    });

    if (summaryEl) summaryEl.textContent = describeTrend(rows, label);
    return canvas._chart;
  }

  /** The text equivalent of the chart, for screen readers and the print view. */
  function describeTrend(rows, label = 'CogniScore') {
    const pts = rows.filter((r) => r.score != null).map((r) => Number(r.score));
    if (pts.length === 0) return `${label}: no readings recorded in this period yet.`;
    if (pts.length === 1) return `${label}: a single reading of ${pts[0]}.`;

    const first = pts[0], last = pts[pts.length - 1];
    const min = Math.min(...pts), max = Math.max(...pts);
    const avg = Math.round(pts.reduce((a, b) => a + b, 0) / pts.length);
    const delta = Math.round(last - first);

    const direction = delta > 4 ? `rising by ${delta} points`
                    : delta < -4 ? `falling by ${Math.abs(delta)} points`
                    : 'broadly flat';

    return `${label} over ${rows.length} days: ${pts.length} readings, ` +
           `average ${avg}, ranging ${Math.round(min)} to ${Math.round(max)}, ` +
           `${direction} from ${Math.round(first)} to ${Math.round(last)}. ` +
           `Days without a reading are shown as gaps.`;
  }

  /** Animate the score ring from 0 to the target over 1.5 s. */
  function animateRing(circle, numEl, score, { radius = 52, duration = 1500 } = {}) {
    const circumference = 2 * Math.PI * radius;
    circle.setAttribute('stroke-dasharray', `0 ${circumference.toFixed(1)}`);

    const target = Math.max(0, Math.min(100, Number(score) || 0));
    circle.style.stroke = bandColor(target);

    if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
      circle.setAttribute('stroke-dasharray',
        `${(circumference * target / 100).toFixed(1)} ${circumference.toFixed(1)}`);
      if (numEl) numEl.textContent = Math.round(target);
      return;
    }

    let finished = false;
    const settle = () => {
      if (finished) return;
      finished = true;
      circle.setAttribute('stroke-dasharray',
        `${(circumference * target / 100).toFixed(1)} ${circumference.toFixed(1)}`);
      if (numEl) numEl.textContent = Math.round(target);
    };

    // requestAnimationFrame is throttled to a standstill in a background tab,
    // which would leave the headline number sitting on an em-dash until the
    // user happens to focus the window. Guarantee the final value lands.
    const guard = setTimeout(settle, duration + 400);

    const start = performance.now();
    function step(now) {
      if (finished) return;
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      const value = target * eased;
      circle.setAttribute('stroke-dasharray',
        `${(circumference * value / 100).toFixed(1)} ${circumference.toFixed(1)}`);
      if (numEl) numEl.textContent = Math.round(value);
      if (t < 1) requestAnimationFrame(step);
      else { clearTimeout(guard); settle(); }
    }
    requestAnimationFrame(step);
  }

  global.CogniCharts = { trendChart, describeTrend, animateRing, bandColor };
})(window);
