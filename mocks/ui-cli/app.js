/*
 * FDAI operator-console CLI - design mock (static, no deps).
 *
 * Plays a JARVIS-style streaming briefing: boot banner -> greeting -> throughput
 * chart drawn left-to-right -> tier bars filling -> branch (HIL approval cards or
 * an all-clear free-chat prompt). Everything here is synthetic and customer-
 * agnostic; the real console would stream the same shape from read-only
 * console-tool calls. Streaming is presentation only - never a judgment.
 */

// --- synthetic briefing data (mirrors the read-only console-tool payload) -----
const BRIEFING = {
  env: 'staging',
  operator: 'Alice',
  clock: '09:41 UTC',
  windowLabel: 'the past 24 hours',
  events: 1204,
  autoResolved: 1201,
  rollbacks: 0,
  shadowCandidates: 6,
  overridesActive: 2,
  // "name" is the plain label a person reads; "tier" is the precise internal
  // term (T0/T1/T2), shown dimmed beside it so experts still get the mapping.
  tiers: [
    { tier: 'T0', name: 'Handled by fixed rules', pct: 74, cls: 'teal' },
    { tier: 'T1', name: 'Matched a past case', pct: 18, cls: 'steel' },
    { tier: 'T2', name: 'Needed AI reasoning', pct: 8, cls: 'plum' },
  ],
  // events-per-5min buckets across the window (drives the streaming chart)
  throughput: [
    120, 140, 135, 160, 210, 260, 240, 300, 520, 610, 700, 900,
    1180, 1240, 980, 760, 540, 430, 360, 300, 280, 240, 200, 170,
  ],
  // Each item is written plain-first; "tech" / "basisTech" carry the precise
  // internal term shown dimmed, so nothing is dumbed-down, just made legible.
  hil: [
    {
      cls: 'med', risk: 'MEDIUM', riskCls: 'terra',
      chip: 'needs your approval', chipCls: 'approve',
      title: 'Give payments-api more memory',
      tech: 'scale-memory - payments-api',
      change: 'Raise the memory limit from 512 MB to 1 GB',
      why: 'It ran out of memory twice in the last hour (incident #1204).',
      basis: 'Looks 91% like incident #0847, which we already fixed this way.',
      basisTech: 'T1 - similarity 0.91',
      safety: 'Affects 1 pod - auto-stops if CPU goes over 80% - fully reversible.',
      how: 'Opens a pull request for review. Nothing changes until it is merged.',
      who: 'Needs 1 approver who is not the requester - that is you.',
      check: 'Dry run passed - no rules broken.',
      ref: '#5521',
      irreversible: false,
    },
    {
      cls: 'high', risk: 'HIGH', riskCls: 'dusty',
      chip: 'high-risk - needs two approvers', chipCls: 'breakglass',
      title: 'Rotate the production signing key',
      tech: 'rotate-key - kv-prod',
      change: 'Replace the signing key with a fresh one',
      why: 'The key is more than 90 days old (security policy kv-014).',
      basis: 'A fixed security rule flagged it.',
      basisTech: 'T0 - policy match',
      safety: 'Affects 1 key - apps reload it automatically - stops if errors go over 1%. Cannot be undone, only rolled forward.',
      how: 'Opens a pull request for review.',
      who: 'High-risk, so it needs 2 approvers, none of them the requester.',
      check: 'Dry run passed - apps support hot reload.',
      ref: '#7781',
      irreversible: true,
    },
    {
      cls: 'low', risk: 'LOW', riskCls: 'sage',
      chip: 'your review', chipCls: 'read',
      title: "Turn on the 'idle disk cleanup' rule for real",
      tech: 'promote-rule - disk-idle-30d',
      change: 'Move the rule from trial to live',
      why: 'Trialed for 30 days: 41 of 41 correct, nothing slipped through.',
      basis: 'A fixed cost rule, proven over the trial.',
      basisTech: 'T0 - trial to live',
      safety: 'Only ever proposes cleanups as pull requests - switches back to trial if anything slips.',
      how: 'Opens a pull request for review.',
      who: 'Needs 1 reviewer.',
      check: 'Replayed the 30-day trial - same results.',
      ref: '#9002',
      irreversible: false,
    },
  ],
  suggestions: [
    'why did payments-api restart?',
    "how's spending trending this week?",
    'what new rules are being trialed?',
  ],
};

// --- tiny animation runtime ---------------------------------------------------
const screen = document.getElementById('screen');
const statusLeft = document.getElementById('status-left');
let SPEED = 1;
let runToken = 0; // cancels an in-flight run on replay

// Respect reduced-motion: render the briefing instantly instead of streaming.
const REDUCED = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
const sleep = (ms) => (REDUCED ? Promise.resolve() : new Promise((r) => setTimeout(r, ms / SPEED)));

function esc(s) {
  return String(s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
}
function el(html) {
  const d = document.createElement('div');
  d.className = 'line';
  d.innerHTML = html;
  screen.appendChild(d);
  screen.scrollTop = screen.scrollHeight;
  return d;
}
function blank() { return el('&nbsp;'); }

// stream text into an element, char by char
async function type(node, text, cps = 48, token) {
  const speedCps = cps;
  for (let i = 0; i <= text.length; i++) {
    if (token !== runToken) return;
    node.innerHTML = esc(text.slice(0, i)) + '<span class="cursor"></span>';
    await sleep(1000 / speedCps);
  }
  node.innerHTML = esc(text);
}

// stream a "narrator" line prefixed with a glyph
async function narrate(text, token, cls = 'narr') {
  const node = el(`<span class="${cls}"><span class="glyph">\u25c7</span> </span>`);
  const span = document.createElement('span');
  node.querySelector('span').appendChild(span);
  for (let i = 0; i <= text.length; i++) {
    if (token !== runToken) return node;
    span.innerHTML = esc(text.slice(0, i)) + '<span class="cursor"></span>';
    await sleep(1000 / 52);
  }
  span.innerHTML = esc(text);
  return node;
}

// --- phases -------------------------------------------------------------------
async function phaseBoot(token) {
  // Clean text header - no emblem or face art, just the wordmark and context.
  el(`<span class="banner b">fdai</span>  <span class="dim">operator-console</span>  <span class="dim">v0.0.1</span>`);
  el(`<span class="dim">${BRIEFING.env} \u00b7 read-only \u00b7 ${BRIEFING.clock}</span>`);
  await sleep(400);
  blank();
}

async function phaseGreeting(token) {
  await narrate(
    `Good morning, ${BRIEFING.operator}. Everything's running normally. Here's what happened over ${BRIEFING.windowLabel}.`,
    token,
  );
  blank();
}

async function phaseChart(token) {
  await narrate('How busy things were - events handled every 5 minutes:', token);
  const series = BRIEFING.throughput;
  const max = Math.max(...series);
  const H = 7; // rows
  const grid = el('<span class="dim"></span>');
  const pre = document.createElement('span');
  grid.innerHTML = '';
  grid.appendChild(pre);

  // reveal columns left-to-right
  for (let shown = 1; shown <= series.length; shown++) {
    if (token !== runToken) return;
    pre.innerHTML = renderChart(series.slice(0, shown), series.length, max, H);
    await sleep(48);
  }
  el(`<span class="dim">  busiest around 13:00 UTC - about ${max} events / 5 min at peak</span>`);
  blank();
}

function renderChart(shownSeries, totalCols, max, H) {
  const heights = shownSeries.map((v) => Math.max(1, Math.round((v / max) * H)));
  let out = '';
  for (let row = H; row >= 1; row--) {
    let axis = row === H ? String(max).padStart(5) + ' \u2524'
             : row === 1 ? '    0 \u2524'
             : '      \u2502';
    let line = '';
    for (let c = 0; c < totalCols; c++) {
      if (c < heights.length) {
        line += heights[c] >= row ? '\u2588' : ' ';
      } else {
        line += ' ';
      }
    }
    out += `<span class="dim">${axis}</span><span class="teal">${line}</span>\n`;
  }
  out += '<span class="dim">      \u2514' + '\u2500'.repeat(totalCols) + '</span>\n';
  // Place hour labels directly under their columns (bars start at gutter index 7).
  const labels = Array(totalCols).fill(' ');
  for (const [i, s] of [[0, '00'], [6, '06'], [12, '12'], [18, '18']]) {
    if (i + 1 < totalCols) { labels[i] = s[0]; labels[i + 1] = s[1]; }
  }
  out += '<span class="dim">       ' + labels.join('') + '   (hour, UTC)</span>';
  return out;
}

async function phaseTiers(token) {
  await narrate('Most of it was handled by fixed rules - no AI needed:', token);
  const WIDTH = 22;
  const rows = BRIEFING.tiers.map((t) => {
    const node = el(
      `<span class="bars"><span class="bar-row">` +
      `<span class="bar-label">${t.name} <span class="dim">(${t.tier})</span></span>` +
      `<span class="bar-fill ${t.cls}"></span>` +
      `<span class="bar-track"></span>` +
      `<span class="pct dim"></span>` +
      `</span></span>`,
    );
    return { t, fill: node.querySelector('.bar-fill'), track: node.querySelector('.bar-track'), pct: node.querySelector('.pct') };
  });

  // fill all bars together, frame by frame
  const maxCells = Math.round((Math.max(...BRIEFING.tiers.map((t) => t.pct)) / 100) * WIDTH);
  for (let step = 0; step <= maxCells; step++) {
    if (token !== runToken) return;
    for (const r of rows) {
      const cells = Math.round((r.t.pct / 100) * WIDTH);
      const on = Math.min(step, cells);
      r.fill.textContent = '\u2588'.repeat(on);
      r.track.textContent = '\u2591'.repeat(WIDTH - on);
      r.pct.textContent = `  ${String(r.t.pct).padStart(3)}%`;
    }
    await sleep(55);
  }
  blank();

  await narrate(
    `It handled ${BRIEFING.autoResolved} of ${BRIEFING.events} on its own. ` +
    `Nothing had to be undone. ${BRIEFING.shadowCandidates} new rules are being trialed safely - watching only, not acting yet.`,
    token,
  );
  const s = BRIEFING;
  const dot = `<span class="dim"> \u00b7 </span>`;
  el(
    `<div class="summary">` +
    `<span class="dim">events </span><span class="b">${s.events}</span>` + dot +
    `<span class="dim">auto-resolved </span><span class="sage b">${s.autoResolved}</span>` + dot +
    `<span class="dim">rolled back </span><span class="sage b">${s.rollbacks}</span>` + dot +
    `<span class="dim">paused rules </span><span class="b">${s.overridesActive}</span>` + dot +
    `<span class="dim">audit </span><span class="teal">complete</span>` +
    `</div>`,
  );
  statusLeft.innerHTML =
    `<span class="dim">${s.env} \u00b7 ${s.clock} \u00b7 read-only \u00b7 ${s.shadowCandidates} rules in trial</span>`;
  blank();
}

// one aligned "label: value" row inside a card (monospace padding keeps labels tidy)
function row(label, valueHtml) {
  return `<div><span class="dim">${label.padEnd(11)}</span>${valueHtml}</div>`;
}
function chip(item) {
  return `<span class="tag ${item.chipCls}">${esc(item.chip)}</span>`;
}

async function phaseBranchHil(token) {
  await narrate(
    `Three things need your decision - they are above the risk level I act on by myself.`,
    token,
  );
  blank();
  let i = 0;
  for (const item of BRIEFING.hil) {
    if (token !== runToken) return;
    i++;
    const irr = item.irreversible ? '  <span class="dusty b">can\u0027t be undone</span>' : '';
    const rowsHtml =
      row('What', esc(item.change)) +
      row('Why', esc(item.why)) +
      row('Confidence', esc(item.basis) + ` <span class="dim">(${esc(item.basisTech)})</span>`) +
      row('Safety', esc(item.safety) + irr) +
      row('How', esc(item.how)) +
      row('Approval', esc(item.who)) +
      row('Checked', `<span class="sage">\u2713</span> ` + esc(item.check));
    el(
      `<div class="card ${item.cls}">` +
      `<div class="hdr">` +
        `<span><span class="b">${i}/3 \u00b7 ${esc(item.title)}</span> <span class="dim">(${esc(item.tech)})</span></span>` +
        `<span class="${item.riskCls} b">${item.risk} risk</span>` +
      `</div>` +
      `<div style="margin:3px 0 7px">${chip(item)}</div>` +
      rowsHtml +
      `<div class="keys">` +
        `<span class="key a">a</span> approve <span class="dim">(opens a PR)</span>   ` +
        `<span class="key r">r</span> decline <span class="dim">(logged, no change)</span>   ` +
        `<span class="key w">w</span> explain` +
      `</div>` +
      `<div class="dim" style="margin-top:6px">logged as ${esc(item.ref)}</div>` +
      `</div>`,
    );
    await sleep(650);
  }
  blank();
  const p = el('');
  p.innerHTML =
    `<span class="prompt-row"><span class="sig">\u203a</span> <span class="dim">open a card (1-3), or type a question</span> <span class="cursor"></span></span>` +
    `<span class="dim">  (keys are illustrative - this is a static design mock)</span>`;
}

async function phaseBranchCalm(token) {
  await narrate(
    `Nothing needs your sign-off right now. Everything is handled, and every change can be undone.`,
    token,
  );
  blank();
  await narrate('Anything you want to look into? For example:', token);
  for (const s of BRIEFING.suggestions) {
    el(`<span class="dim">   \u2022 </span><span class="steel">"${esc(s)}"</span>`);
    await sleep(160);
  }
  blank();
  const p = el('');
  p.innerHTML =
    `<span class="prompt-row"><span class="sig">\u203a</span> <span class="cursor"></span></span>` +
    `<span class="dim">  (I only look things up unless you ask me to act - and I'll confirm before anything changes)</span>`;
}

// --- orchestration ------------------------------------------------------------
async function run() {
  const token = ++runToken;
  screen.innerHTML = '';
  statusLeft.textContent = 'reading status...';
  await phaseBoot(token);
  await phaseGreeting(token);
  await phaseChart(token);
  await phaseTiers(token);
  if (MODE === 'hil') await phaseBranchHil(token);
  else await phaseBranchCalm(token);
}

// --- controls -----------------------------------------------------------------
let MODE = 'hil';
const modeBtn = document.getElementById('mode');
const speedBtn = document.getElementById('speed');
document.getElementById('replay').addEventListener('click', run);
modeBtn.addEventListener('click', () => {
  MODE = MODE === 'hil' ? 'calm' : 'hil';
  modeBtn.textContent = MODE === 'hil' ? 'view: needs me' : 'view: all clear';
  modeBtn.classList.toggle('on', MODE === 'hil');
  run();
});
const SPEEDS = [1, 2, 4, 0.5];
let speedIdx = 0;
speedBtn.addEventListener('click', () => {
  speedIdx = (speedIdx + 1) % SPEEDS.length;
  SPEED = SPEEDS[speedIdx];
  speedBtn.textContent = `speed: ${SPEED}x`;
});

run();
