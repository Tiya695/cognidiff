/* CogniDiff — four cognitive mini-tasks.
 *
 *   1. Word recall     five words for ten seconds, then type them back
 *   2. Reaction time   click the target the instant it lights, five trials
 *   3. Pattern memory  reproduce a highlighted sequence, three rounds
 *   4. Letter scramble unscramble one word, timed
 *
 * Every task builds its DOM with createElement and textContent. The word lists
 * are local constants, but treating them as untrusted costs nothing and means
 * this file has no innerHTML in it at all.
 */

(function () {
  'use strict';

  if (!window.requireAuth()) return;

  const $ = (id) => document.getElementById(id);
  const stage = $('stage');
  const results = { word_recall: null, reaction_time_ms: null,
                    pattern_memory: null, letter_scramble_ms: null };

  let taskIndex = 0;

  const WORD_POOL = [
    'harbour', 'lantern', 'copper', 'meadow', 'signal', 'orbit', 'timber',
    'velvet', 'garden', 'anchor', 'pebble', 'thunder', 'ribbon', 'willow',
    'marble', 'candle', 'silver', 'compass', 'feather', 'monsoon',
  ];
  const SCRAMBLE_POOL = [
    'rhythm', 'baseline', 'monitor', 'pattern', 'signal', 'balance', 'network',
  ];

  const sample = (arr, n) => {
    const copy = [...arr];
    const out = [];
    while (out.length < n && copy.length) {
      out.push(copy.splice(Math.floor(Math.random() * copy.length), 1)[0]);
    }
    return out;
  };

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function clearStage() { stage.textContent = ''; return stage; }

  function el(tag, opts = {}, parent = null) {
    const node = document.createElement(tag);
    if (opts.class) node.className = opts.class;
    if (opts.text != null) node.textContent = opts.text;
    if (opts.style) node.style.cssText = opts.style;
    for (const [k, v] of Object.entries(opts.attrs || {})) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  }

  function setProgress(i) {
    Array.from($('progress').children).forEach((li, idx) => {
      li.className = idx < i ? 'done' : idx === i ? 'active' : '';
    });
  }

  function setTask(name, hint) {
    $('taskName').textContent = name;
    $('taskHint').textContent = hint || '';
  }

  // ---------------------------------------------------------------------
  // 1. word recall
  // ---------------------------------------------------------------------

  async function taskWordRecall() {
    setProgress(0);
    setTask('01 · Word recall', 'MEASURES SHORT-TERM VERBAL MEMORY');

    const words = sample(WORD_POOL, 5);
    const box = clearStage();
    const wrap = el('div', {}, box);
    el('p', { text: 'Memorise these five words. They disappear in 10 seconds.',
              style: 'margin:0 0 1.6rem;color:var(--text-dim)' }, wrap);

    const list = el('div', { class: 'task-words' }, wrap);
    words.forEach((w) => el('span', { class: 'task-word', text: w }, list));

    const countdown = el('p', { style: 'margin:1.8rem 0 0;font-family:var(--mono);color:var(--cyan);letter-spacing:.2em' }, wrap);

    for (let t = 10; t > 0; t--) {
      countdown.textContent = `${String(t).padStart(2, '0')} S`;
      await sleep(1000);
    }

    return new Promise((resolve) => {
      const b = clearStage();
      const form = el('form', { style: 'width:min(100%,420px)' }, b);
      el('p', { text: 'Type the five words, in any order, one per line.',
                style: 'margin:0 0 1.2rem;color:var(--text-dim)' }, form);

      const ta = el('textarea', {
        attrs: { rows: '6', 'aria-label': 'The five words you remember', autocomplete: 'off' },
        style: 'width:100%;padding:.8rem;background:rgba(4,9,28,.7);border:1px solid var(--line);border-radius:9px;color:var(--text);font:inherit;font-size:1.05rem',
      }, form);
      ta.focus();

      const btn = el('button', { class: 'btn btn--solid', text: 'Submit',
                                 attrs: { type: 'submit' }, style: 'margin-top:1.2rem' }, form);

      form.addEventListener('submit', (e) => {
        e.preventDefault();
        btn.disabled = true;
        const given = ta.value.toLowerCase().split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
        const correct = words.filter((w) => given.includes(w)).length;
        results.word_recall = correct;
        resolve();
      });
    });
  }

  // ---------------------------------------------------------------------
  // 2. reaction time
  // ---------------------------------------------------------------------

  async function taskReaction() {
    setProgress(1);
    setTask('02 · Reaction time', 'MEASURES PROCESSING SPEED AND ATTENTION');

    const TRIALS = 5;
    const times = [];

    const box = clearStage();
    const wrap = el('div', {}, box);
    const note = el('p', { text: 'Click the circle the moment it lights up. Five times.',
                           style: 'margin:0 0 1.8rem;color:var(--text-dim)' }, wrap);
    const target = el('button', {
      class: 'task-target',
      attrs: { type: 'button', 'aria-label': 'Reaction target — click when it lights up' },
    }, wrap);
    const tally = el('p', { style: 'margin:1.6rem 0 0;font-family:var(--mono);color:var(--faint);letter-spacing:.2em' }, wrap);

    for (let trial = 0; trial < TRIALS; trial++) {
      tally.textContent = `TRIAL ${trial + 1} / ${TRIALS}`;
      target.classList.remove('task-target--hot');
      note.textContent = 'Wait for it…';

      await sleep(900 + Math.random() * 2200);

      note.textContent = 'Now!';
      target.classList.add('task-target--hot');
      const lit = performance.now();

      await new Promise((resolve) => {
        const onHit = () => { target.removeEventListener('click', onHit); resolve(); };
        target.addEventListener('click', onHit);
      });

      const rt = performance.now() - lit;
      // Guard against a held-down mouse: anything under 90 ms is anticipation,
      // not reaction, and would flatter the score.
      if (rt >= 90 && rt <= 4000) times.push(rt);
      target.classList.remove('task-target--hot');
      await sleep(320);
    }

    results.reaction_time_ms = times.length
      ? Math.round(times.reduce((a, b) => a + b, 0) / times.length)
      : null;
  }

  // ---------------------------------------------------------------------
  // 3. pattern memory
  // ---------------------------------------------------------------------

  async function taskPattern() {
    setProgress(2);
    setTask('03 · Pattern memory', 'MEASURES VISUOSPATIAL WORKING MEMORY');

    const ROUNDS = 3, LEN = 4;
    let correctRounds = 0;

    for (let round = 0; round < ROUNDS; round++) {
      const box = clearStage();
      const wrap = el('div', {}, box);
      const note = el('p', {
        text: `Round ${round + 1} of ${ROUNDS} — watch the sequence.`,
        style: 'margin:0 0 1.6rem;color:var(--text-dim)',
      }, wrap);

      const grid = el('div', { class: 'pattern-grid',
                               attrs: { role: 'group', 'aria-label': 'Pattern grid' } }, wrap);
      const cells = [];
      for (let i = 0; i < 9; i++) {
        const cell = el('button', {
          class: 'pattern-cell',
          attrs: { type: 'button', 'aria-label': `Cell ${i + 1}` },
        }, grid);
        cells.push(cell);
      }

      const sequence = Array.from({ length: LEN }, () => Math.floor(Math.random() * 9));

      await sleep(600);
      for (const idx of sequence) {
        cells[idx].classList.add('pattern-cell--lit');
        await sleep(520);
        cells[idx].classList.remove('pattern-cell--lit');
        await sleep(220);
      }

      note.textContent = 'Now repeat it.';
      const entered = [];

      const ok = await new Promise((resolve) => {
        cells.forEach((cell, i) => {
          cell.addEventListener('click', function onTap() {
            cell.classList.add('pattern-cell--tap');
            setTimeout(() => cell.classList.remove('pattern-cell--tap'), 160);
            entered.push(i);

            if (entered[entered.length - 1] !== sequence[entered.length - 1]) {
              resolve(false);
            } else if (entered.length === sequence.length) {
              resolve(true);
            }
          });
        });
      });

      if (ok) correctRounds++;
      note.textContent = ok ? 'Correct.' : 'Not quite.';
      await sleep(750);
    }

    // Scored out of 5 to share a scale with word recall.
    results.pattern_memory = Math.round((correctRounds / ROUNDS) * 5 * 10) / 10;
  }

  // ---------------------------------------------------------------------
  // 4. letter scramble
  // ---------------------------------------------------------------------

  function taskScramble() {
    setProgress(3);
    setTask('04 · Letter scramble', 'MEASURES WORD RETRIEVAL AND FLEXIBILITY');

    const word = sample(SCRAMBLE_POOL, 1)[0];
    let scrambled = word;
    // Reshuffle until it actually differs — an unscrambled "scramble" is a
    // free point and would quietly inflate the score.
    let guard = 0;
    while (scrambled === word && guard++ < 40) {
      scrambled = word.split('').sort(() => Math.random() - 0.5).join('');
    }

    return new Promise((resolve) => {
      const box = clearStage();
      const wrap = el('div', {}, box);
      el('p', { text: 'Unscramble this word as fast as you can.',
                style: 'margin:0 0 1.4rem;color:var(--text-dim)' }, wrap);
      el('p', { class: 'task-word', text: scrambled.toUpperCase(),
                style: 'letter-spacing:.35em;margin:0 0 1.8rem' }, wrap);

      const form = el('form', { style: 'display:flex;gap:.5rem;justify-content:center;flex-wrap:wrap' }, wrap);
      const input = el('input', {
        attrs: { type: 'text', 'aria-label': 'Your answer', autocomplete: 'off', spellcheck: 'false' },
        style: 'padding:.75rem .95rem;background:rgba(4,9,28,.7);border:1px solid var(--line);border-radius:9px;color:var(--text);font:inherit;font-size:1.05rem;text-align:center',
      }, form);
      el('button', { class: 'btn btn--solid', text: 'Answer', attrs: { type: 'submit' } }, form);
      const feedback = el('p', { style: 'margin:1.2rem 0 0;font-family:var(--mono);color:var(--faint);font-size:11px;letter-spacing:.16em' }, wrap);

      input.focus();
      const started = performance.now();

      form.addEventListener('submit', (e) => {
        e.preventDefault();
        if (input.value.trim().toLowerCase() !== word) {
          feedback.textContent = 'NOT QUITE — TRY AGAIN';
          input.select();
          return;
        }
        results.letter_scramble_ms = Math.round(performance.now() - started);
        resolve();
      });
    });
  }

  // ---------------------------------------------------------------------
  // run + submit
  // ---------------------------------------------------------------------

  async function run() {
    await taskWordRecall();
    await taskReaction();
    await taskPattern();
    await taskScramble();

    setProgress(4);
    setTask('Assessment complete', '');
    clearStage();
    el('p', { text: 'Submitting your results…',
              style: 'color:var(--text-dim)' }, stage);

    $('rRecall').textContent = results.word_recall ?? '—';
    $('rReaction').textContent = results.reaction_time_ms ? `${results.reaction_time_ms} ms` : '—';
    $('rPattern').textContent = results.pattern_memory ?? '—';
    $('rScramble').textContent = results.letter_scramble_ms
      ? `${(results.letter_scramble_ms / 1000).toFixed(1)} s` : '—';
    $('resultsCard').hidden = false;
    $('resultsCard').scrollIntoView({ behavior: 'smooth', block: 'start' });

    try {
      const out = await api.submitTasks(results);
      $('compositeLine').textContent =
        `Composite task score ${out.composite_task_score} from ${out.tasks_completed} tasks. ` +
        `Today's CogniScore now blends keystroke and task evidence.`;
      clearStage();
      el('p', { text: 'Done. Your results are saved.', style: 'color:var(--green)' }, stage);
    } catch (err) {
      $('submitToast').textContent = err.message;
      $('submitToast').classList.add('err');
      clearStage();
      el('p', { text: 'Results shown below, but could not be saved.',
                style: 'color:var(--red)' }, stage);
    }
  }

  $('startBtn').addEventListener('click', () => { run(); });
  $('againBtn').addEventListener('click', () => { location.reload(); });
  $('signOut').addEventListener('click', () => {
    api.logout();
    location.href = 'login.html';
  });
})();
