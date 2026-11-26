/* FDAI Console v4 - XSS-Safe Full-Stack Live Hydration Engine (65 panels).
   Uses textContent / DOM element creation exclusively (zero untrusted innerHTML).
   Preserves honest not-measured semantics in Live mode without leaking mockup values. */
(function () {
  "use strict";

  const PANEL_CONTRACTS = {
    "dashboard": { domain: "overview", endpoint: "/api/v4/overview/dashboard", virtualized: false },
    "dashboard-v2": { domain: "overview", endpoint: "/api/v4/overview/resources", virtualized: true },
    "operating-outcomes": { domain: "overview", endpoint: "/api/v4/overview/outcomes", virtualized: false },
    "control-assurance": { domain: "overview", endpoint: "/api/v4/overview/control-assurance", virtualized: false },
    "verticals": { domain: "overview", endpoint: "/api/v4/overview/verticals", virtualized: false },
    "cost-governance": { domain: "overview", endpoint: "/api/v4/overview/cost-governance", virtualized: false },
    "llm-cost": { domain: "overview", endpoint: "/api/v4/overview/llm-cost", virtualized: false },
    "live": { domain: "operations", endpoint: "/api/v4/operations/live", virtualized: false },
    "gpu": { domain: "operations", endpoint: "/api/v4/operations/gpu", virtualized: false },
    "incidents": { domain: "operations", endpoint: "/api/v4/operations/incidents", virtualized: true },
    "code-security": { domain: "operations", endpoint: "/api/v4/operations/security", virtualized: false },
    "vulnerability-risk": { domain: "operations", endpoint: "/api/v4/operations/security", virtualized: false },
    "configuration-baselines": { domain: "operations", endpoint: "/api/v4/operations/baselines", virtualized: false },
    "hil-queue": { domain: "operations", endpoint: "/api/v4/operations/hil-queue", virtualized: false },
    "alert-quality": { domain: "operations", endpoint: "/api/v4/operations/alert-quality", virtualized: false },
    "detection-readiness": { domain: "operations", endpoint: "/api/v4/operations/detection-readiness", virtualized: false },
    "conversation-delivery": { domain: "operations", endpoint: "/api/v4/operations/conversation-delivery", virtualized: false },
    "workflow-apps": { domain: "operations", endpoint: "/api/v4/operations/workflow-apps", virtualized: false },
    "automation-blueprints": { domain: "operations", endpoint: "/api/v4/operations/automation-blueprints", virtualized: false },
    "processes": { domain: "operations", endpoint: "/api/v4/operations/processes", virtualized: false },
    "scheduler-runs": { domain: "operations", endpoint: "/api/v4/operations/scheduler-runs", virtualized: false },
    "background-tasks": { domain: "operations", endpoint: "/api/v4/operations/background-tasks", virtualized: false },
    "scheduled-continuations": { domain: "operations", endpoint: "/api/v4/operations/scheduled-continuations", virtualized: false },
    "provision": { domain: "operations", endpoint: "/api/v4/operations/provision", virtualized: false },
    "onboarding": { domain: "operations", endpoint: "/api/v4/operations/onboarding", virtualized: false },
    "agents": { domain: "agents", endpoint: "/api/v4/agents/summary", virtualized: false },
    "pantheon": { domain: "agents", endpoint: "/api/v4/agents/pantheon", virtualized: false },
    "handover": { domain: "agents", endpoint: "/api/v4/agents/handover", virtualized: false },
    "agent-activity": { domain: "agents", endpoint: "/api/v4/agents/activity", virtualized: true },
    "skills": { domain: "agents", endpoint: "/api/v4/agents/skills", virtualized: false },
    "capabilities": { domain: "agents", endpoint: "/api/v4/agents/capabilities", virtualized: false },
    "rules": { domain: "governance", endpoint: "/api/v4/governance/rules", virtualized: true },
    "trust-routing": { domain: "governance", endpoint: "/api/v4/governance/trust-routing", virtualized: false },
    "ontology": { domain: "governance", endpoint: "/api/v4/governance/ontology/instances", virtualized: true },
    "scope": { domain: "governance", endpoint: "/api/v4/governance/scope", virtualized: false },
    "architecture": { domain: "governance", endpoint: "/api/v4/governance/architecture", virtualized: true },
    "blast-radius": { domain: "governance", endpoint: "/api/v4/governance/blast-radius", virtualized: true },
    "promotion-gates": { domain: "governance", endpoint: "/api/v4/governance/promotion-gates", virtualized: false },
    "workflow-builder": { domain: "governance", endpoint: "/api/v4/governance/workflows", virtualized: false },
    "knowledge": { domain: "governance", endpoint: "/api/v4/governance/knowledge", virtualized: false },
    "github": { domain: "governance", endpoint: "/api/v4/governance/knowledge/github", virtualized: false },
    "gitlab": { domain: "governance", endpoint: "/api/v4/governance/knowledge/gitlab", virtualized: false },
    "azure-devops": { domain: "governance", endpoint: "/api/v4/governance/knowledge/azure-devops", virtualized: false },
    "documents": { domain: "governance", endpoint: "/api/v4/governance/documents", virtualized: false },
    "audit": { domain: "evidence", endpoint: "/api/v4/evidence/audit", virtualized: true },
    "trace": { domain: "evidence", endpoint: "/api/v4/evidence/trace", virtualized: true },
    "rca": { domain: "evidence", endpoint: "/api/v4/evidence/rca", virtualized: false },
    "browser-evidence": { domain: "evidence", endpoint: "/api/v4/evidence/browser-evidence", virtualized: false },
    "conversation-search": { domain: "evidence", endpoint: "/api/v4/evidence/conversations", virtualized: true },
    "reports": { domain: "evidence", endpoint: "/api/v4/evidence/reports", virtualized: false },
    "settings-general": { domain: "settings", endpoint: "/api/v4/settings/general", virtualized: false },
    "settings-environment": { domain: "settings", endpoint: "/api/v4/settings/environment", virtualized: false },
    "settings-models": { domain: "settings", endpoint: "/api/v4/settings/models", virtualized: false },
    "settings-runtime": { domain: "settings", endpoint: "/api/v4/settings/runtime", virtualized: false },
    "settings-iam": { domain: "settings", endpoint: "/api/v4/settings/iam", virtualized: false },
    "settings-integrations": { domain: "settings", endpoint: "/api/v4/settings/integrations", virtualized: false },
    "settings-diagnostics": { domain: "settings", endpoint: "/api/v4/settings/diagnostics", virtualized: false },
    "settings-memory": { domain: "settings", endpoint: "/api/v4/settings/memory", virtualized: false },
    "labs": { domain: "labs", endpoint: "/api/v4/labs/summary", virtualized: false },
    "aks-commerce": { domain: "labs", endpoint: "/api/v4/labs/aks-commerce", virtualized: false },
    "assurance-twin": { domain: "labs", endpoint: "/api/v4/labs/assurance-twin", virtualized: false },
    "forecast-learning": { domain: "labs", endpoint: "/api/v4/labs/forecast-learning", virtualized: false },
    "conversation-assurance": { domain: "labs", endpoint: "/api/v4/labs/conversation-assurance", virtualized: false },
    "context-selection-comparisons": { domain: "labs", endpoint: "/api/v4/labs/context-comparisons", virtualized: false },
    "command-deck-chat": { domain: "chat", endpoint: "/api/v4/chat/sessions", virtualized: false },
  };

  function createTextNodeEl(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    el.textContent = text == null ? "" : String(text);
    return el;
  }

  function renderMeasurementBadge(container, status, reason) {
    if (!container) return;
    container.replaceChildren();
    const isMeasured = status === "measured";
    const badge = createTextNodeEl(
      "span",
      isMeasured ? "cs-badge tone-live" : "cs-badge tone-neutral",
      isMeasured ? "PostgreSQL 실측 연결됨" : ("미측정 (" + (reason || "not-measured") + ")")
    );
    container.appendChild(badge);
  }

  function renderSafeTableRows(tbody, items, columns) {
    if (!tbody) return;
    const frag = document.createDocumentFragment();
    for (const item of items) {
      const tr = document.createElement("tr");
      for (const col of columns) {
        const val = item && Object.prototype.hasOwnProperty.call(item, col) ? item[col] : "";
        tr.appendChild(createTextNodeEl("td", "", val == null ? "-" : String(val)));
      }
      frag.appendChild(tr);
    }
    tbody.replaceChildren(frag);
  }

  async function fetchJsonSafe(url, opts) {
    try {
      const resp = await fetch(url, Object.assign({ headers: { Accept: "application/json" } }, opts || {}));
      const data = await resp.json().catch(() => null);
      return { ok: resp.ok, status: resp.status, data };
    } catch (_err) {
      return { ok: false, status: 0, data: null };
    }
  }

  async function hydratePanel(panelId, queryParams) {
    const spec = PANEL_CONTRACTS[panelId];
    if (!spec) return { ok: false, reason: "unknown_panel" };
    const qs = queryParams ? ("?" + new URLSearchParams(queryParams).toString()) : "";
    const res = await fetchJsonSafe(spec.endpoint + qs);
    const root = document.querySelector('.panel-view[data-panel-id="' + panelId + '"]');
    if (root) {
      const statusHost = root.querySelector("[data-live-status-host]");
      const status = res.data && res.data.measurement_status ? res.data.measurement_status : "not-measured";
      const reason = res.data && res.data.reason ? res.data.reason : (res.ok ? "empty" : "http_" + res.status);
      renderMeasurementBadge(statusHost, status, reason);
    }
    return res;
  }

  async function submitAuditedMutation(endpoint, method, payload, bearerToken, idempotencyKey) {
    const headers = {
      "Content-Type": "application/json",
      Accept: "application/json",
      "Idempotency-Key": idempotencyKey || ("idem-" + Date.now())
    };
    if (bearerToken) headers.Authorization = "Bearer " + bearerToken;
    return fetchJsonSafe(endpoint, {
      method: method || "PATCH",
      headers,
      body: JSON.stringify(payload || {})
    });
  }

  function isMandatorySeverity(severity) {
    const s = String(severity || "").trim().toLowerCase();
    return s === "critical" || s === "high" || s === "sev1" || s === "sev2" || s === "p0" || s === "p1" || s === "긴급" || s === "높음";
  }

  async function toggleRuleActivation(ruleId, enabled, severity, reason, bearerToken) {
    if (!enabled && isMandatorySeverity(severity)) {
      return { ok: false, status: 409, data: { error: "mandatory_severity_cannot_be_disabled", rule_id: ruleId, severity } };
    }
    return submitAuditedMutation(
      "/api/v4/governance/rules/" + encodeURIComponent(ruleId) + "/activation",
      "PATCH",
      { enabled: !!enabled, severity: String(severity || "medium"), reason: String(reason || "") },
      bearerToken,
      "rule-act-" + ruleId + "-" + Date.now()
    );
  }

  async function enforceMandatoryRules(bearerToken) {
    return submitAuditedMutation(
      "/api/v4/governance/rules/enforce-mandatory",
      "POST",
      {},
      bearerToken,
      "rule-enforce-mandatory-" + Date.now()
    );
  }

  function renderAuditIntegrityBadge(container, auditIntegrity) {
    if (!container) return;
    container.replaceChildren();
    const verified = auditIntegrity && auditIntegrity.status === "verified";
    const gaps = auditIntegrity && typeof auditIntegrity.current_link_gap_count === "number" ? auditIntegrity.current_link_gap_count : null;
    const text = verified
      ? ("원장 무결성: 검증됨 · 결손 " + (gaps == null ? 0 : gaps) + "건")
      : (gaps == null ? "원장 무결성: 미측정" : ("원장 무결성 주의 · 결손 " + gaps + "건"));
    container.appendChild(createTextNodeEl("span", verified ? "cs-badge tone-live" : "cs-badge tone-neutral", text));
  }

  const boot = window.__FDAI_V4_BOOTSTRAP__ || {};

  function openSseSafe(url, onMessage, onError) {
    if (typeof window.EventSource !== "function") return null;
    try {
      const es = new EventSource(url);
      if (typeof onMessage === "function") {
        es.onmessage = (ev) => {
          try {
            onMessage(JSON.parse(ev.data), ev);
          } catch (_e) {
            onMessage(ev.data, ev);
          }
        };
      }
      if (typeof onError === "function") {
        es.onerror = onError;
      }
      return es;
    } catch (_err) {
      return null;
    }
  }

  const savedSubOptions = new WeakMap();

  async function hydrateGlobalSubscriptionSelects() {
    const selects = Array.from(document.querySelectorAll('select[aria-label="Azure 구독 필터"]'));
    if (!selects.length) return;
    const isLive = () => {
      const active = document.querySelector("[data-data-mode].is-active");
      return !active || active.getAttribute("data-data-mode") === "live";
    };
    for (const sel of selects) {
      if (!savedSubOptions.has(sel)) {
        savedSubOptions.set(
          sel,
          Array.from(sel.options).map((o) => ({ value: o.value, text: o.textContent || "" }))
        );
      }
    }
    if (!isLive()) {
      for (const sel of selects) {
        const orig = savedSubOptions.get(sel) || [];
        const frag = document.createDocumentFragment();
        for (const item of orig) {
          const opt = document.createElement("option");
          opt.value = item.value;
          opt.textContent = item.text;
          frag.appendChild(opt);
        }
        sel.replaceChildren(frag);
      }
      return;
    }
    const res = await fetchJsonSafe("/api/v4/overview/summary");
    const subs = res && res.ok && res.data && res.data.data && Array.isArray(res.data.data.subscriptions)
      ? res.data.data.subscriptions
      : null;
    if (!subs || !subs.length) return;
    for (const sel of selects) {
      const prevVal = sel.value || "all";
      const frag = document.createDocumentFragment();
      const allOpt = document.createElement("option");
      allOpt.value = "all";
      allOpt.textContent = "구독: 전체 연결 구독 (" + subs.length + " · 실DB)";
      frag.appendChild(allOpt);
      for (const s of subs) {
        const opt = document.createElement("option");
        opt.value = String(s.id || "");
        opt.textContent = "구독: " + String(s.label || s.id || "");
        frag.appendChild(opt);
      }
      sel.replaceChildren(frag);
      if (Array.from(sel.options).some((o) => o.value === prevVal)) {
        sel.value = prevVal;
      } else {
        sel.value = "all";
      }
    }
  }

  let globalPulseEs = null;
  let globalPulsePaused = false;
  let globalLastPulse = null;
  let globalLastPulseRxAt = 0;
  let globalAgeTimer = null;
  const pulseListeners = new Set();

  function formatAgeKo(rxMs) {
    if (!rxMs) return "연결 중";
    const sec = Math.max(0, Math.floor((Date.now() - rxMs) / 1000));
    if (sec <= 2) return "방금 전";
    if (sec < 60) return sec + "초 전";
    return Math.floor(sec / 60) + "분 전";
  }

  function ensureGlobalPulsePill() {
    let pill = document.getElementById("fdaiGlobalLivePulse");
    if (pill) return pill;
    const modeGroup = document.querySelector('[role="group"][aria-label="데이터 모드"]');
    if (!modeGroup || !modeGroup.parentElement) return null;
    pill = document.createElement("button");
    pill.type = "button";
    pill.id = "fdaiGlobalLivePulse";
    pill.className = "fdai-live-pulse-pill";
    pill.setAttribute("aria-live", "polite");
    pill.setAttribute("data-ut-title", "실시간 PostgreSQL 감지 펄스 (/api/v4/live/pulse)");
    pill.setAttribute("data-ut-body", "4초 간격으로 감사 원장, 온톨로지 계통 워터마크, 인시던트, 승인 대기열의 변화를 실시간 감지합니다. 클릭 시 일시정지/재개.");
    pill.setAttribute("data-ut-tone", "live");
    const dot = document.createElement("span");
    dot.className = "fdai-live-pulse-dot";
    const lbl = document.createElement("span");
    lbl.id = "fdaiGlobalLivePulseLabel";
    lbl.textContent = "실시간 감지 연결 중";
    pill.append(dot, lbl);
    pill.addEventListener("click", () => {
      globalPulsePaused = !globalPulsePaused;
      if (globalPulsePaused) {
        stopGlobalLivePulse();
        renderGlobalPulsePill();
      } else {
        startGlobalLivePulse();
      }
    });
    modeGroup.insertAdjacentElement("afterend", pill);
    return pill;
  }

  function renderGlobalPulsePill() {
    const pill = ensureGlobalPulsePill();
    if (!pill) return;
    const lbl = document.getElementById("fdaiGlobalLivePulseLabel");
    const isLive = () => {
      const active = document.querySelector("[data-data-mode].is-active");
      return !active || active.getAttribute("data-data-mode") === "live";
    };
    if (!isLive()) {
      pill.hidden = true;
      return;
    }
    pill.hidden = false;
    pill.classList.toggle("is-paused", globalPulsePaused);
    if (globalPulsePaused) {
      if (lbl) lbl.textContent = "실시간 감지 일시정지";
      return;
    }
    if (!globalLastPulse) {
      pill.classList.remove("is-offline");
      if (lbl) lbl.textContent = "실시간 감지 연결 중";
      return;
    }
    const measured = globalLastPulse.measurement_status === "measured";
    pill.classList.toggle("is-offline", !measured);
    if (!measured) {
      if (lbl) lbl.textContent = "실시간 감지 · 미측정";
      return;
    }
    const seq = globalLastPulse.audit_latest_seq || 0;
    const age = formatAgeKo(globalLastPulseRxAt);
    const delta = globalLastPulse.delta_audit || 0;
    const deltaTxt = delta > 0 ? (" +" + delta) : "";
    if (lbl) lbl.textContent = "실시간 감지 · #" + seq + deltaTxt + " · " + age;
    const lat = globalLastPulse.db_latency_ms != null ? (globalLastPulse.db_latency_ms + "ms") : "-";
    const resTotal = globalLastPulse.ontology_resources_total != null ? Number(globalLastPulse.ontology_resources_total).toLocaleString() : "-";
    const wm = globalLastPulse.journal_watermark != null ? Number(globalLastPulse.journal_watermark).toLocaleString() : "-";
    const hil = globalLastPulse.hil_pending != null ? Number(globalLastPulse.hil_pending).toLocaleString() : "-";
    const target = (globalLastPulse.latest_event && globalLastPulse.latest_event.target) || "관측 원장";
    pill.setAttribute(
      "data-ut-body",
      "DB 응답 " + lat + " · 리소스 " + resTotal + "개 · 계통 워터마크 #" + wm + " · 승인 대기 " + hil + "건 · 최신 감지: " + target + " (클릭: 일시정지/재개)"
    );
  }

  function stopGlobalLivePulse() {
    if (globalPulseEs) {
      try { globalPulseEs.close(); } catch (_e) {}
      globalPulseEs = null;
    }
    if (globalAgeTimer) {
      clearInterval(globalAgeTimer);
      globalAgeTimer = null;
    }
  }

  function startGlobalLivePulse() {
    const isLive = () => {
      const active = document.querySelector("[data-data-mode].is-active");
      return !active || active.getAttribute("data-data-mode") === "live";
    };
    if (!isLive() || globalPulsePaused) {
      stopGlobalLivePulse();
      renderGlobalPulsePill();
      return;
    }
    ensureGlobalPulsePill();
    renderGlobalPulsePill();
    if (globalPulseEs || typeof window.EventSource !== "function") return;
    try {
      const es = new EventSource("/api/v4/live/pulse");
      es.addEventListener("pulse", (ev) => {
        try {
          const payload = JSON.parse(ev.data);
          globalLastPulse = payload;
          globalLastPulseRxAt = Date.now();
          renderGlobalPulsePill();
          const pill = document.getElementById("fdaiGlobalLivePulse");
          if (pill) {
            pill.classList.add("is-beat");
            setTimeout(() => { pill.classList.remove("is-beat"); }, 320);
          }
          window.dispatchEvent(new CustomEvent("fdai:live-pulse", { detail: payload }));
          for (const cb of pulseListeners) {
            try { cb(payload); } catch (_err) {}
          }
        } catch (_parseErr) {}
      });
      es.onerror = () => {
        renderGlobalPulsePill();
      };
      globalPulseEs = es;
      if (!globalAgeTimer) {
        globalAgeTimer = setInterval(renderGlobalPulsePill, 1000);
      }
    } catch (_err) {}
  }

  function onPulse(cb) {
    if (typeof cb !== "function") return () => {};
    pulseListeners.add(cb);
    if (globalLastPulse) {
      try { cb(globalLastPulse); } catch (_err) {}
    }
    return () => { pulseListeners.delete(cb); };
  }

  function bootGlobalLiveSubscriptions() {
    hydrateGlobalSubscriptionSelects().catch(() => {});
    startGlobalLivePulse();
    document.addEventListener("click", (ev) => {
      const btn = ev.target && ev.target.closest ? ev.target.closest("[data-data-mode]") : null;
      if (btn) {
        setTimeout(() => {
          hydrateGlobalSubscriptionSelects().catch(() => {});
          startGlobalLivePulse();
        }, 40);
      }
    });
    window.addEventListener("beforeunload", stopGlobalLivePulse);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootGlobalLiveSubscriptions);
  } else {
    bootGlobalLiveSubscriptions();
  }

  window.fdaiV4Live = {
    bootstrap: boot,
    panelContracts: PANEL_CONTRACTS,
    fetchJson: fetchJsonSafe,
    openSse: openSseSafe,
    hydratePanel,
    hydrateGlobalSubscriptionSelects,
    onPulse,
    getLastPulse: () => globalLastPulse,
    isPulsePaused: () => globalPulsePaused,
    renderSafeTableRows,
    renderMeasurementBadge,
    renderAuditIntegrityBadge,
    isMandatorySeverity,
    toggleRuleActivation,
    enforceMandatoryRules,
    submitAuditedMutation,
    isLiveMode: () => {
      const active = document.querySelector("[data-data-mode].is-active");
      return !active || active.getAttribute("data-data-mode") === "live";
    }
  };
})();
