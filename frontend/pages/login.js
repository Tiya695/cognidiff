/* CogniDiff sign-in / registration. */

(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);

  let mode = 'login';   // 'login' | 'register'

  function say(text, isError = false) {
    const el = $('toast');
    el.textContent = text;
    el.classList.toggle('err', isError);
  }

  function setMode(next) {
    mode = next;
    const isReg = mode === 'register';

    $('modeTag').textContent = isReg ? 'CREATE ACCOUNT' : 'SIGN IN';
    $('modeTitle').textContent = isReg ? 'Start your baseline.' : 'Welcome back.';
    $('modeBlurb').textContent = isReg
      ? 'CogniDiff needs about two weeks of ordinary typing to learn what normal looks like for you. Nothing you type is ever stored.'
      : 'Your cognitive data is yours. Sign in to see your baseline, your trend and exactly who has accessed it.';

    $('nameField').hidden = !isReg;
    $('roleField').hidden = !isReg;
    $('submitBtn').textContent = isReg ? 'Create account' : 'Sign in';
    $('password').setAttribute('autocomplete', isReg ? 'new-password' : 'current-password');
    $('switchPrompt').textContent = isReg ? 'Already have an account?' : 'No account yet?';
    $('switchBtn').textContent = isReg ? 'Sign in' : 'Create one';
    $('demoHint').hidden = isReg;
    say('');
  }

  $('switchBtn').addEventListener('click', () => {
    setMode(mode === 'login' ? 'register' : 'login');
  });

  // Where to go after a successful sign-in.
  function destination(role) {
    const next = params.get('next');
    if (next && /^[a-z0-9._-]+\.html$/i.test(next)) return next;
    return role === 'DOCTOR' ? 'doctor.html' : 'dashboard.html';
  }

  $('authForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = $('submitBtn');
    const username = $('username').value.trim();
    const password = $('password').value;

    if (username.length < 3) { say('Username must be at least 3 characters.', true); return; }
    if (password.length < 8) { say('Password must be at least 8 characters.', true); return; }

    btn.disabled = true;
    say(mode === 'register' ? 'Creating your account…' : 'Signing in…');

    try {
      let out;
      if (mode === 'register') {
        const role = document.querySelector('input[name="role"]:checked').value;
        out = await api.register(username, password, $('firstName').value.trim(), role);
      } else {
        out = await api.login(username, password);
      }
      say('Signed in. Taking you through…');
      location.href = destination(out.role);
    } catch (err) {
      say(err.message, true);
      btn.disabled = false;
    }
  });

  // -- boot ---------------------------------------------------------------

  if (params.get('expired')) {
    say('Your session expired. Please sign in again.', true);
  }
  if (params.get('role') === 'doctor') {
    setMode('login');
    $('modeBlurb').textContent =
      'Clinician access. You can only open a report for a patient who has explicitly granted you access, and they can revoke it at any moment.';
  }

  // Already signed in? Skip straight through.
  if (api.isSignedIn()) {
    const user = api.store.user;
    if (user) location.href = destination(user.role);
  }

  // Surface a dead backend before the user types a password into nothing.
  api.health().catch(() => {
    say('Cannot reach the CogniDiff API on port 8000. Start it with: uvicorn backend.main:app --port 8000', true);
  });
})();
