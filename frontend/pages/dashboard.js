/* CogniDiff dashboard.
 *
 * Every value from the API is written with textContent. Nothing here builds
 * markup from a server string — a hostile value stored in the database renders
 * as visible characters and never executes (Phase 6, Attack 8).
 */

(function () {
  'use strict';

  if (!window.requireAuth()) return;

  const $ = (id) => document.getElementById(id);
  const { trendChart, animateRing } = window.CogniCharts;

  const BANNER_ICON = {
    green: '✓', yellow: '◉', orange: '!', red: '⚑',
    blue: '↻', grey: '…',
  };

  function toast(el, text, isError = false) {
    el.textContent = text;
    el.classList.toggle('err', isError);
  }

  // ---------------------------------------------------------------------
  // renderers
  // ---------------------------------------------------------------------

  function renderAlert(alert) {
    const banner = $('alertBanner');
    const colour = (alert && alert.color) || 'grey';
    banner.className = `banner banner--${colour}`;
    $('alertIcon').textContent = BANNER_ICON[colour] || '…';
    $('alertLabel').textContent = (alert && alert.label) || 'Monitoring';
    $('alertText').textContent = (alert && alert.user_message) || '';
  }

  function renderScore(d) {
    const score = d.current_score;

    if (score == null) {
      $('scoreNum').textContent = '—';
      $('scoreExplain').textContent = d.message ||
        'Not enough quality sessions yet to produce a score.';
      return;
    }

    animateRing($('ringValue'), $('scoreNum'), score);

    const conf = d.confidence, band = d.confidence_band || 'LOW';
    const badge = $('confBadge');
    badge.className = 'badge badge--' +
      (band === 'HIGH' ? 'green' : band === 'MODERATE' ? 'yellow' : 'orange');
    $('confText').textContent =
      `CONFIDENCE ${conf == null ? '—' : Math.round(conf) + '%'} (${band})`;

    $('scoreExplain').textContent = d.provisional
      ? 'This reading is provisional — there is not enough evidence today for a firm result, so no alert is raised from it.'
      : '100 means today matches your own baseline exactly. This is never compared against anybody else.';

    $('mRaw').textContent = fmt(d.raw_score);
    $('mAdj').textContent = d.context && d.context.context_adjusted
      ? `${fmt(d.adjusted_score)} (+${d.context.tolerance_applied})`
      : fmt(d.adjusted_score);
    $('mBlend').textContent = d.task_score == null
      ? 'keystroke only' : `${d.composite_weighting}`;
    $('mDev').textContent = d.raw_score == null ? '—' : `${fmt(d.deviation_percent)}%`;

    const p = d.lstm_prediction_tomorrow || {};
    $('mPredict').textContent = p.predicted_score == null
      ? '—' : `${p.predicted_score} (${p.trend || 'unknown'})`;

    const dc = d.dual_confirmation || {};
    $('mAgree').textContent = ({
      BOTH_AGREE_NORMAL: 'both models: normal',
      BOTH_AGREE_ANOMALOUS: 'both models: unusual',
      MODELS_DISAGREE: 'models disagree',
    })[dc.agreement] || '—';

    const v = d.versions || {};
    $('versionFoot').textContent =
      `MODEL ${v.model_version || '—'} · BASELINE v${d.user?.baseline_version ?? '—'} · ` +
      `FEATURES ${v.feature_schema_version || '—'} · COMMIT ${v.code_commit || '—'}`;
  }

  const fmt = (n) => (n == null ? '—' : Number(n).toFixed(1));

  function renderDrift(d) {
    const drift = d.drift || {};
    const status = d.user && d.user.baseline_status;
    const banner = $('driftBanner');

    if (status === 'RECALIBRATING') {
      const r = drift.recalibration || {};
      banner.hidden = false;
      $('driftText').textContent =
        `Recalibrating to your new setup — scores are provisional and no alerts ` +
        `will be raised until your new baseline is established. ` +
        `${r.sessions_collected ?? 0} of ${r.sessions_required ?? 30} clean sessions collected.`;
      return;
    }

    if (drift.classification === 'GRADUAL_UNEXPLAINED') {
      banner.hidden = false;
      banner.className = 'banner banner--yellow';
      $('driftText').textContent =
        'A steady shift with no device or environment change to explain it. ' +
        'This is not recalibrated away — it is exactly what CogniDiff watches for. ' +
        'Keep monitoring and review the trend with a professional if it persists.';
      return;
    }

    if (drift.drift_severity === 'high' || drift.drift_severity === 'medium') {
      banner.hidden = false;
      banner.className = 'banner banner--blue';
      const labels = d.feature_labels || {};
      const names = (drift.drifted_features || [])
        .map((f) => (labels[f.feature] || f.feature).toLowerCase())
        .join(', ');
      $('driftText').textContent =
        `Your baseline may need updating${names ? ` (${names} have shifted)` : ''}. ` +
        `This is normal after significant lifestyle changes.`;
      return;
    }

    banner.hidden = true;
  }

  function renderChanges(d) {
    const list = $('changes');
    list.textContent = '';

    const items = d.top_3_changes || [];
    if (items.length === 0) {
      const li = document.createElement('li');
      li.className = 'empty';
      li.textContent = 'Not enough data to explain a change yet.';
      list.appendChild(li);
      return;
    }

    const maxPct = Math.max(...items.map((i) => Math.abs(i.percent_change || 0)), 1);

    for (const item of items) {
      const pct = item.percent_change;
      const up = item.direction === 'increased';
      const li = document.createElement('li');
      li.className = up ? 'up' : 'down';

      const label = document.createElement('span');
      label.className = 'changes__label';
      label.textContent = item.text || item.label || item.feature;
      li.appendChild(label);

      const value = document.createElement('span');
      value.className = 'changes__pct';
      value.textContent = pct == null ? '—' : `${pct > 0 ? '+' : ''}${Math.round(pct)}%`;
      li.appendChild(value);

      const bar = document.createElement('span');
      bar.className = 'changes__bar';
      const fill = document.createElement('i');
      fill.style.width = `${Math.min(100, Math.abs(pct || 0) / maxPct * 100)}%`;
      bar.appendChild(fill);
      li.appendChild(bar);

      list.appendChild(li);
    }

    $('changesMethod').textContent =
      `METHOD ${(d.explanation_method || 'baseline_ranking').toUpperCase().replace(/_/g, ' ')} · ` +
      `percentages are versus your own baseline`;
  }

  function renderQuality(d) {
    $('qAnalysed').textContent = d.sessions_analysed ?? '—';
    $('qExcluded').textContent = d.sessions_excluded_quality ?? '—';
    $('qRate').textContent = d.exclusion_rate_percent == null
      ? '—' : `${d.exclusion_rate_percent}%`;
    $('qBaseline').textContent =
      `${d.confidence_breakdown ? Math.round((d.confidence_breakdown.baseline_size / 100) * 30) : 0}`;

    const tbody = $('qReasons');
    tbody.textContent = '';
    const reasons = d.exclusion_reasons || [];

    if (reasons.length === 0) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 3; td.className = 'empty';
      td.textContent = 'No sessions have been excluded.';
      tr.appendChild(td); tbody.appendChild(tr);
      return;
    }

    for (const r of reasons) {
      const tr = document.createElement('tr');
      for (const [text, cls] of [[r.reason_code, ''], [r.description, ''], [r.n, 'num']]) {
        const td = document.createElement('td');
        td.className = cls;
        td.textContent = text ?? '—';
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
  }

  function renderGrants(rows) {
    const tbody = $('grantRows');
    tbody.textContent = '';

    if (!rows || rows.length === 0) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 4; td.className = 'empty';
      td.textContent = 'Nobody has access to your data.';
      tr.appendChild(td); tbody.appendChild(tr);
      return;
    }

    for (const g of rows) {
      const tr = document.createElement('tr');

      const who = document.createElement('td');
      who.textContent = g.doctor_username || g.granted_to;
      tr.appendChild(who);

      const when = document.createElement('td');
      when.textContent = (g.granted_at || '').slice(0, 10);
      tr.appendChild(when);

      const status = document.createElement('td');
      const badge = document.createElement('span');
      badge.className = `badge badge--${g.active ? 'green' : 'grey'}`;
      badge.textContent = g.active ? 'ACTIVE' : 'REVOKED';
      status.appendChild(badge);
      tr.appendChild(status);

      const action = document.createElement('td');
      if (g.active) {
        const btn = document.createElement('button');
        btn.className = 'btn btn--danger';
        btn.style.padding = '.35rem .8rem';
        btn.type = 'button';
        btn.textContent = 'Revoke';
        btn.addEventListener('click', async () => {
          btn.disabled = true;
          try {
            await api.revokeConsent(g.granted_to);
            toast($('grantToast'), 'Access revoked. Effective immediately.');
            renderGrants((await api.grants()).grants);
            loadAudit();
          } catch (err) {
            toast($('grantToast'), err.message, true);
            btn.disabled = false;
          }
        });
        action.appendChild(btn);
      }
      tr.appendChild(action);
      tbody.appendChild(tr);
    }
  }

  function renderAudit(entries) {
    const tbody = $('auditRows');
    tbody.textContent = '';

    if (!entries || entries.length === 0) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = 4; td.className = 'empty';
      td.textContent = 'No entries yet.';
      tr.appendChild(td); tbody.appendChild(tr);
      return;
    }

    for (const e of entries) {
      const tr = document.createElement('tr');

      const when = document.createElement('td');
      when.textContent = (e.timestamp || '').replace('T', ' ').slice(0, 16);
      tr.appendChild(when);

      const who = document.createElement('td');
      who.textContent = e.actor === 'you' ? 'You' : (e.actor || 'unknown');
      tr.appendChild(who);

      const what = document.createElement('td');
      what.textContent = (e.action || '').replace(/_/g, ' ').toLowerCase();
      tr.appendChild(what);

      const outcome = document.createElement('td');
      const badge = document.createElement('span');
      badge.className = `badge badge--${e.outcome === 'SUCCESS' ? 'green' : 'red'}`;
      badge.textContent = e.outcome === 'SUCCESS' ? 'ALLOWED' : 'DENIED';
      outcome.appendChild(badge);
      tr.appendChild(outcome);

      tbody.appendChild(tr);
    }
  }

  // ---------------------------------------------------------------------
  // context form
  // ---------------------------------------------------------------------

  function buildScale(container, name, labels) {
    container.textContent = '';
    labels.forEach((text, i) => {
      const label = document.createElement('label');
      const input = document.createElement('input');
      input.type = 'radio'; input.name = name; input.value = String(i + 1);
      label.appendChild(input);
      label.appendChild(document.createTextNode(` ${text}`));
      container.appendChild(label);
    });
  }

  async function loadContext() {
    buildScale($('sleepRadios'), 'sleep', ['1 poor', '2', '3 ok', '4', '5 great']);
    buildScale($('stressRadios'), 'stress', ['1 calm', '2', '3 ok', '4', '5 high']);
    try {
      const { context } = await api.contextToday();
      if (!context) return;
      if (context.sleep_quality) {
        const el = document.querySelector(`input[name="sleep"][value="${context.sleep_quality}"]`);
        if (el) el.checked = true;
      }
      if (context.stress_level) {
        const el = document.querySelector(`input[name="stress"][value="${context.stress_level}"]`);
        if (el) el.checked = true;
      }
      $('ctxUnwell').checked = Boolean(context.feeling_unwell);
      $('ctxDevice').checked = Boolean(context.device_changed);
    } catch { /* no context yet — leave the form blank */ }
  }

  $('contextForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const pick = (name) => {
      const el = document.querySelector(`input[name="${name}"]:checked`);
      return el ? Number(el.value) : null;
    };
    try {
      await api.setContext({
        sleep_quality: pick('sleep'),
        stress_level: pick('stress'),
        feeling_unwell: $('ctxUnwell').checked,
        device_changed: $('ctxDevice').checked,
      });
      toast($('contextToast'), 'Saved. Today\'s reading has been adjusted.');
      load();
    } catch (err) {
      toast($('contextToast'), err.message, true);
    }
  });

  // ---------------------------------------------------------------------
  // actions
  // ---------------------------------------------------------------------

  $('grantForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = $('doctorUser').value.trim();
    if (!name) return;
    try {
      await api.grantConsent(name);
      $('doctorUser').value = '';
      toast($('grantToast'), `${name} can now open your report.`);
      renderGrants((await api.grants()).grants);
      loadAudit();
    } catch (err) {
      toast($('grantToast'), err.message, true);
    }
  });

  $('btnFit').addEventListener('click', async () => {
    toast($('actionToast'), 'Refitting your baseline and detector…');
    try {
      const b = await api.refitBaseline();
      try { await api.fitAnomaly(); } catch { /* needs more sessions — fine */ }
      try { await api.fitLstm(); } catch { /* needs more days — fine */ }
      toast($('actionToast'),
        `Baseline v${b.baseline_version} fitted on ${b.sessions_used} sessions.`);
      load();
    } catch (err) {
      toast($('actionToast'), err.message, true);
    }
  });

  $('btnExport').addEventListener('click', async () => {
    toast($('actionToast'), 'Preparing your export…');
    try {
      const data = await api.exportData();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `cognidiff-export-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      toast($('actionToast'), 'Exported. No typed text is in the file, because none was ever stored.');
    } catch (err) {
      toast($('actionToast'), err.message, true);
    }
  });

  $('btnDelete').addEventListener('click', async () => {
    const ok = confirm(
      'Delete every CogniDiff record on your account?\n\n' +
      'Sessions, scores, task results, context and consent grants will be erased ' +
      'and your models deleted. This cannot be undone.'
    );
    if (!ok) return;
    try {
      const out = await api.deleteEverything();
      alert(out.message);
      api.logout();
      location.href = 'login.html';
    } catch (err) {
      toast($('actionToast'), err.message, true);
    }
  });

  $('refreshSummary').addEventListener('click', loadSummary);

  $('signOut').addEventListener('click', () => {
    api.logout();
    location.href = 'login.html';
  });

  // ---------------------------------------------------------------------
  // loading
  // ---------------------------------------------------------------------

  async function loadSummary() {
    $('summaryText').textContent = 'Generating…';
    $('summarySrc').textContent = '';
    try {
      const out = await api.summary();
      if (!out.summary) {
        $('summaryText').textContent = out.message ||
          'A summary appears once your baseline is established.';
        return;
      }
      $('summaryText').textContent = out.summary.text;
      $('summarySrc').textContent = out.summary.source === 'claude_api'
        ? `GENERATED BY ${String(out.summary.model || 'CLAUDE').toUpperCase()}`
        : 'LOCAL TEMPLATE · SET ANTHROPIC_API_KEY FOR CLAUDE-WRITTEN SUMMARIES';
    } catch (err) {
      $('summaryText').textContent = err.message;
    }
  }

  async function loadAudit() {
    try { renderAudit((await api.auditLog()).entries); } catch { /* non-fatal */ }
  }

  async function load() {
    try {
      const d = await api.dashboard();

      const name = d.user && d.user.first_name;
      $('greeting').textContent = name ? `${name}'s baseline, today.` : 'Your baseline, today.';
      $('subhead').textContent = d.status === 'OK'
        ? `${d.sessions_analysed} sessions analysed · ${d.sessions_excluded_quality} excluded on quality · trend ${d.trend_direction.replace(/_/g, ' ')}`
        : (d.message || 'Collecting data.');

      renderAlert(d.alert_status);
      renderDrift(d);
      renderScore(d);
      renderChanges(d);
      renderQuality(d);

      trendChart($('chart7'), d.trend_7d || [], {
        summaryEl: $('chart7Summary'), label: '7-day CogniScore',
      });
      trendChart($('chart30'), d.trend_30d || [], {
        summaryEl: $('chart30Summary'), label: '30-day CogniScore',
      });
    } catch (err) {
      $('subhead').textContent = err.message;
      renderAlert({ color: 'red', label: 'Connection', user_message: err.message });
    }
  }

  (async function boot() {
    await Promise.all([load(), loadContext(), loadAudit()]);
    try { renderGrants((await api.grants()).grants); } catch { /* non-fatal */ }
    loadSummary();
  })();
})();
