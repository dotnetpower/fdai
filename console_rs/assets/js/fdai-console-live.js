/* FDAI Console v4 — XSS-Safe Full-Stack Live Hydration Engine (65 panels).
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
        tr.appendChild(createTextNodeEl("td", "", val == null ? "—" : String(val)));
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
    // Clear sample subscription options immediately in Live mode before fetching
    for (const sel of selects) {
      const hasSample = Array.from(sel.options).some((o) =>
        o.value === "prod-core-kr" || o.value === "prod-data-platform" || o.value === "sec-shared-hub"
      );
      if (hasSample) {
        const loadingOpt = document.createElement("option");
        loadingOpt.value = "all";
        loadingOpt.textContent = "구독: 실측 구독 조회 중...";
        sel.replaceChildren(loadingOpt);
      }
    }
    const res = await fetchJsonSafe("/api/v4/overview/summary");
    const subs = res && res.ok && res.data && res.data.data && Array.isArray(res.data.data.subscriptions)
      ? res.data.data.subscriptions
      : null;
    if (!isLive()) return;
    if (!subs || !subs.length) {
      for (const sel of selects) {
        const emptyOpt = document.createElement("option");
        emptyOpt.value = "all";
        emptyOpt.textContent = "구독: 연결된 실측 구독 없음 (미측정)";
        sel.replaceChildren(emptyOpt);
      }
      return;
    }
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

  const RESOURCE_TYPE_KO = {
    "compute.container-app-job": "컨테이너 앱 작업",
    "compute.container-app": "컨테이너 앱",
    "compute.kubernetes-cluster": "AKS 쿠버네티스 클러스터",
    "kubernetes-cluster": "AKS 쿠버네티스 클러스터",
    "compute.virtual-machine": "가상 머신 (VM)",
    "compute.virtual-machine-scale-set": "가상 머신 확장 집합 (VMSS)",
    "compute.vm-scale-set": "가상 머신 확장 집합 (VMSS)",
    "compute.vm": "가상 머신 (VM)",
    "compute.app-service": "App Service 웹 앱",
    "compute.function-app": "Azure Function 앱",
    "database.postgresql-flexible": "PostgreSQL 데이터베이스",
    "postgresql-flexible": "PostgreSQL 데이터베이스",
    "database.sql-database": "Azure SQL 데이터베이스",
    "database.cosmos-db": "Cosmos DB",
    "cache.redis": "Redis 캐시",
    "cache-redis": "Redis 캐시",
    "network.network-security-group": "네트워크 보안 그룹 (NSG)",
    "network-security-group": "네트워크 보안 그룹 (NSG)",
    "network.application-gateway": "애플리케이션 게이트웨이",
    "network.firewall": "Azure 방화벽",
    "firewall": "Azure 방화벽",
    "network.virtual-network": "가상 네트워크 (VNet)",
    "network.vnet": "가상 네트워크 (VNet)",
    "network.load-balancer": "부하 분산 장치",
    "network.private-endpoint": "프라이빗 엔드포인트",
    "security.key-vault": "Key Vault (키 보관소)",
    "key-vault": "Key Vault (키 보관소)",
    "storage.storage-account": "스토리지 계정",
    "data-storage": "스토리지 계정",
    "messaging.service-bus": "Service Bus 메시지 브로커",
    "monitoring.log-analytics": "Log Analytics 작업 영역",
    "ai.openai": "Azure OpenAI 서비스",
    "container.registry": "컨테이너 레지스트리 (ACR)",
  };

  const ACTION_KIND_KO = {
    "hil.requested": "사람 승인 요청 생성",
    "hil.approved": "사람 승인 완료",
    "hil.rejected": "사람 승인 반려",
    "hil.timeout": "승인 요청 기한 만료",
    "hil.expired": "승인 요청 기한 만료",
    "measurement.control_loop.v1": "운영 제어 루프 관측 완료",
    "measurement.control_loop": "운영 제어 루프 관측 완료",
    "action.executed": "자동 조치 실행 완료",
    "action.denied": "정책에 의해 조치 차단",
    "action.blocked": "정책에 의해 조치 차단",
    "action.dry_run": "사전 드라이런 검증 완료",
    "action.rolled_back": "자동 롤백 완료",
    "container.restart": "컨테이너 재시작",
    "policy.evaluated": "운영 정책 평가",
    "policy.required": "필수 정책 검증",
    "policy.violation": "운영 정책 위반 감지",
    "incident.opened": "운영 이상(인시던트) 감지",
    "incident.detected": "운영 이상(인시던트) 감지",
    "incident.resolved": "운영 이상 해결 완료",
    "inventory.observed": "리소스 인벤토리 스냅샷 갱신",
    "inventory.upsert": "리소스 상태 정보 갱신",
    "security.finding": "보안 취약점·기준선 항목 발견",
    "promotion.approved": "자동화 승격 승인",
    "promotion.recalled": "자동화 즉시 회수",
    "conversation.delivered": "운영 알림 메시지 전송",
  };

  const ACTOR_KO = {
    "fdai.measurement": "관측 수집기 (Heimdall)",
    "fdai.core.hil_resume": "승인 워크플로 (Var)",
    "fdai.core.control_loop": "제어 루프 엔진 (Odin)",
    "fdai.core.rca": "원인 분석 엔진 (Mimir)",
    "fdai.scope-draft.v1": "관리 범위 초안",
    "fdai.policy": "정책 심의 엔진 (Forseti)",
    "fdai.forseti": "정책 심의 엔진 (Forseti)",
    "fdai.executor": "격리 실행기 (Thor)",
    "fdai.inventory": "인벤토리 수집기 (Huginn)",
    "fdai.huginn": "인벤토리 수집기 (Huginn)",
    "fdai.ontology": "온톨로지 저장소 (Muninn)",
    "fdai.muninn": "온톨로지 저장소 (Muninn)",
    "fdai.audit": "감사 원장 (Saga)",
    "fdai.saga": "감사 원장 (Saga)",
    "fdai.operator": "운영자 서비스",
  };

  const MODE_STATE_KO = {
    "shadow": "관찰 전용 (Shadow)",
    "enforce": "자동 적용 (Enforce)",
    "dry_run": "사전 검증 (Dry-run)",
    "advisory": "권고 모드",
    "in_progress": "대응 진행 중",
    "open": "확인 필요",
    "resolved": "해결 완료",
    "closed": "종료됨",
    "pending": "승인 대기 중",
    "approved": "승인됨",
    "rejected": "반려됨",
    "timeout": "기한 만료",
    "expired": "기한 만료",
    "running": "정상 실행 중",
    "stopped": "중지됨",
    "degraded": "성능 저하",
    "healthy": "정상",
    "critical": "긴급",
    "high": "높음",
    "medium": "보통",
    "low": "낮음",
    "measured": "실측 연결됨",
    "not-measured": "미측정",
  };

  function humanizeResourceType(raw) {
    const s = String(raw || "").trim();
    if (!s) return "관측 대상";
    const key = s.toLowerCase();
    if (RESOURCE_TYPE_KO[key]) return RESOURCE_TYPE_KO[key];
    for (const [k, label] of Object.entries(RESOURCE_TYPE_KO)) {
      if (key.endsWith("." + k) || key.includes(k)) return label;
    }
    if (/^[a-z0-9_.-]+$/i.test(s) && (s.includes(".") || s.includes("-") || s.includes("_"))) {
      const tail = s.split("/").pop().split(".").pop();
      return tail.replace(/[-_]+/g, " ");
    }
    return s;
  }

  const TABLE_NAME_KO = {
    "audit_log": "감사 원장",
    "ontology_resource": "온톨로지 리소스 원장",
    "inventory_observation_journal": "인벤토리 관측 기록",
    "operator_incident_projection": "인시던트 운영 원장",
    "conversation_outbound_delivery": "알림 전송 이력 원장",
    "document_knowledge_source": "운영 지식 문서 원장",
  };

  function humanizeTableName(raw) {
    const s = String(raw || "").trim();
    if (!s) return "운영 원장";
    return TABLE_NAME_KO[s.toLowerCase()] || s;
  }

  function humanizeAction(raw) {
    const s = String(raw || "").trim();
    if (!s) return "운영 이벤트 기록";
    const key = s.toLowerCase();
    if (ACTION_KIND_KO[key]) return ACTION_KIND_KO[key];
    if (/^inventory\.[0-9a-f]{8,}$/i.test(key)) return "인벤토리 동기화 작업";
    if (key.startsWith("hil.")) return "사람 승인 절차 이벤트";
    if (key.startsWith("measurement.")) return "운영 상태 측정 기록";
    if (key.startsWith("incident.")) return "장애·이상 대응 이벤트";
    if (key.startsWith("security.") || key.startsWith("code_security.")) return "보안 점검 이벤트";
    if (key.startsWith("policy.") || key.startsWith("rule.")) return "운영 정책 평가 이벤트";
    if (key.startsWith("inventory.") || key.startsWith("ontology.")) return "리소스 상태 갱신";
    if (key.startsWith("container.")) return "컨테이너 운영 이벤트";
    if (key.startsWith("action.")) return "운영 조치 처리";
    return s;
  }

  function humanizeActor(raw) {
    const s = String(raw || "").trim();
    if (!s) return "FDAI 시스템";
    const key = s.toLowerCase();
    if (ACTOR_KO[key]) return ACTOR_KO[key];
    if (key.includes("hil")) return "승인 워크플로 (Var)";
    if (key.includes("measurement") || key.includes("heimdall")) return "관측 수집기 (Heimdall)";
    if (key.includes("huginn") || key.includes("inventory")) return "인벤토리 수집기 (Huginn)";
    if (key.includes("muninn") || key.includes("ontology")) return "온톨로지 저장소 (Muninn)";
    if (key.includes("forseti") || key.includes("policy")) return "정책 심의 엔진 (Forseti)";
    if (key.includes("saga") || key.includes("audit")) return "감사 원장 (Saga)";
    if (key.includes("mimir")) return "규칙 평가기 (Mimir)";
    if (key.includes("thor") || key.includes("executor")) return "격리 실행기 (Thor)";
    return s;
  }

  function humanizeMode(raw) {
    const s = String(raw || "").trim();
    if (!s) return "미측정";
    const key = s.toLowerCase();
    return MODE_STATE_KO[key] || s;
  }

  function humanizeTimestamp(isoOrMs) {
    if (isoOrMs == null || isoOrMs === "") return "미측정";
    const d = typeof isoOrMs === "number" ? new Date(isoOrMs) : new Date(String(isoOrMs));
    if (Number.isNaN(d.getTime())) return String(isoOrMs);
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getMonth() + 1}월 ${d.getDate()}일 ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  function humanizeEventSummary(ev) {
    const rawActor = String(ev?.actor || "").trim();
    const rawAction = String(ev?.action_kind || ev?.action || "").trim();
    const rawTarget = String(ev?.target || ev?.resource_type || "").trim();
    const rawMode = String(ev?.mode || ev?.status || "").trim();
    const actorKo = humanizeActor(rawActor);
    const actionKo = humanizeAction(rawAction);
    const targetKo = humanizeResourceType(rawTarget);
    const modeKo = rawMode ? humanizeMode(rawMode) : "";
    const title = rawTarget && targetKo !== "관측 대상"
      ? `${targetKo} — ${actionKo}`
      : actionKo;
    const description = `${actorKo}에서 ${targetKo} 대상으로 '${actionKo}' 작업을 처리했습니다.${modeKo ? ` 현재 실행 모드는 ${modeKo}입니다.` : ""}`;
    const techRows = [];
    if (ev?.id) techRows.push(["항목 식별자", String(ev.id)]);
    if (rawAction) techRows.push(["원본 액션 키", rawAction]);
    if (rawActor) techRows.push(["원본 행위자", rawActor]);
    if (rawTarget) techRows.push(["원본 대상 키", rawTarget]);
    if (rawMode) techRows.push(["원본 모드", rawMode]);
    return { title, actorKo, actionKo, targetKo, modeKo, description, techRows };
  }

  const RULE_ID_KO = {
    "compute.vm.environment-tag.required": "가상 머신 필수 environment 태그 기준",
    "compute.vm-scale-set.zone-redundancy": "가상 머신 확장 집합(VMSS) 가용성 영역 이중화 기준",
    "disk.snapshot-policy.required": "디스크 스냅샷 정책 필수 기준",
    "network.nsg.open-ssh": "NSG 공용 SSH 포트 차단 기준",
    "security.key-vault.public-access": "Key Vault 공용 접근 차단 기준",
  };

  const REMEDIATION_ACTION_KO = {
    "remediate.tag-add": "필수 태그 자동 추가",
    "remediate.tag-update": "리소스 태그 보정",
    "remediate.scale-out": "노드 풀 확장",
    "remediate.restart": "워크로드 재시작",
    "remediate.revoke-access": "임시 접근 권한 회수",
    "remediate.restrict-network": "네트워크 접근 제한",
  };

  function humanizeRuleId(raw) {
    const s = String(raw || "").trim();
    if (!s) return "";
    const key = s.toLowerCase();
    if (RULE_ID_KO[key]) return RULE_ID_KO[key];
    if (key.includes("environment-tag")) return "필수 environment 태그 기준";
    if (key.includes("snapshot")) return "디스크 스냅샷 정책 기준";
    if (key.includes("zone-redundancy")) return "가용성 영역 이중화 기준";
    if (key.includes("ddos")) return "DDoS 보호 정책 기준";
    if (key.includes("public-access")) return "공용 접근 차단 기준";
    if (key.includes("tag")) return "리소스 태그 정책 기준";
    return s.replace(/[._-]+/g, " ");
  }

  function humanizeRemediationAction(raw) {
    const s = String(raw || "").trim();
    if (!s) return "";
    const key = s.toLowerCase();
    if (REMEDIATION_ACTION_KO[key]) return REMEDIATION_ACTION_KO[key];
    if (key.startsWith("remediate.")) {
      return key.slice("remediate.".length).replace(/[._-]+/g, " ") + " 조치";
    }
    return humanizeAction(s);
  }

  function humanizeLocalClock(isoOrMs) {
    if (isoOrMs == null || isoOrMs === "") return "--:--:--";
    const d = typeof isoOrMs === "number" ? new Date(isoOrMs) : new Date(String(isoOrMs));
    if (Number.isNaN(d.getTime())) return String(isoOrMs);
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  function humanizeSeverity(raw) {
    const k = String(raw || "").trim().toLowerCase();
    if (k === "critical" || k === "sev1" || k === "p0") return "긴급";
    if (k === "high" || k === "sev2" || k === "p1") return "높음";
    if (k === "medium" || k === "moderate" || k === "sev3" || k === "p2") return "보통";
    if (k === "low" || k === "sev4" || k === "p3") return "낮음";
    if (k === "info" || k === "informational") return "정보";
    return raw ? String(raw) : "미측정";
  }

  window.fdaiV4Humanize = {
    resourceType: humanizeResourceType,
    action: humanizeAction,
    remediationAction: humanizeRemediationAction,
    ruleId: humanizeRuleId,
    actor: humanizeActor,
    mode: humanizeMode,
    severity: humanizeSeverity,
    tableName: humanizeTableName,
    timestamp: humanizeTimestamp,
    localClock: humanizeLocalClock,
    eventSummary: humanizeEventSummary,
  };

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
      if (lbl) lbl.textContent = "실시간 동기화 일시정지";
      return;
    }
    if (!globalLastPulse) {
      pill.classList.remove("is-offline");
      if (lbl) lbl.textContent = "실시간 연결 확인 중";
      return;
    }
    const measured = globalLastPulse.measurement_status === "measured";
    pill.classList.toggle("is-offline", !measured);
    if (!measured) {
      if (lbl) lbl.textContent = "실시간 미연결";
      return;
    }
    const seq = globalLastPulse.audit_latest_seq || 0;
    const age = formatAgeKo(globalLastPulseRxAt);
    const delta = globalLastPulse.delta_audit || 0;
    const deltaTxt = delta > 0 ? (" · 새 기록 +" + delta + "건") : "";
    if (lbl) lbl.textContent = "실시간 연결됨" + deltaTxt + " · " + age;
    const lat = globalLastPulse.db_latency_ms != null ? (globalLastPulse.db_latency_ms + "ms") : "—";
    const resTotal = globalLastPulse.ontology_resources_total != null ? Number(globalLastPulse.ontology_resources_total).toLocaleString() : "—";
    const hil = globalLastPulse.hil_pending != null ? Number(globalLastPulse.hil_pending).toLocaleString() : "—";
    const rawTarget = (globalLastPulse.latest_event && globalLastPulse.latest_event.target) || "";
    const targetKo = rawTarget ? humanizeResourceType(rawTarget) : "운영 원장";
    pill.setAttribute("data-ut-title", "실시간 운영 원장 동기화 상태");
    pill.setAttribute(
      "data-ut-body",
      "관측 리소스 " + resTotal + "개 · 승인 대기 " + hil + "건 · 최근 관측: " + targetKo + " (기술 정보: 원장 #" + seq + ", DB 응답 " + lat + " · 클릭 시 일시정지/재개)"
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
            triggerShimmerClass(pill, "fdai-shimmer-pulse", 1150);
            setTimeout(() => { pill.classList.remove("is-beat"); }, 360);
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

  function triggerShimmerClass(el, cls, durationMs) {
    if (!el || !(el instanceof Element)) return;
    el.classList.remove("fdai-shimmer-border", "fdai-shimmer-bg", "fdai-shimmer-pulse");
    void el.offsetWidth;
    el.classList.add(cls);
    const ms = durationMs || 1200;
    if (el._fdaiShimmerTimer) clearTimeout(el._fdaiShimmerTimer);
    el._fdaiShimmerTimer = setTimeout(() => {
      el.classList.remove(cls);
      el._fdaiShimmerTimer = null;
    }, ms);
  }

  window.fdaiV4Shimmer = {
    border: (el, ms) => triggerShimmerClass(el, "fdai-shimmer-border", ms),
    bg: (el, ms) => triggerShimmerClass(el, "fdai-shimmer-bg", ms),
    pulse: (el, ms) => triggerShimmerClass(el, "fdai-shimmer-pulse", ms),
    markStreaming: (el, active) => {
      if (el && el instanceof Element) el.classList.toggle("fdai-live-streaming", Boolean(active));
    },
  };

  /* =========================================================================
     Global Bottom Ticker Bar (All Console v4 Pages)
     - 58+ curated & live-ledger messages, deduplicated across page transitions
     - Vertical slide-up every 5s, pause on hover/focus, compact recent-3 popover
     - Clickable links both inline and inside the hover popover
     ========================================================================= */
  const GLOBAL_TICKER_STATIC_CATALOG = [
    { id: "s01", priority: "highlight", badge: "실측 연동", tone: "live", text: "로컬 PostgreSQL 실측 원장과 직접 연동되었습니다. 미수집 필드는 0이나 예제 값으로 대체하지 않습니다." },
    { id: "s02", priority: "info", badge: "운영 원칙", tone: "live", text: "결정론 규칙(T0)으로 반복 이벤트를 우선 처리하고, 잔여 모호성만 근거 검증을 거쳐 AI(T1/T2)로 분석합니다.", href: "/governance/trust-routing", linkText: "신뢰 라우팅" },
    { id: "s03", priority: "info", badge: "안전 경계", tone: "sec", text: "모든 상태 변경은 명시적 사람 승인 또는 유효한 상시 위임 없이 실행되지 않으며, 침묵은 승인이 아닙니다.", href: "/operations/hil-queue", linkText: "승인 대기열" },
    { id: "s04", priority: "info", badge: "7대 안전장치", tone: "live", text: "모든 변경 조치에는 중단 조건·검증 롤백·영향 제한·사전 시뮬레이션·잠금·멱등키·2단계 감사가 적용됩니다.", href: "/overview/control-assurance", linkText: "안전 통제" },
    { id: "s05", priority: "info", badge: "관찰 우선", tone: "auto", text: "신규 자동화 기능은 관찰(Shadow) 모드로 시작하며, 승격 게이트 증거 또는 승인된 전환으로만 실행 단계에 진입합니다.", href: "/governance/promotion-gates", linkText: "승격 심사" },
    { id: "s06", priority: "info", badge: "역할 분리", tone: "human", text: "사람 승인자(Var)와 변경 실행자(Thor)의 정체성은 항상 분리 기록되어 단일 권한 오남용을 차단합니다.", href: "/agents/pantheon", linkText: "에이전트 구성" },
    { id: "s07", priority: "info", badge: "결과 검증", tone: "live", text: "API 호출 성공이나 요청 접수는 완료로 간주하지 않으며, 독립된 권위 관측으로 실제 효과를 검증합니다.", href: "/evidence/audit", linkText: "감사 원장" },
    { id: "s08", priority: "info", badge: "온톨로지", tone: "auto", text: "모든 리소스·관계·근거·조치는 표준 운영 온톨로지에 근거하며, 온톨로지는 의미를 검증하되 권한을 부여하지 않습니다.", href: "/governance/ontology", linkText: "온톨로지" },
    { id: "s09", priority: "info", badge: "인과 분리", tone: "sre", text: "시계열 상관관계와 원인은 엄격히 구분하며, 근거가 부족하거나 오래된 경우 추정 대신 보류·확인을 선택합니다.", href: "/evidence/rca", linkText: "원인 분석" },
    { id: "s10", priority: "info", badge: "시간축 안내", tone: "live", text: "대시보드 차트·툴팁·드로어 시각은 모두 브라우저 로컬 시간대 기준으로 통일되어 표시됩니다.", href: "/overview/dashboard", linkText: "대시보드" },
    { id: "s11", priority: "info", badge: "예측 영역", tone: "auto", text: "실측 예측 모델 결과가 없는 경우 미래(+5m) 예측 구간은 예제 점 없이 미측정 상태로 정직하게 비워둡니다." },
    { id: "s12", priority: "info", badge: "즉시 회수", tone: "sec", text: "이상 징후나 회귀가 감지되면 즉시 회수(Recall)와 자동 강등(Demotion)이 모든 운영자 예외보다 최우선 적용됩니다.", href: "/overview/control-assurance", linkText: "회수 현황" },
    { id: "s13", priority: "info", badge: "감사 무결성", tone: "live", text: "감사 원장은 추가 전용(Append-only) 해시 체인으로 기록되어 사후 변조 검증과 타임라인 재생을 지원합니다.", href: "/evidence/audit", linkText: "감사 원장" },
    { id: "s14", priority: "info", badge: "단축키 팁", tone: "auto", text: "어느 화면에서나 Ctrl+K(⌘K)로 전체 메뉴를 빠르게 검색하고 Ctrl+J로 AI 운영 채팅을 열 수 있습니다." },
    { id: "s15", priority: "info", badge: "링크 공유", tone: "auto", text: "카드·행·산점도 항목을 선택하면 주소창에 고유 ?item= URL이 반영되어 팀원에게 동일 상태를 바로 공유할 수 있습니다." },
    { id: "s16", priority: "info", badge: "Live / Sample", tone: "live", text: "상단 Live / Sample 토글로 실측 PostgreSQL 원장 화면과 교육용 예제 화면을 데이터 혼합 없이 전환할 수 있습니다." },
    { id: "s17", priority: "info", badge: "스코프 필터", tone: "auto", text: "구독·리소스 그룹 필터를 변경하면 대시보드 지표·관측 항목·시계열이 선택한 범위에 맞춰 즉시 재집계됩니다." },
    { id: "s18", priority: "info", badge: "영향 반경", tone: "sre", text: "변경 전 Blast Radius(영향 반경) 시뮬레이션으로 다운스트림 의존성과 동시 장애 위험을 사전에 확인하세요.", href: "/governance/blast-radius", linkText: "영향 반경" },
    { id: "s19", priority: "info", badge: "비용 거버넌스", tone: "auto", text: "미수집 과금·절감 지표는 0원으로 표시하지 않고 미측정으로 유지하며, 확인된 비용 항목만 집계합니다.", href: "/overview/cost-governance", linkText: "비용 거버넌스" },
    { id: "s20", priority: "info", badge: "AI 토큰 절감", tone: "live", text: "결정론 규칙(T0) 비중이 높을수록 AI 추론 비용과 응답 지연이 동시에 감소합니다. 모델별 호출 분포를 점검하세요.", href: "/overview/llm-cost", linkText: "AI 모델 비용" },
    { id: "s21", priority: "info", badge: "관측 신선도", tone: "auto", text: "Heimdall 관측 수집기는 리소스 상태의 유효 시각·수집 시각·기록 시각을 분리해 신선도 저하를 즉시 알립니다.", href: "/overview/dashboard-v2", linkText: "리소스 현황" },
    { id: "s22", priority: "info", badge: "보안 기준선", tone: "sec", text: "구성 드리프트와 보안 기준선 이탈 항목은 구성 기준선 화면에서 정책별 준수 상태와 근거를 함께 확인할 수 있습니다.", href: "/operations/configuration-baselines", linkText: "구성 기준선" },
    { id: "s23", priority: "info", badge: "취약점 위험", tone: "sec", text: "코드·컨테이너 취약점은 실제 노출 경로와 운영 중요도를 함께 평가해 우선순위를 산정합니다.", href: "/operations/vulnerability-risk", linkText: "취약점 위험" },
    { id: "s24", priority: "info", badge: "경보 품질", tone: "sre", text: "중복·노이즈 알림을 억제해 운영자에게 정말 확인이 필요한 신호만 전달합니다. 억제율은 경보 품질에서 확인하세요.", href: "/operations/alert-quality", linkText: "경보 품질" },
    { id: "s25", priority: "info", badge: "탐지 준비도", tone: "auto", text: "장애 시나리오별 탐지 규칙 커버리지와 미연결 텔레메트리 공백은 탐지 준비도 매트릭스에서 점검할 수 있습니다.", href: "/operations/detection-readiness", linkText: "탐지 준비도" },
    { id: "s26", priority: "info", badge: "에이전트 책임", tone: "human", text: "15개 고정 에이전트 역할마다 담당 운영자(Steward)가 지정되어 에스컬레이션과 인수인계 경로가 명확합니다.", href: "/agents/handover", linkText: "담당자 인수인계" },
    { id: "s27", priority: "info", badge: "이벤트 버스", tone: "auto", text: "권한이 수반되는 에이전트 협업은 직접 함수 호출 없이 스키마 검증된 이벤트 버스 pub/sub으로만 전달됩니다.", href: "/agents/agent-activity", linkText: "에이전트 활동" },
    { id: "s28", priority: "info", badge: "운영 성과", tone: "live", text: "자동 처리율·평균 인지 시간·안전 준수 추이는 운영 성과 화면에서 기간별로 비교할 수 있습니다.", href: "/overview/operating-outcomes", linkText: "운영 성과" },
    { id: "s29", priority: "info", badge: "영역별 현황", tone: "auto", text: "복원력(SRE)·변경 안전·비용 거버넌스·보안 4개 영역의 통합 상태는 영역별 현황에서 한눈에 확인할 수 있습니다.", href: "/overview/verticals", linkText: "영역별 현황" },
    { id: "s30", priority: "info", badge: "어드바이저", tone: "live", text: "Well-Architected 5대 축(안정성·보안·비용·운영·성능) 기반 개선 권고사항을 어드바이저 허브에서 검토하세요.", href: "/advisor/overview", linkText: "어드바이저" },
    { id: "s31", priority: "info", badge: "규칙 카탈로그", tone: "auto", text: "모든 정책 규칙은 조건·위험 등급·롤백 경로와 함께 버전 관리되며 규칙 카탈로그에서 즉시 조회할 수 있습니다.", href: "/governance/rules", linkText: "규칙 카탈로그" },
    { id: "s32", priority: "info", badge: "아키텍처 맵", tone: "auto", text: "서비스 간 의존 관계와 네트워크·데이터 계층 토폴로지는 아키텍처 맵에서 확대·탐색할 수 있습니다.", href: "/governance/architecture", linkText: "아키텍처 맵" },
    { id: "s33", priority: "info", badge: "스코프 경계", tone: "sec", text: "허용된 구독·리소스 그룹 경계 밖의 리소스는 읽기·변경 대상에서 자동 차단됩니다.", href: "/governance/scope", linkText: "스코프 설정" },
    { id: "s34", priority: "info", badge: "승인 만료 정책", tone: "human", text: "응답 기한이 지난 승인 요청은 자동 실행되지 않고 만료 처리되어 안전하게 종료됩니다.", href: "/operations/hil-queue", linkText: "승인 대기열" },
    { id: "s35", priority: "info", badge: "실시간 펄스", tone: "live", text: "상단 실시간 연결 배지를 클릭하면 SSE 실시간 동기화를 일시정지하거나 즉시 재개할 수 있습니다." },
    { id: "s36", priority: "info", badge: "심각도 기준", tone: "auto", text: "산점도 Y축은 임의 합성 점수가 아닌 실제 심각도 등급(관측·낮음·보통·높음·긴급)을 그대로 반영합니다." },
    { id: "s37", priority: "info", badge: "추적 로그", tone: "auto", text: "특정 사건의 제어 루프 전체 단계와 지연 분포는 분산 추적(Trace) 화면에서 구간별로 확인할 수 있습니다.", href: "/evidence/trace", linkText: "분산 추적" },
    { id: "s38", priority: "info", badge: "보고서 내보내기", tone: "auto", text: "경영진 요약 및 감사 제출용 증적 리포트는 보고서 화면에서 기간별로 생성할 수 있습니다.", href: "/evidence/reports", linkText: "보고서" },
    { id: "s39", priority: "info", badge: "워크플로 점검", tone: "auto", text: "승인 후 실행되는 자동화 워크플로와 사전 드라이런 결과는 워크플로 빌더에서 검증할 수 있습니다.", href: "/governance/workflow-builder", linkText: "워크플로" },
    { id: "s40", priority: "info", badge: "지식 베이스", tone: "auto", text: "런북·장애 대응 절차·아키텍처 문서는 지식 베이스에 인덱싱되어 원인 분석 시 근거로 인용됩니다.", href: "/governance/knowledge", linkText: "지식 베이스" },
    { id: "s41", priority: "info", badge: "대화 검색", tone: "auto", text: "과거 운영자 질의와 AI 판단 근거, 인용된 감사 원장 기록은 대화 검색 화면에서 다시 조회할 수 있습니다.", href: "/evidence/conversation-search", linkText: "대화 검색" },
    { id: "s42", priority: "info", badge: "스케줄러", tone: "auto", text: "주기적 인벤토리 동기화·기준선 점검·비용 집계 작업의 실행 상태는 스케줄러 실행 이력에서 확인하세요.", href: "/operations/scheduler-runs", linkText: "스케줄러 이력" },
    { id: "s43", priority: "info", badge: "백그라운드 작업", tone: "auto", text: "장기 실행되는 수집·분석·검증 파이프라인의 진행 상황과 실패 재시도 내역을 한곳에서 모니터링합니다.", href: "/operations/background-tasks", linkText: "백그라운드 작업" },
    { id: "s44", priority: "info", badge: "비밀 보호", tone: "sec", text: "자격 증명·토큰·고객 식별 정보는 콘솔 화면·로그·티커·채팅 출력에서 자동으로 제외됩니다." },
  ];

  const globalTickerEngine = (() => {
    const STORAGE_KEY = "fdai_v4_ticker_state_v1";
    const CACHE_KEY = "fdai_v4_ticker_dash_cache_v1";
    const TICKER_INTERVAL_MS = 5000;
    const PRIORITY_RANK = { critical: 0, warn: 1, highlight: 2, info: 3 };

    const seenIds = new Set();
    const priorityQueue = [];
    let recentHistory = [];
    let catalogCursor = 0;
    let currentMsg = null;
    let shownCount = 0;
    let totalPoolSize = GLOBAL_TICKER_STATIC_CATALOG.length + 14;
    let rotateTimer = null;
    let isHoverPaused = false;
    let mountedBar = null;
    let initialized = false;
    let dashboardIngested = false;

    function safeHref(url) {
      if (!url || typeof url !== "string") return "";
      const t = url.trim();
      if (t.startsWith("/") && !t.startsWith("//")) return t;
      return "";
    }

    function loadPersistedState() {
      try {
        const raw = window.sessionStorage.getItem(STORAGE_KEY);
        if (!raw) return;
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed.seenIds)) {
          parsed.seenIds.slice(-120).forEach((id) => {
            if (typeof id === "string" && id && id !== "boot:init") seenIds.add(id);
          });
        }
        if (Array.isArray(parsed.recentHistory)) {
          recentHistory = parsed.recentHistory
            .filter((it) => it && typeof it.id === "string" && typeof it.text === "string")
            .slice(0, 3);
        }
        if (typeof parsed.catalogCursor === "number" && Number.isFinite(parsed.catalogCursor)) {
          catalogCursor = Math.max(0, parsed.catalogCursor % GLOBAL_TICKER_STATIC_CATALOG.length);
        }
      } catch (_e) {}
    }

    function persistState() {
      try {
        window.sessionStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({
            seenIds: Array.from(seenIds).slice(-120),
            recentHistory: recentHistory.slice(0, 3),
            catalogCursor,
          })
        );
      } catch (_e) {}
    }

    function toneClassFor(msg) {
      if (msg.badgeClass) return msg.badgeClass;
      if (msg.tone === "sec" || msg.priority === "critical") return "cs-badge tone-sec";
      if (msg.tone === "sre" || msg.priority === "warn") return "cs-badge tone-sre";
      if (msg.tone === "human") return "cs-badge tone-human";
      if (msg.tone === "live" || msg.priority === "highlight") return "cs-badge tone-live";
      return "cs-badge";
    }

    function setBadge(el, cls, label) {
      if (!el) return;
      el.className = cls;
      const dot = document.createElement("span");
      dot.className = "cs-dot";
      el.replaceChildren(dot, document.createTextNode(label || "운영 안내"));
    }

    function buildTickerShell(hostEl) {
      hostEl.classList.add("principle-bar", "fdai-global-ticker");
      hostEl.setAttribute("role", "note");
      hostEl.setAttribute("aria-label", "실측 연동 상태 및 운영 안내 티커");

      const badge = document.createElement("span");
      badge.className = "cs-badge tone-live fdai-ticker-badge";
      badge.id = hostEl.id === "ovBottomTickerBar" ? "ovBottomTickerBadge" : "fdaiGlobalTickerBadge";
      badge.dataset.tickerRole = "badge";
      setBadge(badge, "cs-badge tone-live fdai-ticker-badge", "실측 안내");

      const viewport = document.createElement("div");
      viewport.className = "fdai-ticker-viewport";
      viewport.tabIndex = 0;
      viewport.setAttribute("aria-label", "운영 안내 티커 (마우스를 올리면 최근 3건 표시 및 일시정지)");

      const track = document.createElement("div");
      track.className = "fdai-ticker-track";
      track.id = hostEl.id === "ovBottomTickerBar" ? "ovBottomTickerTrack" : "fdaiGlobalTickerTrack";
      track.dataset.tickerRole = "track";

      const item = document.createElement("span");
      item.className = "fdai-ticker-item";
      item.id = hostEl.id === "ovBottomTickerBar" ? "ovLiveStateText" : "fdaiGlobalTickerText";
      item.dataset.tickerRole = "text";
      item.textContent = "실시간 운영 원장에서 관측 상태를 확인하고 있습니다.";

      track.appendChild(item);
      viewport.appendChild(track);

      const right = document.createElement("span");
      right.className = "fdai-ticker-right";

      const counter = document.createElement("span");
      counter.className = "fdai-ticker-count";
      counter.id = hostEl.id === "ovBottomTickerBar" ? "ovBottomTickerCounter" : "fdaiGlobalTickerCounter";
      counter.dataset.tickerRole = "counter";
      counter.textContent = `1 / ${totalPoolSize}`;

      const nextBtn = document.createElement("button");
      nextBtn.type = "button";
      nextBtn.className = "fdai-ticker-next";
      nextBtn.id = hostEl.id === "ovBottomTickerBar" ? "ovBottomTickerNextBtn" : "fdaiGlobalTickerNextBtn";
      nextBtn.dataset.tickerRole = "next";
      nextBtn.setAttribute("aria-label", "다음 운영 안내 메시지 보기");
      nextBtn.textContent = "다음";

      right.append(counter, nextBtn);

      const popover = document.createElement("div");
      popover.className = "fdai-ticker-popover";
      popover.id = hostEl.id === "ovBottomTickerBar" ? "ovBottomTickerPopover" : "fdaiGlobalTickerPopover";
      popover.dataset.tickerRole = "popover";
      popover.setAttribute("role", "region");
      popover.setAttribute("aria-label", "최근 운영 안내 3건");

      const popHead = document.createElement("div");
      popHead.className = "fdai-ticker-pop-head";
      const popTitle = document.createElement("span");
      popTitle.textContent = "최근 안내 (3건)";
      const popHint = document.createElement("span");
      popHint.textContent = "클릭 이동 · 호버 일시정지";
      popHead.append(popTitle, popHint);

      const popList = document.createElement("div");
      popList.className = "fdai-ticker-pop-list";
      popList.id = hostEl.id === "ovBottomTickerBar" ? "ovBottomTickerHistoryList" : "fdaiGlobalTickerHistoryList";
      popList.dataset.tickerRole = "history";

      popover.append(popHead, popList);
      hostEl.replaceChildren(badge, viewport, right, popover);
      return hostEl;
    }

    function ensureFallbackStyles() {
      if (document.querySelector('link[href*="fdai-console-shared.css"]')) return;
      if (document.getElementById("fdaiTickerFallbackStyle")) return;
      const st = document.createElement("style");
      st.id = "fdaiTickerFallbackStyle";
      st.textContent = [
        ".fdai-global-ticker{position:relative;display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:10px;padding:8px 16px;margin-top:16px;border-top:1px solid var(--line,#e5e7eb);background:var(--surface,#fff);font-size:12px;color:var(--text-soft,#4b5563);overflow:visible;z-index:25;}",
        ".fdai-ticker-viewport{overflow:hidden;min-width:0;min-height:22px;display:flex;align-items:center;}",
        ".fdai-ticker-track{display:flex;align-items:center;min-width:0;width:100%;}",
        ".fdai-ticker-item{display:inline-flex;align-items:center;gap:8px;min-width:0;max-width:100%;}",
        ".fdai-ticker-text{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;}",
        ".fdai-ticker-right{display:inline-flex;align-items:center;gap:6px;white-space:nowrap;}",
        ".fdai-ticker-next{border:1px solid var(--line,#d1d5db);background:transparent;color:inherit;border-radius:999px;padding:2px 8px;font-size:12px;cursor:pointer;}",
        ".fdai-ticker-popover{position:absolute;left:0;bottom:calc(100% + 6px);width:min(540px,calc(100vw - 40px));padding:6px 8px;border:1px solid var(--line,#d1d5db);border-radius:8px;background:var(--surface,#fff);box-shadow:0 8px 20px rgba(15,23,42,.13);display:grid;gap:4px;opacity:0;transform:translateY(4px);pointer-events:none;transition:opacity .14s ease,transform .14s ease;z-index:65;}",
        ".fdai-ticker-popover::after{content:'';position:absolute;left:0;right:0;top:100%;height:10px;}",
        ".fdai-global-ticker:hover .fdai-ticker-popover,.fdai-global-ticker:focus-within .fdai-ticker-popover{opacity:1;transform:translateY(0);pointer-events:auto;}",
        ".fdai-ticker-pop-head{display:flex;justify-content:space-between;font-size:12px;font-weight:600;}",
        ".fdai-ticker-pop-list{display:grid;gap:3px;}",
        ".fdai-ticker-pop-item{display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:7px;padding:4px 7px;border:1px solid var(--line,#e5e7eb);border-radius:6px;text-decoration:none;color:inherit;font-size:12px;}",
        ".fdai-ticker-pop-text{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0;}",
        ".fdai-ticker-pop-item:hover .fdai-ticker-pop-text{white-space:normal;}",
      ].join("");
      document.head.appendChild(st);
    }

    function ensureMountedBar() {
      if (mountedBar && document.body.contains(mountedBar)) return mountedBar;
      ensureFallbackStyles();
      let target = document.getElementById("ovBottomTickerBar");
      if (!target) {
        const candidates = Array.from(document.querySelectorAll("#fdaiMain .principle-bar, .content-wrap > .principle-bar, #fdaiMain .footer-note, .content-wrap > .footer-note"));
        target = candidates.find((el) => !el.closest("[hidden]")) || candidates[0] || null;
      }
      if (!target) {
        const container = document.querySelector("#fdaiMain > .content-wrap") || document.getElementById("fdaiMain") || document.querySelector("main");
        if (!container) return null;
        target = document.createElement("div");
        target.id = "fdaiGlobalTickerBar";
        container.appendChild(target);
      }
      buildTickerShell(target);
      mountedBar = target;

      const pause = () => {
        isHoverPaused = true;
        if (rotateTimer) {
          window.clearTimeout(rotateTimer);
          rotateTimer = null;
        }
      };
      const resume = () => {
        isHoverPaused = false;
        scheduleNext();
      };
      target.addEventListener("mouseenter", pause);
      target.addEventListener("mouseleave", resume);
      target.addEventListener("focusin", pause);
      target.addEventListener("focusout", (ev) => {
        if (!target.contains(ev.relatedTarget)) resume();
      });
      const nextBtn = target.querySelector('[data-ticker-role="next"]');
      if (nextBtn) {
        nextBtn.addEventListener("click", () => {
          playNext();
        });
      }
      return mountedBar;
    }

    function scheduleNext() {
      if (rotateTimer) {
        window.clearTimeout(rotateTimer);
        rotateTimer = null;
      }
      if (isHoverPaused) return;
      rotateTimer = window.setTimeout(() => {
        rotateTimer = null;
        if (!isHoverPaused) playNext();
      }, TICKER_INTERVAL_MS);
    }

    function renderHistoryPopover() {
      const bar = ensureMountedBar();
      if (!bar) return;
      const list = bar.querySelector('[data-ticker-role="history"]');
      if (!list) return;
      const frag = document.createDocumentFragment();
      recentHistory.slice(0, 3).forEach((item, idx) => {
        const href = safeHref(item.href);
        const row = document.createElement(href ? "a" : "div");
        row.className = "fdai-ticker-pop-item";
        if (href) row.href = href;
        row.title = item.text;

        const bdg = document.createElement("span");
        setBadge(bdg, toneClassFor(item), item.badge || "운영 안내");

        const txt = document.createElement("span");
        txt.className = "fdai-ticker-pop-text"
          + (item.priority === "critical" ? " is-critical" : item.priority === "warn" ? " is-warn" : item.priority === "highlight" ? " is-highlight" : "");
        txt.textContent = item.text;

        const rightMeta = document.createElement("span");
        rightMeta.className = "fdai-ticker-pop-action";
        rightMeta.textContent = href ? `${item.linkText || "열기"} →` : (idx === 0 ? "현재" : (item.shownAt || ""));

        row.append(bdg, txt, rightMeta);
        frag.appendChild(row);
      });
      list.replaceChildren(frag);
    }

    function renderMessage(msg, recordSeen) {
      const bar = ensureMountedBar();
      if (!bar || !msg) return;
      currentMsg = msg;
      if (recordSeen !== false && msg.id && msg.id !== "boot:init") {
        seenIds.add(msg.id);
        const existingIdx = recentHistory.findIndex((h) => h.id === msg.id);
        if (existingIdx >= 0) recentHistory.splice(existingIdx, 1);
        recentHistory.unshift(Object.assign({}, msg, { shownAt: humanizeLocalClock(Date.now()) }));
        if (recentHistory.length > 3) recentHistory.length = 3;
        persistState();
      }
      shownCount = Math.min(totalPoolSize, Math.max(1, seenIds.size));
      renderHistoryPopover();

      const badge = bar.querySelector('[data-ticker-role="badge"]');
      const track = bar.querySelector('[data-ticker-role="track"]');
      const textEl = bar.querySelector('[data-ticker-role="text"]');
      const counter = bar.querySelector('[data-ticker-role="counter"]');

      if (badge) setBadge(badge, `${toneClassFor(msg)} fdai-ticker-badge`, msg.badge || "운영 안내");
      if (counter) counter.textContent = `${shownCount} / ${Math.max(totalPoolSize, shownCount)}`;
      if (textEl) {
        textEl.className = "fdai-ticker-item"
          + (msg.priority === "critical" ? " is-critical" : msg.priority === "warn" ? " is-warn" : msg.priority === "highlight" ? " is-highlight" : "");
        const txtSpan = document.createElement("span");
        txtSpan.className = "fdai-ticker-text";
        txtSpan.textContent = msg.text;
        textEl.replaceChildren(txtSpan);
        const href = safeHref(msg.href);
        if (href && msg.linkText) {
          const a = document.createElement("a");
          a.className = "fdai-ticker-link";
          a.href = href;
          a.textContent = `${msg.linkText} →`;
          textEl.appendChild(a);
        }
      }
      if (msg.priority === "critical") triggerShimmerClass(bar, "fdai-shimmer-pulse", 1150);
      else if (msg.priority === "warn" || msg.priority === "highlight") triggerShimmerClass(bar, "fdai-shimmer-border", 1050);

      if (track) {
        track.classList.remove("is-entering");
        void track.offsetWidth;
        track.classList.add("is-entering");
      }
      scheduleNext();
    }

    function enqueue(msg, interruptIfInfo) {
      if (!msg || !msg.id || !msg.text) return;
      if (seenIds.has(msg.id)) return;
      if (priorityQueue.some((q) => q.id === msg.id)) return;
      priorityQueue.push(msg);
      priorityQueue.sort((a, b) => (PRIORITY_RANK[a.priority] ?? 3) - (PRIORITY_RANK[b.priority] ?? 3));
      if (interruptIfInfo && !isHoverPaused && (!currentMsg || currentMsg.priority === "info" || currentMsg.id === "boot:init")) {
        playNext();
      }
    }

    function pullNextMessage() {
      while (priorityQueue.length) {
        const candidate = priorityQueue.shift();
        if (!seenIds.has(candidate.id)) return candidate;
      }
      const staticLen = GLOBAL_TICKER_STATIC_CATALOG.length;
      for (let tries = 0; tries < staticLen; tries += 1) {
        const item = GLOBAL_TICKER_STATIC_CATALOG[(catalogCursor + tries) % staticLen];
        if (!seenIds.has(item.id)) {
          catalogCursor = (catalogCursor + tries + 1) % staticLen;
          return item;
        }
      }
      GLOBAL_TICKER_STATIC_CATALOG.forEach((it) => seenIds.delete(it.id));
      catalogCursor = 0;
      return GLOBAL_TICKER_STATIC_CATALOG[0];
    }

    function playNext() {
      const next = pullNextMessage();
      if (next) renderMessage(next, true);
    }

    function fmtNum(v) {
      return typeof v === "number" && Number.isFinite(v) ? v.toLocaleString("ko-KR") : "미측정";
    }

    function ingestDashboardData(data) {
      if (!data) return;
      dashboardIngested = true;
      const activeMode = document.querySelector("[data-data-mode].is-active");
      if (activeMode && activeMode.getAttribute("data-data-mode") === "sample") return;

      const sig = data.signals || {};
      const posture = data.posture || {};
      const routing = data.routing || {};
      const byTier = routing.by_tier || {};
      const policyEsc = Number(posture.policy_escape_count || 0);
      const dynamicMsgs = [];

      if (policyEsc > 0) {
        dynamicMsgs.push({
          id: `live:policy-escape:${policyEsc}`,
          priority: "critical",
          badge: "긴급 · 정책 위반",
          tone: "sec",
          text: `안전 정책 위반 ${policyEsc}건이 감지되었습니다. 즉시 안전 통제 현황에서 회수(Recall) 및 감사 원장을 확인하세요.`,
          href: "/overview/control-assurance",
          linkText: "안전 통제",
        });
      } else if (typeof posture.event_count === "number") {
        dynamicMsgs.push({
          id: `live:policy-zero:${posture.event_count}`,
          priority: "highlight",
          badge: "안전 유지",
          tone: "live",
          text: `감사 원장 ${posture.event_count.toLocaleString()}건 전수 대조 결과 안전 정책 위반 0건 불변식이 정상 유지되고 있습니다.`,
          href: "/overview/control-assurance",
          linkText: "안전 통제",
        });
      }
      if (typeof sig.hil_pending_estimate === "number" && sig.hil_pending_estimate > 0) {
        dynamicMsgs.push({
          id: `live:hil-pending:${sig.hil_pending_estimate}`,
          priority: "warn",
          badge: "승인 필요",
          tone: "human",
          text: `운영자 확인이 필요한 사람 승인 요청 ${sig.hil_pending_estimate}건이 대기 중입니다. 승인 대기열에서 변경 내용을 검토하세요.`,
          href: "/operations/hil-queue",
          linkText: "승인 대기열",
        });
      }
      if (typeof sig.hil_expired === "number" && sig.hil_expired > 0) {
        dynamicMsgs.push({
          id: `live:hil-expired:${sig.hil_expired}`,
          priority: "warn",
          badge: "승인 만료",
          tone: "sre",
          text: `응답 시간 만료된 승인 요청이 누적 ${sig.hil_expired}건 있습니다. 반복 규칙은 자동화 승격 심사를 검토하세요.`,
          href: "/governance/promotion-gates",
          linkText: "승격 심사",
        });
      }
      if (typeof sig.open_incidents === "number" && sig.open_incidents > 0) {
        const latestInc = Array.isArray(data.incidents) && data.incidents[0];
        const incId = latestInc && latestInc.id ? String(latestInc.id) : "";
        dynamicMsgs.push({
          id: `live:open-incidents:${sig.open_incidents}:${incId}`,
          priority: "warn",
          badge: "진행 인시던트",
          tone: "sre",
          text: `진행 중인 운영 인시던트 ${sig.open_incidents}건이 추적 중입니다. 원인 분석과 최근 영향 범위를 확인하세요.`,
          href: incId && window.fdaiV4Selection ? window.fdaiV4Selection.buildItemUrl("incidents", incId) : "/operations/incidents",
          linkText: "인시던트",
        });
      }
      if (typeof sig.code_security_findings === "number" && sig.code_security_findings > 0) {
        dynamicMsgs.push({
          id: `live:code-sec:${sig.code_security_findings}`,
          priority: "warn",
          badge: "보안 경고",
          tone: "sec",
          text: `코드 보안 스캔에서 취약점 이슈 ${sig.code_security_findings.toLocaleString()}건이 검출되었습니다. 치명·높음 항목을 우선 분류하세요.`,
          href: "/operations/code-security",
          linkText: "보안 취약점",
        });
      }
      if (typeof data.uncollected_resource_count === "number" && data.uncollected_resource_count > 0) {
        dynamicMsgs.push({
          id: `live:uncollected:${data.uncollected_resource_count}`,
          priority: "highlight",
          badge: "미수집 분리",
          tone: "sre",
          text: `상태 미수집 리소스 ${data.uncollected_resource_count.toLocaleString()}개는 정상이나 0으로 합산하지 않고 별도 분리했습니다.`,
          href: "/overview/dashboard-v2",
          linkText: "리소스 현황",
        });
      }
      if (typeof data.resource_count === "number") {
        const cov = typeof data.coverage_pct === "number" ? `${data.coverage_pct.toFixed(1)}%` : "미측정";
        dynamicMsgs.push({
          id: `live:inventory:${data.resource_count}:${cov}`,
          priority: "info",
          badge: "관측 현황",
          tone: "live",
          text: `전체 온톨로지 ${data.resource_count.toLocaleString()}개(Azure ${fmtNum(data.azure_resource_count)}개 · 관계 ${fmtNum(data.relationship_count)}개)를 커버리지 ${cov}로 상시 관측 중입니다.`,
          href: "/overview/dashboard-v2",
          linkText: "리소스 현황",
        });
      }
      if (typeof posture.shadow_ratio_pct === "number") {
        dynamicMsgs.push({
          id: `live:posture:${posture.shadow_ratio_pct}:${posture.enforced_ratio_pct}`,
          priority: "info",
          badge: "자율 경계",
          tone: "auto",
          text: `현재 제어 자세는 관찰(Shadow) ${posture.shadow_ratio_pct}% · 실행(Enforced) ${posture.enforced_ratio_pct ?? 0}%입니다.`,
          href: "/overview/control-assurance",
          linkText: "안전 통제",
        });
      }
      if (typeof byTier.T0 === "number" || typeof byTier.T1 === "number") {
        const t0 = Number(byTier.T0 || 0);
        const t1 = Number(byTier.T1 || 0);
        const t2 = Number(byTier.T2 || 0);
        const total = t0 + t1 + t2;
        const t0Pct = total > 0 ? ((t0 / total) * 100).toFixed(1) : "0.0";
        dynamicMsgs.push({
          id: `live:tier:${t0}:${t1}:${t2}`,
          priority: "highlight",
          badge: "AI 비용 절감",
          tone: "live",
          text: `결정론 T0 규칙 ${t0}건(${t0Pct}%)을 토큰 0으로 처리했고, T1 경량 ${t1}건 · T2 심층 ${t2}건만 선별 호출했습니다.`,
          href: "/overview/llm-cost",
          linkText: "AI 모델 비용",
        });
      }
      if (typeof data.active_rules_count === "number") {
        dynamicMsgs.push({
          id: `live:rules:${data.active_rules_count}`,
          priority: "info",
          badge: "운영 규칙",
          tone: "auto",
          text: `활성 운영 규칙 ${data.active_rules_count.toLocaleString()}개가 상시 평가 중이며, 위험 관문 평가 ${fmtNum(sig.risk_gate_evaluations)}건이 기록되었습니다.`,
          href: "/governance/rules",
          linkText: "규칙 카탈로그",
        });
      }
      if (data.timeline_meta && data.timeline_meta.anchor_at && data.timeline_meta.has_recent_events === false) {
        dynamicMsgs.push({
          id: `live:quiet-window:${data.timeline_meta.anchor_at}`,
          priority: "info",
          badge: "실시간 감시",
          tone: "live",
          text: `최근 15분 신규 이상 이벤트 없이 정상 감시 중입니다. 마지막 원장 기록은 ${humanizeTimestamp(data.timeline_meta.anchor_at)}입니다.`,
          href: "/overview/dashboard",
          linkText: "대시보드",
        });
      }
      if (posture.audit_sample && typeof posture.audit_sample.row_count === "number") {
        dynamicMsgs.push({
          id: `live:audit-sample:${posture.audit_sample.row_count}`,
          priority: "info",
          badge: "원장 무결성",
          tone: "live",
          text: `추가 전용 감사 원장 ${posture.audit_sample.row_count.toLocaleString()}건이 연속 해시 체인으로 기록되어 사후 변조 없이 검증 가능합니다.`,
          href: "/evidence/audit",
          linkText: "감사 원장",
        });
      }

      totalPoolSize = GLOBAL_TICKER_STATIC_CATALOG.length + dynamicMsgs.length;
      dynamicMsgs.forEach((m) => enqueue(m, false));
      if (!currentMsg || currentMsg.id === "boot:init") {
        playNext();
      } else {
        const bar = ensureMountedBar();
        const counter = bar && bar.querySelector('[data-ticker-role="counter"]');
        if (counter) counter.textContent = `${shownCount} / ${Math.max(totalPoolSize, shownCount)}`;
      }
    }

    function pushRealtimeEvent(evSum, seqNum) {
      if (!evSum || !evSum.title) return;
      const actorTxt = evSum.actorKo ? evSum.actorKo.replace(/\s*\(([^)]+)\)/g, " · $1") : "운영 엔진";
      enqueue({
        id: `live:rt:${seqNum || Date.now()}`,
        priority: "highlight",
        badge: "새 기록 감지",
        tone: "live",
        text: `실시간 새 이벤트 감지: ${evSum.title} (${actorTxt})`,
        href: seqNum && window.fdaiV4Selection ? window.fdaiV4Selection.buildItemUrl("audit", `audit:${seqNum}`) : "/evidence/audit",
        linkText: "감사 원장",
      }, true);
    }

    async function hydrateFromBackgroundDashboard() {
      if (dashboardIngested) return;
      const activeMode = document.querySelector("[data-data-mode].is-active");
      if (activeMode && activeMode.getAttribute("data-data-mode") === "sample") return;
      try {
        const cachedRaw = window.sessionStorage.getItem(CACHE_KEY);
        if (cachedRaw) {
          const cached = JSON.parse(cachedRaw);
          if (cached && cached.ts && (Date.now() - cached.ts) < 30000 && cached.data) {
            ingestDashboardData(cached.data);
            return;
          }
        }
      } catch (_e) {}
      try {
        const data = await fetchJsonSafe("/api/v4/overview/dashboard?subscription=all&window=15m");
        if (data && data.measurement_status !== "error") {
          try {
            window.sessionStorage.setItem(CACHE_KEY, JSON.stringify({ ts: Date.now(), data }));
          } catch (_e) {}
          if (!dashboardIngested) ingestDashboardData(data);
        }
      } catch (_err) {}
    }

    function init() {
      if (initialized) return;
      initialized = true;
      loadPersistedState();
      const bar = ensureMountedBar();
      if (!bar) return;

      if (recentHistory.length > 0) {
        renderMessage(recentHistory[0], false);
      } else {
        playNext();
      }

      window.addEventListener("fdai:live-pulse", (ev) => {
        const p = ev && ev.detail;
        if (!p || p.measurement_status !== "measured") return;
        if ((p.delta_audit || 0) > 0 && p.latest_event) {
          const evSum = humanizeEventSummary(p.latest_event);
          pushRealtimeEvent(evSum, p.latest_event.seq || p.audit_latest_seq);
        }
      });

      window.setTimeout(() => {
        if (!dashboardIngested) hydrateFromBackgroundDashboard();
      }, 750);
    }

    return {
      init,
      enqueue,
      ingestDashboardData,
      pushRealtimeEvent,
      playNext,
      getCatalogSize: () => totalPoolSize,
    };
  })();

  window.fdaiV4Ticker = globalTickerEngine;

  function bootGlobalLiveSubscriptions() {
    hydrateGlobalSubscriptionSelects().catch(() => {});
    startGlobalLivePulse();
    globalTickerEngine.init();
    document.addEventListener("click", (ev) => {
      const btn = ev.target && ev.target.closest ? ev.target.closest("[data-data-mode]") : null;
      if (btn) {
        setTimeout(() => {
          hydrateGlobalSubscriptionSelects().catch(() => {});
          startGlobalLivePulse();
        }, 40);
      }
    });
    window.addEventListener("fdai:data-mode-change", () => {
      hydrateGlobalSubscriptionSelects().catch(() => {});
      startGlobalLivePulse();
    });
    window.addEventListener("beforeunload", stopGlobalLivePulse);
    window.addEventListener("pagehide", stopGlobalLivePulse);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootGlobalLiveSubscriptions);
  } else {
    bootGlobalLiveSubscriptions();
  }

  window.fdaiV4Live = {
    bootstrap: boot,
    panelContracts: PANEL_CONTRACTS,
    humanize: window.fdaiV4Humanize,
    shimmer: window.fdaiV4Shimmer,
    ticker: window.fdaiV4Ticker,
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
