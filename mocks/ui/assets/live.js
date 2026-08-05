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
  var STAGES = ["route", "decide", "authorize", "execute", "effect", "audit"];
  // Per-tier total pipeline duration (ms). Randomised +/-25% per event.
  var TIER_TOTAL_MS = { t0: 2400, t1: 3400, t2: 4800 };
  var BASE_RATE = 2; // events / sec, bounded for the six-card preview
  var FADE_1_MS = 900;
  var FADE_2_MS = 1600;
  var RETIRE_MS = 2400;
  var FLOW_POOL_SIZE = 6;
  var SPARK_BUCKETS = 60; // one second per bucket
  var SPARK_BUCKET_MS = 1000;
  var PULSE_COOLDOWN_MS = 5000;

  var CATALOG = [
    { title: "Disable public blob access", target: "Web app storage", reason: "Public access violates storage policy", rule: "storage.public-blob.deny", at: "storage.public-blob.disable", scope: "rg-webapp", vertical: "change" },
    { title: "Enable point-in-time restore", target: "Billing database", reason: "Recovery coverage is below policy", rule: "database.pitr.required", at: "database.enable-pitr", scope: "rg-billing", vertical: "resilience" },
    { title: "Raise autoscale minimum", target: "EU web service", reason: "Capacity is below the reliability floor", rule: "compute.autoscale.floor.min-2", at: "compute.autoscale.raise-floor", scope: "rg-web-eu", vertical: "change" },
    { title: "Rotate expiring certificate", target: "Core identity service", reason: "Certificate expires within 30 days", rule: "identity.cert.expiry.30d", at: "identity.cert.rotate", scope: "rg-core", vertical: "change" },
    { title: "Right-size batch compute", target: "Batch worker pool", reason: "CPU is consistently underused", rule: "cost.rightsize.candidate", at: "cost.rightsize.downshift-cpu", scope: "rg-batch", vertical: "cost" },
    { title: "Remove orphan firewall rule", target: "Shared network", reason: "Rule has no active workload owner", rule: "network.firewall.orphan-rule", at: "network.firewall.deny-orphan", scope: "rg-net", vertical: "change" },
    { title: "Narrow cluster admin access", target: "Production Kubernetes", reason: "Cluster-wide privilege exceeds need", rule: "k8s.rbac.cluster-admin.narrow", at: "k8s.rbac.narrow-cluster-admin", scope: "aks-prod", vertical: "change" },
    { title: "Pin DNS to internal resolver", target: "Shared network", reason: "Public resolver bypasses network policy", rule: "network.dns.public-resolver.deny", at: "network.dns.pin-internal", scope: "rg-net", vertical: "change" },
    { title: "Reduce vault access", target: "Identity secrets vault", reason: "Grant is broader than the workload needs", rule: "keyvault.access.grant-narrow", at: "keyvault.grant-narrow", scope: "rg-ident", vertical: "change" },
    { title: "Extend log retention", target: "Operations workspace", reason: "Retention is shorter than evidence policy", rule: "observability.log.retention", at: "observability.log.extend-retention", scope: "rg-obs", vertical: "change" },
    { title: "Delete unattached disk", target: "Legacy workload", reason: "Disk is unused and still accruing cost", rule: "cost.orphan-disk.cleanup", at: "cost.disk.delete-orphan", scope: "rg-legacy", vertical: "cost" },
    { title: "Fail over lagging replica", target: "EU database replica", reason: "Replication lag threatens recovery time", rule: "reliability.replica-lag.alert", at: "reliability.replica.failover", scope: "rg-db-eu", vertical: "resilience" }
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
  var workWorkspace = document.getElementById("live-workspace");
  var fullscreenButton = document.getElementById("live-fullscreen");
  var detailBackdrop = document.getElementById("detail-backdrop");
  var detailClose = document.getElementById("detail-close");
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var pool = []; // tile records: { el, ev, startedAt, endsAt, retiresAt, state }
  var lastFrame = 0;
  var emitAccum = 0;
  var paused = false;
  var running = true;
  var viewMode = "flow";
  var currentFilter = "all";
  var selectedEventId = null;
  var detailPreviousFocus = null;
  var detailReturnEventId = null;
  var droppedFrames = 0;
  var lastEventAt = Date.now();
  var lastOperationalRender = 0;
  var pulseTimers = new WeakMap();
  var lastPulseAt = new WeakMap();
  var pauseStartedAt = 0;
  var pauseStartedWallAt = 0;

  function fullscreenActive() {
    return document.fullscreenElement === workWorkspace || workWorkspace.classList.contains("is-fullscreen-fallback");
  }

  function fullscreenIcon(active) {
    return active
      ? '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 7 H7 V3 M17 7 H13 V3 M17 13 H13 V17 M3 13 H7 V17" /></svg>'
      : '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M7 3 H3 V7 M13 3 H17 V7 M17 13 V17 H13 M7 17 H3 V13" /></svg>';
  }

  function syncFullscreen() {
    var active = fullscreenActive();
    var label = active ? "Exit full screen" : "View work full screen";
    fullscreenButton.setAttribute("aria-label", label);
    fullscreenButton.setAttribute("title", label);
    fullscreenButton.setAttribute("aria-pressed", active ? "true" : "false");
    fullscreenButton.innerHTML = fullscreenIcon(active);
  }

  function enterFallbackFullscreen() {
    workWorkspace.classList.add("is-fullscreen-fallback");
    document.body.classList.add("cs-live-fullscreen-fallback");
    syncFullscreen();
  }

  function exitFallbackFullscreen() {
    workWorkspace.classList.remove("is-fullscreen-fallback");
    document.body.classList.remove("cs-live-fullscreen-fallback");
    syncFullscreen();
    fullscreenButton.focus();
  }

  function toggleFullscreen() {
    if (workWorkspace.classList.contains("is-fullscreen-fallback")) {
      exitFallbackFullscreen();
      return;
    }
    if (document.fullscreenElement) {
      document.exitFullscreen().then(function () {
        syncFullscreen();
        window.setTimeout(function () { fullscreenButton.focus(); }, 50);
      }).catch(enterFallbackFullscreen);
      return;
    }
    if (!workWorkspace.requestFullscreen) {
      enterFallbackFullscreen();
      return;
    }
    workWorkspace.requestFullscreen({ navigationUI: "hide" }).then(syncFullscreen).catch(enterFallbackFullscreen);
  }

  // Sliding buckets for the last 60s
  var buckets = []; // each: { t0, t1, t2, auto, hil, abstain, deny }
  for (var i = 0; i < SPARK_BUCKETS; i++) buckets.push(zeroBucket());
  var lastBucketAt = performance.now();

  // ---------- helpers ----------
  function zeroBucket() { return { t0: 0, t1: 0, t2: 0, total: 0, auto: 0, hil: 0, abstain: 0, deny: 0, dropped: 0 }; }
  function rng() { return Math.random(); }
  function pick(arr) { return arr[Math.floor(rng() * arr.length)]; }
  function pickAvailableWork() {
    var activeRules = new Set(pool.filter(function (slot) { return slot.ev; }).map(function (slot) { return slot.ev.sample.rule; }));
    var available = CATALOG.filter(function (sample) { return !activeRules.has(sample.rule); });
    return pick(available.length > 0 ? available : CATALOG);
  }
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
    var now = performance.now();
    if (!element || reduced || pulseTimers.has(element) || now - (lastPulseAt.get(element) || -PULSE_COOLDOWN_MS) < PULSE_COOLDOWN_MS) return;
    element.classList.add("is-content-updated");
    lastPulseAt.set(element, now);
    var timer = window.setTimeout(function () {
      pulseTimers.delete(element);
      element.classList.remove("is-content-updated");
    }, 1350);
    pulseTimers.set(element, timer);
  }

  function riskProfile(sample) {
    var action = sample.at;
    if (/failover|delete-orphan|cluster-admin|cert\.rotate/.test(action)) {
      return { risk: "High", impact: "1 protected target", autonomy: "A3-H", slaMs: 30000 };
    }
    if (sample.vertical === "resilience" || /rbac|firewall|public-blob|dns/.test(action)) {
      return { risk: "Medium", impact: "1 resource", autonomy: "A2", slaMs: 45000 };
    }
    return { risk: "Low", impact: "1 resource", autonomy: "A1", slaMs: 60000 };
  }

  function authorityLabel(ev) {
    if (ev.outcome === "hil") return "A3-H";
    if (ev.outcome === "deny") return "A4";
    if (ev.outcome === "abstain" || ev.mode === "shadow") return "A0";
    return ev.profile.autonomy;
  }

  function stagePath(ev) {
    if (ev.outcome !== "auto" || ev.mode === "shadow") {
      return ["route", "decide", "authorize", "audit"];
    }
    if (ev.failed) {
      return ["route", "decide", "authorize", "execute", "audit"];
    }
    return STAGES;
  }

  function stageAt(ev, elapsedRatio) {
    var path = stagePath(ev);
    return path[Math.min(path.length - 1, Math.floor(elapsedRatio * path.length))];
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
      +     '<span class="cs-tile-mode"></span>'
      +     '<span class="cs-tile-stage"></span>'
      +   '</div>'
      +   '<div class="cs-tile-title"></div>'
      +   '<div class="cs-tile-target"></div>'
      +   '<div class="cs-tile-reason"></div>'
      +   '<div class="cs-tile-meta">'
      +     '<span class="cs-tile-owner"></span>'
      +     '<span class="cs-tile-scope"></span>'
      +   '</div>'
      + '</div>'
      + '<div class="cs-tile-bar"><span></span></div>';
    return {
      el: el,
      tierEl: el.querySelector(".cs-tile-tier"),
      modeEl: el.querySelector(".cs-tile-mode"),
      stageEl: el.querySelector(".cs-tile-stage"),
      titleEl: el.querySelector(".cs-tile-title"),
      targetEl: el.querySelector(".cs-tile-target"),
      reasonEl: el.querySelector(".cs-tile-reason"),
      ownerEl: el.querySelector(".cs-tile-owner"),
      scopeEl: el.querySelector(".cs-tile-scope"),
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
    if (!slot) {
      droppedFrames++;
      buckets[buckets.length - 1].dropped++;
      return false;
    }
    var tier = weightedTier();
    var jitter = 0.75 + rng() * 0.5; // 75%..125%
    var total = Math.round(TIER_TOTAL_MS[tier] * jitter);
    var sample = pickAvailableWork();
    var profile = riskProfile(sample);
    var outcome = weightedOutcome(tier);
    if (profile.risk === "High" && outcome === "auto") outcome = "hil";
    var id = shortId();
    var mode = outcome === "auto" ? (rng() < 0.22 ? "shadow" : "enforce") : "gated";
    var failed = mode === "enforce" && rng() < 0.018;
    var stuck = !failed && rng() < 0.025;

    slot.ev = {
      tier: tier,
      outcome: outcome,
      sample: sample,
      profile: profile,
      id: id,
      total: total,
      emitAt: Date.now(),
      failed: failed,
      stuck: stuck,
      mode: mode,
      idempotencyKey: "preview:" + sample.rule + ":" + id,
      targetRevision: "preview-rev-" + id.slice(4),
      auditClosed: false
    };
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
    el.setAttribute("data-mode", mode);
    el.setAttribute("data-event-id", id);
    el.setAttribute("tabindex", "0");
    el.setAttribute("aria-label", sample.title + ". Target: " + sample.target + ". Why: " + sample.reason + ". Huginn, route stage.");
    el.removeAttribute("data-fade");
    slot.tierEl.className = "cs-tile-tier " + tier;
    slot.tierEl.textContent = tier.toUpperCase();
    slot.modeEl.textContent = "Pending";
    slot.stageEl.textContent = STAGES[0];
    slot.titleEl.textContent = sample.title;
    slot.titleEl.title = sample.at;
    slot.targetEl.textContent = sample.target;
    slot.reasonEl.textContent = "Why: " + sample.reason;
    slot.ownerEl.textContent = "Huginn · Route";
    slot.scopeEl.textContent = sample.scope;
    slot.barEl.style.width = "0%";
    lastEventAt = Date.now();
    applyFlowFilter(slot);

    if (reduced) {
      // Skip animation - jump to done state visually
      finish(slot, now);
    }

    countInBucket(now, tier);
    return true;
  }

  function finish(slot, now) {
    slot.state = "done";
    slot.retiresAt = now + RETIRE_MS;
    slot.el.setAttribute("data-state", "done");
    slot.barEl.style.width = "100%";
    slot.ev.auditClosed = true;
    var terminalLabel = slot.ev.failed
      ? "execution failed"
      : slot.ev.outcome === "auto" && slot.ev.mode === "enforce"
        ? "preview verified"
        : slot.ev.outcome === "auto"
          ? "shadow recorded"
          : slot.ev.outcome === "hil"
            ? "approval required"
            : slot.ev.outcome === "abstain" ? "held" : "denied";
    slot.stageEl.textContent = terminalLabel;
    slot.ownerEl.textContent = "Saga · Recorded";
    slot.modeEl.textContent = authorityLabel(slot.ev) + " · " + slot.ev.mode.toUpperCase();
    slot.el.setAttribute("aria-label", slot.ev.sample.title + ". Target: " + slot.ev.sample.target + ". Why: " + slot.ev.sample.reason + ". Saga, recorded. Decision: " + terminalLabel + ".");
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
    slot.el.removeAttribute("data-mode");
    slot.el.removeAttribute("data-event-id");
    slot.el.removeAttribute("aria-label");
    slot.el.setAttribute("tabindex", "-1");
    applyFlowFilter(slot);
  }

  function tick(now) {
    if (running) {
      if (!lastFrame) lastFrame = now;
      var dt = Math.min(200, now - lastFrame);
      lastFrame = now;

      if (paused) return;

      var rate = BASE_RATE;
      emitAccum += (dt / 1000) * rate;
      while (emitAccum >= 1) { spawn(now); emitAccum -= 1; }

      // Advance tiles
      for (var i = 0; i < pool.length; i++) {
        var t = pool[i];
        if (t.state === "active") {
          var elapsed = now - t.startedAt;
          var total = t.endsAt - t.startedAt;
          var ratio = Math.min(1, elapsed / total);
          t.barEl.style.width = (ratio * 100).toFixed(1) + "%";
          var stage = stageAt(t.ev, ratio);
          if (t.stageEl.textContent !== stage) {
            t.stageEl.textContent = stage;
            t.ownerEl.textContent = stageOwner(stage) + " · " + titleCase(stage);
            renderTileControl(t);
            t.el.setAttribute("aria-label", t.ev.sample.title + ". Target: " + t.ev.sample.target + ". Why: " + t.ev.sample.reason + ". " + stageOwner(stage) + ", " + stage + " stage.");
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
          if (now >= t.retiresAt) {
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
    var t = { t0: 0, t1: 0, t2: 0, total: 0, auto: 0, hil: 0, abstain: 0, deny: 0, dropped: 0 };
    for (var i = 0; i < buckets.length; i++) {
      var b = buckets[i];
      t.t0 += b.t0; t.t1 += b.t1; t.t2 += b.t2; t.total += b.total;
      t.auto += b.auto; t.hil += b.hil; t.abstain += b.abstain; t.deny += b.deny;
      t.dropped += b.dropped;
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
  var gateChart = document.getElementById("k-gate-chart");
  var tierChart = document.getElementById("k-tier-chart");
  var chartTooltip = document.getElementById("live-chart-tooltip");
  var gateKeys = ["auto", "hil", "abstain", "deny"];
  var gateLabels = { auto: "Auto", hil: "Approval", abstain: "Review", deny: "Deny" };
  var gateMeanings = {
    auto: "Policy allowed without per-execution approval; execution and effect remain separate",
    hil: "Waiting for a human decision",
    abstain: "Held because confidence is insufficient",
    deny: "Blocked by policy"
  };
  var tierKeys = ["t0", "t1", "t2"];
  var tierLabels = { t0: "T0 Deterministic", t1: "T1 Evidence-backed", t2: "T2 Adaptive" };
  var tierMeanings = {
    t0: "Deterministic rule decision",
    t1: "Prior-pattern similarity reuse",
    t2: "Grounded adaptive reasoning"
  };

  function precisePercent(value, total) {
    if (total <= 0 || value <= 0) return "0";
    var percentage = (value / total) * 100;
    return percentage < 10 ? percentage.toFixed(1) : String(Math.round(percentage));
  }

  function previewCoverageLabel(dropped) {
    return dropped > 0 ? dropped + " omitted synthetic attempts" : "complete synthetic sample";
  }

  function previewWindowSentence(dropped) {
    return dropped > 0
      ? "Synthetic preview window omitted " + dropped + " generation attempts."
      : "Complete synthetic preview window.";
  }

  function setChartTip(anchor, text) {
    anchor.dataset.liveChartTip = text;
    anchor.setAttribute("aria-label", text);
  }

  function renderGateChart(totals, total) {
    var offset = 0;
    gateKeys.forEach(function (key) {
      var value = totals[key];
      var percentage = total > 0 ? (value / total) * 100 : 0;
      var text = gateLabels[key] + ": " + value + " of " + total + " finalized decisions (" + precisePercent(value, total) + "%). " + gateMeanings[key] + ". " + previewWindowSentence(totals.dropped);
      var segment = document.querySelector('[data-gate-segment="' + key + '"]');
      var legend = document.querySelector('[data-gate-legend="' + key + '"]');
      segment.style.strokeDasharray = percentage + " " + (100 - percentage);
      segment.style.strokeDashoffset = String(-offset);
      setChartTip(segment, text);
      setChartTip(legend, text);
      offset += percentage;
    });
    gateChart.setAttribute("aria-label", gateKeys.map(function (key) {
      return gateLabels[key] + " " + precisePercent(totals[key], total) + "%";
    }).join(", "));
  }

  function renderTierChart(totals, total) {
    tierKeys.forEach(function (key) {
      var value = totals[key];
      var percentage = total > 0 ? (value / total) * 100 : 0;
      var text = tierLabels[key] + ": " + value + " of " + total + " routed events (" + precisePercent(value, total) + "%). " + tierMeanings[key] + ". " + previewWindowSentence(totals.dropped);
      document.getElementById("k-" + key + "-stem").style.width = percentage + "%";
      setChartTip(document.getElementById("k-" + key + "-track"), text);
    });
    tierChart.setAttribute("aria-label", tierKeys.map(function (key) {
      return tierLabels[key] + " " + precisePercent(totals[key], total) + "%";
    }).join(", "));
  }

  function showChartTooltip(anchor, clientX, clientY) {
    var text = anchor.dataset.liveChartTip;
    if (!text) return;
    chartTooltip.textContent = text;
    chartTooltip.hidden = false;
    chartTooltip.style.transform = "translate(-50%, -100%)";
    var anchorBox = anchor.getBoundingClientRect();
    var tooltipBox = chartTooltip.getBoundingClientRect();
    var left = typeof clientX === "number" ? clientX : anchorBox.left + anchorBox.width / 2;
    left = Math.max(tooltipBox.width / 2 + 8, Math.min(window.innerWidth - tooltipBox.width / 2 - 8, left));
    var top = typeof clientY === "number" ? clientY - 10 : anchorBox.top - 6;
    if (top - tooltipBox.height < 8) {
      top = anchorBox.bottom + 6;
      chartTooltip.style.transform = "translate(-50%, 0)";
    }
    chartTooltip.style.left = left + "px";
    chartTooltip.style.top = top + "px";
    anchor.setAttribute("aria-describedby", "live-chart-tooltip");
  }

  function hideChartTooltip(anchor) {
    chartTooltip.hidden = true;
    anchor.removeAttribute("aria-describedby");
  }

  document.querySelectorAll("[data-live-chart-tip]").forEach(function (anchor) {
    anchor.addEventListener("pointerenter", function () { showChartTooltip(anchor); });
    anchor.addEventListener("pointerleave", function () { hideChartTooltip(anchor); });
    anchor.addEventListener("focus", function () { showChartTooltip(anchor); });
    anchor.addEventListener("blur", function () { hideChartTooltip(anchor); });
  });

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
    kT0.textContent = pct(t.t0, t.total) + "%";
    kT1.textContent = pct(t.t1, t.total) + "%";
    kT2.textContent = pct(t.t2, t.total) + "%";
    renderGateChart(t, outcomeTotal);
    renderTierChart(t, t.total);
    var coverageLabel = previewCoverageLabel(t.dropped);
    document.getElementById("k-eps-meta").textContent = "60s window · " + t.total + " events · " + coverageLabel;
    document.getElementById("k-gate-meta").textContent = outcomeTotal + " finalized decisions · " + coverageLabel;
    document.getElementById("k-tier-meta").textContent = t.total + " routed events · " + coverageLabel;
    var next = [eps, kAuto.textContent, kT0.textContent, kT1.textContent, kT2.textContent].join("|");
    if (spark) {
      spark.setAttribute("aria-label", "Events per second over the last 60 seconds. " + t.total + " synthetic events and " + t.dropped + " omitted generation attempts. Average " + eps + ". Focus and use left or right arrow keys to inspect each second.");
    }
    if (previous !== next) {
      document.querySelectorAll(".cs-live-kpi").forEach(pulse);
    }
  }

  // ---------- sparkline ----------
  var spark = document.querySelector('canvas[data-spark="eps"]');
  var sparkCtx = spark ? spark.getContext("2d") : null;
  var sparkHoverIndex = null;

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

    if (sparkHoverIndex !== null) {
      var hoverX = sparkHoverIndex * stepX;
      sparkCtx.save();
      sparkCtx.beginPath();
      sparkCtx.moveTo(hoverX, pad);
      sparkCtx.lineTo(hoverX, base);
      sparkCtx.strokeStyle = COL.hairline;
      sparkCtx.lineWidth = 1;
      sparkCtx.stroke();
      [["t0", COL.t0], ["t1", COL.t1], ["t2", COL.t2]].forEach(function (series) {
        sparkCtx.beginPath();
        sparkCtx.arc(hoverX, yFor(buckets[sparkHoverIndex][series[0]]), 2.2, 0, Math.PI * 2);
        sparkCtx.fillStyle = series[1];
        sparkCtx.fill();
        sparkCtx.strokeStyle = "#FFFFFF";
        sparkCtx.lineWidth = 1;
        sparkCtx.stroke();
      });
      sparkCtx.restore();
    }
  }

  function sparkBucketTip(index) {
    var bucket = buckets[index];
    var secondsAgo = buckets.length - 1 - index;
    var when = secondsAgo === 0 ? "Current second" : secondsAgo === 1 ? "1 second ago" : secondsAgo + " seconds ago";
    return when + "\nTotal " + bucket.total + " events/s · T0 " + bucket.t0 + " · T1 " + bucket.t1 + " · T2 " + bucket.t2 + "\nSynthetic bucket · " + previewCoverageLabel(bucket.dropped);
  }

  function inspectSparkBucket(index, clientX, clientY) {
    sparkHoverIndex = Math.max(0, Math.min(buckets.length - 1, index));
    spark.dataset.liveChartTip = sparkBucketTip(sparkHoverIndex);
    renderSparkline();
    showChartTooltip(spark, clientX, clientY);
  }

  function latestObservedBucket() {
    for (var index = buckets.length - 1; index >= 0; index--) {
      if (buckets[index].total > 0) return index;
    }
    return buckets.length - 1;
  }

  spark.addEventListener("pointermove", function (event) {
    var box = spark.getBoundingClientRect();
    var ratio = box.width > 0 ? (event.clientX - box.left) / box.width : 1;
    inspectSparkBucket(Math.round(Math.max(0, Math.min(1, ratio)) * (buckets.length - 1)), event.clientX, event.clientY);
  });
  spark.addEventListener("pointerleave", function () {
    sparkHoverIndex = null;
    renderSparkline();
    hideChartTooltip(spark);
  });
  spark.addEventListener("focus", function () {
    inspectSparkBucket(sparkHoverIndex === null ? latestObservedBucket() : sparkHoverIndex);
  });
  spark.addEventListener("blur", function () {
    sparkHoverIndex = null;
    renderSparkline();
    hideChartTooltip(spark);
  });
  spark.addEventListener("keydown", function (event) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    var current = sparkHoverIndex === null ? latestObservedBucket() : sparkHoverIndex;
    inspectSparkBucket(current + (event.key === "ArrowLeft" ? -1 : 1));
  });

  // ---------- production-aligned operational projection ----------
  function isSlotStuck(slot, now) {
    return Boolean(slot.ev && slot.ev.stuck && slot.state === "active" && now - slot.startedAt > 850);
  }

  function stagePosition(slot) {
    if (slot.state === "done") return STAGES.length;
    var position = STAGES.indexOf(slot.stageEl.textContent);
    return position < 0 ? 0 : position;
  }

  function decisionObserved(slot) {
    return stagePosition(slot) >= STAGES.indexOf("authorize");
  }

  function controlState(slot) {
    var ev = slot.ev;
    var position = stagePosition(slot);
    var decided = decisionObserved(slot);
    var policy = !decided ? "Pending" : ev.outcome === "auto" ? "Allow" : ev.outcome === "hil" ? "Human approval" : ev.outcome === "abstain" ? "Hold" : "Deny";
    var policyNote = !decided ? "Decision evidence not observed" : ev.outcome === "auto" ? "Policy gate allowed this candidate" : ev.outcome === "hil" ? "Per-execution approval required" : ev.outcome === "abstain" ? "Insufficient decision evidence" : "Policy blocked this candidate";
    var authority = !decided ? "Pending" : authorityLabel(ev) + (ev.outcome === "hil" ? " pending" : ev.outcome === "deny" ? " denied" : ev.mode === "shadow" ? " shadow" : " delegated");
    var authorityNote = !decided ? "Authority not evaluated" : ev.outcome === "hil" ? "Silence grants no authority" : ev.outcome === "deny" ? "Execution is prohibited" : ev.mode === "shadow" ? "Observation only; mutation disabled" : "Synthetic authority envelope only";
    var execution = "Not started";
    var executionNote = "No dispatch receipt";
    if (ev.failed && slot.state === "done") {
      execution = "Failed";
      executionNote = "Synthetic terminal failure recorded";
    } else if (decided && ev.outcome !== "auto") {
      execution = "Not dispatched";
      executionNote = "Decision path blocks execution";
    } else if (decided && ev.mode === "shadow") {
      execution = "Simulated";
      executionNote = "Shadow mode cannot mutate";
    } else if (position === STAGES.indexOf("execute")) {
      execution = "In progress";
      executionNote = "Synthetic dispatch frame observed";
    } else if (position > STAGES.indexOf("execute")) {
      execution = "Completed";
      executionNote = "Dispatch receipt is synthetic, not effect proof";
    }
    var effect = "Not verified";
    var effectNote = "Independent authoritative observation required";
    if (decided && (ev.outcome !== "auto" || ev.mode === "shadow")) {
      effect = "Not applicable";
      effectNote = "No external mutation was eligible";
    } else if (position === STAGES.indexOf("effect")) {
      effect = "Observing";
      effectNote = "Synthetic observer window is open";
    } else if (position > STAGES.indexOf("effect") && !ev.failed) {
      effect = "Preview verified";
      effectNote = "Mechanics only; no operational success claim";
    }
    return {
      policy: policy,
      policyNote: policyNote,
      authority: authority,
      authorityNote: authorityNote,
      execution: execution,
      executionNote: executionNote,
      effect: effect,
      effectNote: effectNote
    };
  }

  function renderTileControl(slot) {
    if (!slot.ev) return;
    var state = controlState(slot);
    slot.modeEl.textContent = decisionObserved(slot)
      ? state.authority.replace(" delegated", "").replace(" pending", "").replace(" denied", "").replace(" shadow", "") + " · " + slot.ev.mode.toUpperCase()
      : "Pending";
  }

  function slotStatus(slot, now) {
    var hasDecision = decisionObserved(slot);
    if (slot.ev.failed && slot.state === "done") return "failed";
    if (isSlotStuck(slot, now)) return "stuck";
    if (hasDecision && slot.ev.outcome === "hil") return "hil";
    if (hasDecision && slot.ev.outcome === "abstain") return "abstain";
    if (hasDecision && slot.ev.outcome === "deny") return "deny";
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
    return status === "failed" ? 0 : status === "stuck" ? 1 : status === "hil" ? 2 : status === "abstain" ? 3 : status === "deny" ? 4 : status === "active" ? 5 : 6;
  }

  function queueRiskRank(slot) {
    return slot.ev.profile.risk === "High" ? 0 : slot.ev.profile.risk === "Medium" ? 1 : 2;
  }

  function slaLabel(slot) {
    var elapsed = Date.now() - slot.ev.emitAt;
    var remaining = Math.max(0, Math.ceil((slot.ev.profile.slaMs - elapsed) / 1000));
    return remaining > 0 ? remaining + "s left" : "Budget exceeded";
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character];
    });
  }

  function titleCase(value) {
    return value.charAt(0).toUpperCase() + value.slice(1);
  }

  function stageOwner(stage) {
    return stage === "route" ? "Huginn" : stage === "decide" ? "Forseti" : stage === "authorize" ? "Var" : stage === "execute" ? "Thor" : stage === "effect" ? "Heimdall" : "Saga";
  }

  function renderQueue(now) {
    var visible = pool.filter(function (slot) { return matchesSlot(slot, currentFilter, now); });
    visible.sort(function (left, right) {
      var rank = queueRank(left, now) - queueRank(right, now);
      return rank || queueRiskRank(left) - queueRiskRank(right) || left.ev.emitAt - right.ev.emitAt;
    });
    visible = visible.slice(0, 12);
    queueEmpty.hidden = visible.length > 0;
    queueBody.innerHTML = visible.map(function (slot) {
      var ev = slot.ev;
      var status = slotStatus(slot, now);
      var state = controlState(slot);
      var hasDecision = decisionObserved(slot);
      var decisionClass = status === "failed" ? "deny" : hasDecision ? ev.outcome : "";
      var attentionBasis = status === "failed" ? "Execution failed" : status === "stuck" ? "Stage budget exceeded" : status === "hil" ? "Human approval required" : status === "abstain" ? "Decision evidence is insufficient" : status === "deny" ? "Policy denial recorded" : ev.sample.reason;
      return '<tr data-status="' + status + '" data-event-id="' + escapeHtml(ev.id) + '">'
        + '<td><button class="cs-live-queue-action" type="button" data-select-event="' + escapeHtml(ev.id) + '"><strong>' + escapeHtml(ev.sample.title) + '</strong><span>' + escapeHtml(ev.sample.target) + ' · ' + escapeHtml(ev.sample.scope) + '</span></button></td>'
        + '<td data-label="Priority basis"><span class="cs-live-queue-reason">' + escapeHtml(attentionBasis) + '</span></td>'
        + '<td data-label="Owner / stage"><strong>' + escapeHtml(slot.state === "done" ? "Saga" : stageOwner(slot.stageEl.textContent)) + '</strong><br><small>' + escapeHtml(slot.state === "done" ? "Recorded" : titleCase(slot.stageEl.textContent)) + '</small></td>'
        + '<td data-label="Risk / impact"><strong>' + ev.profile.risk + '</strong><br><small>' + escapeHtml(ev.profile.impact) + '</small></td>'
        + '<td data-label="Age / SLA">' + ageLabel(Date.now() - ev.emitAt) + '<br><small>' + slaLabel(slot) + '</small></td>'
        + '<td data-label="Control state"><span class="out ' + decisionClass + '">' + escapeHtml(state.policy) + '</span><br><small>' + escapeHtml(state.authority) + ' · ' + escapeHtml(state.execution) + ' · ' + escapeHtml(state.effect) + '</small></td>'
        + '</tr>';
    }).join("");
  }

  function renderOperationalState(now) {
    var counts = { all: 0, hil: 0, abstain: 0, deny: 0, failed: 0, stuck: 0 };
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
    ["hil", "abstain", "deny", "failed", "stuck"].forEach(function (key) {
      document.getElementById("attention-" + key).textContent = counts[key];
      var button = document.querySelector('[data-attention-filter="' + key + '"]');
      if (button) button.hidden = counts[key] === 0;
    });

    var attentionTotal = counts.hil + counts.abstain + counts.deny + counts.failed + counts.stuck;
    document.getElementById("work-summary").textContent = counts.all + " active · " + attentionTotal + " need attention";
    var attention = document.getElementById("live-attention");
    document.getElementById("attention-calm").hidden = attentionTotal > 0;
    document.getElementById("attention-items").hidden = attentionTotal === 0;
    attention.classList.toggle("is-calm", attentionTotal === 0);
    attention.classList.toggle("is-active", attentionTotal > 0);

    var secondsSinceEvent = Math.max(0, Math.floor((Date.now() - lastEventAt) / 1000));
    document.getElementById("health-last-event").textContent = secondsSinceEvent === 0 ? "Signal now" : secondsSinceEvent + "s ago";
    var backlog = document.getElementById("health-backlog");
    backlog.textContent = droppedFrames > 0 ? droppedFrames + " omitted" : "Intact";
    backlog.className = droppedFrames > 0 ? "is-warn" : "is-ok";
    document.getElementById("health-coverage").textContent = droppedFrames > 0 ? "Partial synthetic" : "1/1 synthetic";
    document.getElementById("health-watermark").textContent = paused ? "Frozen" : "0s synthetic";

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
    var path = stagePath(ev);
    var currentStage = path.indexOf(slot.stageEl.textContent);
    if (currentStage < 0) currentStage = slot.state === "done" ? path.length : 0;
    var agents = { route: "Huginn", decide: "Forseti", authorize: "Var", execute: "Thor", effect: "Heimdall", audit: "Saga" };
    document.getElementById("detail-title").textContent = ev.sample.title;
    document.getElementById("detail-trace").innerHTML = STAGES.map(function (stage) {
      var pathIndex = path.indexOf(stage);
      var skipped = pathIndex < 0;
      var css = skipped ? "is-skipped" : slot.state === "done" || pathIndex < currentStage ? "is-done" : pathIndex === currentStage ? "is-current" : "";
      var state = skipped ? "Not applicable" : slot.state === "done" || pathIndex < currentStage ? "Observed" : pathIndex === currentStage ? "In progress" : "Not observed";
      return '<li class="' + css + '"><i aria-hidden="true"></i><div><strong>' + stage + '</strong><small>' + agents[stage] + ' - ' + state + '</small></div></li>';
    }).join("");
    document.getElementById("detail-event").textContent = ev.id;
    document.getElementById("detail-correlation").textContent = "corr-" + ev.id.slice(4);
    document.getElementById("detail-rule").textContent = ev.sample.rule;
    document.getElementById("detail-action").textContent = ev.sample.at;
    document.getElementById("detail-reason").textContent = ev.sample.reason;
    document.getElementById("detail-target").textContent = ev.sample.target;
    document.getElementById("detail-mode").textContent = ev.mode;
    document.getElementById("detail-vertical").textContent = ev.sample.vertical;
    document.getElementById("detail-scope").textContent = ev.sample.scope;
    document.getElementById("detail-tier").textContent = ev.tier.toUpperCase();
    document.getElementById("detail-decision").textContent = decisionObserved(slot) ? ev.outcome : "pending";
    document.getElementById("detail-age").textContent = ageLabel(Date.now() - ev.emitAt);
    var state = controlState(slot);
    ["policy", "authority", "execution", "effect"].forEach(function (key) {
      document.getElementById("detail-" + key).textContent = state[key];
      document.getElementById("detail-" + key + "-note").textContent = state[key + "Note"];
    });
    var observedAt = new Date(ev.emitAt).toISOString();
    var recordedAt = new Date().toISOString();
    document.getElementById("detail-source-time").textContent = observedAt + " / " + recordedAt;
    var sourceAge = Date.now() - ev.emitAt;
    document.getElementById("detail-source-freshness").textContent = ageLabel(sourceAge) + " old · " + (sourceAge <= 5000 ? "within" : "outside") + " 5s preview policy";
    document.getElementById("detail-source-digest").textContent = "synthetic:" + ev.id.slice(4);
    document.getElementById("detail-source-coverage").textContent = "1 synthetic generator · " + (droppedFrames > 0 ? droppedFrames + " omitted attempts since load" : "no omitted attempts since load");
    document.getElementById("detail-impact").textContent = ev.profile.risk + " · synthetic receipt";
    document.getElementById("detail-impact-note").textContent = ev.profile.impact + " inside the preview scope.";
    document.getElementById("detail-lock").textContent = ev.targetRevision;
    document.getElementById("detail-idempotency").textContent = "Synthetic receipt";
    document.getElementById("detail-idempotency-note").textContent = ev.idempotencyKey;
    document.getElementById("detail-audit-state").textContent = ev.auditClosed ? "Synthetic closure" : "Intent only";
    document.getElementById("detail-audit-note").textContent = ev.auditClosed ? "Intent and terminal preview frames recorded." : "Terminal closure not observed.";
    document.getElementById("detail-trace-link").href = "rule-trace.html?correlation=corr-" + encodeURIComponent(ev.id.slice(4));
    document.getElementById("detail-audit-link").href = "audit.html?correlation=corr-" + encodeURIComponent(ev.id.slice(4));
    document.getElementById("detail-audit-link").textContent = ev.auditClosed ? "Open synthetic audit" : "View audit intent";
    detailBackdrop.hidden = false;
    document.body.style.overflow = "hidden";
    detailClose.focus();
  }

  // ---------- controls ----------
  pauseBtn.addEventListener("click", function () {
    paused = !paused;
    var now = performance.now();
    var wallNow = Date.now();
    if (paused) {
      pauseStartedAt = now;
      pauseStartedWallAt = wallNow;
    } else {
      var elapsed = now - pauseStartedAt;
      var wallElapsed = wallNow - pauseStartedWallAt;
      pool.forEach(function (slot) {
        if (!slot.ev) return;
        slot.startedAt += elapsed;
        slot.endsAt += elapsed;
        if (slot.retiresAt) slot.retiresAt += elapsed;
        slot.ev.emitAt += wallElapsed;
      });
      lastBucketAt += elapsed;
      lastEventAt += wallElapsed;
      lastFrame = now;
    }
    pauseBtn.textContent = paused ? "Resume view" : "Freeze view";
    pauseBtn.setAttribute("aria-pressed", paused ? "true" : "false");
    document.querySelectorAll(".cs-live-connection i").forEach(function (indicator) {
      indicator.style.animationPlayState = paused ? "paused" : "";
    });
    renderOperationalState(performance.now());
  });
  queueButton.addEventListener("click", function () { setView("queue"); });
  flowButton.addEventListener("click", function () { setView("flow"); });
  fullscreenButton.addEventListener("click", toggleFullscreen);
  document.addEventListener("fullscreenchange", function () {
    syncFullscreen();
    if (!fullscreenActive()) {
      window.setTimeout(function () { fullscreenButton.focus(); }, 0);
    }
  });
  document.addEventListener("fullscreenerror", enterFallbackFullscreen);
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
    if (event.key === "Escape" && workWorkspace.classList.contains("is-fullscreen-fallback")) {
      exitFallbackFullscreen();
      return;
    }
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
  setView("flow");
  setFilter("all");
  syncFullscreen();
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
