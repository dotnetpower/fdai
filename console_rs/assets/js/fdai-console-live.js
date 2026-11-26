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

  window.fdaiV4Humanize = {
    resourceType: humanizeResourceType,
    action: humanizeAction,
    actor: humanizeActor,
    mode: humanizeMode,
    tableName: humanizeTableName,
    timestamp: humanizeTimestamp,
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
