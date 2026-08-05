// Calm Slate - Live cockpit for the FDAI operator console mock.
// Synthesizes control-plane events (T0/T1/T2 -> gate -> executor -> audit) and
// renders them as an activity swarm. Nothing here calls a real backend; the
// production console will bind the same DOM structure to a read-only event feed.
//
// Distribution deliberately matches the roadmap: T0 dominates (~75%), T1 mid
// (~18%), T2 minority (~7%). Gate outcomes follow the risk model: T2 escalates
// to HIL / abstain far more often than T0.

(function () {
  "use strict";

  // ---------- config ----------
  var TIER_WEIGHTS = { t0: 0.75, t1: 0.18, t2: 0.07 };
  var GATE_MIX = {
    t0: { auto: 0.92, hil: 0.03, abstain: 0.01, deny: 0.04 },
    t1: { auto: 0.83, hil: 0.10, abstain: 0.04, deny: 0.03 },
    t2: { auto: 0.35, hil: 0.42, abstain: 0.18, deny: 0.05 }
  };
  var STAGES = ["route", "verify", "gate", "execute"];
  // Per-tier total pipeline duration (ms). Randomised +/-25% per event.
  var TIER_TOTAL_MS = { t0: 320, t1: 750, t2: 2100 };
  var BASE_RATE = 2; // events / sec, bounded for the six-card preview
  var FADE_1_MS = 900;
  var FADE_2_MS = 1600;
  var RETIRE_MS = 2400;
  var FLOW_POOL_SIZE = 6;
  var SPARK_BUCKETS = 60; // one second per bucket
  var SPARK_BUCKET_MS = 1000;

  var CATALOG = [
    { rule: "storage.public-blob.deny",           at: "storage.public-blob.disable",       scope: "rg-webapp",   vertical: "change"     },
    { rule: "database.pitr.required",             at: "database.enable-pitr",              scope: "rg-billing",  vertical: "resilience" },
    { rule: "compute.autoscale.floor.min-2",      at: "compute.autoscale.raise-floor",     scope: "rg-web-eu",   vertical: "change"     },
    { rule: "identity.cert.expiry.30d",           at: "identity.cert.rotate",              scope: "rg-core",     vertical: "change"     },
    { rule: "cost.rightsize.candidate",           at: "cost.rightsize.downshift-cpu",      scope: "rg-batch",    vertical: "cost"       },
    { rule: "network.firewall.orphan-rule",       at: "network.firewall.deny-orphan",      scope: "rg-net",      vertical: "change"     },
    { rule: "k8s.rbac.cluster-admin.narrow",      at: "k8s.rbac.narrow-cluster-admin",     scope: "aks-prod",    vertical: "change"     },
    { rule: "network.dns.public-resolver.deny",   at: "network.dns.pin-internal",          scope: "rg-net",      vertical: "change"     },
    { rule: "keyvault.access.grant-narrow",       at: "keyvault.grant-narrow",             scope: "rg-ident",    vertical: "change"     },
    { rule: "observability.log.retention",        at: "observability.log.extend-retention", scope: "rg-obs",     vertical: "change"     },
    { rule: "cost.orphan-disk.cleanup",           at: "cost.disk.delete-orphan",           scope: "rg-legacy",   vertical: "cost"       },
    { rule: "reliability.replica-lag.alert",      at: "reliability.replica.failover",      scope: "rg-db-eu",    vertical: "resilience" },
    { rule: "storage.tls.min-1_2",                at: "storage.tls.enforce-min-1_2",       scope: "rg-media",    vertical: "change"     },
    { rule: "compute.public-ip.deny",             at: "compute.public-ip.remove",          scope: "rg-net",      vertical: "change"     },
    { rule: "cost.reserved-instance.recommend",   at: "cost.ri.propose-purchase",          scope: "rg-fleet",    vertical: "cost"       },
    { rule: "reliability.backup.stale",           at: "reliability.backup.trigger",        scope: "rg-billing",  vertical: "resilience" },
    { rule: "network.nsg.overly-permissive",      at: "network.nsg.narrow-source",         scope: "rg-web-us",   vertical: "change"     },
    { rule: "identity.mi.unused",                 at: "identity.mi.retire",                scope: "rg-core",     vertical: "change"     }
  ];

  // ---------- state ----------
  var swarm = document.getElementById("swarm");
  var pauseBtn = document.getElementById("live-pause");
  var queueBody = document.getElementById("live-queue");
  var queueEmpty = document.getElementById("queue-empty");
  var queueView = document.getElementById("queue-view");
  var flowView = document.getElementById("flow-view");
  var queueButton = document.getElementById("view-queue");
  var flowButton = document.getElementById("view-flow");
  var detailBackdrop = document.getElementById("detail-backdrop");
  var detailClose = document.getElementById("detail-close");
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var pool = []; // tile records: { el, ev, startedAt, endsAt, retiresAt, state }
  var lastFrame = 0;
  var emitAccum = 0;
  var paused = false;
  var running = true;
  var viewMode = "queue";
  var currentFilter = "all";
  var selectedEventId = null;
  var detailPreviousFocus = null;
  var detailReturnEventId = null;
  var droppedFrames = 0;
  var lastEventAt = Date.now();
  var lastOperationalRender = 0;
  var pulseTimers = new WeakMap();

  // Sliding buckets for the last 60s
  var buckets = []; // each: { t0, t1, t2, auto, hil, abstain, deny }
  for (var i = 0; i < SPARK_BUCKETS; i++) buckets.push(zeroBucket());
  var lastBucketAt = performance.now();

  // ---------- helpers ----------
  function zeroBucket() { return { t0: 0, t1: 0, t2: 0, total: 0, auto: 0, hil: 0, abstain: 0, deny: 0 }; }
  function rng() { return Math.random(); }
  function pick(arr) { return arr[Math.floor(rng() * arr.length)]; }
  function weightedTier() {
    var r = rng();
    if (r < TIER_WEIGHTS.t0) return "t0";
    if (r < TIER_WEIGHTS.t0 + TIER_WEIGHTS.t1) return "t1";
    return "t2";
  }
  function weightedOutcome(tier) {
    var m = GATE_MIX[tier];
    var r = rng();
    var acc = 0;
    var keys = ["auto", "hil", "abstain", "deny"];
    for (var i = 0; i < keys.length; i++) {
      acc += m[keys[i]];
      if (r < acc) return keys[i];
    }
    return "auto";
  }
  function shortId() {
    var s = Math.floor(rng() * 0xFFFFFF).toString(16).padStart(6, "0");
    return "evt-" + s;
  }
  function ageLabel(ms) {
    if (ms < 1000) return "now";
    if (ms < 60000) return Math.floor(ms / 1000) + "s";
    return Math.floor(ms / 60000) + "m";
  }
  function pulse(element) {
    if (!element || reduced || pulseTimers.has(element)) return;
    element.classList.add("is-content-updated");
    var timer = window.setTimeout(function () {
      pulseTimers.delete(element);
      element.classList.remove("is-content-updated");
    }, 1350);
    pulseTimers.set(element, timer);
  }

  // ---------- pool creation ----------
  function computePoolSize() {
    return FLOW_POOL_SIZE;
  }

  function buildTile() {
    var el = document.createElement("div");
    el.className = "cs-tile";
    el.setAttribute("role", "button");
    el.setAttribute("tabindex", "-1");
    el.setAttribute("data-empty", "true");
    el.innerHTML = ''
      + '<div class="cs-tile-inner">'
      +   '<div class="cs-tile-top">'
      +     '<span class="cs-tile-tier"></span>'
      +     '<span class="cs-tile-stage"></span>'
      +   '</div>'
      +   '<div class="cs-tile-title"></div>'
      +   '<div class="cs-tile-meta">'
      +     '<span class="cs-tile-scope"></span>'
      +     '<span class="cs-tile-id"></span>'
      +   '</div>'
      + '</div>'
      + '<div class="cs-tile-bar"><span></span></div>';
    return {
      el: el,
      tierEl: el.querySelector(".cs-tile-tier"),
      stageEl: el.querySelector(".cs-tile-stage"),
      titleEl: el.querySelector(".cs-tile-title"),
      scopeEl: el.querySelector(".cs-tile-scope"),
      idEl: el.querySelector(".cs-tile-id"),
      barEl: el.querySelector(".cs-tile-bar > span"),
      ev: null,
      startedAt: 0,
      endsAt: 0,
      retiresAt: 0,
      state: "empty"
    };
  }

  function initPool() {
    swarm.innerHTML = "";
    pool.length = 0;
    var n = computePoolSize();
    for (var i = 0; i < n; i++) {
      var t = buildTile();
      pool.push(t);
      swarm.appendChild(t.el);
    }
  }

  // ---------- lifecycle ----------
  function pickSlot() {
    // Only recycle fully-retired slots. A full synthetic preview pauses new
    // generation instead of presenting artificial transport backpressure.
    for (var i = 0; i < pool.length; i++) {
      if (pool[i].state === "empty") return pool[i];
    }
    return null;
  }

  function spawn(now) {
    var slot = pickSlot();
    if (!slot) return; // fully busy - drop; the swarm is at capacity
    var tier = weightedTier();
    var jitter = 0.75 + rng() * 0.5; // 75%..125%
    var total = Math.round(TIER_TOTAL_MS[tier] * jitter);
    var outcome = weightedOutcome(tier);
    var sample = pick(CATALOG);
    var id = shortId();
    var failed = rng() < 0.018;
    var stuck = !failed && rng() < 0.025;
    var mode = outcome === "auto" ? (rng() < 0.22 ? "shadow" : "enforce") : "gated";

    slot.ev = { tier: tier, outcome: outcome, sample: sample, id: id, total: total, emitAt: Date.now(), failed: failed, stuck: stuck, mode: mode };
    slot.startedAt = now;
    slot.endsAt = now + total;
    slot.retiresAt = 0;
    slot.state = "active";

    var el = slot.el;
    el.setAttribute("data-empty", "false");
    el.setAttribute("data-tier", tier);
    el.setAttribute("data-state", "active");
    el.setAttribute("data-outcome", outcome);
    el.setAttribute("data-failed", failed ? "true" : "false");
    el.setAttribute("data-event-id", id);
    el.setAttribute("tabindex", "0");
    el.removeAttribute("data-fade");
    slot.tierEl.className = "cs-tile-tier " + tier;
    slot.tierEl.textContent = tier.toUpperCase();
    slot.stageEl.textContent = STAGES[0];
    slot.titleEl.textContent = sample.at;
    slot.titleEl.title = sample.rule + " -> " + sample.at;
    slot.scopeEl.textContent = sample.scope;
    slot.idEl.textContent = id;
    slot.barEl.style.width = "0%";
    lastEventAt = Date.now();
    applyFlowFilter(slot);

    if (reduced) {
      // Skip animation - jump to done state visually
      finish(slot, now);
    }

    countInBucket(now, tier);
  }

  function stageIndex(elapsedRatio) {
    // 0..0.35 route, 0.35..0.60 verify, 0.60..0.80 gate, 0.80..1.0 execute
    if (elapsedRatio < 0.35) return 0;
    if (elapsedRatio < 0.60) return 1;
    if (elapsedRatio < 0.80) return 2;
    return 3;
  }

  function finish(slot, now) {
    slot.state = "done";
    slot.retiresAt = now + RETIRE_MS;
    slot.el.setAttribute("data-state", "done");
    slot.barEl.style.width = "100%";
    // Human-facing stage label reflects the outcome
    var terminalLabel = slot.ev.failed ? "failed" : slot.ev.outcome === "auto" ? "auto" : slot.ev.outcome;
    slot.stageEl.textContent = terminalLabel;
    pulse(slot.el);

    // Count the observed terminal outcome in the rolling KPI window.
    countOutcomeInBucket(now, slot.ev.outcome);
  }

  function retire(slot) {
    slot.state = "empty";
    slot.ev = null;
    slot.el.setAttribute("data-empty", "true");
    slot.el.removeAttribute("data-state");
    slot.el.removeAttribute("data-outcome");
    slot.el.removeAttribute("data-tier");
    slot.el.removeAttribute("data-fade");
    slot.el.removeAttribute("data-failed");
    slot.el.removeAttribute("data-event-id");
    slot.el.setAttribute("tabindex", "-1");
    applyFlowFilter(slot);
  }

  function tick(now) {
    if (running) {
      if (!lastFrame) lastFrame = now;
      var dt = Math.min(200, now - lastFrame);
      lastFrame = now;

      if (!paused) {
        var rate = BASE_RATE;
        emitAccum += (dt / 1000) * rate;
        while (emitAccum >= 1) { spawn(now); emitAccum -= 1; }
      }

      // Advance tiles
      for (var i = 0; i < pool.length; i++) {
        var t = pool[i];
        if (t.state === "active") {
          var elapsed = now - t.startedAt;
          var total = t.endsAt - t.startedAt;
          var ratio = Math.min(1, elapsed / total);
          t.barEl.style.width = (ratio * 100).toFixed(1) + "%";
          var s = stageIndex(ratio);
          if (t.stageEl.textContent !== STAGES[s]) {
            t.stageEl.textContent = STAGES[s];
            pulse(t.el);
          }
          if (elapsed >= total) finish(t, now);
        } else if (t.state === "done") {
          var age = now - t.endsAt;
          if (age > FADE_2_MS) {
            if (t.el.getAttribute("data-fade") !== "2") t.el.setAttribute("data-fade", "2");
          } else if (age > FADE_1_MS) {
            if (t.el.getAttribute("data-fade") !== "1") t.el.setAttribute("data-fade", "1");
          }
          if (now >= t.retiresAt && !paused) {
            retire(t);
            spawn(now);
          }
        }
      }

      // Slide sparkline buckets every second
      if (now - lastBucketAt >= SPARK_BUCKET_MS) {
        while (now - lastBucketAt >= SPARK_BUCKET_MS) {
          buckets.shift();
          buckets.push(zeroBucket());
          lastBucketAt += SPARK_BUCKET_MS;
        }
        renderKpis();
        renderSparkline();
      }
      if (now - lastOperationalRender >= 250) {
        renderOperationalState(now);
        lastOperationalRender = now;
      }
    }
  }

  // ---------- buckets ----------
  function countInBucket(now, tier) {
    var b = buckets[buckets.length - 1];
    b[tier]++;
    b.total++;
  }
  function countOutcomeInBucket(now, outcome) {
    var b = buckets[buckets.length - 1];
    b[outcome]++;
  }
  function windowTotals() {
    var t = { t0: 0, t1: 0, t2: 0, total: 0, auto: 0, hil: 0, abstain: 0, deny: 0 };
    for (var i = 0; i < buckets.length; i++) {
      var b = buckets[i];
      t.t0 += b.t0; t.t1 += b.t1; t.t2 += b.t2; t.total += b.total;
      t.auto += b.auto; t.hil += b.hil; t.abstain += b.abstain; t.deny += b.deny;
    }
    return t;
  }
  function pct(n, d) { return d > 0 ? Math.round((n / d) * 100) : 0; }

  // ---------- render KPIs ----------
  var kEps = document.getElementById("k-eps");
  var kEpsT0 = document.getElementById("k-eps-t0");
  var kEpsT1 = document.getElementById("k-eps-t1");
  var kEpsT2 = document.getElementById("k-eps-t2");
  var kAuto = document.getElementById("k-auto");
  var kAutoCount = document.getElementById("k-auto-count");
  var kHilCount = document.getElementById("k-hil-count");
  var kAbstainCount = document.getElementById("k-abstain-count");
  var kDenyCount = document.getElementById("k-deny-count");
  var kT0 = document.getElementById("k-t0");
  var kT1 = document.getElementById("k-t1");
  var kT2 = document.getElementById("k-t2");
  var mixBar = document.getElementById("k-mix");
  var tierBar = document.getElementById("k-tier");

  function renderKpis() {
    var t = windowTotals();
    var eps = (t.total / SPARK_BUCKETS).toFixed(1);
    var previous = [kEps.firstChild.nodeValue, kAuto.textContent, kT0.textContent, kT1.textContent, kT2.textContent].join("|");
    kEps.firstChild.nodeValue = eps;
    if (kEpsT0) kEpsT0.textContent = (t.t0 / SPARK_BUCKETS).toFixed(1);
    if (kEpsT1) kEpsT1.textContent = (t.t1 / SPARK_BUCKETS).toFixed(1);
    if (kEpsT2) kEpsT2.textContent = (t.t2 / SPARK_BUCKETS).toFixed(1);
    var outcomeTotal = t.auto + t.hil + t.abstain + t.deny;
    kAuto.textContent = pct(t.auto, outcomeTotal) + "%";
    kAutoCount.textContent = t.auto;
    kHilCount.textContent = t.hil;
    kAbstainCount.textContent = t.abstain;
    kDenyCount.textContent = t.deny;
    kT0.textContent = "T0 " + pct(t.t0, t.total) + "%";
    kT1.textContent = "T1 " + pct(t.t1, t.total) + "%";
    kT2.textContent = "T2 " + pct(t.t2, t.total) + "%";
    // Stacked bars
    var mixSpans = mixBar.children;
    mixSpans[0].style.width = pct(t.auto, outcomeTotal) + "%";
    mixSpans[1].style.width = pct(t.hil, outcomeTotal) + "%";
    mixSpans[2].style.width = pct(t.abstain, outcomeTotal) + "%";
    mixSpans[3].style.width = pct(t.deny, outcomeTotal) + "%";
    var tierSpans = tierBar.children;
    tierSpans[0].style.width = pct(t.t0, t.total) + "%";
    tierSpans[1].style.width = pct(t.t1, t.total) + "%";
    tierSpans[2].style.width = pct(t.t2, t.total) + "%";
    var next = [eps, kAuto.textContent, kT0.textContent, kT1.textContent, kT2.textContent].join("|");
    if (previous !== next) {
      document.querySelectorAll(".cs-live-kpi").forEach(pulse);
    }
  }

  // ---------- sparkline ----------
  var spark = document.querySelector('canvas[data-spark="eps"]');
  var sparkCtx = spark ? spark.getContext("2d") : null;

  function readColor(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  var COL = {
    t0: readColor("--cs-sage")   || "#5E8259",
    t1: readColor("--cs-teal")   || "#4F847E",
    t2: readColor("--cs-plum")   || "#7B6C9C",
    hairline: readColor("--cs-hairline") || "#E3E1DE"
  };

  function hexToRgba(hex, alpha) {
    var h = String(hex).trim().replace("#", "");
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    var r = parseInt(h.slice(0, 2), 16);
    var g = parseInt(h.slice(2, 4), 16);
    var b = parseInt(h.slice(4, 6), 16);
    // Guard against a non-hex CSS variable (e.g. a fork overriding with rgb()):
    // fall back to a neutral translucent fill instead of emitting rgba(NaN,...).
    if (isNaN(r) || isNaN(g) || isNaN(b)) return "rgba(120,120,120," + alpha + ")";
    return "rgba(" + r + "," + g + "," + b + "," + alpha + ")";
  }

  function resizeSpark() {
    if (!spark) return;
    var dpr = window.devicePixelRatio || 1;
    var w = spark.clientWidth;
    var h = spark.clientHeight;
    spark.width = Math.round(w * dpr);
    spark.height = Math.round(h * dpr);
    sparkCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function renderSparkline() {
    if (!sparkCtx) return;
    var w = spark.clientWidth;
    var h = spark.clientHeight;
    sparkCtx.clearRect(0, 0, w, h);

    var n = buckets.length;
    // Shared scale so the three tiers stay comparable; a small headroom
    // keeps the dominant T0 line off the top edge for a calmer read.
    var max = 1;
    for (var i = 0; i < n; i++) if (buckets[i].total > max) max = buckets[i].total;
    max = max * 1.15;
    var pad = 3;                 // vertical breathing room
    var base = h - pad;          // y for value 0
    var span = h - pad * 2;      // usable height
    var stepX = w / (n - 1);

    function yFor(v) { return base - (v / max) * span; }

    // Build a smoothed path (quadratic through bucket midpoints) so the
    // line reads as a calm curve instead of a jagged polyline.
    function tracePath(field) {
      var pts = [];
      for (var i = 0; i < n; i++) pts.push({ x: i * stepX, y: yFor(buckets[i][field]) });
      sparkCtx.beginPath();
      sparkCtx.moveTo(pts[0].x, pts[0].y);
      for (var j = 0; j < pts.length - 1; j++) {
        var mx = (pts[j].x + pts[j + 1].x) / 2;
        var my = (pts[j].y + pts[j + 1].y) / 2;
        sparkCtx.quadraticCurveTo(pts[j].x, pts[j].y, mx, my);
      }
      var last = pts[pts.length - 1];
      sparkCtx.lineTo(last.x, last.y);
      return last;
    }

    function drawSeries(field, color, fillAlpha) {
      // Area fill first (very light), then the stroke on top.
      var last = tracePath(field);
      sparkCtx.lineTo(last.x, base);
      sparkCtx.lineTo(0, base);
      sparkCtx.closePath();
      sparkCtx.fillStyle = hexToRgba(color, fillAlpha);
      sparkCtx.fill();

      tracePath(field);
      sparkCtx.strokeStyle = color;
      sparkCtx.lineWidth = 1.75;
      sparkCtx.lineJoin = "round";
      sparkCtx.lineCap = "round";
      sparkCtx.stroke();
    }

    sparkCtx.save();
    sparkCtx.lineWidth = 1.75;
    // Draw largest tier first so the smaller ones sit legibly on top.
    drawSeries("t0", COL.t0, 0.10);
    drawSeries("t1", COL.t1, 0.12);
    drawSeries("t2", COL.t2, 0.14);
    sparkCtx.restore();
  }

  // ---------- production-aligned operational projection ----------
  function isSlotStuck(slot, now) {
    return Boolean(slot.ev && slot.ev.stuck && slot.state === "active" && now - slot.startedAt > 850);
  }

  function slotStatus(slot, now) {
    var decisionObserved = slot.state === "done" || slot.stageEl.textContent === "gate" || slot.stageEl.textContent === "execute";
    if (slot.ev.failed && slot.state === "done") return "failed";
    if (isSlotStuck(slot, now)) return "stuck";
    if (decisionObserved && slot.ev.outcome === "hil") return "hil";
    if (decisionObserved && slot.ev.outcome === "deny") return "deny";
    return slot.state === "done" ? "done" : "active";
  }

  function matchesSlot(slot, filter, now) {
    if (!slot.ev || slot.state === "empty") return false;
    if (filter === "all") return true;
    return slotStatus(slot, now) === filter;
  }

  function applyFlowFilter(slot) {
    if (!slot || !slot.el) return;
    slot.el.hidden = currentFilter !== "all" && !matchesSlot(slot, currentFilter, performance.now());
  }

  function queueRank(slot, now) {
    var status = slotStatus(slot, now);
    return status === "failed" ? 0 : status === "stuck" ? 1 : status === "hil" ? 2 : status === "deny" ? 3 : status === "active" ? 4 : 5;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character];
    });
  }

  function renderQueue(now) {
    var visible = pool.filter(function (slot) { return matchesSlot(slot, currentFilter, now); });
    visible.sort(function (left, right) {
      var rank = queueRank(left, now) - queueRank(right, now);
      return rank || right.ev.emitAt - left.ev.emitAt;
    });
    visible = visible.slice(0, 12);
    queueEmpty.hidden = visible.length > 0;
    queueBody.innerHTML = visible.map(function (slot) {
      var ev = slot.ev;
      var status = slotStatus(slot, now);
      var decisionObserved = slot.state === "done" || slot.stageEl.textContent === "gate" || slot.stageEl.textContent === "execute";
      var decision = status === "failed" ? "Failed" : status === "stuck" ? "Pending" : !decisionObserved ? "Pending" : ev.outcome === "hil" ? "Approval" : ev.outcome === "deny" ? "Deny" : ev.outcome === "abstain" ? "Review" : "Auto";
      var decisionClass = status === "failed" ? "deny" : decisionObserved ? ev.outcome : "";
      var visibleMode = decisionObserved ? ev.mode : "-";
      return '<tr data-status="' + status + '" data-event-id="' + escapeHtml(ev.id) + '">'
        + '<td><button class="cs-live-queue-action" type="button" data-select-event="' + escapeHtml(ev.id) + '"><strong>' + escapeHtml(ev.sample.at) + '</strong><span>' + escapeHtml(ev.sample.scope) + '</span><code>' + escapeHtml(ev.id) + '</code></button></td>'
        + '<td data-label="Stage"><strong>' + escapeHtml(slot.stageEl.textContent) + '</strong><br><small>' + (slot.state === "done" ? "Saga" : "Forseti") + '</small></td>'
        + '<td data-label="Age">' + ageLabel(Date.now() - ev.emitAt) + (status === "stuck" ? '<br><small>Over budget</small>' : '') + '</td>'
        + '<td data-label="Tier"><span class="cs-tier ' + ev.tier + '">' + ev.tier.toUpperCase() + '</span></td>'
        + '<td data-label="Mode"><span class="cs-tk-mode ' + visibleMode + '">' + visibleMode + '</span></td>'
        + '<td data-label="Decision"><span class="out ' + decisionClass + '">' + decision + '</span></td>'
        + '</tr>';
    }).join("");
  }

  function renderOperationalState(now) {
    var counts = { all: 0, hil: 0, deny: 0, failed: 0, stuck: 0 };
    pool.forEach(function (slot) {
      if (!slot.ev || slot.state === "empty") return;
      counts.all++;
      var status = slotStatus(slot, now);
      if (Object.prototype.hasOwnProperty.call(counts, status)) counts[status]++;
      applyFlowFilter(slot);
    });

    Object.keys(counts).forEach(function (key) {
      var count = document.getElementById("filter-" + key);
      if (count) count.textContent = counts[key];
    });
    ["hil", "deny", "failed", "stuck"].forEach(function (key) {
      document.getElementById("attention-" + key).textContent = counts[key];
      var button = document.querySelector('[data-attention-filter="' + key + '"]');
      if (button) button.hidden = counts[key] === 0;
    });

    var attentionTotal = counts.hil + counts.deny + counts.failed + counts.stuck;
    var attention = document.getElementById("live-attention");
    document.getElementById("attention-calm").hidden = attentionTotal > 0;
    document.getElementById("attention-items").hidden = attentionTotal === 0;
    attention.classList.toggle("is-calm", attentionTotal === 0);
    attention.classList.toggle("is-active", attentionTotal > 0);

    var secondsSinceEvent = Math.max(0, Math.floor((Date.now() - lastEventAt) / 1000));
    document.getElementById("health-last-event").textContent = secondsSinceEvent === 0 ? "Signal now" : secondsSinceEvent + "s ago";
    document.getElementById("health-presentation").textContent = paused ? "Frozen" : "Following";
    var backlog = document.getElementById("health-backlog");
    backlog.textContent = droppedFrames > 0 ? droppedFrames + " dropped" : "Complete";
    backlog.className = droppedFrames > 0 ? "is-warn" : "is-ok";

    if (viewMode === "queue") renderQueue(now);
  }

  function setFilter(filter) {
    currentFilter = filter;
    document.querySelectorAll("[data-live-filter]").forEach(function (button) {
      var active = button.getAttribute("data-live-filter") === filter;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    pool.forEach(applyFlowFilter);
    renderOperationalState(performance.now());
  }

  function setView(mode) {
    viewMode = mode;
    queueView.hidden = mode !== "queue";
    flowView.hidden = mode !== "flow";
    queueButton.classList.toggle("is-active", mode === "queue");
    flowButton.classList.toggle("is-active", mode === "flow");
    queueButton.setAttribute("aria-pressed", mode === "queue" ? "true" : "false");
    flowButton.setAttribute("aria-pressed", mode === "flow" ? "true" : "false");
    if (mode === "flow") {
      resizeSpark();
      pool.forEach(applyFlowFilter);
    } else {
      renderQueue(performance.now());
    }
  }

  function slotForEvent(eventId) {
    return pool.find(function (slot) { return slot.ev && slot.ev.id === eventId; }) || null;
  }

  function closeDetail() {
    detailBackdrop.hidden = true;
    document.body.style.overflow = "";
    var fallbackFocus = detailReturnEventId
      ? document.querySelector('[data-select-event="' + detailReturnEventId + '"]')
      : null;
    if (!fallbackFocus && detailReturnEventId && viewMode === "flow") {
      fallbackFocus = document.querySelector('.cs-tile[data-event-id="' + detailReturnEventId + '"]');
    }
    if (!fallbackFocus) fallbackFocus = viewMode === "queue" ? queueButton : flowButton;
    var restoreFocus = detailPreviousFocus && detailPreviousFocus !== document.body && detailPreviousFocus.isConnected
      ? detailPreviousFocus
      : fallbackFocus;
    window.setTimeout(function () {
      if (restoreFocus && restoreFocus.isConnected) restoreFocus.focus();
    }, 0);
    detailPreviousFocus = null;
    detailReturnEventId = null;
  }

  function openDetail(slot) {
    if (!slot || !slot.ev) return;
    detailPreviousFocus = document.activeElement;
    detailReturnEventId = slot.ev.id;
    var ev = slot.ev;
    var currentStage = STAGES.indexOf(slot.stageEl.textContent);
    if (currentStage < 0) currentStage = slot.state === "done" ? STAGES.length : 0;
    var agents = { route: "Huginn", verify: "Forseti", gate: "Var", execute: "Thor" };
    document.getElementById("detail-title").textContent = ev.sample.at;
    document.getElementById("detail-trace").innerHTML = STAGES.map(function (stage, index) {
      var css = slot.state === "done" || index < currentStage ? "is-done" : index === currentStage ? "is-current" : "";
      var state = slot.state === "done" || index < currentStage ? "Observed" : index === currentStage ? "In progress" : "Not observed";
      return '<li class="' + css + '"><i aria-hidden="true"></i><div><strong>' + stage + '</strong><small>' + agents[stage] + ' - ' + state + '</small></div></li>';
    }).join("");
    document.getElementById("detail-event").textContent = ev.id;
    document.getElementById("detail-correlation").textContent = "corr-" + ev.id.slice(4);
    document.getElementById("detail-rule").textContent = ev.sample.rule;
    document.getElementById("detail-action").textContent = ev.sample.at;
    document.getElementById("detail-mode").textContent = ev.mode;
    document.getElementById("detail-vertical").textContent = ev.sample.vertical;
    document.getElementById("detail-scope").textContent = ev.sample.scope;
    document.getElementById("detail-tier").textContent = ev.tier.toUpperCase();
    document.getElementById("detail-decision").textContent = slot.state === "done" ? (ev.failed ? "failed" : ev.outcome) : "pending";
    document.getElementById("detail-age").textContent = ageLabel(Date.now() - ev.emitAt);
    document.getElementById("detail-trace-link").href = "rule-trace.html?correlation=corr-" + encodeURIComponent(ev.id.slice(4));
    document.getElementById("detail-audit-link").href = "audit.html?correlation=corr-" + encodeURIComponent(ev.id.slice(4));
    detailBackdrop.hidden = false;
    document.body.style.overflow = "hidden";
    detailClose.focus();
  }

  // ---------- controls ----------
  pauseBtn.addEventListener("click", function () {
    paused = !paused;
    pauseBtn.textContent = paused ? "Resume" : "Freeze";
    pauseBtn.setAttribute("aria-pressed", paused ? "true" : "false");
    document.querySelector(".cs-live-heartbeat").style.animationPlayState = paused ? "paused" : "";
    renderOperationalState(performance.now());
  });
  queueButton.addEventListener("click", function () { setView("queue"); });
  flowButton.addEventListener("click", function () { setView("flow"); });
  document.querySelectorAll("[data-live-filter]").forEach(function (button) {
    button.addEventListener("click", function () { setFilter(button.getAttribute("data-live-filter")); });
  });
  document.querySelectorAll("[data-attention-filter]").forEach(function (button) {
    button.addEventListener("click", function () { setFilter(button.getAttribute("data-attention-filter")); });
  });
  queueBody.addEventListener("click", function (event) {
    var target = event.target instanceof Element ? event.target : null;
    var button = target ? target.closest("[data-select-event]") : null;
    if (!button) return;
    selectedEventId = button.getAttribute("data-select-event");
    queueBody.querySelectorAll("tr").forEach(function (row) {
      row.toggleAttribute("data-selected", row.getAttribute("data-event-id") === selectedEventId);
    });
    openDetail(slotForEvent(selectedEventId));
  });
  swarm.addEventListener("click", function (event) {
    var target = event.target instanceof Element ? event.target : null;
    var tile = target ? target.closest("[data-event-id]") : null;
    if (!tile) return;
    selectedEventId = tile.getAttribute("data-event-id");
    openDetail(slotForEvent(selectedEventId));
  });
  swarm.addEventListener("keydown", function (event) {
    if (event.key !== "Enter" && event.key !== " ") return;
    var target = event.target instanceof Element ? event.target.closest("[data-event-id]") : null;
    if (!target) return;
    event.preventDefault();
    selectedEventId = target.getAttribute("data-event-id");
    openDetail(slotForEvent(selectedEventId));
  });
  detailClose.addEventListener("click", closeDetail);
  detailBackdrop.addEventListener("click", function (event) {
    if (event.target === detailBackdrop) closeDetail();
  });
  document.addEventListener("keydown", function (event) {
    if (detailBackdrop.hidden) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeDetail();
      return;
    }
    if (event.key !== "Tab") return;
    var focusable = Array.from(detailBackdrop.querySelectorAll('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'));
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }
    var first = focusable[0];
    var last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  window.addEventListener("resize", function () {
    resizeSpark();
  });

  // ---------- boot ----------
  initPool();
  setView("queue");
  setFilter("all");
  // Timer-driven so the synthetic preview continues in integrated browser
  // tabs where requestAnimationFrame may pause when the iframe is hidden.
  window.setTimeout(function () {
    var t = performance.now();
    resizeSpark();
    lastFrame = t;
    lastBucketAt = t;
    for (var slotIndex = 0; slotIndex < FLOW_POOL_SIZE; slotIndex++) spawn(t);
    renderSparkline();
    tick(t);
    window.setInterval(function () { tick(performance.now()); }, 50);
  }, 0);

  // Prime a few seconds of history so the sparkline is not empty at load
  (function prime() {
    var now = performance.now();
    for (var i = 0; i < 60; i++) {
      var b = buckets[i];
      // low-baseline synthetic history for visual continuity
      for (var k = 0; k < BASE_RATE; k++) {
        var tier = weightedTier();
        b[tier]++;
        b.total++;
        var out = weightedOutcome(tier);
        b[out]++;
      }
    }
    renderKpis();
    renderSparkline();
  }());
})();
