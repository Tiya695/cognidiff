/* CogniDiff, four cognitive mini-tasks.
 *
 *   1. Word recall     five words for ten seconds, then type them back
 *   2. Reaction time   click the target the instant it lights, five trials
 *   3. Pattern memory  reproduce a highlighted sequence, three rounds
 *   4. Letter scramble unscramble one word, timed
 *
 * Every task opens with a brief: what you are about to do, how it is scored,
 * and what it measures. The first version dropped straight into each task and
 * left people guessing at the rules, which does not just feel bad, it corrupts
 * the measurement. A slow first trial spent working out what is being asked is
 * recorded as a slow reaction, and that is exactly the number the tool then
 * tracks over months.
 *
 * Everything is built with createElement and textContent. No innerHTML anywhere.
 */

(function () {
  'use strict';

  if (!window.requireAuth()) return;

  const $ = (id) => document.getElementById(id);
  const stage = $('stage');
  const results = { word_recall: null, reaction_time_ms: null,
                    pattern_memory: null, letter_scramble_ms: null };

  const WORD_POOL = [
    'harbour', 'lantern', 'copper', 'meadow', 'signal', 'orbit', 'timber',
    'velvet', 'garden', 'anchor', 'pebble', 'thunder', 'ribbon', 'willow',
    'marble', 'candle', 'silver', 'compass', 'feather', 'monsoon',
  ];
  const SCRAMBLE_POOL = [
    'rhythm', 'baseline', 'monitor', 'pattern', 'signal', 'balance', 'network',
  ];

  const sample = (arr, n) => {
    const copy = [...arr], out = [];
    while (out.length < n && copy.length) {
      out.push(copy.splice(Math.floor(Math.random() * copy.length), 1)[0]);
    }
    return out;
  };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const clearStage = () => { stage.textContent = ''; return stage; };

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
  // the brief shown before every task
  // ---------------------------------------------------------------------

  /**
   * @param {object} spec  {n, title, measures, steps[], scoring, cta}
   * Resolves when the person presses the button, so no task can begin before
   * it has been read.
   */
  function brief(spec) {
    setProgress(spec.n - 1);
    setTask(`0${spec.n} · ${spec.title}`, spec.measures.toUpperCase());

    return new Promise((resolve) => {
      const box = clearStage();
      const wrap = el('div', { class: 'brief' }, box);

      el('p', { class: 'brief__step', text: `TASK ${spec.n} OF 4` }, wrap);
      el('h3', { class: 'brief__title', text: spec.title }, wrap);

      const list = el('ol', { class: 'brief__list' }, wrap);
      spec.steps.forEach((s) => el('li', { text: s }, list));

      el('p', { class: 'brief__scoring', text: spec.scoring }, wrap);

      const btn = el('button', {
        class: 'btn btn--solid', text: spec.cta || 'Start this task',
        attrs: { type: 'button' }, style: 'margin-top:1.6rem',
      }, wrap);

      btn.focus();
      btn.addEventListener('click', () => resolve(), { once: true });
    });
  }

  /** Short confirmation between tasks, so progress feels real. */
  async function done(text) {
    const box = clearStage();
    const wrap = el('div', {}, box);
    el('p', { class: 'brief__done', text: '✓' }, wrap);
    el('p', { text, style: 'color:var(--text-dim);margin:.6rem 0 0' }, wrap);
    await sleep(1400);
  }

  // ---------------------------------------------------------------------
  // 1. word recall
  // ---------------------------------------------------------------------

  async function taskWordRecall() {
    await brief({
      n: 1, title: 'Word recall', measures: 'Short-term verbal memory',
      steps: [
        'Five unrelated words appear on screen.',
        'You have 10 seconds to memorise them. A countdown shows the time left.',
        'The words disappear, then you type back as many as you remember.',
        'Order does not matter. Spelling does.',
      ],
      scoring: 'Scored out of 5, one point per word recalled correctly.',
    });

    const words = sample(WORD_POOL, 5);
    const box = clearStage();
    const wrap = el('div', {}, box);
    el('p', { text: 'Memorise these five words.',
              style: 'margin:0 0 1.6rem;color:var(--text-dim)' }, wrap);

    const list = el('div', { class: 'task-words' }, wrap);
    words.forEach((w) => el('span', { class: 'task-word', text: w }, list));

    const bar = el('div', { class: 'task-timer' }, wrap);
    const fill = el('i', {}, bar);
    const countdown = el('p', { class: 'task-count' }, wrap);

    for (let t = 10; t > 0; t--) {
      countdown.textContent = `${t} SECOND${t === 1 ? '' : 'S'} LEFT`;
      fill.style.width = `${(t / 10) * 100}%`;
      await sleep(1000);
    }

    return new Promise((resolve) => {
      const b = clearStage();
      const form = el('form', { style: 'width:min(100%,440px)' }, b);
      el('p', { text: 'Now type the five words, one per line or separated by spaces.',
                style: 'margin:0 0 1.2rem;color:var(--text-dim)' }, form);

      const ta = el('textarea', {
        attrs: { rows: '6', 'aria-label': 'The five words you remember', autocomplete: 'off' },
        style: 'width:100%;padding:.8rem;background:rgba(4,9,28,.7);border:1px solid var(--line);border-radius:9px;color:var(--text);font:inherit;font-size:1.05rem',
      }, form);
      ta.focus();

      const btn = el('button', { class: 'btn btn--solid', text: 'Submit answers',
                                 attrs: { type: 'submit' }, style: 'margin-top:1.2rem' }, form);

      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        btn.disabled = true;
        const given = ta.value.toLowerCase().split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
        const correct = words.filter((w) => given.includes(w)).length;
        results.word_recall = correct;
        await done(`${correct} of 5 recalled.`);
        resolve();
      });
    });
  }

  // ---------------------------------------------------------------------
  // 2. reaction time
  // ---------------------------------------------------------------------

  async function taskReaction() {
    await brief({
      n: 2, title: 'Reaction time', measures: 'Processing speed and attention',
      steps: [
        'A large circle sits in the middle of the screen, dim.',
        'After an unpredictable pause it lights up bright blue.',
        'Click it as fast as you can the moment it lights.',
        'This repeats five times. Do not click early, those trials are discarded.',
      ],
      scoring: 'Scored as your mean reaction time in milliseconds. Lower is better.',
    });

    const TRIALS = 5;
    const times = [];

    const box = clearStage();
    const wrap = el('div', {}, box);
    const note = el('p', { class: 'task-cue',
                           text: 'Get ready…' }, wrap);
    const target = el('button', {
      class: 'task-target',
      attrs: { type: 'button', 'aria-label': 'Reaction target, click when it lights up' },
    }, wrap);
    const tally = el('p', { class: 'task-count' }, wrap);
    const lastTime = el('p', { class: 'task-last' }, wrap);

    await sleep(900);

    for (let trial = 0; trial < TRIALS; trial++) {
      tally.textContent = `TRIAL ${trial + 1} OF ${TRIALS}`;
      target.classList.remove('task-target--hot');
      note.textContent = 'Wait…';
      note.classList.remove('task-cue--go');

      let jumped = false;
      const early = () => { jumped = true; };
      target.addEventListener('click', early);

      await sleep(1000 + Math.random() * 2400);
      target.removeEventListener('click', early);

      if (jumped) {
        note.textContent = 'Too early, that one does not count.';
        lastTime.textContent = '';
        await sleep(1100);
        trial--;                       // redo the trial
        continue;
      }

      note.textContent = 'Now!';
      note.classList.add('task-cue--go');
      target.classList.add('task-target--hot');
      const lit = performance.now();

      await new Promise((resolve) => {
        const onHit = () => { target.removeEventListener('click', onHit); resolve(); };
        target.addEventListener('click', onHit);
      });

      const rt = performance.now() - lit;
      // Anything under 90 ms is anticipation, not reaction, and would flatter
      // the score.
      if (rt >= 90 && rt <= 4000) {
        times.push(rt);
        lastTime.textContent = `${Math.round(rt)} ms`;
      } else {
        lastTime.textContent = 'discarded';
      }

      target.classList.remove('task-target--hot');
      note.classList.remove('task-cue--go');
      await sleep(600);
    }

    results.reaction_time_ms = times.length
      ? Math.round(times.reduce((a, b) => a + b, 0) / times.length)
      : null;

    await done(results.reaction_time_ms
      ? `Mean reaction time ${results.reaction_time_ms} ms.`
      : 'No valid trials recorded.');
  }

  // ---------------------------------------------------------------------
  // 3. pattern memory
  // ---------------------------------------------------------------------

  async function taskPattern() {
    await brief({
      n: 3, title: 'Pattern memory', measures: 'Visuospatial working memory',
      steps: [
        'A grid of nine squares appears.',
        'Four of them light up one after another. Watch the order carefully.',
        'When the grid turns active, click the same squares in the same order.',
        'Three rounds, each with a new sequence.',
      ],
      scoring: 'Scored out of 5, based on how many of the three sequences you reproduce exactly.',
    });

    const ROUNDS = 3, LEN = 4;
    let correctRounds = 0;

    for (let round = 0; round < ROUNDS; round++) {
      const box = clearStage();
      const wrap = el('div', {}, box);
      const note = el('p', { class: 'task-cue', text: 'Watch the sequence' }, wrap);
      const tally = el('p', { class: 'task-count', text: `ROUND ${round + 1} OF ${ROUNDS}` }, wrap);

      const grid = el('div', { class: 'pattern-grid',
                               attrs: { role: 'group', 'aria-label': 'Pattern grid' } }, wrap);
      const cells = [];
      for (let i = 0; i < 9; i++) {
        cells.push(el('button', {
          class: 'pattern-cell',
          attrs: { type: 'button', 'aria-label': `Cell ${i + 1}`, disabled: 'disabled' },
        }, grid));
      }

      const seq = Array.from({ length: LEN }, () => Math.floor(Math.random() * 9));

      await sleep(700);
      for (let i = 0; i < seq.length; i++) {
        note.textContent = `Watch the sequence  ${i + 1}/${LEN}`;
        cells[seq[i]].classList.add('pattern-cell--lit');
        await sleep(560);
        cells[seq[i]].classList.remove('pattern-cell--lit');
        await sleep(240);
      }

      note.textContent = 'Your turn, click them in the same order';
      note.classList.add('task-cue--go');
      cells.forEach((c) => c.removeAttribute('disabled'));

      const entered = [];
      const ok = await new Promise((resolve) => {
        cells.forEach((cell, i) => {
          cell.addEventListener('click', () => {
            cell.classList.add('pattern-cell--tap');
            setTimeout(() => cell.classList.remove('pattern-cell--tap'), 170);
            entered.push(i);
            note.textContent = `Your turn  ${entered.length}/${LEN}`;

            if (entered[entered.length - 1] !== seq[entered.length - 1]) resolve(false);
            else if (entered.length === seq.length) resolve(true);
          });
        });
      });

      cells.forEach((c) => c.setAttribute('disabled', 'disabled'));
      if (ok) correctRounds++;
      note.classList.remove('task-cue--go');
      note.textContent = ok ? 'Correct' : 'Not quite';
      await sleep(900);
    }

    // Scored out of 5 to share a scale with word recall.
    results.pattern_memory = Math.round((correctRounds / ROUNDS) * 5 * 10) / 10;
    await done(`${correctRounds} of ${ROUNDS} sequences correct.`);
  }

  // ---------------------------------------------------------------------
  // 4. letter scramble
  // ---------------------------------------------------------------------

  async function taskScramble() {
    await brief({
      n: 4, title: 'Letter scramble', measures: 'Word retrieval and flexibility',
      steps: [
        'One ordinary English word appears with its letters shuffled.',
        'Work out the word and type it into the box.',
        'The timer starts the moment the word appears.',
        'A wrong answer does not end the task, you can keep trying.',
      ],
      scoring: 'Scored on how long you take to get it right. Faster is better.',
      cta: 'Show me the word',
    });

    const word = sample(SCRAMBLE_POOL, 1)[0];
    let scrambled = word;
    let guard = 0;
    while (scrambled === word && guard++ < 40) {
      scrambled = word.split('').sort(() => Math.random() - 0.5).join('');
    }

    return new Promise((resolve) => {
      const box = clearStage();
      const wrap = el('div', {}, box);
      el('p', { class: 'task-cue', text: 'Unscramble this word' }, wrap);
      el('p', { class: 'task-word', text: scrambled.toUpperCase(),
                style: 'letter-spacing:.35em;margin:.8rem 0 1.8rem' }, wrap);

      const form = el('form', { style: 'display:flex;gap:.5rem;justify-content:center;flex-wrap:wrap' }, wrap);
      const input = el('input', {
        attrs: { type: 'text', 'aria-label': 'Your answer', autocomplete: 'off',
                 spellcheck: 'false', placeholder: 'your answer' },
        style: 'padding:.75rem .95rem;background:rgba(4,9,28,.7);border:1px solid var(--line);border-radius:9px;color:var(--text);font:inherit;font-size:1.05rem;text-align:center',
      }, form);
      el('button', { class: 'btn btn--solid', text: 'Answer', attrs: { type: 'submit' } }, form);

      const elapsed = el('p', { class: 'task-count' }, wrap);
      const feedback = el('p', { class: 'task-last' }, wrap);

      input.focus();
      const started = performance.now();
      const tick = setInterval(() => {
        elapsed.textContent = `${((performance.now() - started) / 1000).toFixed(1)} S`;
      }, 100);

      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (input.value.trim().toLowerCase() !== word) {
          feedback.textContent = 'Not that one, keep going';
          input.select();
          return;
        }
        clearInterval(tick);
        results.letter_scramble_ms = Math.round(performance.now() - started);
        await done(`Solved in ${(results.letter_scramble_ms / 1000).toFixed(1)} seconds.`);
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
    setTask('Assessment complete', 'SUBMITTING YOUR RESULTS');
    clearStage();
    el('p', { text: 'Saving your results…', style: 'color:var(--text-dim)' }, stage);

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
      el('p', { class: 'brief__done', text: '✓' }, stage);
      el('p', { text: 'Done. Your results are saved.',
                style: 'color:var(--green);margin:.6rem 0 0' }, stage);
    } catch (err) {
      $('submitToast').textContent = err.message;
      $('submitToast').classList.add('err');
      clearStage();
      el('p', { text: 'Results are shown below, but could not be saved.',
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
