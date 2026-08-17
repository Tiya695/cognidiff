/* CogniDiff API client.
 *
 * Two rules this file exists to enforce:
 *
 *  1. The base URL lives here and nowhere else. No page hardcodes
 *     http://localhost:8000 — that was a Phase 6 finding.
 *  2. The identity is the token. Nothing in the frontend ever sends a user_id;
 *     the server resolves who you are from the Bearer token, which is what
 *     closed the IDOR hole.
 */

(function (global) {
  'use strict';

  const API_BASE = (global.COGNIDIFF_API_BASE) || 'http://localhost:8000';
  const TOKEN_KEY = 'cognidiff.token';
  const USER_KEY = 'cognidiff.user';

  const store = {
    get token() { return localStorage.getItem(TOKEN_KEY); },
    set token(v) {
      if (v) localStorage.setItem(TOKEN_KEY, v);
      else localStorage.removeItem(TOKEN_KEY);
    },
    get user() {
      try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null'); }
      catch { return null; }
    },
    set user(v) {
      if (v) localStorage.setItem(USER_KEY, JSON.stringify(v));
      else localStorage.removeItem(USER_KEY);
    },
    clear() { this.token = null; this.user = null; },
  };

  class ApiError extends Error {
    constructor(status, detail, body) {
      super(detail || `Request failed (${status})`);
      this.name = 'ApiError';
      this.status = status;
      this.body = body;
    }
  }

  async function request(path, { method = 'GET', body, auth = true } = {}) {
    const headers = {};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (auth && store.token) headers.Authorization = `Bearer ${store.token}`;

    let res;
    try {
      res = await fetch(`${API_BASE}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (err) {
      throw new ApiError(0, 'Cannot reach the CogniDiff API. Is the backend running on port 8000?');
    }

    if (res.status === 401 && auth) {
      store.clear();
      if (!location.pathname.endsWith('login.html')) {
        location.href = 'login.html?expired=1';
      }
      throw new ApiError(401, 'Your session has expired. Please sign in again.');
    }

    const text = await res.text();
    let payload = null;
    if (text) { try { payload = JSON.parse(text); } catch { payload = { detail: text }; } }

    if (!res.ok) {
      throw new ApiError(res.status, detailOf(payload, res.status), payload);
    }
    return payload;
  }

  /** Pydantic 422 bodies are structured; flatten them into one readable line. */
  function detailOf(payload, status) {
    if (!payload) return `Request failed (${status})`;
    const d = payload.detail;
    if (typeof d === 'string') return d;
    if (Array.isArray(d)) {
      return d.map((e) => {
        const where = Array.isArray(e.loc) ? e.loc.filter((p) => p !== 'body').join('.') : '';
        return where ? `${where}: ${e.msg}` : e.msg;
      }).join('; ');
    }
    return `Request failed (${status})`;
  }

  const api = {
    base: API_BASE,
    store,
    ApiError,

    isSignedIn: () => Boolean(store.token),

    async login(username, password) {
      const out = await request('/api/auth/login', {
        method: 'POST', auth: false, body: { username, password },
      });
      store.token = out.access_token;
      store.user = {
        user_id: out.user_id, username: out.username,
        role: out.role, first_name: out.first_name,
      };
      return out;
    },

    async register(username, password, first_name, role) {
      const out = await request('/api/auth/register', {
        method: 'POST', auth: false,
        body: { username, password, first_name: first_name || null, role },
      });
      store.token = out.access_token;
      store.user = { user_id: out.user_id, username: out.username, role: out.role, first_name };
      return out;
    },

    logout() { store.clear(); },

    health:        () => request('/api/health', { auth: false }),
    me:            () => request('/api/auth/me'),
    dashboard:     () => request('/api/dashboard/me'),
    summary:       () => request('/api/summary/me'),
    alert:         () => request('/api/alert/me'),
    sessionSummary:() => request('/api/sessions/me/summary'),
    quality:       () => request('/api/sessions/quality'),
    drift:         () => request('/api/drift/me'),
    auditLog:      () => request('/api/audit-log/me'),
    grants:        () => request('/api/consent/my-grants'),
    contextToday:  () => request('/api/context/me'),
    predict:       () => request('/api/lstm/predict'),
    featureImportance: () => request('/api/feature-importance'),
    ablation:      () => request('/api/ablation/me'),
    federated:     () => request('/api/federated/status'),
    exportData:    () => request('/api/export/me'),

    score:         () => request('/api/score', { method: 'POST', body: { recompute: true } }),
    fitBaseline:   () => request('/api/baseline/fit', { method: 'POST', body: null }),
    refitBaseline: () => request('/api/baseline/refit', { method: 'POST', body: null }),
    fitAnomaly:    () => request('/api/anomaly/fit', { method: 'POST', body: null }),
    fitLstm:       () => request('/api/lstm/fit', { method: 'POST', body: null }),

    setContext:    (payload) => request('/api/context', { method: 'POST', body: payload }),
    submitTasks:   (payload) => request('/api/task-score', { method: 'POST', body: payload }),
    grantConsent:  (doctor_username) =>
      request('/api/consent/grant', { method: 'POST', body: { doctor_username } }),
    revokeConsent: (doctor_id) =>
      request('/api/consent/revoke', { method: 'POST', body: { doctor_id } }),

    patients:      () => request('/api/doctor/patients'),
    doctorReport:  (userId) => request(
      userId ? `/api/doctor-report/${encodeURIComponent(userId)}` : '/api/doctor-report/me'
    ),

    deleteEverything: () => request('/api/user/me', { method: 'DELETE' }),
  };

  global.api = api;

  /** Redirect to login unless a token is present. */
  global.requireAuth = function requireAuth() {
    if (!api.isSignedIn()) {
      location.href = `login.html?next=${encodeURIComponent(location.pathname.split('/').pop())}`;
      return false;
    }
    return true;
  };
})(window);
