/* CogniDiff, cognitive trend report.
 *
 * Serves two readers from one page: a user viewing their own report, and a
 * clinician viewing a patient who granted them access. The clinician path adds
 * a patient picker; everything below it is identical, because the report must
 * say the same thing to both.
 */

(function () {
  'use strict';

  if (!window.requireAuth()) return;

  const $ = (id) => document.getElementById(id);
  const { trendChart } = window.CogniCharts;

  const STATUS_TEXT = {
    STABLE: 'Typing patterns are consistent with the individual\'s personal baseline.',
    MONITOR: 'A small number of sessions differed from baseline this week. Within the range of normal variation.',
    SIGNIFICANT_DEVIATION: 'Several sessions this week differed noticeably from baseline. Common non-cognitive causes include sleep, stress and illness.',
    PERSISTENT_DEVIATION: 'Typing patterns have shifted steadily over the past month and the change has persisted. Professional evaluation is recommended.',
    RECALIBRATING: 'The baseline is being rebuilt after a device or environment change. Scores are provisional and no alerts are raised in this window.',
    INSUFFICIENT_DATA: 'Not enough quality-passing data to report a reliable trend.',
  };

  const STATUS_COLOR = {
    STABLE: 'green', MONITOR: 'yellow', SIGNIFICANT_DEVIATION: 'orange',
    PERSISTENT_DEVIATION: 'red', RECALIBRATING: 'blue', INSUFFICIENT_DATA: 'grey',
  };

  function toast(text, isError = false) {
    const el = $('reportToast');
    el.textContent = text;
    el.classList.toggle('err', isError);
  }

  const fmt = (n, suffix = '') => (n == null ? ',' : `${n}${suffix}`);

  function row(tbody, cells) {
    const tr = document.createElement('tr');
    for (const cell of cells) {
      const td = document.createElement('td');
      if (cell && cell.badge) {
        const b = document.createElement('span');
        b.className = `badge badge--${cell.color}`;
        b.textContent = cell.badge;
        td.appendChild(b);
      } else if (cell && cell.num != null) {
        td.className = 'num';
        td.textContent = cell.num;
      } else {
        td.textContent = cell == null ? ',' : String(cell);
      }
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
    return tr;
  }

  function emptyRow(tbody, span, text) {
    tbody.textContent = '';
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = span; td.className = 'empty'; td.textContent = text;
    tr.appendChild(td); tbody.appendChild(tr);
  }

  // ---------------------------------------------------------------------
  // render
  // ---------------------------------------------------------------------

  function renderReport(r) {
    $('report').hidden = false;

    const p = r.patient || {};
    $('patientName').textContent = p.first_name || p.username || 'Monitored individual';

    const bp = r.baseline_period || {};
    $('monitoringPeriod').textContent = bp.start
      ? `Baseline period ${bp.start} to ${bp.end} · ${bp.sessions} sessions · baseline v${bp.version}`
      : 'Baseline not yet established.';

    $('reportMeta').textContent = '';
    [
      ['GENERATED', (r.generated_at || '').replace('T', ' ').slice(0, 16)],
      ['SUBJECT ID', p.user_id || ','],
      ['REPORT', 'COGNITIVE TREND'],
    ].forEach(([k, v]) => {
      const line = document.createElement('div');
      line.appendChild(document.createTextNode(`${k} `));
      const b = document.createElement('b');
      b.textContent = v;
      line.appendChild(b);
      $('reportMeta').appendChild(line);
    });

    $('sCurrent').textContent = fmt(r.current_avg_score);
    $('sPrevious').textContent = fmt(r.previous_avg_score);
    $('sChange').textContent = r.score_change_percent == null
      ? ',' : `${r.score_change_percent > 0 ? '+' : ''}${r.score_change_percent}%`;
    $('sTrend').textContent = (r.trend_direction || ',').replace(/_/g, ' ');

    const status = r.alert_status || 'INSUFFICIENT_DATA';
    const badge = $('statusBadge');
    badge.className = `badge badge--${STATUS_COLOR[status] || 'grey'}`;
    badge.textContent = status.replace(/_/g, ' ');

    const cb = $('confidenceBadge');
    const band = r.confidence_band || 'LOW';
    cb.className = `badge badge--${band === 'HIGH' ? 'green' : band === 'MODERATE' ? 'yellow' : 'orange'}`;
    cb.textContent = `CONFIDENCE ${r.confidence_level == null ? ',' : Math.round(r.confidence_level) + '%'} (${band})`;

    $('statusNote').textContent = (STATUS_TEXT[status] || '') +
      (r.provisional ? ' This reading is flagged provisional and no alert is raised from it.' : '');

    $('dAnalysed').textContent = fmt(r.sessions_analyzed);
    $('dExcluded').textContent = fmt(r.sessions_excluded_quality);
    $('dBaseline').textContent = fmt(bp.sessions);
    $('dStatus').textContent = (p.baseline_status || ',').replace(/_/g, ' ');

    // 90-day chart plus the same information written out, because a canvas is
    // invisible to a screen reader and blank on some printers.
    const summaryEl = $('chart90Summary');
    trendChart($('chart90'), r.trend_90d || [], {
      summaryEl, label: '90-day CogniScore',
    });

    const ft = $('featureRows');
    const feats = r.top_deviating_features || [];
    if (feats.length === 0) {
      emptyRow(ft, 3, 'No deviations recorded in the last 30 days.');
    } else {
      ft.textContent = '';
      feats.forEach((f) => row(ft, [f.label || f.feature, f.days, { num: `${f.avg_deviation}%` }]));
    }

    const ct = $('consentRows');
    const consents = r.consent_record || [];
    if (consents.length === 0) {
      emptyRow(ct, 4, 'No access has been granted.');
    } else {
      ct.textContent = '';
      consents.forEach((c) => row(ct, [
        c.doctor,
        (c.granted_at || '').slice(0, 10),
        c.revoked_at ? c.revoked_at.slice(0, 10) : ',',
        { badge: c.active ? 'ACTIVE' : 'REVOKED', color: c.active ? 'green' : 'grey' },
      ]));
    }

    const v = r.versions || {};
    $('provenance').textContent =
      `MODEL ${v.model_version || ','} · BASELINE v${v.baseline_version ?? ','} · ` +
      `FEATURE SCHEMA ${v.feature_schema_version || ','} · COMMIT ${v.code_commit || ','}`;

    $('disclaimer').textContent = r.disclaimer || '';
    toast('');
  }

  // ---------------------------------------------------------------------
  // load
  // ---------------------------------------------------------------------

  async function loadFor(userId) {
    toast('Loading report…');
    try {
      renderReport(await api.doctorReport(userId));
    } catch (err) {
      toast(err.message, true);
      $('report').hidden = true;
    }
  }

  async function loadPatients() {
    const tbody = $('patientRows');
    try {
      const { patients } = await api.patients();
      if (!patients.length) {
        emptyRow(tbody, 4,
          'No patient has granted you access yet. Ask them to add your username under "Manage access" on their dashboard.');
        return;
      }
      tbody.textContent = '';
      patients.forEach((pt) => {
        const tr = row(tbody, [
          pt.first_name || pt.username,
          (pt.granted_at || '').slice(0, 10),
          (pt.baseline_status || ',').replace(/_/g, ' '),
          '',
        ]);
        const btn = document.createElement('button');
        btn.className = 'btn btn--ghost';
        btn.style.padding = '.35rem .8rem';
        btn.type = 'button';
        btn.textContent = 'Open report';
        btn.addEventListener('click', () => loadFor(pt.user_id));
        tr.lastElementChild.appendChild(btn);
      });
    } catch (err) {
      emptyRow(tbody, 4, err.message);
    }
  }

  $('printBtn').addEventListener('click', () => window.print());
  $('signOut').addEventListener('click', () => {
    api.logout();
    location.href = 'login.html';
  });

  (async function boot() {
    let me = api.store.user;
    try { me = await api.me(); } catch { /* fall back to the cached identity */ }

    if (me && me.role === 'DOCTOR') {
      $('patientPicker').hidden = false;
      loadPatients();
      toast('Select a patient above to open their report.');
    } else {
      loadFor(null);   // own report
    }
  })();
})();
