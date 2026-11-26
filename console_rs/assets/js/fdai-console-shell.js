(function () {
  "use strict";

  const ICONS = {
    chat: `<svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 016.5 3h7A2.5 2.5 0 0116 5.5v5A2.5 2.5 0 0113.5 13H9l-3.5 3v-3H6.5A2.5 2.5 0 014 10.5v-5z"/></svg>`,
    theme: `<svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><circle cx="10" cy="10" r="6"/><path d="M10 4v12a6 6 0 000-12z" fill="currentColor"/></svg>`,
    menu: `<svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M3 5h14M3 10h14M3 15h14"/></svg>`,
    pin: `<svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true"><path d="M7 3h6l-1 5 3 3H5l3-3-1-5zm3 8v6"/></svg>`,
    history: `<svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 10a6.5 6.5 0 101.8-4.5L3.5 7.2"/><path d="M3.5 3.8v3.4h3.4"/><path d="M10 6.8v3.4l2.3 1.4"/></svg>`,
    panelRight: `<svg width="15" height="15" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.5" y="3.5" width="15" height="13" rx="2"/><path d="M12.5 3.5v13"/></svg>`,
    close: `<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M3 3l8 8M11 3l-8 8"/></svg>`,
    expand: `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M10 2h4v4M6 14H2v-4M14 2l-4.5 4.5M2 14l4.5-4.5"/></svg>`,
    dock: `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><rect x="2" y="2.5" width="12" height="11" rx="1.5"/><path d="M9.5 2.5v11"/></svg>`,
    settings: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09a1.65 1.65 0 00-1-1.51 1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 110-4h.09a1.65 1.65 0 001.51-1 1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9c.26.6.85 1 1.51 1H21a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>`,
    labs: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 3h6M10 3v5.5L4.8 18.2A2 2 0 006.5 21h11a2 2 0 001.7-2.8L14 8.5V3"/><path d="M7.5 15h9"/></svg>`,
    external: `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9.5 2.5h4v4M13.5 2.5L7 9M6.5 3.5H3.5a1 1 0 00-1 1v8a1 1 0 001 1h8a1 1 0 001-1v-3"/></svg>`,
    clip: `<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><path d="M13 7.5l-5.6 5.6a3 3 0 01-4.2-4.2l6.2-6.2a2 2 0 012.8 2.8L6 11.7a1 1 0 01-1.4-1.4l5.2-5.2"/></svg>`
  };

  const NAV_DOMAINS = [
    {
      id: "overview", label: "전체 현황", file: "/overview", icon: "M3 13h4v6H3zm6-5h4v11H9zm6-5h4v16h-4z",
      items: [
        { id: "dashboard", label: "대시보드" },
        { id: "dashboard-v2", label: "리소스 현황", sub: true },
        { id: "operating-outcomes", label: "운영 성과" },
        { id: "control-assurance", label: "안전 통제 현황", sub: true },
        { id: "verticals", label: "영역별 성과", sub: true },
        { id: "cost-governance", label: "비용 거버넌스" },
        { id: "llm-cost", label: "AI 모델 비용", sub: true }
      ]
    },
    {
      id: "operations", label: "운영", file: "/operations", icon: "M13 2L4 14h6l-1 8 9-12h-6z",
      items: [
        { id: "live", label: "실시간 모니터링" },
        { id: "gpu", label: "GPU 현황", sub: true },
        { id: "incidents", label: "장애 대응" },
        { id: "code-security", label: "코드 보안" },
        { id: "vulnerability-risk", label: "취약점 · 위험 예측", sub: true },
        { id: "configuration-baselines", label: "설정 기준 관리", sub: true },
        { id: "hil-queue", label: "승인 요청" },
        { id: "alert-quality", label: "알림 품질", sub: true },
        { id: "detection-readiness", label: "탐지 커버리지", sub: true },
        { id: "conversation-delivery", label: "알림 전송 이력", sub: true },
        { id: "workflow-apps", label: "자동화 실행" },
        { id: "automation-blueprints", label: "자동화 템플릿", sub: true },
        { id: "processes", label: "실행 중인 작업", sub: true },
        { id: "scheduler-runs", label: "정기 작업 이력", sub: true },
        { id: "background-tasks", label: "백그라운드 작업", sub: true },
        { id: "scheduled-continuations", label: "예약된 후속 점검", sub: true },
        { id: "provision", label: "배포 관리" },
        { id: "onboarding", label: "초기 설정" }
      ]
    },
    {
      id: "agents", label: "에이전트", file: "/agents", icon: "M12 4a4 4 0 110 8 4 4 0 010-8zm-7 15a7 7 0 0114 0",
      items: [
        { id: "agents", label: "에이전트 현황" },
        { id: "pantheon", label: "역할 · 담당 영역" },
        { id: "handover", label: "담당자 · 인수인계", sub: true },
        { id: "agent-activity", label: "에이전트 작업 이력" },
        { id: "skills", label: "에이전트 도구(스킬)" },
        { id: "capabilities", label: "지원 기능 목록", sub: true }
      ]
    },
    {
      id: "governance", label: "거버넌스", file: "/governance", icon: "M12 3l7 4v5c0 4.5-3 7.5-7 9-4-1.5-7-4.5-7-9V7l7-4z",
      items: [
        { id: "rules", label: "운영 규칙" },
        { id: "trust-routing", label: "자동 · AI 처리 비율", sub: true },
        { id: "ontology", label: "온톨로지" },
        { id: "scope", label: "관리 대상 범위", sub: true },
        { id: "architecture", label: "시스템 구성도", sub: true },
        { id: "blast-radius", label: "변경 영향 분석" },
        { id: "promotion-gates", label: "자동화 적용 심사", sub: true },
        { id: "workflow-builder", label: "자동화 편집기" },
        { id: "knowledge", label: "지식 관리" },
        { id: "github", label: "GitHub 연동", sub: true },
        { id: "gitlab", label: "GitLab 연동", sub: true },
        { id: "azure-devops", label: "Azure DevOps 연동", sub: true },
        { id: "documents", label: "운영 문서", sub: true }
      ]
    },
    {
      id: "evidence", label: "감사 · 이력", file: "/evidence", icon: "M5 4h14v16H5zm3 4h8m-8 4h8m-8 4h5",
      items: [
        { id: "audit", label: "감사 로그" },
        { id: "trace", label: "실행 추적" },
        { id: "rca", label: "원인 분석(RCA)", sub: true },
        { id: "browser-evidence", label: "웹 수집 기록", sub: true },
        { id: "conversation-search", label: "대화 이력 검색" },
        { id: "reports", label: "운영 보고서" }
      ]
    },
    {
      id: "settings_labs", label: "설정 · 실험실", file: "/settings", icon: "",
      items: [
        { id: "settings-general", label: "일반" },
        { id: "settings-environment", label: "실행 환경 · 수집기", sub: true },
        { id: "settings-models", label: "AI 모델" },
        { id: "settings-runtime", label: "운영 정책", sub: true },
        { id: "settings-iam", label: "사용자 · 권한" },
        { id: "settings-integrations", label: "외부 연동" },
        { id: "settings-diagnostics", label: "시스템 상태 진단" },
        { id: "settings-memory", label: "저장된 운영 메모", sub: true },
        { id: "labs", label: "실험실 개요" },
        { id: "aks-commerce", label: "AKS 데모 환경", sub: true },
        { id: "assurance-twin", label: "사전 검증 시뮬레이션" },
        { id: "forecast-learning", label: "예측 모델 학습", sub: true },
        { id: "conversation-assurance", label: "대화 품질 점검", sub: true },
        { id: "context-selection-comparisons", label: "참조 정보 비교", sub: true }
      ]
    }
  ];

  const LAB_SUBPANELS = new Set([
    "aks-commerce",
    "assurance-twin",
    "forecast-learning",
    "conversation-assurance",
    "context-selection-comparisons"
  ]);

  const IS_STATIC_MOCK = /\.html$/i.test(location.pathname || "");
  const MOCK_DOMAIN_FILE = {
    overview: "mockup-overview.html",
    operations: "mockup-operations.html",
    agents: "mockup-agents.html",
    governance: "mockup-governance.html",
    evidence: "mockup-evidence.html",
    settings_labs: "mockup-settings-labs.html",
    chat: "mockup-chat.html"
  };

  function panelUrl(panelId) {
    if (IS_STATIC_MOCK) {
      if (!panelId) return "mockup-overview.html#tab=dashboard";
      if (panelId === "command-deck-chat") return "mockup-chat.html";
      const owner = NAV_DOMAINS.find((d) => d.items.some((it) => it.id === panelId));
      const file = (owner && MOCK_DOMAIN_FILE[owner.id]) || "mockup-overview.html";
      return `${file}#tab=${panelId}`;
    }
    if (!panelId) return "/dashboard";
    if (panelId === "command-deck-chat") return "/chat";
    if (panelId === "labs") return "/labs";
    if (LAB_SUBPANELS.has(panelId)) return `/labs/${panelId}`;
    if (panelId.startsWith("settings-")) return `/settings/${panelId.slice("settings-".length)}`;
    return `/${panelId}`;
  }

  function panelFromLocation() {
    const hashMatch = (location.hash || "").match(/tab=([a-z0-9-]+)/i);
    if (hashMatch) return hashMatch[1];
    const clean = (location.pathname || "/").replace(/\/+$/, "") || "/";
    if (clean === "/" || clean === "/overview") return "dashboard";
    if (clean === "/operations") return "live";
    if (clean === "/governance") return "rules";
    if (clean === "/evidence") return "audit";
    if (clean === "/settings") return "settings-general";
    if (clean === "/labs") return "labs";
    if (clean === "/chat") return "command-deck-chat";
    if (clean.startsWith("/settings/")) return `settings-${clean.slice("/settings/".length)}`;
    if (clean.startsWith("/labs/")) return clean.slice("/labs/".length);
    const seg = clean.slice(1);
    if (seg && !seg.includes("/")) return seg;
    const boot = window.__FDAI_V4_BOOTSTRAP__;
    if (boot && typeof boot.defaultPanel === "string" && boot.defaultPanel) return boot.defaultPanel;
    return "";
  }

  function navigatePanel(panelId, replace) {
    if (!panelId) return;
    const targetUrl = panelUrl(panelId);
    const localEl = document.querySelector(`.panel-view[data-panel-id="${panelId}"]`);
    if (localEl) {
      activatePanel(panelId);
      if (IS_STATIC_MOCK) {
        const nextHash = `#tab=${panelId}`;
        if (location.hash !== nextHash) {
          try {
            if (replace) history.replaceState({ panelId }, "", nextHash);
            else history.pushState({ panelId }, "", nextHash);
          } catch (_e) { location.hash = nextHash; }
        }
      } else if (location.pathname !== targetUrl || location.hash) {
        try {
          if (replace) history.replaceState({ panelId }, "", targetUrl);
          else history.pushState({ panelId }, "", targetUrl);
        } catch (_e) {}
      }
      window.dispatchEvent(new CustomEvent("fdai:panelchange", { detail: { panelId, url: targetUrl } }));
      return;
    }
    window.location.href = targetUrl;
  }

  window.fdaiPanelUrl = panelUrl;
  window.fdaiResolvePanelFromLocation = panelFromLocation;
  window.fdaiNavigatePanel = navigatePanel;

  const CHAT_THREADS = [
    {
      id: "t-current", title: "현재 화면 리스크·근거 요약", sub: "방금 전 · 근거 3건", unread: false, starred: true,
      user: "현재 보고 있는 화면에서 가장 시급한 리스크와 근거 상태를 요약해 줘.",
      agent: "가장 우선 검토가 필요한 항목은 prod-aks-02 CPU 포화 예측(+5m)과 kv-prod-kr 임시 예외 만료 2건입니다. 정책 위반은 0건을 유지 중이며, 수집되지 않은 지표는 0으로 표시하지 않고 별도 상태로 분리했습니다.",
      messages: []
    },
    {
      id: "t-aks", title: "prod-aks-02 CPU 포화 예측", sub: "12분 전 · Freyr 예측", unread: true, starred: false,
      user: "prod-aks-02 노드 풀 CPU 추세 예측의 산출 근거와 사전 조치안을 알려줘.",
      agent: "Freyr가 EWMA 추세 기울기와 14일 요일 주기를 대조한 결과 5분 내 85% 도달 가능성이 91%입니다. 조회 전용 정책에 따라 노드 풀 확장 초안을 승인 요청(HIL-8841)에 준비했습니다.",
      messages: []
    },
    {
      id: "t-kv", title: "kv-prod-kr 예외 만료 검토", sub: "28분 전 · Forseti 판정", unread: false, starred: true,
      user: "kv-prod-kr 임시 IP 허용 규칙 만료 초과 건의 감사 해시와 회수 절차를 보여줘.",
      agent: "Saga 감사 원장 #86641(sha256:9f4a...c10e)에 기록되었으며 Forseti가 고위험(A3) 승인 필수로 판정했습니다. Var 승인 요청(HIL-8839)에서 회수 승인을 진행할 수 있습니다.",
      messages: []
    }
  ];

  const body = document.body;
  const activeDomain = body.dataset.domain || "overview";
  const activeDomainLabel = body.dataset.domainLabel || "전체 현황";
  let chatOpen = body.dataset.openChatDefault === "true";
  let chatFullscreen = false;
  let dockHistoryOpen = false;
  let fullHistoryOpen = true;
  let explorerPinned = false;
  let explorerDomainId = activeDomain === "chat" ? "overview" : (activeDomain === "labs" ? "labs_only" : (activeDomain === "settings" ? "settings_only" : activeDomain));
  let explorerShowAll = false;
  let explorerSubExpanded = {};

  const FAVORITE_MENUS = [
    { id: "dashboard", label: "대시보드" },
    { id: "live", label: "실시간 모니터링" },
    { id: "incidents", label: "장애 대응", badge: "3" },
    { id: "hil-queue", label: "승인 요청", badge: "12" },
    { id: "ontology", label: "온톨로지" },
    { id: "command-deck-chat", label: "AI 채팅" }
  ];

  const MENU_BADGES = {
    incidents: "3",
    "code-security": "4",
    "hil-queue": "12"
  };
  let currentPanelTitle = activeDomainLabel;
  let activeThreadId = "t-current";
  let histFilter = "all";
  let chatMode = "operator";
  let chatTier = "auto";
  let stagedFile = null;
  let isBusy = false;
  let lastDrawerTrigger = null;

  function applySavedTheme() {
    const saved = localStorage.getItem("fdai-mockup-theme");
    if (saved === "dark") document.documentElement.setAttribute("data-theme", "dark");
    else document.documentElement.removeAttribute("data-theme");
  }
  applySavedTheme();

  function renderTopbar() {
    const el = document.getElementById("fdaiTopbar");
    if (!el) return;
    el.innerHTML = `
      <div class="topbar-left-group">
        <a class="brand-link" href="/dashboard">
          <img class="brand-logo" src="/brand/fdai-logo.png" alt="FDAI">
          <span>FDAI</span>
          <span class="brand-sub">운영 콘솔</span>
        </a>
        <button type="button" class="topbar-nav-toggle" id="fdaiNavToggleBtn" aria-label="메뉴 플라이아웃 열기/닫기" aria-expanded="false">▶</button>
      </div>
      <div class="topbar-right">
        <button type="button" class="top-pill" id="fdaiQuickJumpBtn" aria-label="전체 메뉴 빠른 검색 (Ctrl+K)"><span>메뉴 검색</span><span class="count-num">⌘K</span></button>
        <div class="seg-group" role="group" aria-label="데이터 모드">
          <button type="button" class="seg-btn is-active" aria-pressed="true" data-data-mode="live">Live</button>
          <button type="button" class="seg-btn" aria-pressed="false" data-data-mode="sample">Sample</button>
        </div>
        <button type="button" class="chat-header-trigger" id="fdaiChatTrigger" aria-expanded="${chatOpen}" aria-label="AI 채팅 열기 (Ctrl+J)">
          ${ICONS.chat}<span>채팅</span>
        </button>
        <button type="button" class="icon-btn" id="fdaiThemeToggle" aria-label="라이트 다크 테마 전환">${ICONS.theme}</button>
      </div>
    `;
    document.getElementById("fdaiNavToggleBtn")?.addEventListener("click", (e) => {
      e.stopPropagation();
      toggleExplorer();
    });
    document.getElementById("fdaiQuickJumpBtn")?.addEventListener("click", () => openCommandPalette());
    document.getElementById("fdaiChatTrigger")?.addEventListener("click", () => toggleChatSidebar());
    document.getElementById("fdaiThemeToggle")?.addEventListener("click", () => {
      const dark = document.documentElement.getAttribute("data-theme") === "dark";
      if (dark) {
        document.documentElement.removeAttribute("data-theme");
        localStorage.setItem("fdai-mockup-theme", "light");
      } else {
        document.documentElement.setAttribute("data-theme", "dark");
        localStorage.setItem("fdai-mockup-theme", "dark");
      }
    });
    el.querySelectorAll("[data-data-mode]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const mode = btn.getAttribute("data-data-mode");
        el.querySelectorAll("[data-data-mode]").forEach((b) => {
          const on = b === btn;
          b.classList.toggle("is-active", on);
          b.setAttribute("aria-pressed", String(on));
        });
        const bar = document.getElementById("sampleBoundaryBar");
        if (bar) bar.hidden = mode !== "sample";
      });
    });
  }

  function closeExplorer() {
    const explorer = document.getElementById("fdaiExplorer");
    if (!explorer || explorer.hidden) return;
    explorerPinned = false;
    explorer.classList.remove("is-pinned");
    explorer.hidden = true;
    const tbtn = document.getElementById("fdaiNavToggleBtn");
    if (tbtn) { tbtn.textContent = "▶"; tbtn.setAttribute("aria-expanded", "false"); }
  }

  function renderExplorerLink(it, domId) {
    const isActive = it.id === currentPanelId;
    const badge = it.badge || MENU_BADGES[it.id] || "";
    const dot = isActive ? `<span class="explorer-active-dot" aria-hidden="true"></span>` : "";
    const badgeHtml = badge ? `<span class="explorer-badge">${badge}</span>` : "";
    const ariaCur = isActive ? ` aria-current="page"` : "";
    return `<a class="explorer-link${it.sub ? " is-sub" : ""}${isActive ? " is-active" : ""}" href="${panelUrl(it.id)}"${ariaCur} data-exp-domain="${domId}" data-exp-panel="${it.id}"><span class="explorer-link-label">${dot}${it.label}</span>${badgeHtml}</a>`;
  }

  function renderExplorerContents() {
    const explorer = document.getElementById("fdaiExplorer");
    if (!explorer) return;
    const tbtn = document.getElementById("fdaiNavToggleBtn");
    if (tbtn) {
      const open = !explorer.hidden;
      tbtn.textContent = open ? "◀" : "▶";
      tbtn.setAttribute("aria-expanded", String(open));
    }
    const sl = NAV_DOMAINS[5];
    const labsDomainObj = { id: "labs_only", label: "개발 전용 실험실", file: "/labs", items: sl.items.filter((it) => !it.id.startsWith("settings-")) };
    const settingsDomainObj = { id: "settings_only", label: "시스템 설정", file: "/settings", items: sl.items.filter((it) => it.id.startsWith("settings-")) };
    const isLabsOnly = !explorerShowAll && explorerDomainId === "labs_only";
    const isSettingsOnly = !explorerShowAll && explorerDomainId === "settings_only";
    const domainsToShow = explorerShowAll
      ? NAV_DOMAINS
      : (isLabsOnly ? [labsDomainObj] : isSettingsOnly ? [settingsDomainObj] : NAV_DOMAINS.filter((d) => d.id === explorerDomainId));
    const curDom = isLabsOnly ? labsDomainObj : isSettingsOnly ? settingsDomainObj : (NAV_DOMAINS.find((d) => d.id === explorerDomainId) || NAV_DOMAINS[0]);
    const headTitle = explorerShowAll ? "전체 메뉴 (65)" : `${curDom.label} (${curDom.items.length})`;
    explorer.classList.toggle("is-pinned", explorerPinned);

    const renderDomainSection = (d) => {
      const primary = d.items.filter((it) => !it.sub);
      const secondary = d.items.filter((it) => it.sub);
      const hasActiveSub = secondary.some((it) => it.id === currentPanelId);
      const showSub = explorerShowAll || hasActiveSub || Boolean(explorerSubExpanded[d.id]);
      const primaryHtml = primary.map((it) => renderExplorerLink(it, d.id)).join("");
      const secondaryHtml = secondary.length
        ? `<button type="button" class="explorer-more-btn" data-exp-more="${d.id}" aria-expanded="${showSub}"><span>${showSub ? "▾" : "▸"} 세부 메뉴 (${secondary.length})</span></button>${showSub ? secondary.map((it) => renderExplorerLink(it, d.id)).join("") : ""}`
        : "";
      return `
        <div class="explorer-section">
          ${explorerShowAll ? `<div class="explorer-group-title">${d.label} <span>${d.items.length}</span></div>` : ""}
          ${primaryHtml}
          ${secondaryHtml}
        </div>
      `;
    };

    explorer.innerHTML = `
      <div class="explorer-head">
        <span>${headTitle}</span>
        <div class="chat-head-actions">
          <button type="button" class="icon-btn" id="explorerScopeBtn" aria-label="전체 메뉴 보기 전환">${explorerShowAll ? "현재" : "전체"}</button>
          <button type="button" class="icon-btn" id="closeExplorerBtn" aria-label="메뉴 닫기">${ICONS.close}</button>
        </div>
      </div>
      ${domainsToShow.map(renderDomainSection).join("")}
      <div class="explorer-divider"></div>
      <div class="explorer-section">
        <div class="explorer-group-title">자주 쓰는 메뉴</div>
        ${FAVORITE_MENUS.map((it) => renderExplorerLink(it, "fav")).join("")}
      </div>
      <div class="explorer-divider"></div>
      <div class="explorer-section">
        <a class="explorer-link" href="/labs"><span class="explorer-link-label">개발 전용 실험실</span></a>
        <a class="explorer-link" href="/settings/general"><span class="explorer-link-label">시스템 설정</span></a>
        <a class="explorer-link" href="/components"><span class="explorer-link-label">공용 컴포넌트 카탈로그</span></a>
      </div>
    `;
    document.getElementById("explorerScopeBtn")?.addEventListener("click", (e) => {
      e.stopPropagation();
      explorerShowAll = !explorerShowAll;
      renderExplorerContents();
    });
    document.getElementById("closeExplorerBtn")?.addEventListener("click", (e) => {
      e.stopPropagation();
      closeExplorer();
    });
    explorer.querySelectorAll("[data-exp-more]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const k = btn.getAttribute("data-exp-more");
        if (k) {
          explorerSubExpanded[k] = !explorerSubExpanded[k];
          renderExplorerContents();
        }
      });
    });
    explorer.querySelectorAll("[data-exp-panel]").forEach((link) => {
      link.addEventListener("click", (e) => {
        const pid = link.getAttribute("data-exp-panel");
        if (pid && document.querySelector(`.panel-view[data-panel-id="${pid}"]`)) {
          e.preventDefault();
          navigatePanel(pid, false);
          closeExplorer();
        }
      });
    });
  }

  let currentPanelId = "";

  function openExplorerForDomain(domId) {
    window.fdaiTip?.hide?.();
    const explorer = document.getElementById("fdaiExplorer");
    if (!explorer) return;
    if (!explorer.hidden && !explorerShowAll && explorerDomainId === domId) {
      closeExplorer();
      return;
    }
    explorerDomainId = domId;
    explorerShowAll = false;
    explorer.hidden = false;
    renderExplorerContents();
  }

  function renderRailAndExplorer() {
    const rail = document.getElementById("fdaiRail");
    const explorer = document.getElementById("fdaiExplorer");
    if (rail) {
      const topHtml = NAV_DOMAINS.slice(0, 5).map((d) => `
        <button type="button" class="rail-btn${d.id === activeDomain ? " is-active" : ""}"${d.id === activeDomain ? ` aria-current="page"` : ""} data-rail-domain="${d.id}" data-tip="${d.label}" aria-label="${d.label} 하위 메뉴 열기">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${d.icon}"/></svg>
        </button>
      `).join("");
      const isChatActive = activeDomain === "chat";
      const isLabsActive = activeDomain === "labs" || (activeDomain === "settings_labs" && !currentPanelId.startsWith("settings-"));
      const isSettingsActive = activeDomain === "settings" || (activeDomain === "settings_labs" && currentPanelId.startsWith("settings-"));
      rail.innerHTML = `
        <div class="rail-group">${topHtml}</div>
        <div class="rail-group">
          <a class="rail-btn${isChatActive ? " is-active" : ""}"${isChatActive ? ` aria-current="page"` : ""} href="${IS_STATIC_MOCK ? "mockup-chat.html" : "/chat"}" data-tip="AI 채팅" aria-label="AI 채팅">${ICONS.chat}</a>
          <button type="button" class="rail-btn${isLabsActive ? " is-active" : ""}"${isLabsActive ? ` aria-current="page"` : ""} id="railLabsBtn" data-tip="개발 전용 실험실" aria-label="개발 전용 실험실 메뉴 열기">${ICONS.labs}</button>
          <button type="button" class="rail-btn${isSettingsActive ? " is-active" : ""}"${isSettingsActive ? ` aria-current="page"` : ""} id="railSettingsBtn" aria-controls="settings-overlay" aria-expanded="false" data-tip="설정 (Ctrl+,)" aria-label="설정 열기">${ICONS.settings}</button>
        </div>
      `;
      rail.querySelectorAll("[data-rail-domain]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          e.stopPropagation();
          const domId = btn.getAttribute("data-rail-domain");
          if (domId) openExplorerForDomain(domId);
        });
      });
      document.getElementById("railLabsBtn")?.addEventListener("click", (e) => {
        e.stopPropagation();
        openExplorerForDomain("labs_only");
      });
      document.getElementById("railSettingsBtn")?.addEventListener("click", (e) => {
        e.stopPropagation();
        closeExplorer();
        if (typeof openSettingsOverlay === "function") {
          const scrim = document.getElementById("fdaiSettingsOverlayScrim");
          if (scrim && !scrim.hidden) closeSettingsOverlay();
          else openSettingsOverlay("settings-general", e.currentTarget);
        }
      });
    }
    if (explorer) {
      explorer.hidden = true;
      renderExplorerContents();
    }

    // Close Mode-A floating flyout whenever the user clicks anywhere in the main body or outside the menu
    if (!window.__fdaiExplorerOutsideWired) {
      window.__fdaiExplorerOutsideWired = true;
      document.addEventListener("pointerdown", (e) => {
        const exp = document.getElementById("fdaiExplorer");
        if (!exp || exp.hidden) return;
        const target = e.target;
        if (!(target instanceof Element)) return;
        if (exp.contains(target)) return;
        if (target.closest("#fdaiRail, #fdaiNavToggleBtn, [data-toggle-explorer]")) return;
        closeExplorer();
      }, true);
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeExplorer();
      });
    }
  }

  function toggleExplorer() {
    const dom = activeDomain === "chat" ? "overview" : (activeDomain === "labs" ? "labs_only" : (activeDomain === "settings" ? "settings_only" : activeDomain));
    openExplorerForDomain(dom);
  }

  function renderHistoryItems() {
    const list = document.getElementById("chatHistoryList");
    const q = (document.getElementById("chatHistorySearch")?.value || "").trim().toLowerCase();
    if (!list) return;
    const filtered = CHAT_THREADS.filter((t) => {
      if (histFilter === "unread" && !t.unread) return false;
      if (histFilter === "starred" && !t.starred) return false;
      if (q && !`${t.title} ${t.sub}`.toLowerCase().includes(q)) return false;
      return true;
    });
    list.innerHTML = filtered.map((t) => `
      <button type="button" class="chat-hist-item${t.id === activeThreadId ? " is-active" : ""}" data-thread-id="${t.id}">
        <strong>${t.title}</strong>
        <span class="chat-hist-sub">${t.sub}${t.unread ? " · 안 읽음" : ""}</span>
      </button>
    `).join("") || `<div class="chat-hist-sub">일치하는 대화가 없습니다.</div>`;
    list.querySelectorAll("[data-thread-id]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-thread-id");
        const found = CHAT_THREADS.find((x) => x.id === id);
        if (!found) return;
        found.unread = false;
        activeThreadId = found.id;
        if (!chatFullscreen) dockHistoryOpen = false;
        renderActiveThread(found);
        renderHistoryItems();
        syncChatVisibility();
      });
    });
  }

  function buildRichAgentReplyHtml(opts) {
    const kpis = opts.kpis || [
      ["영향 리소스", "3개 (2-Hop)"],
      ["위험 등급", "A3 승인 필수"],
      ["롤백 검증", "18초 통과"],
      ["감사 원장", "#86641 봉인"]
    ];
    const discussion = opts.discussion || [
      { agent: "Heimdall", icon: "/agent-icons/heimdall.svg", role: "실시간 탐지", status: "완료", ref: "metric:pg_pool_92%", text: "pg-orders-kr 연결 풀 점유율 92% 및 p95 응답 1.8초 급증을 19:35:10에 최초 포착했습니다." },
      { agent: "Mimir", icon: "/agent-icons/mimir.svg", role: "온톨로지 · RCA", status: "일치 검증", ref: "ontology:2-hop", text: "orders-api Rev#4810 배포 이후 커넥션 반환 지연이 2-Hop 경로(prod-aks-02 → pg-orders-kr)로 전파된 인과 사슬을 확인했습니다." },
      { agent: "Forseti", icon: "/agent-icons/forseti.svg", role: "정책 · 위험 가드", status: "A3 판정", ref: "policy:7/7-ok", text: "자동 실행을 차단하고 7대 안전장치(중지 조건·18초 롤백·대상 잠금·멱등키)를 검증한 뒤 Var 승인 관문으로 이관했습니다." }
    ];
    const resources = opts.resources || [
      { name: "pg-orders-kr", kind: "PostgreSQL", icon: "/azure-icons/postgresql.svg", href: panelUrl("ontology") },
      { name: "prod-aks-02", kind: "AKS Cluster", icon: "/azure-icons/kubernetes-services.svg", href: panelUrl("incidents") },
      { name: "kv-prod-kr", kind: "Key Vault", icon: "/azure-icons/key-vault.svg", href: panelUrl("code-security") }
    ];
    const followups = opts.followups || [
      "정책 위반 0건 검증 근거를 보여줘",
      "변경 영향 2단계 분석 결과 알려줘",
      "비용 거버넌스 예산 초과 위험을 요약해 줘"
    ];
    const primaryHref = opts.primaryHref || panelUrl("hil-queue");
    const primaryLabel = opts.primaryLabel || "승인 요청 열기 →";
    const secondaryHref = opts.secondaryHref || panelUrl("audit");
    const secondaryLabel = opts.secondaryLabel || "감사 원장 보기 →";

    return `
      <div class="chat-kpi-strip" aria-label="핵심 근거 요약">
        ${kpis.map(([k, v]) => `<div class="chat-kpi-cell"><span>${k}</span><strong>${v}</strong></div>`).join("")}
      </div>
      <details class="cs-disclosure" style="width:100%">
        <summary><span>5단계 근거 파이프라인 · 282ms</span><span class="disc-meta">출처 4건 · 정책 위반 0건</span></summary>
        <div class="disc-body">1. 의도 해석(T0 · 18ms) → 2. 온톨로지 2-Hop 탐색(42ms) → 3. 관측·감사 대조(64ms) → 4. Forseti 7대 안전장치 판정(38ms) → 5. Bragi 근거 요약 생성(120ms)</div>
      </details>
      <div class="agent-prose"><p>${opts.prose}</p></div>
      <section class="deck-agent-discussion" aria-label="에이전트 협력 분석 기록">
        <div class="deck-discussion-head">
          <span>멀티 에이전트 협력 · 교차 검증 (${discussion.length}개 에이전트)</span>
          <span class="cs-badge tone-live"><span class="cs-dot"></span>교차 검증 일치 (consistent)</span>
        </div>
        <div class="deck-discussion-list">
          ${discussion.map((d) => `
            <div class="deck-discussion-row">
              <img src="${d.icon}" alt="${d.agent}">
              <div>
                <div class="deck-discussion-meta"><strong>${d.agent}</strong><span>${d.role} · ${d.status}</span><code>${d.ref}</code></div>
                <div>${d.text}</div>
              </div>
            </div>
          `).join("")}
        </div>
      </section>
      <div class="chat-impact-row" aria-label="영향 리소스 바로가기">
        ${resources.map((r) => `<a class="chat-impact-chip" href="${r.href}"><img src="${r.icon}" alt=""><span>${r.name}</span><span style="color:var(--cs-text-soft);font-weight:500">${r.kind}</span></a>`).join("")}
      </div>
      <div class="chat-evidence-strip" aria-label="감사 근거 및 신선도">
        <span>원장: <code>#86641</code></span>
        <span>해시: <code>sha256:9f4a...c10e</code></span>
        <span>출처: <code>postgres-audit</code></span>
        <span>신선도: <strong>18초 전</strong></span>
        <span>미측정 0 대체: <strong>금지 준수</strong></span>
      </div>
      <div class="chat-proposal">
        <div class="card-head">
          <strong style="font-size:13.5px">${opts.proposalTitle || "작업 제안 초안 · 승인 요청(HIL-8841)"}</strong>
          <span class="cs-badge tone-human"><span class="cs-dot"></span>조회 전용 · 고위험(A3) 승인 필요</span>
        </div>
        <div style="font-size:13px;color:var(--cs-text-soft)">채팅에서는 직접 리소스 변경을 실행하지 않습니다. 아래 7대 안전장치 검증 후 승인 요청 화면에서 명시적으로 승인할 수 있습니다.</div>
        <div class="chat-safeguards-row">
          <span class="cs-badge tone-live">중지 조건</span>
          <span class="cs-badge tone-live">롤백 18초</span>
          <span class="cs-badge tone-live">영향 반경 제한</span>
          <span class="cs-badge tone-live">사전 모의 통과</span>
          <span class="cs-badge tone-live">대상 잠금</span>
          <span class="cs-badge tone-live">멱등키 고정</span>
          <span class="cs-badge tone-live">2단계 감사</span>
        </div>
        <div class="toolbar-inline">
          <a class="cs-btn cs-btn-sm cs-btn-accent" href="${primaryHref}">${primaryLabel}</a>
          <a class="cs-btn cs-btn-sm" href="${secondaryHref}">${secondaryLabel}</a>
        </div>
      </div>
      <div class="chat-reply-actions">
        <button type="button" class="cs-btn cs-btn-sm" data-chat-copy>답변 복사</button>
        <button type="button" class="cs-btn cs-btn-sm" data-chat-fb="up">도움됨</button>
        <button type="button" class="cs-btn cs-btn-sm" data-chat-fb="down">보완 필요</button>
      </div>
      <div class="chat-followups">
        ${followups.map((q) => `<button type="button" class="signal-chip" data-quick-ask="${q}">${q}</button>`).join("")}
      </div>
    `;
  }

  function wireRichReplyEvents(root) {
    root.querySelectorAll("[data-quick-ask]").forEach((btn) => {
      if (btn.dataset.qaWired === "1") return;
      btn.dataset.qaWired = "1";
      btn.addEventListener("click", () => appendUserAndAgentTurn(btn.getAttribute("data-quick-ask") || ""));
    });
    root.querySelectorAll("[data-chat-copy]").forEach((btn) => {
      if (btn.dataset.cpWired === "1") return;
      btn.dataset.cpWired = "1";
      btn.addEventListener("click", () => {
        const prose = btn.closest(".chat-turn-agent")?.querySelector(".agent-prose")?.textContent?.trim() || "";
        if (prose && navigator.clipboard?.writeText) navigator.clipboard.writeText(prose).catch(() => {});
        showToast("에이전트 근거 답변을 클립보드에 복사했습니다.");
      });
    });
    root.querySelectorAll("[data-chat-fb]").forEach((btn) => {
      if (btn.dataset.fbWired === "1") return;
      btn.dataset.fbWired = "1";
      btn.addEventListener("click", () => {
        const kind = btn.getAttribute("data-chat-fb");
        showToast(kind === "up" ? "긍정 피드백을 대화 품질 평가 원장에 기록했습니다." : "보완 요청을 대화 품질 점검 큐에 기록했습니다.");
      });
    });
  }

  function renderActiveThread(thread) {
    const inner = document.getElementById("chatTranscriptInner");
    if (!inner) return;
    const extraTurns = (thread.messages || []).map((m) => `
      <div class="chat-turn-user"><div class="chat-turn-meta"><span>운영자</span><span>${m.ts}</span></div><div class="chat-bubble-user">${m.user}</div></div>
      <div class="chat-turn-agent"><div class="chat-turn-meta"><strong>Bragi · 운영 에이전트</strong><span class="cs-badge tone-live"><span class="cs-dot"></span>근거 검증됨</span></div>${buildRichAgentReplyHtml({ prose: m.agent })}</div>
    `).join("");
    inner.innerHTML = (thread.user ? `
      <div class="chat-turn-user">
        <div class="chat-turn-meta"><span>운영자</span><span>19:40</span></div>
        <div class="chat-bubble-user">${thread.user}</div>
      </div>
      <div class="chat-turn-agent">
        <div class="chat-turn-meta"><strong>Bragi · 운영 에이전트</strong><span class="cs-badge tone-live"><span class="cs-dot"></span>${chatTier.toUpperCase()} · ${chatMode === "operator" ? "운영자" : "에이전트 토론"}</span></div>
        ${buildRichAgentReplyHtml({ prose: thread.agent })}
      </div>
    ` : "") + extraTurns;
    wireRichReplyEvents(inner);
  }

  function renderChatSidebar() {
    const aside = document.getElementById("fdaiChatSidebar");
    if (!aside) return;
    aside.innerHTML = `
      <div class="chat-resize-handle" id="chatResizeHandle" role="separator" aria-orientation="vertical" aria-label="채팅 사이드바 너비 조절" aria-valuemin="380" aria-valuemax="640" aria-valuenow="450" tabindex="0"></div>
      <div class="chat-head">
        <div class="chat-head-left">
          <button type="button" class="icon-btn" id="chatHistoryToggle" data-tip="대화 이력" aria-label="대화 이력 열기/닫기" aria-expanded="false">${ICONS.history}</button>
          <h3 class="chat-head-title">에이전트 채팅</h3>
          <span class="cs-badge tone-live"><span class="cs-dot"></span><span id="chatCtxBadge">${activeDomainLabel}</span></span>
        </div>
        <div class="chat-head-actions">
          <button type="button" class="icon-btn" id="chatInspectorToggle" data-tip="대화 정보 · AI 요약 패널" aria-label="우측 대화 정보 패널 접기/펼치기" aria-pressed="true" hidden>${ICONS.panelRight}<span>대화 정보</span></button>
          <button type="button" class="icon-btn" id="chatFullscreenToggle" data-tip="전체화면으로 확장" aria-label="전체화면 모드 전환">${ICONS.expand}</button>
          <button type="button" class="icon-btn" id="chatCloseBtn" data-tip="채팅 닫기 (Esc)" aria-label="채팅 닫기">${ICONS.close}</button>
        </div>
      </div>
      <div class="chat-body-grid has-history" id="chatBodyGrid">
        <div class="chat-history-scrim" id="chatHistoryScrim" hidden></div>
        <div class="chat-history-pane" id="chatHistoryPane" hidden>
          <button type="button" class="cs-btn cs-btn-accent" id="chatNewBtn">+ 새 대화</button>
          <input type="search" class="cs-input" id="chatHistorySearch" placeholder="대화 제목 검색..." aria-label="대화 제목 검색" style="min-width:0;width:100%;height:32px;min-height:32px">
          <div class="seg-group" role="group" aria-label="대화 이력 필터">
            <button type="button" class="seg-btn is-active" data-hist-filter="all">전체</button>
            <button type="button" class="seg-btn" data-hist-filter="unread">안 읽음</button>
            <button type="button" class="seg-btn" data-hist-filter="starred">즐겨찾기</button>
          </div>
          <div id="chatHistoryList" style="display:grid;gap:6px"></div>
        </div>
        <div class="chat-main-col">
          <div class="chat-toolbar">
            <select class="cs-select" id="chatModeSelect" aria-label="대화 모드" style="height:32px;min-height:32px;font-size:12.5px">
              <option value="operator">운영자 모드</option>
              <option value="discussion">에이전트 토론</option>
            </select>
            <select class="cs-select" id="chatTierSelect" aria-label="모델 티어" style="height:32px;min-height:32px;font-size:12.5px">
              <option value="auto">티어: 자동 (T0 우선)</option>
              <option value="t1">T1 고속 분류</option>
              <option value="t2">T2 심층 추론</option>
            </select>
          </div>
          <details class="chat-readiness">
            <summary><span>근거 서비스 5 / 5 연결됨</span><span class="cs-badge tone-live"><span class="cs-dot"></span>정상</span></summary>
            <div style="padding-top:6px">온톨로지 · 감사 로그 · 승인 요청 · 운영 규칙 · 지식 관리 모두 최신 응답 중</div>
          </details>
          <div class="chat-transcript" id="chatTranscript">
            <div class="chat-transcript-inner" id="chatTranscriptInner"></div>
          </div>
          <form class="chat-composer" id="chatForm">
            <div class="chat-composer-inner">
              <div class="slash-popover" id="chatSlashPopover" role="listbox" aria-label="슬래시 명령 자동완성" hidden>
                <button type="button" class="cmd-row" data-slash-pick="/risks 현재 화면 리스크 요약"><span><strong>/risks</strong> · 현재 화면 핵심 리스크 요약</span><span class="cs-badge tone-sre">SRE·보안</span></button>
                <button type="button" class="cmd-row" data-slash-pick="/approvals 승인 대기 우선순위"><span><strong>/approvals</strong> · 승인 대기 12건 우선순위 정리</span><span class="cs-badge tone-human">승인</span></button>
                <button type="button" class="cmd-row" data-slash-pick="/ontology prod-aks-02 관계 및 데이터 계통"><span><strong>/ontology</strong> · 리소스 관계 및 데이터 계통 조회</span><span class="cs-badge tone-live">온톨로지</span></button>
                <button type="button" class="cmd-row" data-slash-pick="/trace corr-8a91f 실행 추적 요약"><span><strong>/trace</strong> · 실행 추적 워터폴 및 감사 근거 요약</span><span class="cs-badge tone-neutral">감사</span></button>
              </div>
              <div class="chat-composer-bar">
                <div class="toolbar-inline">
                  <button type="button" class="cs-btn cs-btn-sm" id="chatAttachBtn">${ICONS.clip}<span>근거 첨부</span></button>
                  <button type="button" class="signal-chip" data-slash-cmd="/risks">/risks</button>
                  <button type="button" class="signal-chip" data-slash-cmd="/approvals">/approvals</button>
                  <span class="cs-badge tone-live" id="chatAttachmentChip" hidden><span id="chatAttachmentName"></span><button type="button" id="chatAttachmentRemove" aria-label="첨부 제거" style="border:0;background:transparent;color:inherit;cursor:pointer;padding:0 2px;font-weight:700">×</button></span>
                </div>
                <div class="toolbar-inline" id="chatBusyControls" hidden>
                  <select class="cs-select" id="chatBusyMode" aria-label="응답 중 입력 모드" style="height:30px;min-height:30px;font-size:12px">
                    <option value="queue">대기열(Queue)</option>
                    <option value="steer">조향(Steer)</option>
                  </select>
                  <button type="button" class="cs-btn cs-btn-sm" id="chatStopBtn">중지</button>
                </div>
              </div>
              <div class="chat-input-row">
                <textarea class="chat-textarea" id="chatInput" rows="2" aria-label="AI 에이전트에게 질문 입력" placeholder="현재 화면에 대해 질문하거나 / 명령을 입력하세요 (Enter 전송 · Shift+Enter 줄바꿈)"></textarea>
                <button type="submit" class="cs-btn cs-btn-accent">전송</button>
              </div>
            </div>
          </form>
        </div>
        <aside class="chat-inspector-pane" aria-label="대화 정보 및 AI 요약">
          <div class="insp-card">
            <div class="insp-title">대화 정보</div>
            <div class="insp-kv"><span>대상 화면</span><strong id="chatInspContext">${activeDomainLabel}</strong></div>
            <div class="insp-kv"><span>구독 범위</span><strong>전체 Azure 구독 (3)</strong></div>
            <div class="insp-kv"><span>추적 ID</span><strong class="cell-mono">corr-8a91f</strong></div>
            <div class="insp-kv"><span>권한 경계</span><strong>조회 전용 · 위반 0건</strong></div>
          </div>
          <div class="insp-card">
            <div class="insp-title">AI 요약</div>
            <p class="insp-summary" id="chatInspSummary">prod-aks-02 CPU 포화 예측(+5m, 91%)과 kv-prod-kr 예외 만료 2건을 감사 원장과 대조했습니다. 변경 작업은 승인 요청(HIL-8841)으로 연결되었습니다.</p>
          </div>
          <div class="insp-card">
            <div class="insp-title">추출된 후속 조치 초안</div>
            <a class="insp-action-item" href="${panelUrl("hil-queue")}"><span>HIL-8841 · 노드 풀 확장 승인 검토</span><span>→</span></a>
            <a class="insp-action-item" href="${panelUrl("ontology")}"><span>prod-aks-02 데이터 계통 확인</span><span>→</span></a>
            <a class="insp-action-item" href="${panelUrl("trace")}"><span>corr-8a91f 실행 추적 열기</span><span>→</span></a>
          </div>
        </aside>
      </div>
    `;

    renderHistoryItems();
    renderActiveThread(CHAT_THREADS[0]);

    document.getElementById("chatCloseBtn")?.addEventListener("click", () => toggleChatSidebar(false));
    document.getElementById("chatFullscreenToggle")?.addEventListener("click", () => setChatFullscreen(!chatFullscreen));
    document.getElementById("chatInspectorToggle")?.addEventListener("click", (e) => {
      const hidden = aside.classList.toggle("is-insp-hidden");
      e.currentTarget.setAttribute("aria-pressed", String(!hidden));
    });
    document.getElementById("chatHistoryToggle")?.addEventListener("click", () => {
      if (chatFullscreen) fullHistoryOpen = !fullHistoryOpen;
      else dockHistoryOpen = !dockHistoryOpen;
      syncChatVisibility();
    });
    document.getElementById("chatHistoryScrim")?.addEventListener("click", () => {
      dockHistoryOpen = false;
      syncChatVisibility();
    });
    document.getElementById("chatHistorySearch")?.addEventListener("input", renderHistoryItems);
    aside.querySelectorAll("[data-hist-filter]").forEach((btn) => {
      btn.addEventListener("click", () => {
        histFilter = btn.getAttribute("data-hist-filter") || "all";
        aside.querySelectorAll("[data-hist-filter]").forEach((b) => b.classList.toggle("is-active", b === btn));
        renderHistoryItems();
      });
    });
    document.getElementById("chatModeSelect")?.addEventListener("change", (e) => { chatMode = e.target.value; });
    document.getElementById("chatTierSelect")?.addEventListener("change", (e) => { chatTier = e.target.value; });
    document.getElementById("chatAttachBtn")?.addEventListener("click", () => {
      stagedFile = "aks-oomkill-snapshot.log (18 KB)";
      const chip = document.getElementById("chatAttachmentChip");
      const nm = document.getElementById("chatAttachmentName");
      if (nm) nm.textContent = `첨부: ${stagedFile}`;
      if (chip) chip.hidden = false;
    });
    document.getElementById("chatAttachmentRemove")?.addEventListener("click", () => {
      stagedFile = null;
      const chip = document.getElementById("chatAttachmentChip");
      if (chip) chip.hidden = true;
    });
    const slashPop = document.getElementById("chatSlashPopover");
    aside.querySelectorAll("[data-slash-pick]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (slashPop) slashPop.hidden = true;
        const inp = document.getElementById("chatInput");
        if (inp) inp.value = "";
        appendUserAndAgentTurn(btn.getAttribute("data-slash-pick") || "");
      });
    });
    aside.querySelectorAll("[data-slash-cmd]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const cmd = btn.getAttribute("data-slash-cmd") || "";
        appendUserAndAgentTurn(`${cmd} - ${currentPanelTitle} 기준 조회`);
      });
    });
    document.getElementById("chatNewBtn")?.addEventListener("click", () => {
      const nt = { id: `t-${Date.now()}`, title: `${currentPanelTitle} 새 질의`, sub: "방금 전 · 새 대화", unread: false, starred: false, user: "", agent: "", messages: [] };
      CHAT_THREADS.unshift(nt);
      activeThreadId = nt.id;
      renderHistoryItems();
      const inner = document.getElementById("chatTranscriptInner");
      if (inner) {
        inner.innerHTML = `<div class="chat-turn-agent"><div class="chat-turn-meta"><strong>Bragi</strong><span>새 대화 · ${currentPanelTitle}</span></div><div class="agent-prose"><p><strong>${currentPanelTitle}</strong> 컨텍스트로 새 대화를 시작했습니다. 아래 추천 질문을 누르거나 직접 입력하세요.</p></div><div class="chat-followups"><button type="button" class="signal-chip" data-starter-prompt="${currentPanelTitle}에서 가장 시급한 리스크 3건을 요약해 줘">시급한 리스크 3건 요약</button><button type="button" class="signal-chip" data-starter-prompt="승인 대기 중인 고위험(A3) 항목의 롤백 검증 상태를 알려줘">승인 대기 롤백 검증 확인</button><button type="button" class="signal-chip" data-starter-prompt="미수집·지연 수집기 원인과 연결 방법을 안내해 줘">미수집 지표 연결 안내</button></div></div>`;
        inner.querySelectorAll("[data-starter-prompt]").forEach((b) => {
          b.addEventListener("click", () => appendUserAndAgentTurn(b.getAttribute("data-starter-prompt") || ""));
        });
      }
      if (!chatFullscreen) { dockHistoryOpen = false; syncChatVisibility(); }
      document.getElementById("chatInput")?.focus();
    });
    document.getElementById("chatStopBtn")?.addEventListener("click", () => {
      isBusy = false;
      const busy = document.getElementById("chatBusyControls");
      if (busy) busy.hidden = true;
    });
    document.getElementById("chatForm")?.addEventListener("submit", (ev) => {
      ev.preventDefault();
      if (slashPop) slashPop.hidden = true;
      const input = document.getElementById("chatInput");
      const text = (input?.value || "").trim();
      if (!text) return;
      input.value = "";
      appendUserAndAgentTurn(text);
    });
    document.getElementById("chatInput")?.addEventListener("input", (ev) => {
      const val = (ev.target.value || "").trim();
      if (slashPop) slashPop.hidden = !val.startsWith("/");
    });
    document.getElementById("chatInput")?.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && slashPop && !slashPop.hidden) { ev.stopPropagation(); slashPop.hidden = true; return; }
      if (ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        document.getElementById("chatForm")?.requestSubmit();
      }
    });

    // Drag & keyboard resize handle (380px - 640px)
    const handle = document.getElementById("chatResizeHandle");
    let resizing = false;
    handle?.addEventListener("mousedown", (e) => { e.preventDefault(); resizing = true; });
    window.addEventListener("mousemove", (e) => {
      if (!resizing || chatFullscreen) return;
      const w = Math.max(380, Math.min(640, window.innerWidth - e.clientX));
      document.documentElement.style.setProperty("--chat-w", `${w}px`);
      handle?.setAttribute("aria-valuenow", String(Math.round(w)));
    });
    window.addEventListener("mouseup", () => { resizing = false; });
    handle?.addEventListener("keydown", (e) => {
      if (chatFullscreen) return;
      const cur = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--chat-w"), 10) || 450;
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        const next = Math.max(380, Math.min(640, cur + (e.key === "ArrowLeft" ? 24 : -24)));
        document.documentElement.style.setProperty("--chat-w", `${next}px`);
        handle.setAttribute("aria-valuenow", String(next));
      }
    });
    syncChatVisibility();
  }

  function appendUserAndAgentTurn(text) {
    const inner = document.getElementById("chatTranscriptInner");
    const scroller = document.getElementById("chatTranscript");
    const busy = document.getElementById("chatBusyControls");
    if (!inner) return;
    const now = new Date().toTimeString().slice(0, 5);
    const att = stagedFile ? `<div class="chat-turn-meta">첨부: ${stagedFile}</div>` : "";
    stagedFile = null;
    const chip = document.getElementById("chatAttachmentChip");
    if (chip) chip.hidden = true;

    const u = document.createElement("div");
    u.className = "chat-turn-user";
    u.innerHTML = `<div class="chat-turn-meta"><span>운영자</span><span>${now}</span></div>${att}<div class="chat-bubble-user"></div>`;
    u.querySelector(".chat-bubble-user").textContent = text;
    inner.appendChild(u);

    isBusy = true;
    if (busy) busy.hidden = false;
    const grounding = document.createElement("div");
    grounding.className = "chat-turn-agent";
    grounding.innerHTML = `<div class="chat-turn-meta"><strong>Bragi</strong><span class="cs-badge tone-sre"><span class="cs-dot"></span>관련 정보 확인 중</span></div><div class="agent-prose"><p>1. 현재 화면 스냅샷 수집 → 2. 온톨로지·정책 가드 대조 → 3. 근거 검증 중...</p></div>`;
    inner.appendChild(grounding);
    if (scroller) scroller.scrollTop = scroller.scrollHeight;

    window.setTimeout(() => {
      if (!isBusy) return;
      isBusy = false;
      if (busy) busy.hidden = true;
      const replyText = `${currentPanelTitle} 컨텍스트에서 질의를 검증했습니다. 관련 감사 로그와 정책 가드 기준 정책 위반은 0건이며, 변경이 필요한 작업은 조회 전용 정책에 따라 승인 요청을 통해서만 진행됩니다.`;
      const curT = CHAT_THREADS.find((x) => x.id === activeThreadId);
      if (curT) {
        if (!curT.messages) curT.messages = [];
        curT.messages.push({ ts: now, user: text, agent: replyText });
        curT.sub = `방금 전 · 메시지 ${curT.messages.length + (curT.user ? 1 : 0)}건`;
        renderHistoryItems();
      }
      grounding.innerHTML = `
        <div class="chat-turn-meta"><strong>Bragi · 운영 에이전트</strong><span class="cs-badge tone-live"><span class="cs-dot"></span>${chatTier.toUpperCase()} · ${chatMode === "operator" ? "운영자" : "에이전트 토론"}</span></div>
        ${buildRichAgentReplyHtml({
          prose: replyText,
          proposalTitle: `작업 제안 초안 · ${currentPanelTitle} 후속 점검`,
          primaryHref: panelUrl("hil-queue"),
          primaryLabel: "승인 요청 열기 →",
          secondaryHref: panelUrl("audit"),
          secondaryLabel: "감사 원장 보기 →"
        })}
      `;
      wireRichReplyEvents(grounding);
      if (scroller) scroller.scrollTop = scroller.scrollHeight;
    }, 280);
  }

  function syncChatVisibility() {
    const aside = document.getElementById("fdaiChatSidebar");
    const trigger = document.getElementById("fdaiChatTrigger");
    const fsBtn = document.getElementById("chatFullscreenToggle");
    const histBtn = document.getElementById("chatHistoryToggle");
    const inspBtn = document.getElementById("chatInspectorToggle");
    const histPane = document.getElementById("chatHistoryPane");
    const scrim = document.getElementById("chatHistoryScrim");
    const grid = document.getElementById("chatBodyGrid");
    if (aside) {
      aside.hidden = !chatOpen;
      aside.classList.toggle("is-fullscreen", chatOpen && chatFullscreen);
    }
    if (trigger) trigger.setAttribute("aria-expanded", String(chatOpen));
    if (inspBtn) {
      inspBtn.hidden = !chatFullscreen;
    }
    if (fsBtn) {
      fsBtn.innerHTML = chatFullscreen ? `${ICONS.dock}<span>사이드바</span>` : `${ICONS.expand}`;
      fsBtn.setAttribute("data-tip", chatFullscreen ? "사이드바로 축소" : "전체화면으로 확장");
      fsBtn.setAttribute("aria-label", chatFullscreen ? "사이드바로 축소" : "전체화면으로 확장");
    }
    const showHist = chatOpen && (chatFullscreen ? fullHistoryOpen : dockHistoryOpen);
    if (histBtn) {
      histBtn.innerHTML = chatFullscreen ? `${ICONS.history}<span>대화 이력</span>` : `${ICONS.history}`;
      histBtn.setAttribute("aria-expanded", String(showHist));
    }
    if (histPane) histPane.hidden = !showHist;
    if (scrim) scrim.hidden = !(chatOpen && !chatFullscreen && dockHistoryOpen);
    if (grid) grid.classList.toggle("has-history", chatFullscreen && fullHistoryOpen);
  }

  let toastTimer = null;
  function showToast(msg) {
    let el = document.getElementById("fdaiToast");
    if (!el) {
      el = document.createElement("div");
      el.id = "fdaiToast";
      el.className = "fdai-toast";
      el.setAttribute("role", "status");
      el.setAttribute("aria-live", "polite");
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.hidden = false;
    if (toastTimer) window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => { el.hidden = true; }, 2600);
  }

  function openCommandPalette() {
    let bd = document.getElementById("fdaiCmdBackdrop");
    if (!bd) {
      bd = document.createElement("div");
      bd.id = "fdaiCmdBackdrop";
      bd.className = "cmd-backdrop";
      bd.innerHTML = `
        <div class="cmd-modal" role="dialog" aria-modal="true" aria-label="전체 메뉴 빠른 이동">
          <div class="cmd-head">
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="7" cy="7" r="4.8"/><path d="M10.7 10.7L14 14"/></svg>
            <input type="search" class="cmd-input" id="fdaiCmdInput" placeholder="63개 메뉴 중 이동할 화면 검색 (예: 온톨로지, 승인, GPU, 감사, 설정)..." aria-label="메뉴 빠른 검색">
            <button type="button" class="icon-btn" id="fdaiCmdClose" aria-label="닫기">${ICONS.close}</button>
          </div>
          <div class="cmd-list" id="fdaiCmdList"></div>
          <div class="cmd-foot"><span>Enter: 바로 이동 · Esc: 닫기</span><span>채팅 토글: Ctrl+J</span></div>
        </div>
      `;
      document.body.appendChild(bd);
      bd.addEventListener("click", (e) => { if (e.target === bd) bd.hidden = true; });
      document.getElementById("fdaiCmdClose")?.addEventListener("click", () => { bd.hidden = true; });
      const inp = document.getElementById("fdaiCmdInput");
      const allItems = [];
      NAV_DOMAINS.forEach((d) => d.items.forEach((it) => allItems.push({ dom: d.id, domLbl: d.label, file: d.file, id: it.id, label: it.label })));
      allItems.push({ dom: "chat", domLbl: "AI 채팅", file: "/chat", id: "command-deck-chat", label: "AI 채팅 (우측 사이드바 · 3단 전체화면)" });
      const renderList = () => {
        const q = (inp?.value || "").trim().toLowerCase();
        const list = document.getElementById("fdaiCmdList");
        if (!list) return;
        const matched = allItems.filter((x) => !q || `${x.domLbl} ${x.label} ${x.id}`.toLowerCase().includes(q)).slice(0, 14);
        list.innerHTML = matched.map((x, idx) => `
          <button type="button" class="cmd-row${idx === 0 ? " is-active" : ""}" data-cmd-dom="${x.dom}" data-cmd-file="${x.file}" data-cmd-id="${x.id}">
            <span><strong>${x.label}</strong></span>
            <span class="cs-badge tone-neutral">${x.domLbl}</span>
          </button>
        `).join("") || `<div style="padding:16px;text-align:center;color:var(--cs-text-soft);font-size:13px">일치하는 메뉴가 없습니다.</div>`;
        list.querySelectorAll("[data-cmd-id]").forEach((btn) => {
          btn.addEventListener("click", () => {
            const dom = btn.getAttribute("data-cmd-dom");
            const file = btn.getAttribute("data-cmd-file");
            const id = btn.getAttribute("data-cmd-id");
            bd.hidden = true;
            if (id) navigatePanel(id, false);
            else if (file) location.href = file;
          });
        });
      };
      inp?.addEventListener("input", renderList);
      inp?.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          const first = document.querySelector("#fdaiCmdList .cmd-row");
          if (first) first.click();
        }
      });
      renderList();
    }
    bd.hidden = false;
    const inp = document.getElementById("fdaiCmdInput");
    if (inp) { inp.value = ""; inp.dispatchEvent(new Event("input")); inp.focus(); }
  }

  function toggleChatSidebar(forceState) {
    chatOpen = typeof forceState === "boolean" ? forceState : !chatOpen;
    if (chatOpen) closeFloatingDrawer();
    if (!chatOpen) { chatFullscreen = false; dockHistoryOpen = false; }
    syncChatVisibility();
    if (chatOpen) window.setTimeout(() => document.getElementById("chatInput")?.focus(), 40);
  }

  function setChatFullscreen(fs) {
    chatOpen = true;
    chatFullscreen = fs;
    if (!fs) dockHistoryOpen = false;
    syncChatVisibility();
  }

  const FULLBLEED_PANELS = new Set([
    "ontology", "architecture", "blast-radius", "workflow-builder",
    "rules", "agents", "pantheon",
    "hil-queue", "incidents", "audit", "conversation-search"
  ]);
  const WIDE_GRAPH_AUTODOCK_PANELS = new Set([
    "agents", "pantheon", "blast-radius", "workflow-builder"
  ]);

  function autoDockWideGraphInspector(panelId) {
    if (window.innerWidth < 1680 || chatOpen) return;
    if (!WIDE_GRAPH_AUTODOCK_PANELS.has(panelId)) return;
    const target = document.querySelector(`.panel-view[data-panel-id="${panelId}"]:not([hidden])`);
    const aside = target?.querySelector('[data-float-inspector="panel"]');
    if (!aside) return;
    drawerPinned = true;
    openInlineInspector(aside, target);
  }
  const FULLWIDE_PANELS = new Set([
    "dashboard-v2", "trace", "rca", "agent-activity",
    "code-security", "vulnerability-risk", "configuration-baselines",
    "skills", "capabilities", "documents"
  ]);
  const READABLE_PANELS = new Set([
    "settings-general", "settings-environment", "settings-models", "settings-runtime",
    "settings-iam", "settings-integrations", "settings-diagnostics", "settings-memory",
    "provision", "onboarding"
  ]);

  function ensureCompactPageHelp(summaryText) {
    const copy = document.querySelector(".page-head-copy");
    if (!copy) return;
    let wrap = copy.querySelector(".page-help-wrap");
    if (!wrap) {
      wrap = document.createElement("span");
      wrap.className = "page-help-wrap";
      wrap.innerHTML = `<button type="button" class="page-help-btn" id="fdaiPageHelpBtn" aria-label="화면 설명 보기" aria-expanded="false">?</button><div class="page-help-pop" id="fdaiPageHelpPop" role="note" hidden></div>`;
      const h2 = copy.querySelector(".page-breadcrumb");
      if (h2) h2.insertAdjacentElement("afterend", wrap);
      else copy.appendChild(wrap);
      const btn = wrap.querySelector("#fdaiPageHelpBtn");
      const pop = wrap.querySelector("#fdaiPageHelpPop");
      btn?.addEventListener("click", (e) => {
        e.stopPropagation();
        const next = pop.hidden;
        pop.hidden = !next;
        btn.setAttribute("aria-expanded", String(next));
      });
      document.addEventListener("click", (e) => {
        if (pop && !pop.hidden && !wrap.contains(e.target)) {
          pop.hidden = true;
          btn?.setAttribute("aria-expanded", "false");
        }
      });
    }
    const pop = wrap.querySelector("#fdaiPageHelpPop");
    if (pop && summaryText) pop.textContent = summaryText;
  }

  function applyLayoutTier(panelId, summaryText) {
    const main = document.getElementById("fdaiMain") || document.querySelector(".main-canvas");
    if (!main) return;
    let tier = "fluid";
    if (FULLBLEED_PANELS.has(panelId)) tier = "fullbleed";
    else if (FULLWIDE_PANELS.has(panelId)) tier = "fullwide";
    else if (READABLE_PANELS.has(panelId)) tier = "readable";
    main.setAttribute("data-layout-tier", tier);
    ensureCompactPageHelp(summaryText);
    window.requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
  }

  function activatePanel(panelId) {
    closeFloatingDrawer(true);
    closeDrawer();
    const views = document.querySelectorAll(".panel-view[data-panel-id]");
    if (!views.length) return;
    let target = document.querySelector(`.panel-view[data-panel-id="${panelId}"]`);
    if (!target) target = views[0];
    const resolvedId = target.getAttribute("data-panel-id");
    currentPanelId = resolvedId || "";
    const hubRoot = target.getAttribute("data-hub-root") || resolvedId;
    const title = target.getAttribute("data-panel-title") || activeDomainLabel;
    const summary = target.getAttribute("data-panel-summary") || "";
    currentPanelTitle = title;
    renderExplorerContents();
    applyLayoutTier(currentPanelId, summary);

    views.forEach((v) => { v.hidden = v !== target; });
    document.querySelectorAll("[data-hub-trigger]").forEach((btn) => {
      const match = btn.getAttribute("data-hub-trigger") === hubRoot;
      btn.classList.toggle("is-active", match);
      btn.setAttribute("aria-selected", String(match));
    });
    document.querySelectorAll("[data-subtab-group]").forEach((bar) => {
      bar.hidden = bar.getAttribute("data-subtab-group") !== hubRoot;
    });
    document.querySelectorAll("[data-panel-tab]").forEach((btn) => {
      const match = btn.getAttribute("data-panel-tab") === resolvedId;
      btn.classList.toggle("is-active", match);
      btn.setAttribute("aria-selected", String(match));
    });
    const titleEl = document.getElementById("activePanelTitle");
    const subEl = document.getElementById("activePanelSubtitle");
    const badgeEl = document.getElementById("chatCtxBadge");
    const inspCtx = document.getElementById("chatInspContext");
    const inspSum = document.getElementById("chatInspSummary");
    if (titleEl) titleEl.textContent = title;
    if (subEl && summary) subEl.textContent = summary;
    const ctxText = title === activeDomainLabel ? title : `${activeDomainLabel} / ${title}`;
    if (badgeEl) badgeEl.textContent = ctxText;
    if (inspCtx) inspCtx.textContent = ctxText;
    if (inspSum && summary) inspSum.textContent = `${title} 컨텍스트 요약: ${summary} (정책 위반 0건 · 조회 전용)`;
    window.requestAnimationFrame(() => autoDockWideGraphInspector(currentPanelId));
  }

  function openDrawerFrom(el) {
    if (chatOpen) toggleChatSidebar(false);
    lastDrawerTrigger = el;
    const bd = document.getElementById("fdaiDrawerBackdrop");
    const t = document.getElementById("fdaiDrawerTitle");
    const m = document.getElementById("fdaiDrawerMeta");
    const b = document.getElementById("fdaiDrawerBody");
    const f = document.getElementById("fdaiDrawerFacts");
    const foot = bd?.querySelector(".drawer-foot");
    if (t) t.textContent = el.getAttribute("data-drawer-title") || "상세 보기";
    if (m) m.textContent = el.getAttribute("data-drawer-meta") || "";
    if (b) b.textContent = el.getAttribute("data-drawer-body") || "";
    if (foot) {
      let jmp = document.getElementById("fdaiDrawerJump");
      if (!jmp) {
        jmp = document.createElement("a");
        jmp.id = "fdaiDrawerJump";
        jmp.className = "cs-btn cs-btn-sm";
        foot.prepend(jmp);
      }
      const rawHref = el.getAttribute("data-drawer-href") || panelUrl("hil-queue");
      const hashMatch = rawHref.match(/^#tab=([a-z0-9-]+)$/i);
      const cleanHref = hashMatch ? panelUrl(hashMatch[1]) : rawHref;
      jmp.href = cleanHref;
      jmp.textContent = el.getAttribute("data-drawer-href-label") || "관련 화면 바로 이동 →";
    }
    if (t) t.textContent = el.getAttribute("data-drawer-title") || "상세 보기";
    if (m) m.textContent = el.getAttribute("data-drawer-meta") || "";
    if (b) b.textContent = el.getAttribute("data-drawer-body") || "";
    if (f) {
      const rawFacts = el.getAttribute("data-drawer-facts") || "";
      f.innerHTML = rawFacts.split(";").filter(Boolean).map((pair) => {
        const [k, v] = pair.split("|");
        return `<div class="drawer-fact-row"><dt>${k || ""}</dt><dd>${v || ""}</dd></div>`;
      }).join("");
    }
    if (bd) bd.hidden = false;
    document.getElementById("fdaiDrawerClose")?.focus();
  }

  function closeDrawer() {
    const bd = document.getElementById("fdaiDrawerBackdrop");
    if (bd) bd.hidden = true;
    lastDrawerTrigger?.focus?.();
  }

  function wirePageInteractions() {
    document.querySelectorAll("[data-toggle-explorer]").forEach((b) => b.addEventListener("click", toggleExplorer));
    document.querySelectorAll("[data-jump-panel]").forEach((b) => {
      b.addEventListener("click", () => {
        const pid = b.getAttribute("data-jump-panel");
        if (pid) navigatePanel(pid, false);
      });
    });
    document.querySelectorAll("[data-hub-trigger]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const hub = btn.getAttribute("data-hub-trigger");
        if (hub) navigatePanel(hub, false);
      });
    });
    document.querySelectorAll("[data-panel-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const pid = btn.getAttribute("data-panel-tab");
        if (pid) navigatePanel(pid, false);
      });
    });
    // Chart modes, time window, pause, series filters, hover tips
    document.querySelectorAll("[data-chart-mode]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const card = btn.closest(".chart-panel");
        const mode = btn.getAttribute("data-chart-mode");
        if (!card || !mode) return;
        card.querySelectorAll("[data-chart-mode]").forEach((b) => {
          const on = b === btn;
          b.classList.toggle("is-active", on);
          b.setAttribute("aria-selected", String(on));
        });
        card.querySelectorAll("[data-chart-view]").forEach((box) => {
          box.hidden = box.getAttribute("data-chart-view") !== mode;
        });
      });
    });
    const WIN_SUMMARY = {
      "15m": "표본 15m: 412건 (자동 처리 330 · SRE 42 · 보안 28 · 사람 알림 12)",
      "1h": "표본 1h: 1,648건 (자동 처리 1,340 · SRE 164 · 보안 102 · 사람 알림 42)",
      "24h": "표본 24h: 38,420건 (자동 처리 37,910 · SRE 312 · 보안 146 · 사람 알림 52)"
    };
    document.querySelectorAll("[data-chart-win]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const card = btn.closest(".chart-panel");
        const win = btn.getAttribute("data-chart-win") || "15m";
        if (!card) return;
        card.querySelectorAll("[data-chart-win]").forEach((b) => {
          const on = b === btn;
          b.classList.toggle("is-active", on);
          b.setAttribute("aria-pressed", String(on));
        });
        const sum = card.querySelector("[data-chart-summary]");
        if (sum) sum.textContent = WIN_SUMMARY[win] || WIN_SUMMARY["15m"];
      });
    });
    document.querySelectorAll("[data-chart-pause]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const paused = btn.getAttribute("aria-pressed") === "true";
        const next = !paused;
        btn.setAttribute("aria-pressed", String(next));
        btn.textContent = next ? "재개" : "일시정지";
        const badge = btn.closest(".chart-panel")?.querySelector("[data-stream-badge]");
        if (badge) {
          badge.className = `cs-badge ${next ? "tone-sre" : "tone-live"}`;
          badge.innerHTML = `<span class="cs-dot"></span>${next ? "일시정지" : "LIVE"}`;
        }
      });
    });
    document.querySelectorAll("[data-series-toggle]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const next = btn.getAttribute("aria-pressed") !== "true";
        btn.setAttribute("aria-pressed", String(next));
        const key = btn.getAttribute("data-series-toggle");
        const grp = btn.closest(".chart-panel")?.querySelector(`[data-series-group="${key}"]`);
        if (grp) grp.style.display = next ? "" : "none";
      });
    });
    document.querySelectorAll("[data-tip-text]").forEach((pt) => {
      const show = () => {
        const tip = pt.closest(".chart-box")?.querySelector("[data-chart-tip]");
        if (tip) tip.textContent = pt.getAttribute("data-tip-text") || "";
      };
      pt.addEventListener("mouseenter", show);
      pt.addEventListener("focus", show);
    });
    // Subscription filter + table search/clear/status + empty state
    document.querySelectorAll("[data-sub-filter]").forEach((sel) => {
      sel.addEventListener("change", () => {
        const val = sel.value;
        const badge = document.getElementById("chatCtxBadge");
        if (badge) badge.textContent = val === "all" ? currentPanelTitle : `${currentPanelTitle} · ${val}`;
      });
    });
    document.querySelectorAll("[data-table-search], [data-table-status]").forEach((ctrl) => {
      const applyFilter = () => {
        const tblId = ctrl.getAttribute("data-table-search") || ctrl.getAttribute("data-table-status");
        const tbl = document.getElementById(tblId);
        if (!tbl) return;
        const inp = document.querySelector(`[data-table-search="${tblId}"]`);
        const clr = document.querySelector(`[data-clear-search="${tblId}"]`);
        const q = (inp?.value || "").trim().toLowerCase();
        if (clr) clr.hidden = !q;
        const st = document.querySelector(`[data-table-status="${tblId}"]`)?.value || "all";
        let visible = 0;
        tbl.querySelectorAll("tbody tr:not(.empty-row)").forEach((tr) => {
          const ok = (!q || (tr.textContent || "").toLowerCase().includes(q))
            && (st === "all" || tr.getAttribute("data-row-tone") === st);
          tr.hidden = !ok;
          if (ok) visible += 1;
        });
        const emptyRow = tbl.querySelector(`[data-empty-row="${tblId}"]`);
        if (emptyRow) emptyRow.hidden = visible > 0;
      };
      ctrl.addEventListener("input", applyFilter);
      ctrl.addEventListener("change", applyFilter);
    });
    document.querySelectorAll("[data-clear-search]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tblId = btn.getAttribute("data-clear-search");
        const inp = document.querySelector(`[data-table-search="${tblId}"]`);
        if (inp) { inp.value = ""; inp.dispatchEvent(new Event("input")); inp.focus(); }
      });
    });
    // Settings switches + dirty bar, hop depth, copy button
    document.querySelectorAll("[data-switch-toggle]").forEach((sw) => {
      sw.addEventListener("click", () => {
        const on = sw.getAttribute("aria-checked") === "true";
        sw.setAttribute("aria-checked", String(!on));
        const bar = sw.closest(".surface-card")?.querySelector("[data-dirty-bar]");
        if (bar) bar.hidden = false;
      });
    });
    document.querySelectorAll("[data-setting-control]").forEach((el) => {
      el.addEventListener("change", () => {
        const bar = el.closest(".surface-card")?.querySelector("[data-dirty-bar]");
        if (bar) bar.hidden = false;
      });
    });
    document.querySelectorAll("[data-dirty-reset], [data-dirty-save]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const bar = btn.closest("[data-dirty-bar]");
        if (bar) bar.hidden = true;
      });
    });
    document.querySelectorAll("[data-hop-depth]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const grp = btn.closest(".seg-group");
        grp?.querySelectorAll("[data-hop-depth]").forEach((b) => {
          const on = b === btn;
          b.classList.toggle("is-active", on);
          b.setAttribute("aria-pressed", String(on));
        });
      });
    });
    document.querySelectorAll("[data-copy-text]").forEach((btn) => {
      btn.addEventListener("click", () => {
        navigator.clipboard?.writeText(btn.getAttribute("data-copy-text") || "").catch(() => {});
        const orig = btn.textContent;
        btn.textContent = "복사됨";
        window.setTimeout(() => { btn.textContent = orig; }, 1200);
      });
    });
    // Detail drawer (delegated click + Enter/Space keyboard access - supports dynamic tables & cards)
    document.addEventListener("click", (e) => {
      if (!(e.target instanceof Element)) return;
      const el = e.target.closest("[data-drawer-title]");
      if (!el) return;
      openDrawerFrom(el);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      if (!(e.target instanceof Element)) return;
      const el = e.target.closest("[data-drawer-title]");
      if (!el || el.tagName === "BUTTON" || el.tagName === "A") return;
      e.preventDefault();
      openDrawerFrom(el);
    });
    document.getElementById("fdaiDrawerClose")?.addEventListener("click", closeDrawer);
    document.getElementById("fdaiDrawerDismiss")?.addEventListener("click", closeDrawer);
    document.getElementById("fdaiDrawerBackdrop")?.addEventListener("click", (e) => {
      if (e.target === e.currentTarget) closeDrawer();
    });
    document.getElementById("fdaiDrawerAskChat")?.addEventListener("click", () => {
      const t = document.getElementById("fdaiDrawerTitle")?.textContent || currentPanelTitle;
      closeDrawer();
      toggleChatSidebar(true);
      appendUserAndAgentTurn(`${t} 항목의 상세 근거와 권장 조치를 분석해 줘.`);
    });
    document.querySelectorAll("[data-open-chat-context]").forEach((b) => b.addEventListener("click", () => toggleChatSidebar(true)));
    document.querySelectorAll("[data-open-chat-dock]").forEach((b) => b.addEventListener("click", () => setChatFullscreen(false)));
    document.querySelectorAll("[data-open-chat-fullscreen]").forEach((b) => b.addEventListener("click", () => setChatFullscreen(true)));

    // v3 Luxury Workbench Interactions
    // 1) 3-Pane Master-Detail selection & combined AND search + filter chips + approval validation
    document.querySelectorAll("[data-wb-root]").forEach((wb) => {
      const items = Array.from(wb.querySelectorAll("[data-wb-item]"));
      let curFilter = "all";
      const applyWbFilter = () => {
        const q = (wb.querySelector("[data-wb-search]")?.value || "").trim().toLowerCase();
        let vis = 0;
        items.forEach((it) => {
          const ok = (curFilter === "all" || it.getAttribute("data-wb-tone") === curFilter)
            && (!q || (it.textContent || "").toLowerCase().includes(q));
          it.hidden = !ok;
          if (ok) vis += 1;
        });
        const empty = wb.querySelector("[data-wb-empty]");
        if (empty) empty.hidden = vis > 0;
      };
      items.forEach((btn) => {
        btn.addEventListener("click", () => {
          items.forEach((x) => x.classList.toggle("is-active", x === btn));
          const t = wb.querySelector("[data-wb-detail-title]");
          const sub = wb.querySelector("[data-wb-detail-sub]");
          const bodyEl = wb.querySelector("[data-wb-detail-body]");
          const badge = wb.querySelector("[data-wb-detail-badge]");
          const aiSum = wb.querySelector("[data-wb-ai-summary]");
          const kvTarget = wb.querySelector("[data-wb-kv-target]");
          const kvTime = wb.querySelector("[data-wb-kv-time]");
          const diffDel = wb.querySelector("[data-wb-diff-before]");
          const diffAdd = wb.querySelector("[data-wb-diff-after]");
          const tlEl = wb.querySelector("[data-wb-timeline]");
          const trEl = wb.querySelector("[data-wb-transcript]");
          const name = btn.getAttribute("data-wb-title") || "";
          const detail = btn.getAttribute("data-wb-body") || "";
          const ts = btn.getAttribute("data-wb-time") || "";
          if (t) t.textContent = name;
          if (sub) sub.textContent = btn.getAttribute("data-wb-sub") || "";
          if (bodyEl) bodyEl.textContent = detail;
          if (badge) {
            badge.className = `cs-badge tone-${btn.getAttribute("data-wb-tone") || "live"}`;
            badge.innerHTML = `<span class="cs-dot"></span>${btn.getAttribute("data-wb-status") || ""}`;
          }
          if (aiSum) aiSum.textContent = btn.getAttribute("data-wb-ai") || "";
          if (kvTarget) kvTarget.textContent = name;
          if (kvTime) kvTime.textContent = ts;
          if (diffDel) diffDel.textContent = `- 대상: ${name} (현재 운영 기준)`;
          if (diffAdd) diffAdd.textContent = `+ 제안: ${detail}`;
          if (tlEl) tlEl.innerHTML = `<div class="insp-kv"><span>${ts} · Heimdall</span><strong>${name} 이상 신호 감지 및 근거 수집</strong></div><div class="insp-kv"><span>${ts} · Forseti</span><strong>${detail}</strong></div>`;
          if (trEl) trEl.innerHTML = `<div class="chat-turn-user"><div class="chat-bubble-user">${name} 관련 상세 근거와 처리 상태를 알려줘.</div></div><div class="chat-turn-agent" style="margin-top:8px"><div class="agent-prose"><p><mark>${name}</mark> 분석 결과: ${detail}. 감사 원장 대조 및 정책 위반 0건 확인 완료.</p></div></div>`;
        });
        btn.addEventListener("keydown", (e) => {
          if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
          e.preventDefault();
          const vis = items.filter((x) => !x.hidden);
          const idx = vis.indexOf(btn);
          const next = vis[e.key === "ArrowDown" ? Math.min(vis.length - 1, idx + 1) : Math.max(0, idx - 1)];
          if (next) { next.focus(); next.click(); }
        });
      });
      wb.querySelectorAll("[data-wb-filter]").forEach((chip) => {
        chip.addEventListener("click", () => {
          curFilter = chip.getAttribute("data-wb-filter") || "all";
          wb.querySelectorAll("[data-wb-filter]").forEach((c) => c.classList.toggle("is-active", c === chip));
          applyWbFilter();
        });
      });
      wb.querySelector("[data-wb-search]")?.addEventListener("input", applyWbFilter);
      wb.querySelector("[data-wb-reset]")?.addEventListener("click", () => {
        curFilter = "all";
        const inp = wb.querySelector("[data-wb-search]");
        if (inp) inp.value = "";
        wb.querySelectorAll("[data-wb-filter]").forEach((c) => c.classList.toggle("is-active", c.getAttribute("data-wb-filter") === "all"));
        applyWbFilter();
      });
      // Approval/Reject reason validation + live char count
      const reasonEl = wb.querySelector("[data-approval-reason]");
      const countEl = wb.querySelector("[data-approval-count]");
      reasonEl?.addEventListener("input", () => {
        if (countEl) countEl.textContent = `${reasonEl.value.length} / 2000`;
      });
      wb.querySelectorAll("[data-approval-action]").forEach((ab) => {
        ab.addEventListener("click", () => {
          const act = ab.getAttribute("data-approval-action");
          const txt = (reasonEl?.value || "").trim();
          if (!txt) {
            showToast("사유를 1자 이상 입력해야 기록할 수 있습니다 (침묵 시 자동 거부).");
            reasonEl?.focus();
            return;
          }
          showToast(`${act === "approve" ? "승인" : "거절"} 사유 검증 완료 (시안 모드 · 실제 Azure 변경 미실행)`);
        });
      });
    });

    // 2) Interactive Graph & Ontology 4-View switcher + node inspector
    document.querySelectorAll("[data-graph-wb]").forEach((gwb) => {
      gwb.querySelectorAll("[data-graph-view-btn]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const v = btn.getAttribute("data-graph-view-btn");
          gwb.querySelectorAll("[data-graph-view-btn]").forEach((b) => {
            const on = b === btn;
            b.classList.toggle("is-active", on);
            b.setAttribute("aria-selected", String(on));
          });
          const ontoGrid = gwb.querySelector("[data-onto-grid]");
          if (ontoGrid) ontoGrid.hidden = (v === "knowledge" || v === "lineage");
          gwb.querySelectorAll("[data-tree-mode]").forEach((tm) => {
            const want = v === "lineage" ? "lineage" : "instance";
            tm.hidden = tm.getAttribute("data-tree-mode") !== want;
          });
          gwb.querySelectorAll("[data-graph-view-pane]").forEach((p) => {
            p.hidden = p.getAttribute("data-graph-view-pane") !== v;
          });
        });
      });
      // Live 1-Hop / 2-Hop / 3-Hop selector for Blast Radius
      gwb.querySelectorAll("[data-hop-btn]").forEach((hb) => {
        hb.addEventListener("click", () => {
          const hop = parseInt(hb.getAttribute("data-hop-btn") || "1", 10);
          gwb.querySelectorAll("[data-hop-btn]").forEach((b) => {
            const on = b === hb;
            b.classList.toggle("is-active", on);
            b.setAttribute("aria-pressed", String(on));
          });
          gwb.querySelectorAll("[data-hop-ring]").forEach((el) => {
            const r = parseInt(el.getAttribute("data-hop-ring") || "1", 10);
            el.style.opacity = r <= hop ? "1" : "0.22";
          });
          showToast(`${hop}-Hop 영향 반경 시뮬레이션 표시 중`);
        });
      });
      const selectNode = (el) => {
        gwb.querySelectorAll("[data-gnode-name]").forEach((n) => n.classList.toggle("is-selected", n === el));
        gwb.querySelectorAll(".tree-node-btn").forEach((n) => n.classList.toggle("is-active", n === el));
        const nameEl = gwb.querySelector("[data-ginsp-name]");
        const typeEl = gwb.querySelector("[data-ginsp-type]");
        const statusEl = gwb.querySelector("[data-ginsp-status]");
        const lineageEl = gwb.querySelector("[data-ginsp-lineage]");
        const noteEl = gwb.querySelector("[data-ginsp-note]");
        if (nameEl) nameEl.textContent = el.getAttribute("data-gnode-name") || "";
        if (typeEl) typeEl.textContent = el.getAttribute("data-gnode-type") || "";
        if (statusEl) statusEl.textContent = el.getAttribute("data-gnode-status") || "";
        if (lineageEl) lineageEl.textContent = el.getAttribute("data-gnode-lineage") || "";
        if (noteEl) noteEl.textContent = el.getAttribute("data-gnode-note") || "";
        const cSum = document.getElementById("chatInspSummary");
        if (cSum) cSum.textContent = `선택 리소스(${el.getAttribute("data-gnode-name") || ""}): ${el.getAttribute("data-gnode-note") || ""}`;
        // Highlight connected SVG edges when clicking a resource node with data-gnode-id
        const nid = el.getAttribute("data-gnode-id");
        const stage = el.closest(".svg-graph-stage");
        if (nid && stage) {
          stage.classList.add("has-focus");
          const connectedIds = new Set([nid]);
          stage.querySelectorAll(".svg-edge-group").forEach((eg) => {
            const s = eg.getAttribute("data-edge-src");
            const t = eg.getAttribute("data-edge-dst");
            const hit = s === nid || t === nid;
            eg.classList.toggle("is-connected", hit);
            if (hit) { if (s) connectedIds.add(s); if (t) connectedIds.add(t); }
          });
          stage.querySelectorAll(".graph-node[data-gnode-id]").forEach((gn) => {
            gn.classList.toggle("is-connected", connectedIds.has(gn.getAttribute("data-gnode-id")));
          });
        }
      };
      gwb.querySelectorAll("[data-gnode-name]").forEach((el) => {
        el.addEventListener("click", () => selectNode(el));
        el.addEventListener("keydown", (e) => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectNode(el); }
        });
      });
      // Live SVG edge-kind filter checkboxes & Zoom controls
      gwb.querySelectorAll("[data-svg-edge-filter]").forEach((cb) => {
        cb.addEventListener("change", () => {
          const k = cb.getAttribute("data-svg-edge-filter");
          gwb.querySelectorAll(`.svg-edge-group[data-edge-kind="${k}"]`).forEach((eg) => {
            eg.style.display = cb.checked ? "" : "none";
          });
        });
      });
      gwb.querySelectorAll("[data-svg-zoom]").forEach((zbtn) => {
        zbtn.addEventListener("click", () => {
          const stage = zbtn.closest("[data-graph-view-pane]")?.querySelector(".svg-graph-stage") || gwb.querySelector(".svg-graph-stage");
          const svg = stage?.querySelector("svg");
          if (!svg) return;
          const act = zbtn.getAttribute("data-svg-zoom");
          let cur = parseFloat(svg.getAttribute("data-zoom") || "1");
          if (act === "in") cur = Math.min(1.6, cur + 0.15);
          else if (act === "out") cur = Math.max(0.75, cur - 0.15);
          else {
            cur = 1;
            stage.classList.remove("has-focus");
          }
          svg.setAttribute("data-zoom", cur.toFixed(2));
          const vbW = parseFloat(svg.getAttribute("data-orig-vbw") || "920");
          const vbH = parseFloat(svg.getAttribute("data-orig-vbh") || "440");
          const cap = 1.10 * cur;
          svg.style.maxWidth = `${Math.round(vbW * cap)}px`;
          svg.style.maxHeight = `${Math.round(vbH * cap)}px`;
          svg.style.width = cur > 1 ? `${Math.round(vbW * cap)}px` : "100%";
        });
      });
    });

    // 3) Waterfall span selection <-> bidirectional Data Lineage highlight
    document.querySelectorAll("[data-wf-root]").forEach((wfr) => {
      const highlightStep = (step) => {
        wfr.querySelectorAll("[data-lineage-step]").forEach((el) => {
          el.classList.toggle("is-active", el.getAttribute("data-lineage-step") === step);
        });
      };
      wfr.querySelectorAll("[data-wf-span]").forEach((row) => {
        row.addEventListener("click", () => {
          wfr.querySelectorAll("[data-wf-span]").forEach((r) => r.classList.toggle("is-active", r === row));
          const title = wfr.querySelector("[data-wf-sel-title]");
          const meta = wfr.querySelector("[data-wf-sel-meta]");
          const bodyEl = wfr.querySelector("[data-wf-sel-body]");
          if (title) title.textContent = row.getAttribute("data-wf-title") || "";
          if (meta) meta.textContent = row.getAttribute("data-wf-meta") || "";
          if (bodyEl) bodyEl.textContent = row.getAttribute("data-wf-body") || "";
          highlightStep(row.getAttribute("data-wf-step") || "");
        });
      });
      wfr.querySelectorAll("[data-lineage-step]").forEach((ls) => {
        ls.addEventListener("click", () => {
          const step = ls.getAttribute("data-lineage-step") || "";
          const match = wfr.querySelector(`[data-wf-step="${step}"]`);
          if (match) match.click();
        });
      });
    });

    // 3b) Interactive Handover Checkboxes, Heatmap cell readout, Export/Copy toast, Settings snapshot restore
    document.querySelectorAll("[data-handover-check]").forEach((cb) => {
      cb.addEventListener("change", () => {
        cb.closest(".check-row")?.classList.toggle("is-done", cb.checked);
        const root = cb.closest("[data-handover-list]");
        if (!root) return;
        const all = root.querySelectorAll("[data-handover-check]");
        const done = Array.from(all).filter((x) => x.checked).length;
        const prog = root.querySelector("[data-handover-progress]");
        if (prog) prog.textContent = `${done} / ${all.length} 완료`;
        showToast(`인수인계 체크리스트 업데이트 (${done}/${all.length} 완료)`);
      });
    });
    document.querySelectorAll(".hm-cell[data-hm-info]").forEach((cell) => {
      const show = () => {
        const out = cell.closest(".surface-card")?.querySelector("[data-hm-readout]");
        if (out) out.textContent = cell.getAttribute("data-hm-info") || "";
      };
      cell.addEventListener("mouseenter", show);
      cell.addEventListener("click", show);
    });
    document.querySelectorAll("[data-toast-msg]").forEach((btn) => {
      btn.addEventListener("click", () => showToast(btn.getAttribute("data-toast-msg") || "완료되었습니다."));
    });
    document.querySelectorAll("[data-setting-control]").forEach((ctrl) => {
      if (!ctrl.hasAttribute("data-initial-val")) ctrl.setAttribute("data-initial-val", ctrl.value);
      ctrl.addEventListener("change", () => {
        const bar = ctrl.closest(".settings-body")?.querySelector("[data-dirty-bar]");
        if (bar) bar.hidden = false;
      });
    });
    document.querySelectorAll("[data-dirty-reset]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const body = btn.closest(".settings-body");
        body?.querySelectorAll("[data-setting-control]").forEach((c) => {
          c.value = c.getAttribute("data-initial-val") || c.value;
        });
        body?.querySelectorAll("[data-switch-toggle]").forEach((sw) => {
          const orig = sw.getAttribute("data-initial-checked") || "true";
          sw.setAttribute("aria-checked", orig);
        });
        const bar = body?.querySelector("[data-dirty-bar]");
        if (bar) bar.hidden = true;
        showToast("변경 사항을 원래 설정으로 되돌렸습니다.");
      });
    });
    document.querySelectorAll("[data-dirty-save]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const bar = btn.closest("[data-dirty-bar]");
        if (bar) bar.hidden = true;
        showToast("설정 변경 사항이 저장되었습니다 (시안 모드 · 실제 운영 미반영).");
      });
    });

    // 4) Faceted rail table filtering
    document.querySelectorAll("[data-facet-root]").forEach((fr) => {
      fr.querySelectorAll("[data-facet-tone]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const tone = btn.getAttribute("data-facet-tone") || "all";
          fr.querySelectorAll("[data-facet-tone]").forEach((b) => b.classList.toggle("is-active", b === btn));
          fr.querySelectorAll("tbody tr:not(.empty-row)").forEach((tr) => {
            tr.hidden = tone !== "all" && tr.getAttribute("data-row-tone") !== tone;
          });
        });
      });
    });

    // 5) Kanban / Schedule view switcher & Chaos trigger feedback
    document.querySelectorAll("[data-mode-switch-btn]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const grp = btn.closest("[data-mode-switch-root]");
        const key = btn.getAttribute("data-mode-switch-btn");
        if (!grp) return;
        grp.querySelectorAll("[data-mode-switch-btn]").forEach((b) => {
          const on = b === btn;
          b.classList.toggle("is-active", on);
          b.setAttribute("aria-pressed", String(on));
        });
        grp.querySelectorAll("[data-mode-switch-pane]").forEach((p) => {
          p.hidden = p.getAttribute("data-mode-switch-pane") !== key;
        });
      });
    });
    document.querySelectorAll("[data-chaos-btn]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const out = btn.closest(".surface-card")?.querySelector("[data-chaos-status]");
        if (out) out.textContent = `시뮬레이션 실행됨: ${btn.getAttribute("data-chaos-btn")} (개발 전용 격리 범위 · 운영 무영향)`;
        showToast(btn.getAttribute("data-chaos-btn") || "시뮬레이션 실행 완료");
      });
    });
    document.querySelectorAll("[data-rca-toggle-excluded]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const grp = btn.closest(".surface-card")?.querySelector("[data-rca-excluded-group]");
        if (!grp) return;
        const nextHidden = !grp.hidden;
        grp.hidden = nextHidden;
        btn.textContent = nextHidden ? "원인 제외 이벤트 펼치기 (2)" : "원인 제외 이벤트 접기";
      });
    });
    document.querySelectorAll("[data-yaml-toggle]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const box = btn.closest(".graph-wb")?.querySelector("[data-yaml-preview]");
        if (box) box.hidden = !box.hidden;
      });
    });
    document.querySelectorAll("[data-settings-scope]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const sc = btn.getAttribute("data-settings-scope");
        document.querySelectorAll("[data-settings-scope]").forEach((b) => b.classList.toggle("is-active", b === btn));
        const targetId = sc === "labs" ? "labs" : "settings-general";
        navigatePanel(targetId, false);
      });
    });

    initOntologyKnowledgeGraph();
  }

  // Exact reusable HTML5 Canvas 2D Community Knowledge Graph engine matching Console Web (`ontology-knowledge-graph.renderer.ts`)
  function initOntologyKnowledgeGraph() {
    const canvas = document.getElementById("fdaiOntologyKgCanvas");
    const viewport = document.getElementById("fdaiOntologyKgViewport");
    if (!canvas || !viewport) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const NODE_STYLES = {
      object_type: { label: "ObjectType", fill: "#44688e" },
      interface_type: { label: "InterfaceType", fill: "#57758f" },
      function_type: { label: "FunctionType", fill: "#9b7048" },
      resource_type: { label: "ResourceType", fill: "#4f847e" },
      rule: { label: "Rule", fill: "#7b6c9c" },
      action_type: { label: "ActionType", fill: "#bc7449" },
      workflow: { label: "Workflow", fill: "#a58a4a" },
      agent: { label: "Agent", fill: "#5e8259" },
      signal_type: { label: "SignalType", fill: "#a65d67" },
      property: { label: "Property", fill: "#6e747b" }
    };
    const NODE_GLYPHS = {
      object_type: "O",
      resource_type: "R",
      agent: "A",
      rule: "G",
      action_type: "X",
      workflow: "W",
      signal_type: "S",
      function_type: "f",
      interface_type: "I",
      property: "P"
    };
    function drawCrispRoundRect(c, x, y, w, h, r) {
      const rx = Math.round(x) + 0.5;
      const ry = Math.round(y) + 0.5;
      const rw = Math.round(w);
      const rh = Math.round(h);
      const rr = Math.min(r, rw / 2, rh / 2);
      c.beginPath();
      c.moveTo(rx + rr, ry);
      c.arcTo(rx + rw, ry, rx + rw, ry + rh, rr);
      c.arcTo(rx + rw, ry + rh, rx, ry + rh, rr);
      c.arcTo(rx, ry + rh, rx, ry, rr);
      c.arcTo(rx, ry, rx + rw, ry, rr);
      c.closePath();
    }
    const EDGE_COLORS = {
      link_type: "#4f847e",
      interface: "#57758f",
      instance_of: "#a5a8ab",
      rule_dispatch: "#6f88a5",
      workflow: "#7b6c9c",
      agent: "#bc7449"
    };

    // 48 canonical FDAI Ontology nodes clustered into 5 real domain communities
    const nodes = [
      // C0: Core ObjectTypes & ResourceTypes (center-left)
      { id: "ot:Resource", label: "Resource", kind: "object_type", community: 0, x: -210, y: -30 },
      { id: "ot:BusinessService", label: "BusinessService", kind: "object_type", community: 0, x: -330, y: -115 },
      { id: "ot:Deployment", label: "Deployment", kind: "object_type", community: 0, x: -340, y: 50 },
      { id: "ot:Incident", label: "Incident", kind: "object_type", community: 0, x: -115, y: -135 },
      { id: "ot:ChangeRecord", label: "ChangeRecord", kind: "object_type", community: 0, x: -245, y: 120 },
      { id: "rt:aks", label: "kubernetes-cluster", kind: "resource_type", community: 0, x: -415, y: -35 },
      { id: "rt:postgres", label: "postgresql-flexible", kind: "resource_type", community: 0, x: -410, y: 110 },
      { id: "rt:keyvault", label: "key-vault", kind: "resource_type", community: 0, x: -310, y: 185 },
      { id: "rt:redis", label: "redis-cache", kind: "resource_type", community: 0, x: -165, y: 185 },
      { id: "if:Observable", label: "ObservableResource", kind: "interface_type", community: 0, x: -255, y: -185 },
      { id: "prop:recorded_state", label: "recorded_state", kind: "property", community: 0, x: -130, y: 75 },
      // C1: 15-Agent Pantheon & Control Loop (top-right)
      { id: "ag:Odin", label: "Odin (Orchestrator)", kind: "agent", community: 1, x: 185, y: -175 },
      { id: "ag:Heimdall", label: "Heimdall (Detect)", kind: "agent", community: 1, x: 55, y: -230 },
      { id: "ag:Forseti", label: "Forseti (Policy)", kind: "agent", community: 1, x: 195, y: -60 },
      { id: "ag:Var", label: "Var (HIL Approval)", kind: "agent", community: 1, x: 320, y: -120 },
      { id: "ag:Thor", label: "Thor (Executor)", kind: "agent", community: 1, x: 350, y: -25 },
      { id: "ag:Vidar", label: "Vidar (Verifier)", kind: "agent", community: 1, x: 265, y: 35 },
      { id: "ag:Muninn", label: "Muninn (Ontology)", kind: "agent", community: 1, x: 65, y: -120 },
      { id: "ag:Saga", label: "Saga (Audit Ledger)", kind: "agent", community: 1, x: 145, y: 20 },
      { id: "ag:Freyr", label: "Freyr (Forecast)", kind: "agent", community: 1, x: 310, y: -230 },
      { id: "ag:Njord", label: "Njord (FinOps)", kind: "agent", community: 1, x: 185, y: -265 },
      // C2: Rules, Policies & Safety Gates (bottom-right)
      { id: "rl:aks_cpu", label: "rule.aks.cpu_saturation", kind: "rule", community: 2, x: 120, y: 155 },
      { id: "rl:pg_pool", label: "rule.pg.pool_exhaustion", kind: "rule", community: 2, x: 260, y: 145 },
      { id: "rl:kv_exp", label: "rule.kv.temp_ip_expiry", kind: "rule", community: 2, x: 365, y: 125 },
      { id: "rl:policy_zero", label: "rule.policy_escape_zero", kind: "rule", community: 2, x: 215, y: 240 },
      { id: "fn:ewma", label: "fn.ewma_horizon_14d", kind: "function_type", community: 2, x: 345, y: 225 },
      { id: "fn:blast", label: "fn.blast_radius_hop", kind: "function_type", community: 2, x: 95, y: 245 },
      { id: "if:RiskGated", label: "RiskGatedAction", kind: "interface_type", community: 2, x: 20, y: 185 },
      // C3: Telemetry, Data Lineage & Signals (top-left)
      { id: "sig:cpu_p95", label: "sig.aks_cpu_p95", kind: "signal_type", community: 3, x: -75, y: -260 },
      { id: "sig:pg_conn", label: "sig.pg_active_conn", kind: "signal_type", community: 3, x: -195, y: -275 },
      { id: "sig:kv_audit", label: "sig.kv_access_drift", kind: "signal_type", community: 3, x: -325, y: -255 },
      { id: "ot:SLO", label: "SLOObjective", kind: "object_type", community: 3, x: -425, y: -175 },
      { id: "ot:Lineage", label: "orders_slo_hourly", kind: "object_type", community: 3, x: -155, y: -195 },
      { id: "prop:freshness", label: "freshness_sec", kind: "property", community: 3, x: -40, y: -195 },
      // C4: ActionTypes & Workflows (bottom-center)
      { id: "act:scale_aks", label: "aks.scale_node_pool", kind: "action_type", community: 4, x: -45, y: 105 },
      { id: "act:pg_pool", label: "pg.adjust_pool_size", kind: "action_type", community: 4, x: -115, y: 255 },
      { id: "act:kv_revoke", label: "kv.revoke_temp_ip", kind: "action_type", community: 4, x: -245, y: 265 },
      { id: "wf:sre_relief", label: "wf.pg_pool_relief", kind: "workflow", community: 4, x: -10, y: 270 },
      { id: "wf:aks_scale", label: "wf.aks_autoscale_gate", kind: "workflow", community: 4, x: -185, y: 315 },
      { id: "ot:AuditReceipt", label: "AuditReceipt (SHA-256)", kind: "object_type", community: 4, x: 45, y: 45 }
    ];

    const edges = [
      { id: "e1", source: "ot:BusinessService", target: "ot:Resource", kind: "link_type", label: "owns" },
      { id: "e2", source: "ot:Deployment", target: "ot:Resource", kind: "link_type", label: "deploys_to" },
      { id: "e3", source: "ot:Incident", target: "ot:Resource", kind: "link_type", label: "affects" },
      { id: "e4", source: "ot:ChangeRecord", target: "ot:Resource", kind: "link_type", label: "modifies" },
      { id: "e5", source: "rt:aks", target: "ot:Resource", kind: "instance_of", label: "instance_of" },
      { id: "e6", source: "rt:postgres", target: "ot:Resource", kind: "instance_of", label: "instance_of" },
      { id: "e7", source: "rt:keyvault", target: "ot:Resource", kind: "instance_of", label: "instance_of" },
      { id: "e8", source: "rt:redis", target: "ot:Resource", kind: "instance_of", label: "instance_of" },
      { id: "e9", source: "rt:aks", target: "rt:postgres", kind: "link_type", label: "depends_on" },
      { id: "e10", source: "rt:aks", target: "rt:redis", kind: "link_type", label: "caches_in" },
      { id: "e11", source: "rt:aks", target: "rt:keyvault", kind: "link_type", label: "reads_secret" },
      { id: "e12", source: "ot:Resource", target: "if:Observable", kind: "interface", label: "implements" },
      { id: "e13", source: "ot:Resource", target: "prop:recorded_state", kind: "link_type", label: "has_property" },
      { id: "e14", source: "ot:Resource", target: "ot:Resource", kind: "link_type", label: "depends_on" },
      { id: "e15", source: "ot:BusinessService", target: "ot:SLO", kind: "link_type", label: "measured_by" },
      { id: "e16", source: "sig:cpu_p95", target: "ot:Lineage", kind: "link_type", label: "feeds" },
      { id: "e17", source: "sig:pg_conn", target: "ot:Lineage", kind: "link_type", label: "feeds" },
      { id: "e18", source: "sig:kv_audit", target: "ot:Incident", kind: "link_type", label: "triggers" },
      { id: "e19", source: "ot:Lineage", target: "ot:SLO", kind: "link_type", label: "computes" },
      { id: "e20", source: "ot:Lineage", target: "prop:freshness", kind: "link_type", label: "tracks" },
      { id: "e21", source: "ag:Heimdall", target: "sig:cpu_p95", kind: "agent", label: "observes" },
      { id: "e22", source: "ag:Heimdall", target: "ot:Incident", kind: "agent", label: "detects" },
      { id: "e23", source: "ag:Muninn", target: "ot:Resource", kind: "agent", label: "snapshots" },
      { id: "e24", source: "ag:Odin", target: "ag:Heimdall", kind: "agent", label: "orchestrates" },
      { id: "e25", source: "ag:Odin", target: "ag:Forseti", kind: "agent", label: "orchestrates" },
      { id: "e26", source: "ag:Odin", target: "ag:Var", kind: "agent", label: "orchestrates" },
      { id: "e27", source: "ag:Odin", target: "ag:Freyr", kind: "agent", label: "orchestrates" },
      { id: "e28", source: "ag:Odin", target: "ag:Njord", kind: "agent", label: "orchestrates" },
      { id: "e29", source: "ag:Heimdall", target: "ag:Forseti", kind: "agent", label: "pub_sub" },
      { id: "e30", source: "ag:Forseti", target: "ag:Var", kind: "agent", label: "routes_a3" },
      { id: "e31", source: "ag:Var", target: "ag:Thor", kind: "agent", label: "approves" },
      { id: "e32", source: "ag:Thor", target: "ag:Vidar", kind: "agent", label: "verifies" },
      { id: "e33", source: "ag:Vidar", target: "ag:Saga", kind: "agent", label: "seals" },
      { id: "e34", source: "ag:Saga", target: "ot:AuditReceipt", kind: "agent", label: "appends" },
      { id: "e35", source: "ag:Freyr", target: "fn:ewma", kind: "agent", label: "evaluates" },
      { id: "e36", source: "ag:Forseti", target: "rl:aks_cpu", kind: "rule_dispatch", label: "evaluates" },
      { id: "e37", source: "ag:Forseti", target: "rl:pg_pool", kind: "rule_dispatch", label: "evaluates" },
      { id: "e38", source: "ag:Forseti", target: "rl:kv_exp", kind: "rule_dispatch", label: "evaluates" },
      { id: "e39", source: "ag:Forseti", target: "rl:policy_zero", kind: "rule_dispatch", label: "enforces" },
      { id: "e40", source: "rl:aks_cpu", target: "act:scale_aks", kind: "rule_dispatch", label: "proposes" },
      { id: "e41", source: "rl:pg_pool", target: "act:pg_pool", kind: "rule_dispatch", label: "proposes" },
      { id: "e42", source: "rl:kv_exp", target: "act:kv_revoke", kind: "rule_dispatch", label: "proposes" },
      { id: "e43", source: "rl:pg_pool", target: "fn:blast", kind: "rule_dispatch", label: "checks_hop" },
      { id: "e44", source: "act:scale_aks", target: "if:RiskGated", kind: "interface", label: "implements" },
      { id: "e45", source: "act:pg_pool", target: "if:RiskGated", kind: "interface", label: "implements" },
      { id: "e46", source: "act:kv_revoke", target: "if:RiskGated", kind: "interface", label: "implements" },
      { id: "e47", source: "wf:sre_relief", target: "act:pg_pool", kind: "workflow", label: "runs_shadow" },
      { id: "e48", source: "wf:aks_scale", target: "act:scale_aks", kind: "workflow", label: "runs_shadow" },
      { id: "e49", source: "wf:sre_relief", target: "ot:AuditReceipt", kind: "workflow", label: "records" },
      { id: "e50", source: "act:scale_aks", target: "ot:Resource", kind: "link_type", label: "targets" },
      { id: "e51", source: "act:pg_pool", target: "rt:postgres", kind: "link_type", label: "targets" },
      { id: "e52", source: "act:kv_revoke", target: "rt:keyvault", kind: "link_type", label: "targets" },
      { id: "e53", source: "ot:Lineage", target: "rl:aks_cpu", kind: "rule_dispatch", label: "inputs" },
      { id: "e54", source: "ot:AuditReceipt", target: "ot:Incident", kind: "link_type", label: "evidences" }
    ];

    const nodeById = new Map();
    const adj = new Map();
    nodes.forEach((n) => { n.degree = 0; nodeById.set(n.id, n); adj.set(n.id, []); });
    edges.forEach((e) => {
      const s = nodeById.get(e.source);
      const t = nodeById.get(e.target);
      if (s && t) {
        s.degree += 1;
        t.degree += 1;
        adj.get(e.source).push(e);
        if (e.source !== e.target) adj.get(e.target).push(e);
      }
    });

    const enabledEdges = new Set(Object.keys(EDGE_COLORS));
    let selectedId = "ot:Resource";
    let hoveredId = null;
    const camera = { x: 0, y: 0, scale: 1 };
    let gesture = null;

    function nodeRadius(n) { return Math.min(18, 6.2 + Math.sqrt(n.degree) * 2.5); }
    function worldToScreen(pt) { return { x: pt.x * camera.scale + camera.x, y: pt.y * camera.scale + camera.y }; }
    function screenToWorld(pt) { return { x: (pt.x - camera.x) / camera.scale, y: (pt.y - camera.y) / camera.scale }; }

    function convexHull(pts) {
      if (pts.length <= 2) return pts;
      const s = [...pts].sort((a, b) => a.x - b.x || a.y - b.y);
      const cross = (o, a, b) => (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
      const lo = [];
      for (const p of s) { while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], p) <= 0) lo.pop(); lo.push(p); }
      const hi = [];
      for (let i = s.length - 1; i >= 0; i--) { const p = s[i]; while (hi.length >= 2 && cross(hi[hi.length - 2], hi[hi.length - 1], p) <= 0) hi.pop(); hi.push(p); }
      hi.pop(); lo.pop();
      return lo.concat(hi);
    }

    function palette() {
      const dark = document.documentElement.getAttribute("data-theme") === "dark";
      return {
        bg: dark ? "#0f1114" : "#fbfaf9",
        fg: dark ? "#f0f2f4" : "#1f2937",
        muted: dark ? "#9ca3af" : "#59616a",
        selected: dark ? "#2dd4bf" : "#0f766e",
        hovered: dark ? "#c5d0da" : "#4b5563",
        labelBg: dark ? "rgba(18,20,24,.92)" : "rgba(255,255,255,.92)",
        nodeStroke: dark ? "#16191e" : "#ffffff",
        grid: dark ? "rgba(139,183,223,.075)" : "rgba(68,104,142,.06)",
        hull: dark ? "rgba(45,212,191,.04)" : "rgba(68,104,142,.03)",
        hullStroke: dark ? "rgba(139,183,223,.22)" : "rgba(68,104,142,.18)",
        selectedHull: dark ? "rgba(45,212,191,.10)" : "rgba(15,118,110,.07)"
      };
    }

    function fit() {
      const r = viewport.getBoundingClientRect();
      if (r.width < 10 || r.height < 10) return;
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
      nodes.forEach((n) => {
        if (n.x < minX) minX = n.x; if (n.x > maxX) maxX = n.x;
        if (n.y < minY) minY = n.y; if (n.y > maxY) maxY = n.y;
      });
      const pad = 74;
      const sx = (r.width - pad * 2) / Math.max(1, maxX - minX);
      const sy = (r.height - pad * 2) / Math.max(1, maxY - minY);
      camera.scale = Math.max(0.45, Math.min(1.25, Math.min(sx, sy)));
      camera.x = r.width / 2 - ((minX + maxX) / 2) * camera.scale;
      camera.y = r.height / 2 - ((minY + maxY) / 2) * camera.scale;
      draw();
    }

    function focusNode(id) {
      const n = nodeById.get(id);
      if (!n) return;
      selectedId = id;
      const r = viewport.getBoundingClientRect();
      camera.scale = Math.max(camera.scale, 0.95);
      camera.x = r.width / 2 - n.x * camera.scale;
      camera.y = r.height / 2 - n.y * camera.scale;
      updateInspector();
      draw();
    }

    function updateInspector() {
      const n = nodeById.get(selectedId);
      const nameEl = document.getElementById("ontoKgInspName");
      const kindEl = document.getElementById("ontoKgInspKind");
      const commEl = document.getElementById("ontoKgInspComm");
      const degEl = document.getElementById("ontoKgInspDeg");
      const relList = document.getElementById("ontoKgInspRels");
      if (!n || !nameEl) return;
      const st = NODE_STYLES[n.kind] || { label: n.kind, fill: "#44688e" };
      nameEl.textContent = n.label;
      if (kindEl) kindEl.textContent = st.label;
      if (commEl) commEl.textContent = `C${n.community} 커뮤니티`;
      if (degEl) degEl.textContent = `${n.degree}개 연결`;
      if (relList) {
        const rels = (adj.get(n.id) || []).filter((e) => enabledEdges.has(e.kind));
        relList.innerHTML = rels.map((e) => {
          const out = e.source === n.id;
          const otherId = out ? e.target : e.source;
          const other = nodeById.get(otherId);
          return `<button type="button" class="insp-action-item" data-kg-jump="${otherId}"><span>${out ? "→" : "←"} <strong>${e.label}</strong> · ${other ? other.label : otherId}</span><span>이동</span></button>`;
        }).join("") || `<div class="wb-item-sub">표시된 관계 필터에 해당하는 연결이 없습니다.</div>`;
        relList.querySelectorAll("[data-kg-jump]").forEach((btn) => {
          btn.addEventListener("click", () => focusNode(btn.getAttribute("data-kg-jump")));
        });
      }
    }

    function visualNodeState(n) {
      if (n.id === selectedId) return "selected";
      if (n.id === hoveredId) return "hovered";
      if (!selectedId) return "normal";
      const rels = adj.get(selectedId) || [];
      return rels.some((e) => enabledEdges.has(e.kind) && (e.source === n.id || e.target === n.id)) ? "related" : "muted";
    }

    function draw() {
      const r = viewport.getBoundingClientRect();
      if (r.width < 10 || r.height < 10) return;
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      if (canvas.width !== Math.round(r.width * dpr) || canvas.height !== Math.round(r.height * dpr)) {
        canvas.width = Math.round(r.width * dpr);
        canvas.height = Math.round(r.height * dpr);
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const pal = palette();
      ctx.fillStyle = pal.bg;
      ctx.fillRect(0, 0, r.width, r.height);

      // 1) Precision micro-dot blueprint grid (camera-synced, zero visual clutter)
      const spacing = Math.max(20, 44 * camera.scale);
      const ox = ((camera.x % spacing) + spacing) % spacing;
      const oy = ((camera.y % spacing) + spacing) % spacing;
      ctx.fillStyle = pal.grid;
      for (let x = ox; x < r.width; x += spacing) {
        const px = Math.round(x);
        for (let y = oy; y < r.height; y += spacing) {
          ctx.fillRect(px, Math.round(y), 1.5, 1.5);
        }
      }

      // 2) Smooth quadratic-spline community contours
      const groups = new Map();
      nodes.forEach((n) => {
        const arr = groups.get(n.community) || [];
        arr.push(worldToScreen(n));
        groups.set(n.community, arr);
      });
      const selComm = selectedId ? nodeById.get(selectedId)?.community : null;
      groups.forEach((pts, c) => {
        const base = convexHull(pts);
        if (base.length < 3) return;
        const cx = base.reduce((s, p) => s + p.x, 0) / base.length;
        const cy = base.reduce((s, p) => s + p.y, 0) / base.length;
        const hull = base.map((p) => {
          const dx = p.x - cx, dy = p.y - cy, d = Math.max(1, Math.hypot(dx, dy));
          return { x: p.x + (dx / d) * 26, y: p.y + (dy / d) * 26 };
        });
        ctx.beginPath();
        const len = hull.length;
        const m0x = (hull[len - 1].x + hull[0].x) / 2;
        const m0y = (hull[len - 1].y + hull[0].y) / 2;
        ctx.moveTo(m0x, m0y);
        for (let i = 0; i < len; i++) {
          const cur = hull[i];
          const nxt = hull[(i + 1) % len];
          ctx.quadraticCurveTo(cur.x, cur.y, (cur.x + nxt.x) / 2, (cur.y + nxt.y) / 2);
        }
        ctx.closePath();
        ctx.fillStyle = c === selComm ? pal.selectedHull : pal.hull;
        ctx.fill();
        ctx.setLineDash([4, 5]);
        ctx.strokeStyle = c === selComm ? pal.selected : pal.hullStroke;
        ctx.lineWidth = c === selComm ? 1.4 : 1;
        ctx.stroke();
        ctx.setLineDash([]);
        const top = hull.reduce((a, b) => b.y < a.y ? b : a);
        const tag = `C${c} · ${pts.length}`;
        ctx.font = "600 12px 'Cascadia Code', monospace";
        const tw = ctx.measureText(tag).width + 10;
        drawCrispRoundRect(ctx, top.x - 2, top.y - 20, tw, 18, 3);
        ctx.fillStyle = pal.labelBg;
        ctx.fill();
        ctx.strokeStyle = c === selComm ? pal.selected : pal.hullStroke;
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        ctx.fillStyle = pal.muted;
        ctx.fillText(tag, top.x + 3, top.y - 11);
      });

      // 3) Quadratic curved directional edges with delicate micro-arrowheads & non-overlapping labels
      const edgeLabelBoxes = [];
      edges.forEach((e) => {
        if (!enabledEdges.has(e.kind)) return;
        const sn = nodeById.get(e.source), tn = nodeById.get(e.target);
        if (!sn || !tn) return;
        const sp = worldToScreen(sn), tp = worldToScreen(tn);
        const rel = !selectedId ? "normal" : (e.source === selectedId || e.target === selectedId ? "related" : "muted");
        const color = EDGE_COLORS[e.kind] || "#4f847e";
        ctx.save();
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.globalAlpha = rel === "related" ? 0.78 : rel === "muted" ? 0.04 : 0.2;
        ctx.lineWidth = rel === "related" ? 1.35 : 0.85;
        if (e.source === e.target) {
          const rad = nodeRadius(sn) * Math.min(1.15, Math.max(0.65, camera.scale)) + 10;
          ctx.beginPath();
          ctx.arc(sp.x, sp.y - rad, rad * 0.72, 0.3, Math.PI * 2 - 0.3);
          ctx.stroke();
        } else {
          const dx = tp.x - sp.x, dy = tp.y - sp.y, dist = Math.max(1, Math.hypot(dx, dy));
          const dir = (e.id.charCodeAt(e.id.length - 1) % 2) ? 1 : -1;
          const bend = Math.min(28, dist * 0.12) * dir;
          const cx = (sp.x + tp.x) / 2 - (dy / dist) * bend;
          const cy = (sp.y + tp.y) / 2 + (dx / dist) * bend;
          ctx.beginPath();
          ctx.moveTo(sp.x, sp.y);
          ctx.quadraticCurveTo(cx, cy, tp.x, tp.y);
          ctx.stroke();
          // Balanced tapered arrowhead
          const nr = nodeRadius(tn) * Math.min(1.15, Math.max(0.65, camera.scale)) + 3;
          const ang = Math.atan2(tp.y - cy, tp.x - cx);
          const tx = tp.x - Math.cos(ang) * nr;
          const ty = tp.y - Math.sin(ang) * nr;
          const al = rel === "related" ? 8.5 : 6.8;
          ctx.beginPath();
          ctx.moveTo(tx, ty);
          ctx.lineTo(tx - al * Math.cos(ang - 0.42), ty - al * Math.sin(ang - 0.42));
          ctx.lineTo(tx - al * Math.cos(ang + 0.42), ty - al * Math.sin(ang + 0.42));
          ctx.closePath();
          ctx.fill();
          if (rel === "related" && camera.scale > 0.65) {
            const mx = 0.25 * sp.x + 0.5 * cx + 0.25 * tp.x;
            const my = 0.25 * sp.y + 0.5 * cy + 0.25 * tp.y;
            ctx.globalAlpha = 1;
            ctx.font = "500 12px 'Cascadia Code', monospace";
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            const lw = Math.ceil(ctx.measureText(e.label).width) + 10;
            const lh = 17;
            const eb = { l: mx - lw / 2, r: mx + lw / 2, t: my - lh / 2, b: my + lh / 2 };
            const overlap = edgeLabelBoxes.some((o) => eb.l < o.r + 4 && eb.r > o.l - 4 && eb.t < o.b + 3 && eb.b > o.t - 3);
            if (!overlap) {
              edgeLabelBoxes.push(eb);
              drawCrispRoundRect(ctx, eb.l, eb.t, lw, lh, 3);
              ctx.fillStyle = pal.labelBg;
              ctx.fill();
              ctx.strokeStyle = pal.hullStroke;
              ctx.lineWidth = 0.8;
              ctx.stroke();
              ctx.fillStyle = pal.muted;
              ctx.fillText(e.label, Math.round(mx), Math.round(my + 0.5));
            }
          }
        }
        ctx.restore();
      });

      // 4) Ultra-crisp High-DPI degree-scaled nodes (double-ring collar + soft elevation + kind glyph)
      const isDarkMode = document.documentElement.getAttribute("data-theme") === "dark";
      const ordered = [...nodes].sort((a, b) => a.degree - b.degree);
      ordered.forEach((n) => {
        const p = worldToScreen(n);
        const st = visualNodeState(n);
        const rad = Math.max(5.5, nodeRadius(n) * Math.min(1.18, Math.max(0.68, camera.scale)));
        const fill = (NODE_STYLES[n.kind] || { fill: "#44688e" }).fill;
        ctx.save();
        ctx.globalAlpha = st === "muted" ? 0.16 : 1;
        if (st === "selected" || st === "hovered") {
          ctx.beginPath();
          ctx.arc(p.x, p.y, rad + 5, 0, Math.PI * 2);
          ctx.fillStyle = st === "selected" ? "rgba(15, 118, 110, 0.14)" : "rgba(15, 118, 110, 0.08)";
          ctx.fill();
          ctx.beginPath();
          ctx.arc(p.x, p.y, rad + 3.5, 0, Math.PI * 2);
          ctx.strokeStyle = st === "selected" ? pal.selected : pal.hovered;
          ctx.lineWidth = 2;
          ctx.stroke();
        }
        // Subtle architectural shadow
        ctx.shadowColor = isDarkMode ? "rgba(0,0,0,0.45)" : "rgba(15,23,42,0.14)";
        ctx.shadowBlur = st === "selected" ? 10 : 6;
        ctx.shadowOffsetY = 1.5;
        // Clean outer collar ring
        ctx.beginPath();
        ctx.arc(p.x, p.y, rad + 1.4, 0, Math.PI * 2);
        ctx.fillStyle = pal.nodeStroke;
        ctx.fill();
        ctx.shadowBlur = 0;
        ctx.shadowOffsetY = 0;
        // Core filled node
        ctx.beginPath();
        ctx.arc(p.x, p.y, rad, 0, Math.PI * 2);
        ctx.fillStyle = fill;
        ctx.fill();
        // Crisp inner hairline rim
        ctx.beginPath();
        ctx.arc(p.x, p.y, Math.max(2, rad - 1), 0, Math.PI * 2);
        ctx.strokeStyle = "rgba(255,255,255,0.28)";
        ctx.lineWidth = 1;
        ctx.stroke();
        // Kind monogram glyph inside node when readable
        if (rad >= 8.5) {
          const glyph = NODE_GLYPHS[n.kind] || "";
          if (glyph) {
            ctx.font = `700 ${Math.min(11, Math.round(rad * 0.92))}px 'Cascadia Code', monospace`;
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillStyle = "#ffffff";
            ctx.fillText(glyph, p.x, p.y + 0.5);
          }
        }
        ctx.restore();
      });

      // 5) Crisp pixel-snapped bordered label tags (non-overlapping)
      const boxes = [];
      const prio = { selected: 4, hovered: 3, related: 2, normal: 1, muted: 0 };
      const labelOrder = [...nodes].sort((a, b) => prio[visualNodeState(b)] - prio[visualNodeState(a)] || b.degree - a.degree);
      labelOrder.forEach((n) => {
        const st = visualNodeState(n);
        if (!(st === "selected" || st === "hovered" || st === "related" || n.degree >= 4 || camera.scale > 1.0)) return;
        const p = worldToScreen(n);
        const rad = Math.max(5.5, nodeRadius(n) * Math.min(1.18, Math.max(0.68, camera.scale)));
        ctx.save();
        ctx.globalAlpha = st === "muted" ? 0.2 : 1;
        ctx.font = `${st === "selected" ? "700" : "600"} 12px 'Segoe UI', sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        const txt = n.label.length > 26 ? `${n.label.slice(0, 24)}..` : n.label;
        const w = Math.ceil(ctx.measureText(txt).width) + 12;
        const h = 19;
        const box = { l: p.x - w / 2, r: p.x + w / 2, t: p.y + rad + 5, b: p.y + rad + 5 + h };
        const hit = boxes.some((o) => box.l < o.r + 4 && box.r > o.l - 4 && box.t < o.b + 3 && box.b > o.t - 3);
        if (!hit || st === "selected" || st === "hovered") {
          boxes.push(box);
          drawCrispRoundRect(ctx, box.l, box.t, w, h, 3);
          ctx.fillStyle = pal.labelBg;
          ctx.fill();
          ctx.strokeStyle = st === "selected" ? pal.selected : pal.hullStroke;
          ctx.lineWidth = st === "selected" ? 1.4 : 1;
          ctx.stroke();
          ctx.fillStyle = pal.fg;
          ctx.fillText(txt, Math.round(p.x), Math.round(box.t + h / 2 + 0.5));
        }
        ctx.restore();
      });
    }

    function hitNode(sx, sy) {
      for (let i = nodes.length - 1; i >= 0; i--) {
        const n = nodes[i];
        const p = worldToScreen(n);
        const rad = Math.max(7, nodeRadius(n) * Math.min(1.15, Math.max(0.65, camera.scale)) + 4);
        if (Math.hypot(sx - p.x, sy - p.y) <= rad) return n;
      }
      return null;
    }

    canvas.addEventListener("pointerdown", (e) => {
      if (window.fdaiTip) window.fdaiTip.hide();
      const r = canvas.getBoundingClientRect();
      const sx = e.clientX - r.left, sy = e.clientY - r.top;
      const hit = hitNode(sx, sy);
      canvas.setPointerCapture(e.pointerId);
      viewport.classList.add("is-dragging");
      if (hit) gesture = { mode: "node", id: hit.id, sx, sy, nx: hit.x, ny: hit.y, moved: false };
      else gesture = { mode: "pan", sx, sy, cx: camera.x, cy: camera.y, moved: false };
    });
    canvas.addEventListener("pointermove", (e) => {
      const r = canvas.getBoundingClientRect();
      const sx = e.clientX - r.left, sy = e.clientY - r.top;
      if (gesture) {
        const dx = sx - gesture.sx, dy = sy - gesture.sy;
        if (Math.hypot(dx, dy) > 3) gesture.moved = true;
        if (gesture.mode === "node") {
          const n = nodeById.get(gesture.id);
          if (n) { n.x = gesture.nx + dx / camera.scale; n.y = gesture.ny + dy / camera.scale; }
        } else {
          camera.x = gesture.cx + dx;
          camera.y = gesture.cy + dy;
        }
        draw();
      } else {
        const hit = hitNode(sx, sy);
        const nid = hit ? hit.id : null;
        if (nid !== hoveredId) { hoveredId = nid; canvas.style.cursor = nid ? "pointer" : "grab"; draw(); }
        if (window.fdaiTip) {
          if (hit) {
            const commNames = [
              "핵심 ObjectType · Resource",
              "15-에이전트 판테온",
              "규칙 · 정책 · 안전 관문",
              "텔레메트리 · 데이터 계통",
              "ActionType · 워크플로"
            ];
            const styleMeta = NODE_STYLES[hit.kind] || { label: hit.kind };
            const relEdges = edges.filter((ed) => enabledEdges.has(ed.kind) && (ed.source === hit.id || ed.target === hit.id));
            const tone = hit.kind === "action_type" || hit.kind === "workflow" ? "human"
              : hit.kind === "object_type" || hit.kind === "resource_type" ? "live"
              : hit.kind === "rule" || hit.kind === "signal_type" ? "sre" : "auto";
            window.fdaiTip.show({
              title: hit.label,
              value: `차수 ${hit.degree || relEdges.length}`,
              tone,
              body: `${commNames[hit.community] || "온톨로지"} · ${styleMeta.label} · 활성 관계 ${relEdges.length}건`,
              meta: "클릭하여 우측 상세 인스펙터 열기 · 드래그 이동 · 휠 확대/축소"
            }, { x: e.clientX, y: e.clientY });
          } else {
            window.fdaiTip.hide();
          }
        }
      }
    });
    canvas.addEventListener("pointerleave", () => {
      if (hoveredId) { hoveredId = null; draw(); }
      if (window.fdaiTip) window.fdaiTip.hide();
    });
    canvas.addEventListener("pointerup", (e) => {
      if (!gesture) return;
      const g = gesture;
      gesture = null;
      viewport.classList.remove("is-dragging");
      if (!g.moved) {
        selectedId = g.mode === "node" ? g.id : null;
        updateInspector();
        draw();
        if (g.mode === "node") {
          const kgAside = viewport.parentElement?.querySelector('[data-float-inspector="panel"]');
          if (kgAside && window.fdaiOpenInlineInspector) window.fdaiOpenInlineInspector(kgAside, canvas);
        } else if (!drawerPinned) {
          closeFloatingDrawer();
        }
      }
    });
    canvas.addEventListener("wheel", (e) => {
      if (!(e.ctrlKey || e.metaKey)) {
        showCanvasZoomHint(viewport);
        return;
      }
      e.preventDefault();
      hideCanvasZoomHint(viewport);
      const r = canvas.getBoundingClientRect();
      const sx = e.clientX - r.left, sy = e.clientY - r.top;
      const before = screenToWorld({ x: sx, y: sy });
      camera.scale = Math.max(0.4, Math.min(2.6, camera.scale * (e.deltaY < 0 ? 1.12 : 0.9)));
      camera.x = sx - before.x * camera.scale;
      camera.y = sy - before.y * camera.scale;
      draw();
    }, { passive: false });
    canvas.addEventListener("keydown", (e) => {
      if (e.key === "+" || e.key === "=") { camera.scale = Math.min(2.4, camera.scale * 1.15); draw(); }
      else if (e.key === "-") { camera.scale = Math.max(0.4, camera.scale / 1.15); draw(); }
      else if (e.key === "0" || e.key === "Home") { fit(); }
      else if (e.key === "ArrowLeft") { camera.x += 36; draw(); }
      else if (e.key === "ArrowRight") { camera.x -= 36; draw(); }
      else if (e.key === "ArrowUp") { camera.y += 36; draw(); }
      else if (e.key === "ArrowDown") { camera.y -= 36; draw(); }
    });
    if (typeof window.ResizeObserver === "function") {
      let kgRaf = 0;
      const kgRo = new ResizeObserver(() => {
        if (kgRaf) cancelAnimationFrame(kgRaf);
        kgRaf = requestAnimationFrame(() => { kgRaf = 0; fit(); });
      });
      kgRo.observe(viewport);
    }

    // Wire toolbar controls
    const dl = document.getElementById("fdaiOntologyKgDatalist");
    if (dl) dl.innerHTML = nodes.map((n) => `<option value="${n.label}"></option>`).join("");
    const searchInp = document.getElementById("fdaiOntologyKgSearch");
    const runFind = () => {
      const q = (searchInp?.value || "").trim().toLowerCase();
      if (!q) return;
      const m = nodes.find((n) => n.label.toLowerCase() === q) || nodes.find((n) => n.label.toLowerCase().includes(q));
      if (m) focusNode(m.id);
    };
    document.getElementById("fdaiOntologyKgFind")?.addEventListener("click", runFind);
    searchInp?.addEventListener("keydown", (e) => { if (e.key === "Enter") runFind(); });
    document.getElementById("fdaiOntologyKgZoomIn")?.addEventListener("click", () => { camera.scale = Math.min(2.4, camera.scale * 1.18); draw(); });
    document.getElementById("fdaiOntologyKgZoomOut")?.addEventListener("click", () => { camera.scale = Math.max(0.4, camera.scale / 1.18); draw(); });
    document.getElementById("fdaiOntologyKgFit")?.addEventListener("click", () => { selectedId = "ot:Resource"; updateInspector(); fit(); });
    document.querySelectorAll("[data-kg-edge-filter]").forEach((cb) => {
      cb.addEventListener("change", () => {
        const k = cb.getAttribute("data-kg-edge-filter");
        if (cb.checked) enabledEdges.add(k); else enabledEdges.delete(k);
        updateInspector();
        draw();
      });
    });

    // Re-fit when tab becomes visible or window resizes or theme changes
    const ro = new ResizeObserver(() => { if (viewport.getBoundingClientRect().width > 40) fit(); });
    ro.observe(viewport);
    const mo = new MutationObserver(() => draw());
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    updateInspector();
    window.requestAnimationFrame(() => fit());
  }

  let lastFloatDrawerTrigger = null;
  let drawerPinned = false;
  try { drawerPinned = window.localStorage.getItem("fdai-drawer-pinned") === "1"; } catch {}
  function canDockInspector() {
    return window.innerWidth >= 1520;
  }
  function ensureFloatDrawer() {
    let scrim = document.getElementById("fdaiFloatDrawerScrim");
    let drawer = document.getElementById("fdaiFloatDrawer");
    if (!scrim) {
      scrim = document.createElement("div");
      scrim.id = "fdaiFloatDrawerScrim";
      scrim.className = "cs-float-drawer-scrim";
      scrim.hidden = true;
      scrim.addEventListener("click", () => closeFloatingDrawer(false));
      document.body.appendChild(scrim);
    }
    if (!drawer) {
      drawer = document.createElement("aside");
      drawer.id = "fdaiFloatDrawer";
      drawer.className = "cs-float-drawer";
      drawer.setAttribute("role", "dialog");
      drawer.setAttribute("aria-modal", "true");
      drawer.setAttribute("aria-labelledby", "fdaiFloatDrawerTitle");
      drawer.hidden = true;
      drawer.innerHTML = `
        <div class="cs-float-drawer-head">
          <div>
            <h3 class="cs-float-drawer-title" id="fdaiFloatDrawerTitle">상세 정보</h3>
            <p class="cs-float-drawer-sub" id="fdaiFloatDrawerSub"></p>
          </div>
          <div class="cs-float-inline-actions">
            <span class="cs-badge tone-live" id="fdaiFloatDrawerBadge" hidden></span>
            <button type="button" class="cs-btn cs-btn-sm cs-pin-btn" data-float-pin aria-pressed="false">핀 고정</button>
            <button type="button" class="icon-btn" id="fdaiFloatDrawerClose" aria-label="상세 사이드바 닫기">${ICONS.close}</button>
          </div>
        </div>
        <div class="cs-float-drawer-body" id="fdaiFloatDrawerBody"></div>
        <div class="cs-float-drawer-foot" id="fdaiFloatDrawerFoot"></div>
      `;
      document.body.appendChild(drawer);
      document.getElementById("fdaiFloatDrawerClose")?.addEventListener("click", closeFloatingDrawer);
      drawer.querySelector("[data-float-pin]")?.addEventListener("click", toggleInspectorPin);
    }
    return { scrim, drawer };
  }
  let activeInlineInspector = null;
  function syncInspectorPinState() {
    const scrim = document.getElementById("fdaiFloatDrawerScrim");
    const drawer = document.getElementById("fdaiFloatDrawer");
    const hasOpenGeneric = !!(drawer && !drawer.hidden);
    const hasOpenInline = !!activeInlineInspector;
    const anyOpen = hasOpenGeneric || hasOpenInline;
    const docked = anyOpen && drawerPinned && canDockInspector();
    document.body.classList.toggle("has-docked-inspector", docked);
    if (scrim) scrim.hidden = !anyOpen || docked;
    if (drawer) drawer.classList.toggle("is-pin-docked", docked && hasOpenGeneric);
    if (activeInlineInspector) activeInlineInspector.classList.toggle("is-pin-docked", docked && hasOpenInline);
    document.querySelectorAll("[data-float-pin]").forEach((btn) => {
      const on = drawerPinned && canDockInspector();
      btn.classList.toggle("is-pinned", on);
      btn.setAttribute("aria-pressed", String(on));
      btn.textContent = on ? "핀 해제" : "핀 고정";
    });
    if (anyOpen) window.requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
  }
  function toggleInspectorPin() {
    if (!drawerPinned && !canDockInspector()) {
      showToast("1520px 미만 화면에서는 중앙 캔버스(680px 이상) 확보를 위해 플로팅 모드로 유지됩니다.");
      return;
    }
    drawerPinned = !drawerPinned;
    try { window.localStorage.setItem("fdai-drawer-pinned", drawerPinned ? "1" : "0"); } catch {}
    syncInspectorPinState();
    showToast(drawerPinned ? "우측 상세 패널을 화면에 고정했습니다 (Esc로 닫기)." : "우측 상세 패널을 플로팅 모드로 전환했습니다.");
  }
  function closeFloatingDrawer(skipRelease) {
    const scrim = document.getElementById("fdaiFloatDrawerScrim");
    const drawer = document.getElementById("fdaiFloatDrawer");
    const wasOpen = Boolean((drawer && !drawer.hidden) || activeInlineInspector);
    if (scrim) scrim.hidden = true;
    if (drawer) {
      drawer.hidden = true;
      drawer.classList.remove("is-pin-docked");
    }
    if (activeInlineInspector) {
      activeInlineInspector.classList.remove("is-float-open");
      activeInlineInspector.classList.remove("is-pin-docked");
      activeInlineInspector = null;
    }
    document.body.classList.remove("has-docked-inspector");
    if (wasOpen && skipRelease !== true && typeof releaseDiagramSelection === "function") {
      const activePanel = document.querySelector(".panel-view[data-panel-id]:not([hidden])");
      if (activePanel) releaseDiagramSelection(activePanel, true);
    }
    window.requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
    lastFloatDrawerTrigger?.focus?.();
    lastFloatDrawerTrigger = null;
  }
  function openInlineInspector(asideEl, triggerEl) {
    if (!asideEl) return;
    if (chatOpen) toggleChatSidebar(false);
    if (activeInlineInspector && activeInlineInspector !== asideEl) {
      activeInlineInspector.classList.remove("is-float-open");
      activeInlineInspector.classList.remove("is-pin-docked");
    }
    ensureFloatDrawer();
    lastFloatDrawerTrigger = triggerEl || document.activeElement;
    activeInlineInspector = asideEl;
    asideEl.classList.add("is-float-open");
    asideEl.scrollTop = 0;
    syncInspectorPinState();
  }
  window.fdaiOpenInlineInspector = openInlineInspector;
  window.fdaiToggleInspectorPin = toggleInspectorPin;
  window.addEventListener("resize", () => {
    if (activeInlineInspector || (document.getElementById("fdaiFloatDrawer") && !document.getElementById("fdaiFloatDrawer").hidden)) {
      syncInspectorPinState();
    }
  });

  // Convert all 25 Group A (21) + Group B (4) panels to Full-Width Default + Right Floating Slide-Over Drawer
  function initFloatingInspectors() {
    const GROUP_A = new Set([
      "rules", "ontology", "architecture", "blast-radius", "workflow-builder", "documents", "promotion-gates",
      "dashboard-v2", "gpu", "code-security", "vulnerability-risk", "configuration-baselines", "detection-readiness", "processes", "scheduler-runs",
      "agents", "pantheon", "agent-activity", "skills", "capabilities", "conversation-assurance", "rca"
    ]);
    const GROUP_B = new Set(["hil-queue", "incidents", "conversation-search"]);
    const LEFT_COL_BY_CLASS = {
      "wb-3pane": "296px",
      "ag-act-3pane": "268px",
      "ag-const-grid": "248px",
      "gov-rules-wb": "236px",
      "graph-grid": "232px",
      "ag-catalog-wb": "230px",
      "gov-doc-3pane": "230px",
      "ops-facet-3col": "216px"
    };
    const ITEM_TRIGGER_SELECTOR = [
      "tbody tr",
      ".wb-item",
      ".graph-node",
      ".tree-node-btn",
      ".kanban-card",
      ".gov-rule-row",
      ".gov-ctrl-row",
      ".gov-doc-row",
      ".gov-gate-row",
      ".ag-card",
      ".ag-roster-row",
      ".ag-node",
      ".ag-tree-node",
      ".ag-org-node",
      ".ag-swim-chip",
      ".ag-ev-row",
      ".ag-cat-item",
      ".ov-res-chip",
      ".ov-res-row",
      ".ov-res-tile",
      ".gpu-node-card",
      ".ops-gpu-card",
      ".ops-cve-row",
      ".ops-drift-row",
      ".ops-det-cell",
      ".det-cell",
      ".ops-proc-row",
      ".ops-run-row",
      ".sl-eval-row",
      "[data-gnode-name]",
      "[data-rule-id]",
      "[data-ctrl-id]",
      "[data-control-id]",
      "[data-agent-id]",
      "[data-skill-id]",
      "[data-cap-id]",
      "[data-doc-id]",
      "[data-gate-id]",
      "[data-gpu-id]",
      "[data-cve-id]",
      "[data-drift-id]",
      "[data-proc-id]",
      "[data-run-id]",
      "[data-case-id]",
      "[data-eval-id]",
      "[data-res-id]",
      "[data-rca-node]",
      ".ops-slot-pill",
      "[data-sched-id]",
      ".ag-list-btn",
      ".ag-cnode",
      "[data-ag-pick]",
      "[data-org-node]"
    ].join(", ");

    document.querySelectorAll(".panel-view[data-panel-id]").forEach((panel) => {
      const pid = panel.getAttribute("data-panel-id") || "";
      const isA = GROUP_A.has(pid);
      const isB = GROUP_B.has(pid);
      if (!isA && !isB) return;

      const panelTitle = panel.getAttribute("data-panel-title") || pid;
      const candidates = Array.from(panel.querySelectorAll("aside, .ov-inspector-card, .gov-inspector")).filter((el) => {
        if (el.classList.contains("graph-tree") || el.classList.contains("facet-rail") || el.classList.contains("gov-rules-rail") || el.classList.contains("ops-facet-rail") || el.classList.contains("ag-left-rail") || el.classList.contains("settings-nav")) return false;
        const p = el.parentElement;
        if (!p) return false;
        const kids = Array.from(p.children).filter((c) => c.tagName !== "SCRIPT");
        return kids.length >= 2 && kids[kids.length - 1] === el;
      });

      candidates.forEach((aside) => {
        if (aside.classList.contains("lin-inspector") || aside.classList.contains("lin-explorer")) return;
        if (aside.getAttribute("data-float-inspector") === "panel") return;
        aside.setAttribute("data-float-inspector", "panel");
        const parent = aside.parentElement;
        if (parent) {
          const kids = Array.from(parent.children).filter((c) => c.tagName !== "SCRIPT");
          if (kids.length === 2) {
            parent.setAttribute("data-float-grid", "1col");
            parent.style.gridTemplateColumns = "minmax(0, 1fr)";
          } else if (kids.length >= 3) {
            parent.setAttribute("data-float-grid", "2col");
            let leftW = "240px";
            for (const [cls, w] of Object.entries(LEFT_COL_BY_CLASS)) {
              if (parent.classList.contains(cls)) { leftW = w; break; }
            }
            parent.style.gridTemplateColumns = `${leftW} minmax(0, 1fr)`;
          }
        }
        // Inject sticky floating header with pin + close button
        if (!aside.querySelector(".cs-float-inline-head")) {
          const head = document.createElement("div");
          head.className = "cs-float-inline-head";
          const label = aside.getAttribute("aria-label") || `${panelTitle} 상세`;
          head.innerHTML = `<span class="cs-float-inline-title">${label}</span><div class="cs-float-inline-actions"><button type="button" class="cs-btn cs-btn-sm cs-pin-btn" data-float-pin aria-pressed="false">핀 고정</button><button type="button" class="icon-btn" data-float-close aria-label="상세 사이드바 닫기">${ICONS.close}</button></div>`;
          head.querySelector("[data-float-pin]")?.addEventListener("click", toggleInspectorPin);
          head.querySelector("[data-float-close]")?.addEventListener("click", closeFloatingDrawer);
          aside.prepend(head);
        }
        // Inject reopen toggle button in toolbar/center header
        const reopenHost = isB
          ? parent?.querySelector(".wb-center-head")
          : (parent?.closest(".graph-wb")?.querySelector(".graph-toolbar") || parent?.querySelector(".card-head, .wb-center-head, .gov-rules-toolbar, .ag-toolbar, .ov-res-bar") || panel.querySelector(".card-head, .graph-toolbar, .stat-strip"));
        if (reopenHost && !reopenHost.querySelector(`[data-float-open-target="${pid}"]`)) {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "cs-btn cs-btn-sm cs-float-reopen-btn";
          btn.setAttribute("data-float-open-target", pid);
          btn.textContent = isB ? "AI 요약 · 상세" : "상세 패널 열기";
          btn.addEventListener("click", (e) => {
            e.stopPropagation();
            const liveAside = Array.from(panel.querySelectorAll('[data-float-inspector="panel"]')).find((a) => !a.closest("[hidden]")) || aside;
            openInlineInspector(liveAside, btn);
          });
          reopenHost.appendChild(btn);
        }
        // Group A: clicking any item/row/node/card opens this panel's floating right inspector
        if (isA && parent) {
          parent.addEventListener("click", (e) => {
            const target = e.target;
            if (!(target instanceof Element)) return;
            if (target.closest('[data-float-inspector="panel"]')) return;
            if (target.closest(".graph-toolbar, .svg-graph-controls, .onto-kg-toolbar, .seg-group, .search-wrap, [data-float-open-target], select, input, a[href]")) return;
            if (target.closest(".wb-filter-chips") && !target.closest("[data-proc-id]")) return;
            // Inside Ontology KG canvas, pointerup handles node clicks cleanly (skip generic canvas click)
            if (target.tagName === "CANVAS") return;
            const hit = target.closest(ITEM_TRIGGER_SELECTOR);
            if (!hit) return;
            // Let the domain script update the inspector first (synchronous), then open floating drawer
            window.requestAnimationFrame(() => openInlineInspector(aside, hit));
          });
        }
      });
    });
  }
  function openFloatingDrawer(opts = {}) {
    if (chatOpen) toggleChatSidebar(false);
    lastFloatDrawerTrigger = opts.triggerEl || document.activeElement;
    const { scrim, drawer } = ensureFloatDrawer();
    const t = document.getElementById("fdaiFloatDrawerTitle");
    const s = document.getElementById("fdaiFloatDrawerSub");
    const b = document.getElementById("fdaiFloatDrawerBadge");
    const bodyEl = document.getElementById("fdaiFloatDrawerBody");
    const footEl = document.getElementById("fdaiFloatDrawerFoot");
    if (t) t.textContent = opts.title || "상세 정보";
    if (s) s.textContent = opts.subtitle || opts.meta || "";
    if (b) {
      if (opts.badgeText) {
        b.className = `cs-badge tone-${opts.badgeTone || "live"}`;
        b.innerHTML = `<span class="cs-dot"></span>${opts.badgeText}`;
        b.hidden = false;
      } else b.hidden = true;
    }
    if (bodyEl) {
      if (opts.bodyHtml) {
        bodyEl.innerHTML = opts.bodyHtml;
      } else {
        const escD = (v) => String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        const factsHtml = Array.isArray(opts.facts) && opts.facts.length
          ? `<div class="insp-card">${opts.facts.map(([k, v]) => `<div class="insp-kv"><span>${escD(k)}</span><strong>${escD(v)}</strong></div>`).join("")}</div>`
          : "";
        const proseHtml = opts.body ? `<div class="insp-card"><div class="insp-title">상세 근거 및 설명</div><p class="insp-summary">${escD(opts.body)}</p></div>` : "";
        bodyEl.innerHTML = `${factsHtml}${proseHtml}`;
      }
    }
    if (footEl) {
      const resolvedLinks = (opts.footerLinks && opts.footerLinks.length)
        ? opts.footerLinks
        : (opts.href ? [{ href: opts.href, label: opts.hrefLabel || "관련 화면 열기 →" }] : []);
      const links = resolvedLinks.map((l) => `<a class="cs-btn cs-btn-sm cs-btn-accent" href="${l.href}">${l.label}</a>`).join("");
      const askPrompt = opts.askChatPrompt || (opts.title ? `${opts.title} 항목의 원인 근거와 권장 조치를 설명해 줘.` : "");
      const ask = askPrompt ? `<button type="button" class="cs-btn cs-btn-sm" id="fdaiFloatDrawerAsk">AI 채팅에 묻기</button>` : "";
      footEl.innerHTML = `<div class="toolbar-inline">${links}</div><div class="toolbar-inline">${ask}<button type="button" class="cs-btn cs-btn-sm" id="fdaiFloatDrawerDismiss">닫기</button></div>`;
      document.getElementById("fdaiFloatDrawerDismiss")?.addEventListener("click", () => closeFloatingDrawer(false));
      document.getElementById("fdaiFloatDrawerAsk")?.addEventListener("click", () => {
        closeFloatingDrawer(false);
        toggleChatSidebar(true);
        appendUserAndAgentTurn(askPrompt);
      });
    }
    scrim.hidden = false;
    drawer.hidden = false;
    syncInspectorPinState();
    document.getElementById("fdaiFloatDrawerClose")?.focus();
  }
  window.fdaiOpenFloatingDrawer = openFloatingDrawer;
  window.fdaiCloseFloatingDrawer = closeFloatingDrawer;

  // Phase 2: Collapsible Left Tree / Facet Rail ([◀ 접기] / [▶ 탐색 패널])
  function initCollapsibleLeftRails() {
    const RAIL_SELECTOR = ".graph-tree, .gov-rules-rail, .wb-col-list, .ops-facet-rail, .ag-left-rail, .facet-rail";
    document.querySelectorAll(".panel-view[data-panel-id]").forEach((panel) => {
      const pid = panel.getAttribute("data-panel-id") || "";
      const rails = Array.from(panel.querySelectorAll(RAIL_SELECTOR));
      rails.forEach((rail, idx) => {
        if (rail.hasAttribute("data-collapsible-left-rail")) return;
        const grid = rail.parentElement;
        if (!grid) return;
        const visibleKids = Array.from(grid.children).filter((c) => c.tagName !== "SCRIPT" && c.getAttribute("data-float-inspector") !== "panel");
        if (visibleKids.length < 2 || visibleKids[0] !== rail) return;
        rail.setAttribute("data-collapsible-left-rail", "true");
        const storeKey = `fdai-left-rail-collapsed:${pid}:${idx}`;
        const label = rail.getAttribute("aria-label") || "탐색 · 필터";
        const bar = document.createElement("div");
        bar.className = "cs-rail-collapse-bar";
        bar.innerHTML = `<span>${label}</span><button type="button" class="cs-rail-collapse-btn" data-rail-collapse aria-label="좌측 탐색 패널 접기">◀ 접기</button>`;
        rail.prepend(bar);

        const host = grid.closest(".graph-wb")?.querySelector(".graph-toolbar")
          || grid.querySelector(".wb-center-head, .gov-rules-toolbar, .ag-toolbar, .card-head")
          || panel.querySelector(".graph-toolbar, .stat-strip");
        let restoreBtn = null;
        if (host) {
          restoreBtn = document.createElement("button");
          restoreBtn.type = "button";
          restoreBtn.className = "cs-btn cs-btn-sm cs-rail-restore-btn";
          restoreBtn.setAttribute("data-rail-restore", `${pid}:${idx}`);
          restoreBtn.textContent = "▶ 탐색 패널";
          restoreBtn.hidden = true;
          host.prepend(restoreBtn);
        }
        const applyCollapsed = (collapsed) => {
          grid.setAttribute("data-left-rail-collapsed", collapsed ? "true" : "false");
          if (restoreBtn) restoreBtn.hidden = !collapsed;
          try { window.localStorage.setItem(storeKey, collapsed ? "1" : "0"); } catch {}
          window.requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
        };
        bar.querySelector("[data-rail-collapse]")?.addEventListener("click", () => applyCollapsed(true));
        restoreBtn?.addEventListener("click", () => applyCollapsed(false));
        try {
          if (window.localStorage.getItem(storeKey) === "1") applyCollapsed(true);
        } catch {}
      });
    });
  }

  // =========================================================================
  // Console Web Parity Settings Overlay Modal (`#settings-overlay`)
  // 5 Grouped Left Nav Sections + Top Sub-Tabs + All 8 Interactive Settings Panels
  // =========================================================================
  const SETTINGS_GROUPS = [
    {
      id: "general",
      label: "일반 · 실행 환경",
      hint: "표시, 접근성 및 브라우저 로컬 환경 설정",
      tabs: [
        { id: "settings-general", label: "일반" },
        { id: "settings-environment", label: "실행 환경 · 수집기" }
      ]
    },
    {
      id: "models",
      label: "AI 모델 · 운영 정책",
      hint: "T1 및 T2 모델, 프로비저닝, 지연 시간 및 개인 라우팅",
      tabs: [
        { id: "settings-models", label: "AI 모델" },
        { id: "settings-runtime", label: "운영 정책" }
      ]
    },
    {
      id: "iam",
      label: "사용자 · 권한",
      hint: "사용자 역할, 기능 및 통제된 액세스 요청",
      tabs: [{ id: "settings-iam", label: "사용자 · 권한" }]
    },
    {
      id: "integrations",
      label: "외부 연동",
      hint: "ID, 전달 및 운영자 채널 연결",
      tabs: [{ id: "settings-integrations", label: "외부 연동" }]
    },
    {
      id: "diagnostics",
      label: "상태 진단 · 운영 메모",
      hint: "읽기 전용 런타임 및 인증 진단",
      tabs: [
        { id: "settings-diagnostics", label: "시스템 상태 진단" },
        { id: "settings-memory", label: "저장된 운영 메모" }
      ]
    }
  ];

  const soState = {
    activePanel: "settings-general",
    dirtyCount: 0,
    pendingAction: null,
    lastTrigger: null,
    modelsTab: "overview",
    iamTab: "my-access",
    locale: "ko",
    motionReduced: false,
    showTokenUsage: true,
    showModelTrace: true,
    answerDetail: "standard",
    answerFormat: "mixed",
    answerPrefsEnabled: true,
    timezone: "Asia/Seoul",
    shareWithLearner: false,
    openingBriefing: true,
    briefingHour: "9",
    briefings: [
      { id: "br-1", name: "일일 SRE·보안 리스크 브리핑", hour: "09:00", tz: "Asia/Seoul", nextRun: "내일 09:00 KST" }
    ],
    personalMemories: [
      { id: "pm-1", text: "prod-aks-02 배포 창구는 화/목 02:00~04:00 KST 유지", savedAt: "2일 전" },
      { id: "pm-2", text: "비용 이상치 브리핑은 KRW 환산 없이 USD 원화 병기", savedAt: "5일 전" }
    ],
    envFilter: "all",
    envSearch: "",
    envRefreshedAt: "방금 전 (19:42:10 KST)",
    t0First: true,
    narratorModel: "gpt-4o-mini-narrator",
    t2Primary: "azure-openai::gpt-4o-ops-kr",
    t2Secondary: "cross-verifier::o3-mini-verifier",
    webSearchEnabled: true,
    allowedDomains: ["learn.microsoft.com", "status.azure.com", "msrc.microsoft.com"],
    autonomyProfile: "standard-shadow",
    approvalExpiryMin: "30",
    riskConfirmed: false,
    turnBudget: "12",
    batchConcurrency: "4",
    runtimeJson: "{\n  \"shadow_required\": true,\n  \"max_blast_radius_resources\": 10\n}",
    iamRoleFilter: "all",
    iamRequests: [
      { id: "req-iam-104", actor: "minsu.park@contoso-ops.example", role: "Operator", selfOwned: false, reason: "prod-aks-02 야간 배포 승인 대기열 대응 권한 요청", status: "pending" },
      { id: "req-iam-105", actor: "admin@contoso-ops.example (본인)", role: "Owner", selfOwned: true, reason: "단일 운영자 테스트 범위 권한 승격 요청", status: "pending" }
    ],
    webhookMasked: true,
    webhookTestStatus: "HTTP 200 OK · 19:38:04 KST",
    emailTarget: "account",
    emailCustom: "ops-alerts@contoso-ops.example",
    emailPreviewMode: "html",
    ocrProvider: "azure-doc-intel",
    diagTimestamp: "19:41:55 KST",
    diagP95: "18ms",
    memScope: "all",
    memSearch: "",
    memPendingDelete: null,
    opMemories: [
      { id: "om-1", scope: "구독", target: "prod-core-kr", body: "분기 DR 훈련 기간 중 알람 억제 규칙은 승인 완료 건만 허용", expiresDays: 14 },
      { id: "om-2", scope: "리소스 그룹", target: "rg-orders-prod", body: "pg-orders-kr 연결 풀 임계치 75% 초과 시 읽기 복제본 점검 우선", expiresDays: 9 },
      { id: "om-3", scope: "리소스", target: "kv-prod-kr", body: "임시 방화벽 예외 규칙은 24시간 초과 불가 (Forseti 자동 회수)", expiresDays: 21 }
    ]
  };

  function findSettingsGroupForPanel(panelId) {
    return SETTINGS_GROUPS.find((g) => g.tabs.some((t) => t.id === panelId)) || SETTINGS_GROUPS[0];
  }

  function ensureSettingsOverlay() {
    let scrim = document.getElementById("fdaiSettingsOverlayScrim");
    if (!scrim) {
      scrim = document.createElement("div");
      scrim.id = "fdaiSettingsOverlayScrim";
      scrim.className = "settings-overlay-scrim";
      scrim.hidden = true;
      scrim.innerHTML = `
        <section id="settings-overlay" class="settings-overlay" role="dialog" aria-modal="true" aria-labelledby="settingsOverlayTitle">
          <header class="settings-overlay-header">
            <div>
              <h2 id="settingsOverlayTitle">설정</h2>
              <p>일반, 사용자 권한, 외부 연동 및 운영 정책 설정</p>
            </div>
            <div class="settings-overlay-head-actions">
              <a class="cs-btn cs-btn-sm" id="soOpenFullPageLink" href="/settings/general">
                <span>전체 페이지</span>
                ${ICONS.external}
              </a>
              <button type="button" class="settings-overlay-close" id="soCloseBtn" aria-label="설정 닫기">${ICONS.close}</button>
            </div>
          </header>
          <div class="settings-overlay-workspace">
            <nav class="settings-overlay-navigation" aria-label="설정 섹션">
              <ul class="settings-overlay-nav-list" id="soNavList"></ul>
            </nav>
            <div class="settings-overlay-content" id="soContent"></div>
          </div>
        </section>
      `;
      document.body.appendChild(scrim);
      scrim.addEventListener("pointerdown", (e) => {
        if (e.target === scrim) closeSettingsOverlay();
      });
      document.getElementById("soCloseBtn")?.addEventListener("click", () => closeSettingsOverlay());
    }
    return scrim;
  }

  function isValidIanaTz(tz) {
    const clean = (tz || "").trim();
    if (!clean) return false;
    try { Intl.DateTimeFormat(undefined, { timeZone: clean }); return true; } catch { return false; }
  }

  function getCurrentTheme() {
    return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }

  function setLiveTheme(nextTheme) {
    const dark = nextTheme === "dark";
    if (dark) {
      document.documentElement.setAttribute("data-theme", "dark");
      try { localStorage.setItem("fdai-mockup-theme", "dark"); } catch {}
    } else {
      document.documentElement.removeAttribute("data-theme");
      try { localStorage.setItem("fdai-mockup-theme", "light"); } catch {}
    }
  }

  function renderSettingsPanelBody(panelId) {
    const curTheme = getCurrentTheme();
    if (panelId === "settings-general") {
      const tzOk = isValidIanaTz(soState.timezone);
      const hr = Math.max(0, Math.min(23, Number(soState.briefingHour) || 0));
      const formats = [
        ["prose", "문단"], ["bullets", "글머리 기호"], ["numbered_steps", "단계별"],
        ["table", "표"], ["chart", "차트"], ["checklist", "체크리스트"], ["mixed", "혼합"]
      ];
      return `
        <div class="settings-overlay-page-head">
          <div>
            <h3>일반</h3>
            <p>브라우저 표시 설정과 응답, 브리핑, 메모리의 계정 환경 설정을 관리합니다.</p>
          </div>
          <span class="cs-badge tone-live"><span class="cs-dot"></span>개인 설정 편집 가능</span>
        </div>
        <nav class="settings-overlay-jumps" aria-label="일반 설정 섹션 이동">
          <button type="button" class="settings-overlay-jump is-active" data-so-jump="so-sec-appearance">화면 표시</button>
          <button type="button" class="settings-overlay-jump" data-so-jump="so-sec-context">사용자 context</button>
          <button type="button" class="settings-overlay-jump" data-so-jump="so-sec-briefings">사전 briefing</button>
          <button type="button" class="settings-overlay-jump" data-so-jump="so-sec-memory">저장된 메모리</button>
          <button type="button" class="settings-overlay-jump" data-so-jump="so-sec-reset">환경 설정 초기화</button>
        </nav>

        <section class="settings-overlay-section" id="so-sec-appearance">
          <div class="settings-overlay-sec-head">
            <h4>화면 표시</h4>
            <span class="settings-overlay-scope-pill">이 브라우저</span>
            <p>이 브라우저의 표시 및 접근성 선택 사항은 즉시 적용됩니다.</p>
          </div>
          <div class="settings-overlay-row">
            <div class="settings-overlay-row-meta"><strong>테마</strong><span>모든 콘솔 화면에 즉시 적용됩니다.</span></div>
            <div class="seg-group" role="group" aria-label="테마 선택">
              <button type="button" class="seg-btn${curTheme === "light" ? " is-active" : ""}" data-so-theme="light">라이트</button>
              <button type="button" class="seg-btn${curTheme === "dark" ? " is-active" : ""}" data-so-theme="dark">다크</button>
            </div>
          </div>
          <div class="settings-overlay-row">
            <div class="settings-overlay-row-meta"><strong>언어</strong><span>모든 탐색 레이블에 선택한 언어를 적용하며 미번역 키는 영어로 대체됩니다.</span></div>
            <div class="seg-group" role="group" aria-label="언어 선택">
              <button type="button" class="seg-btn${soState.locale === "en" ? " is-active" : ""}" data-so-locale="en">English</button>
              <button type="button" class="seg-btn${soState.locale === "ko" ? " is-active" : ""}" data-so-locale="ko">한국어</button>
            </div>
          </div>
          <div class="settings-overlay-row">
            <div class="settings-overlay-row-meta"><strong>모션</strong><span>실시간 상태 갱신을 유지하면서 장식 애니메이션을 줄입니다.</span></div>
            <div class="settings-overlay-row-ctrl">
              <span class="wb-item-sub">${soState.motionReduced ? "축소" : "시스템 환경 설정"}</span>
              <button type="button" class="cs-switch" role="switch" aria-checked="${soState.motionReduced}" aria-label="모션 축소" data-so-browser-switch="motionReduced"><span class="cs-switch-thumb" aria-hidden="true"></span></button>
            </div>
          </div>
          <div class="settings-overlay-row">
            <div class="settings-overlay-row-meta"><strong>토큰 사용량 표시</strong><span>채팅 답변 배지에 모델·지연시간 옆으로 답변당 사용된 토큰 수를 표시합니다.</span></div>
            <div class="settings-overlay-row-ctrl">
              <span class="wb-item-sub">${soState.showTokenUsage ? "활성화" : "비활성화"}</span>
              <button type="button" class="cs-switch" role="switch" aria-checked="${soState.showTokenUsage}" aria-label="토큰 사용량 표시" data-so-browser-switch="showTokenUsage"><span class="cs-switch-thumb" aria-hidden="true"></span></button>
            </div>
          </div>
          <div class="settings-overlay-row">
            <div class="settings-overlay-row-meta"><strong>모델 요청 및 응답 trace 캡처</strong><span>기본값은 꺼짐입니다. 새 채팅 턴부터 실제 provider message와 assistant content의 제한된 redacted copy를 저장하고 표시합니다. Credential, identifier, URL, image 및 hidden reasoning은 저장하지 않습니다.</span></div>
            <div class="settings-overlay-row-ctrl">
              <span class="wb-item-sub">${soState.showModelTrace ? "활성화" : "비활성화"}</span>
              <button type="button" class="cs-switch" role="switch" aria-checked="${soState.showModelTrace}" aria-label="모델 요청 및 응답 trace 캡처" data-so-browser-switch="showModelTrace"><span class="cs-switch-thumb" aria-hidden="true"></span></button>
            </div>
          </div>
        </section>

        <section class="settings-overlay-section" id="so-sec-context">
          <div class="settings-overlay-sec-head">
            <h4>사용자 context</h4>
            <span class="settings-overlay-scope-pill">내 계정</span>
            <p>계정 범위 narrator 선호와 명시적 학습 동의를 관리합니다. 표시 선호는 브라우저에만 유지됩니다.</p>
          </div>
          <div class="settings-overlay-row">
            <div class="settings-overlay-row-meta"><strong>답변 상세도</strong><span>에이전트 응답의 기본 설명 깊이를 지정합니다.</span></div>
            <div class="seg-group" role="group" aria-label="답변 상세도">
              ${[["brief", "간략"], ["standard", "표준"], ["deep", "상세"]].map(([v, l]) =>
                `<button type="button" class="seg-btn${soState.answerDetail === v ? " is-active" : ""}" data-so-acct-seg="answerDetail" data-val="${v}">${l}</button>`
              ).join("")}
            </div>
          </div>
          <div class="settings-overlay-row">
            <div class="settings-overlay-row-meta"><strong>기본 답변 형식</strong><span>AI 채팅 응답의 기본 구조화 선호를 지정합니다.</span></div>
            <div class="seg-group" role="group" aria-label="기본 답변 형식">
              ${formats.map(([v, l]) =>
                `<button type="button" class="seg-btn${soState.answerFormat === v ? " is-active" : ""}" data-so-acct-seg="answerFormat" data-val="${v}">${l}</button>`
              ).join("")}
            </div>
          </div>
          <div class="settings-overlay-row">
            <div class="settings-overlay-row-meta"><strong>답변 선호 적용</strong><span>새 대화 시작 시 위 상세도·형식 선호를 자동으로 적용합니다.</span></div>
            <div class="settings-overlay-row-ctrl">
              <span class="wb-item-sub">${soState.answerPrefsEnabled ? "활성화" : "비활성화"}</span>
              <button type="button" class="cs-switch" role="switch" aria-checked="${soState.answerPrefsEnabled}" aria-label="답변 선호 적용" data-so-acct-switch="answerPrefsEnabled"><span class="cs-switch-thumb" aria-hidden="true"></span></button>
            </div>
          </div>
          <div class="settings-overlay-row">
            <div class="settings-overlay-row-meta"><strong>표준 타임존 (IANA)</strong><span>${tzOk ? `유효한 IANA 타임존입니다 (${soState.timezone}).` : "유효한 IANA 타임존을 입력하세요 (예: Asia/Seoul)."}</span></div>
            <input type="text" class="cs-input" style="width:200px" aria-label="표준 타임존" id="soTzInput" value="${soState.timezone}">
          </div>
          <div class="settings-overlay-row">
            <div class="settings-overlay-row-meta"><strong>명시적 학습 동의 (Learner Access)</strong><span>운영자 피드백을 비식별 품질 개선 학습에 활용할지 선택합니다.</span></div>
            <div class="settings-overlay-row-ctrl">
              <span class="wb-item-sub">${soState.shareWithLearner ? "명시적 동의" : "메타데이터만"}</span>
              <button type="button" class="cs-switch" role="switch" aria-checked="${soState.shareWithLearner}" aria-label="명시적 학습 동의" data-so-acct-switch="shareWithLearner"><span class="cs-switch-thumb" aria-hidden="true"></span></button>
            </div>
          </div>
        </section>

        <section class="settings-overlay-section" id="so-sec-briefings">
          <div class="settings-overlay-sec-head">
            <h4>사전 briefing</h4>
            <span class="settings-overlay-scope-pill">내 계정</span>
            <p>대화 시작 브리핑과 일일 정기 운영 브리핑 일정을 관리합니다.</p>
          </div>
          <div class="settings-overlay-row">
            <div class="settings-overlay-row-meta"><strong>대화 시작 브리핑</strong><span>새 대화를 열 때 현재 구독의 상위 리스크·승인 대기 요약을 자동 첨부합니다.</span></div>
            <button type="button" class="cs-btn cs-btn-sm" id="soToggleOpeningBriefing">${soState.openingBriefing ? "비활성화" : "활성화"}</button>
          </div>
          <div class="settings-overlay-row">
            <div class="settings-overlay-row-meta"><strong>일일 브리핑 시각 (0~23시)</strong><span>예상 실행: 매일 ${String(hr).padStart(2, "0")}:00 (${soState.timezone})</span></div>
            <div class="settings-overlay-row-ctrl">
              <input type="number" class="cs-input" style="width:88px" min="0" max="23" aria-label="일일 브리핑 시각" id="soBriefingHour" value="${soState.briefingHour}">
              <button type="button" class="cs-btn cs-btn-sm cs-btn-accent" id="soAddBriefingBtn">일일 브리핑 추가</button>
            </div>
          </div>
          <div style="display:grid;gap:8px;">
            ${soState.briefings.map((b) => `
              <div class="settings-overlay-card" style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
                <div><strong>${b.name}</strong><div class="wb-item-sub">매일 ${b.hour} (${b.tz}) · 다음 실행: ${b.nextRun}</div></div>
                <button type="button" class="cs-btn cs-btn-sm" data-so-del-briefing="${b.id}">구독 해제</button>
              </div>
            `).join("") || `<div class="wb-item-sub">등록된 일일 브리핑 구독이 없습니다.</div>`}
          </div>
        </section>

        <section class="settings-overlay-section" id="so-sec-memory">
          <div class="settings-overlay-sec-head">
            <h4>저장된 메모리</h4>
            <span class="settings-overlay-scope-pill">내 계정</span>
            <p>대화에서 명시적으로 저장한 개인 운영 선호입니다. 실행 권한을 부여하지 않습니다.</p>
          </div>
          <div style="display:grid;gap:8px;">
            ${soState.personalMemories.map((m) => `
              <div class="settings-overlay-card" style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
                <div><strong>${m.text}</strong><div class="wb-item-sub">저장 시각: ${m.savedAt}</div></div>
                <button type="button" class="cs-btn cs-btn-sm" data-so-del-pmem="${m.id}">삭제</button>
              </div>
            `).join("") || `<div class="wb-item-sub">저장된 개인 메모리가 없습니다.</div>`}
          </div>
        </section>

        <section class="settings-overlay-section" id="so-sec-reset">
          <div class="settings-overlay-sec-head">
            <h4>환경 설정 초기화</h4>
            <p>이 계정의 응답 선호와 브라우저 표시 설정을 기본값으로 되돌립니다.</p>
          </div>
          <div>
            <button type="button" class="cs-btn" id="soResetPrefsBtn">환경 설정 기본값으로 초기화</button>
          </div>
        </section>
      `;
    }

    if (panelId === "settings-environment") {
      const collectors = [
        { id: "azure-resource-graph", name: "azure-resource-graph", status: "live", badge: "정상 수집", meta: "주기 30초 · 마지막 스냅샷 12초 전 · 리소스 2,213개" },
        { id: "aks-workload-observer", name: "aks-workload-observer", status: "live", badge: "정상 수집", meta: "주기 15초 · 클러스터 4개 · Pod/Node 메트릭 정상" },
        { id: "focus-cost-export", name: "focus-cost-export", status: "unmeasured", badge: "미수집 (연결 필요)", meta: "스토리지 계정 SAS 권한 미할당 · 비용 지표는 0으로 추정하지 않고 별도 분리 표시됨" }
      ].filter((c) => {
        if (soState.envFilter !== "all" && c.status !== soState.envFilter) return false;
        if (soState.envSearch && !`${c.name} ${c.meta}`.toLowerCase().includes(soState.envSearch.toLowerCase())) return false;
        return true;
      });
      return `
        <div class="settings-overlay-page-head">
          <div>
            <h3>실행 환경 · 수집기</h3>
            <p>로컬/배포 실행 베뉴, 수집기 3종 준비 상태 및 설치 버전 수명주기를 확인합니다.</p>
          </div>
          <button type="button" class="cs-btn cs-btn-sm" id="soEnvRefreshBtn">근거 새로고침 ↻</button>
        </div>
        <div class="settings-overlay-card" style="display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;">
          <span><strong>실행 베뉴</strong>: Local + Azure Parity</span>
          <span><strong>런타임</strong>: Pure-Rust 6 Services</span>
          <span><strong>수집기</strong>: 2/3 정상 · 1 미수집</span>
          <span class="wb-item-sub">최근 갱신: ${soState.envRefreshedAt}</span>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between;">
          <div class="seg-group" role="group" aria-label="수집기 상태 필터">
            ${[["all", "전체 (3)"], ["live", "정상 (2)"], ["unmeasured", "미수집 (1)"]].map(([v, l]) =>
              `<button type="button" class="seg-btn${soState.envFilter === v ? " is-active" : ""}" data-so-env-filter="${v}">${l}</button>`
            ).join("")}
          </div>
          <input type="search" class="cs-input" style="width:220px" id="soEnvSearch" placeholder="수집기 이름 검색..." value="${soState.envSearch}">
        </div>
        <div style="display:grid;gap:10px;">
          ${collectors.map((c) => `
            <div class="settings-overlay-card${c.status === "unmeasured" ? " is-unmeasured" : ""}">
              <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
                <strong>${c.name}</strong>
                <span class="cs-badge tone-${c.status === "live" ? "live" : "neutral"}"><span class="cs-dot"></span>${c.badge}</span>
              </div>
              <div class="wb-item-sub">${c.meta}</div>
            </div>
          `).join("")}
        </div>
        <div class="settings-overlay-card">
          <strong>설치 버전 · 롤백 수명주기</strong>
          <div class="wb-item-sub">현재 배포: <code>v2026.11.26-rust-core</code> (서명 검증 통과) · 이전 정상 스냅샷: <code>v2026.11.24-rust-core</code> (즉시 롤백 가능)</div>
        </div>
      `;
    }

    if (panelId === "settings-models") {
      const sameProvider = soState.t2Primary.split("::")[0] === soState.t2Secondary.split("::")[0];
      return `
        <div class="settings-overlay-page-head">
          <div>
            <h3>AI 모델</h3>
            <p>T0/T1 결정론 우선 원칙, T2 독립 교차 검증기 바인딩 및 승인된 Azure OpenAI 카탈로그를 관리합니다.</p>
          </div>
          <button type="button" class="cs-btn cs-btn-sm" id="soCopyT2DraftBtn">T2 정책 PR 초안 복사</button>
        </div>
        <div class="seg-group" role="group" aria-label="AI 모델 세부 보기">
          ${[["overview", "개요"], ["catalog", "모델 카탈로그 (4)"], ["routing", "T1/T2 라우팅"], ["web-search", "웹 검색 허용 도메인"]].map(([v, l]) =>
            `<button type="button" class="seg-btn${soState.modelsTab === v ? " is-active" : ""}" data-so-models-tab="${v}">${l}</button>`
          ).join("")}
        </div>
        ${soState.modelsTab === "catalog" ? `
          <div class="settings-overlay-card">
            <strong>승인된 Azure OpenAI · 교차 검증 모델 카탈로그 (4종)</strong>
            <table class="data-table">
              <thead><tr><th>배포 모델</th><th>공급자 · 리전</th><th>역할</th><th>p95 지연</th><th>상태</th></tr></thead>
              <tbody>
                <tr><td>gpt-4o-mini-narrator</td><td>Azure OpenAI · koreacentral</td><td>T1 내레이터</td><td>340ms</td><td><span class="cs-badge tone-live"><span class="cs-dot"></span>검증됨</span></td></tr>
                <tr><td>gpt-4o-ops-kr</td><td>Azure OpenAI · koreacentral</td><td>T2 주 추론</td><td>920ms</td><td><span class="cs-badge tone-live"><span class="cs-dot"></span>검증됨</span></td></tr>
                <tr><td>o3-mini-verifier</td><td>Cross-Verifier · japaneast</td><td>T2 독립 검증기</td><td>1,180ms</td><td><span class="cs-badge tone-live"><span class="cs-dot"></span>검증됨</span></td></tr>
                <tr><td>phi-4-guard-local</td><td>Local Guard · loopback</td><td>T1 분류 백업</td><td>110ms</td><td><span class="cs-badge tone-neutral"><span class="cs-dot"></span>대기</span></td></tr>
              </tbody>
            </table>
          </div>
        ` : soState.modelsTab === "web-search" ? `
          <div class="settings-overlay-card">
            <div class="settings-overlay-row">
              <div class="settings-overlay-row-meta"><strong>제한된 웹 검색 허용</strong><span>허용 도메인 목록의 공식 문서만 조회하며 원문 스니펫은 마스킹 검증합니다.</span></div>
              <button type="button" class="cs-switch" role="switch" aria-checked="${soState.webSearchEnabled}" aria-label="웹 검색 허용" data-so-acct-switch="webSearchEnabled"><span class="cs-switch-thumb" aria-hidden="true"></span></button>
            </div>
            <div style="display:flex;flex-wrap:wrap;gap:6px;">
              ${soState.allowedDomains.map((d) => `<span class="cs-badge tone-neutral">${d} <button type="button" style="border:0;background:transparent;color:inherit;cursor:pointer;padding:0 2px;" data-so-del-domain="${d}" aria-label="${d} 제거">×</button></span>`).join("")}
            </div>
            <div style="display:flex;gap:8px;margin-top:6px;">
              <input type="text" class="cs-input" style="flex:1" id="soDomainInput" placeholder="예: docs.github.com">
              <button type="button" class="cs-btn cs-btn-sm" id="soAddDomainBtn">도메인 추가</button>
            </div>
          </div>
        ` : `
          <div class="settings-overlay-card">
            <div class="settings-overlay-row">
              <div class="settings-overlay-row-meta"><strong>T0 / T1 결정론 우선 처리</strong><span>반복 운영 이벤트는 AI 호출 없이 규칙·정책 엔진으로 먼저 해결합니다.</span></div>
              <button type="button" class="cs-switch" role="switch" aria-checked="${soState.t0First}" aria-label="T0 T1 결정론 우선" data-so-acct-switch="t0First"><span class="cs-switch-thumb" aria-hidden="true"></span></button>
            </div>
            <div class="settings-overlay-row">
              <div class="settings-overlay-row-meta"><strong>T2 독립 교차 검증기 필수 (헌법 불변식)</strong><span>T2 추론은 주 모델과 분리된 독립 검증기의 통과 없이 실행 제안을 생성할 수 없습니다.</span></div>
              <span class="cs-badge tone-live"><span class="cs-dot"></span>잠금 · 해제 불가</span>
            </div>
            <div class="settings-overlay-row">
              <div class="settings-overlay-row-meta"><strong>T1 내레이터 기본 바인딩</strong><span>대화 요약 및 브리핑 작성에 사용할 검증된 경량 배포를 선택합니다.</span></div>
              <select class="cs-select" aria-label="T1 내레이터 모델" id="soNarratorSel">
                <option value="gpt-4o-mini-narrator"${soState.narratorModel === "gpt-4o-mini-narrator" ? " selected" : ""}>gpt-4o-mini-narrator (Azure KR)</option>
                <option value="phi-4-guard-local"${soState.narratorModel === "phi-4-guard-local" ? " selected" : ""}>phi-4-guard-local (Loopback)</option>
              </select>
            </div>
            <div class="settings-overlay-row">
              <div class="settings-overlay-row-meta"><strong>T2 주 모델 · 보조 교차 검증기 쌍</strong><span>${sameProvider ? "동일 공급자 조합은 차단됩니다. 서로 다른 공급자/검증기를 선택하세요." : "공급자 분리 검증 통과 (Mixed-Model Verifier Ready)"}</span></div>
              <div class="settings-overlay-row-ctrl">
                <select class="cs-select" aria-label="T2 주 모델" id="soT2PrimarySel">
                  <option value="azure-openai::gpt-4o-ops-kr"${soState.t2Primary === "azure-openai::gpt-4o-ops-kr" ? " selected" : ""}>azure-openai · gpt-4o-ops-kr</option>
                  <option value="cross-verifier::o3-mini-verifier"${soState.t2Primary === "cross-verifier::o3-mini-verifier" ? " selected" : ""}>cross-verifier · o3-mini-verifier</option>
                </select>
                <select class="cs-select" aria-label="T2 보조 검증기" id="soT2SecondarySel">
                  <option value="cross-verifier::o3-mini-verifier"${soState.t2Secondary === "cross-verifier::o3-mini-verifier" ? " selected" : ""}>cross-verifier · o3-mini-verifier</option>
                  <option value="azure-openai::gpt-4o-ops-kr"${soState.t2Secondary === "azure-openai::gpt-4o-ops-kr" ? " selected" : ""}>azure-openai · gpt-4o-ops-kr</option>
                </select>
              </div>
            </div>
          </div>
        `}
      `;
    }

    if (panelId === "settings-runtime") {
      const highImpact = soState.autonomyProfile !== "standard-shadow" || Number(soState.approvalExpiryMin) >= 60;
      let jsonOk = true;
      try { const p = JSON.parse(soState.runtimeJson); if (!p || typeof p !== "object" || Array.isArray(p)) jsonOk = false; } catch { jsonOk = false; }
      return `
        <div class="settings-overlay-page-head">
          <div>
            <h3>운영 정책</h3>
            <p>Shadow 시작 불변식, 자율성 프로필, 승인 만료 및 실행 가드레일을 관리합니다.</p>
          </div>
          <span class="cs-badge tone-neutral">Owner 권한 필요</span>
        </div>
        <div class="settings-overlay-card">
          <strong>잠금 보호 헌법 불변식 (해제 불가)</strong>
          <div class="settings-overlay-row">
            <div class="settings-overlay-row-meta"><strong>신규 기능 Shadow 모드 시작</strong><span>승격 심사(Promotion Gate) 없이 신규 기능이 자동 실행 모드로 시작할 수 없습니다.</span></div>
            <span class="cs-badge tone-live"><span class="cs-dot"></span>잠금 · 불변식</span>
          </div>
          <div class="settings-overlay-row">
            <div class="settings-overlay-row-meta"><strong>미수집 지표 0 대체 금지</strong><span>수집되지 않은 메트릭·비용·보안 신호는 0으로 추정하지 않고 미측정으로 분리 표시합니다.</span></div>
            <span class="cs-badge tone-live"><span class="cs-dot"></span>잠금 · 불변식</span>
          </div>
        </div>
        <div class="settings-overlay-card">
          <div class="settings-overlay-row">
            <div class="settings-overlay-row-meta"><strong>자율성 프로필</strong><span>고영향 프로필 변경 시 아래 위험 확인 체크박스가 필수입니다.</span></div>
            <select class="cs-select" aria-label="자율성 프로필" id="soAutonomySel">
              <option value="standard-shadow"${soState.autonomyProfile === "standard-shadow" ? " selected" : ""}>표준 운영 (Shadow 우선 · 권장)</option>
              <option value="single-operator-dev"${soState.autonomyProfile === "single-operator-dev" ? " selected" : ""}>단일 운영자 개발 (전용 테스트 범위)</option>
              <option value="enforced-guarded"${soState.autonomyProfile === "enforced-guarded" ? " selected" : ""}>승인된 제한 자동 실행 (7대 안전장치)</option>
            </select>
          </div>
          <div class="settings-overlay-row">
            <div class="settings-overlay-row-meta"><strong>승인 요청 유효 만료 시간 (분)</strong><span>만료된 승인 요청은 자동 거부되며 침묵은 권한을 부여하지 않습니다.</span></div>
            <select class="cs-select" aria-label="승인 만료 시간" id="soExpirySel">
              <option value="15"${soState.approvalExpiryMin === "15" ? " selected" : ""}>15분</option>
              <option value="30"${soState.approvalExpiryMin === "30" ? " selected" : ""}>30분 (권장)</option>
              <option value="60"${soState.approvalExpiryMin === "60" ? " selected" : ""}>60분 (고영향)</option>
            </select>
          </div>
          <div class="settings-overlay-risk-box" id="soRuntimeRiskBox" ${highImpact ? "" : "hidden"}>
            <strong>고영향 운영 정책 변경 확인 필요</strong>
            <span>자율성 범위 확대 또는 승인 만료 60분 이상 설정은 감사 로그에 기록됩니다. 확인 체크 후 저장할 수 있습니다.</span>
            <label style="display:flex;align-items:center;gap:8px;cursor:pointer;">
              <input type="checkbox" id="soRuntimeRiskCheck" ${soState.riskConfirmed ? "checked" : ""}>
              <span>7대 안전장치(롤백·드라이런·잠금·2단계 감사) 유지를 확인했습니다.</span>
            </label>
          </div>
          <div class="settings-overlay-grid-2">
            <label style="display:grid;gap:6px;font-size:13px;">
              <strong>조사 턴 예산 (최대)</strong>
              <input type="number" class="cs-input" id="soTurnBudget" min="3" max="30" value="${soState.turnBudget}">
            </label>
            <label style="display:grid;gap:6px;font-size:13px;">
              <strong>배치 동시 실행 한도</strong>
              <input type="number" class="cs-input" id="soBatchConc" min="1" max="16" value="${soState.batchConcurrency}">
            </label>
          </div>
          <label style="display:grid;gap:6px;font-size:13px;">
            <span><strong>고급 정책 오버라이드 (JSON 객체)</strong> · <span class="wb-item-sub">${jsonOk ? "JSON 구문 정상" : "유효한 JSON 객체를 입력하세요"}</span></span>
            <textarea class="settings-overlay-textarea" id="soRuntimeJson">${soState.runtimeJson}</textarea>
          </label>
        </div>
      `;
    }

    if (panelId === "settings-iam") {
      const roster = [
        { user: "admin@contoso-ops.example", role: "Owner", agents: "Odin · Forseti · Saga", scope: "전체 구독 (3)" },
        { user: "minsu.park@contoso-ops.example", role: "Operator", agents: "Heimdall · Thor · Freyr", scope: "prod-core-kr" },
        { user: "jiyoung.lee@contoso-ops.example", role: "Operator", agents: "Vidar · Var · Njord", scope: "sec-shared-hub" },
        { user: "audit.viewer@contoso-ops.example", role: "Viewer", agents: "읽기 전용 (감사 열람)", scope: "전체 구독 (조회)" }
      ].filter((r) => soState.iamRoleFilter === "all" || r.role === soState.iamRoleFilter);
      return `
        <div class="settings-overlay-page-head">
          <div>
            <h3>사용자 · 권한</h3>
            <p>승인자·실행자 분리 불변식, 역할 권한 매트릭스, 15-판테온 담당자 배정 및 통제된 액세스 요청을 관리합니다.</p>
          </div>
          <span class="cs-badge tone-live"><span class="cs-dot"></span>승인자 ≠ 실행자 잠금</span>
        </div>
        <div class="seg-group" role="group" aria-label="IAM 탭">
          ${[["my-access", "내 권한"], ["users", "사용자 · 배정 (4)"], ["roles", "역할 · 기능 매트릭스"], ["requests", `액세스 요청 (${soState.iamRequests.filter((r) => r.status === "pending").length})`]].map(([v, l]) =>
            `<button type="button" class="seg-btn${soState.iamTab === v ? " is-active" : ""}" data-so-iam-tab="${v}">${l}</button>`
          ).join("")}
        </div>
        ${soState.iamTab === "roles" ? `
          <div class="settings-overlay-card">
            <strong>Owner / Operator / Viewer 권한 매트릭스</strong>
            <table class="data-table">
              <thead><tr><th>기능 영역</th><th>Owner</th><th>Operator</th><th>Viewer</th></tr></thead>
              <tbody>
                <tr><td>대시보드 · 온톨로지 · 감사 조회</td><td>허용</td><td>허용</td><td>허용</td></tr>
                <tr><td>승인 요청(HIL) 검토 및 승인</td><td>허용</td><td>할당 범위</td><td>차단</td></tr>
                <tr><td>운영 정책 · T2 모델 바인딩 변경</td><td>허용</td><td>제안만</td><td>차단</td></tr>
                <tr><td>사용자 역할 · 액세스 요청 승인</td><td>허용</td><td>차단</td><td>차단</td></tr>
                <tr><td>본인 요청 자가 승인 (Self-Approval)</td><td>차단 (불변식)</td><td>차단 (불변식)</td><td>차단</td></tr>
              </tbody>
            </table>
          </div>
        ` : soState.iamTab === "requests" ? `
          <div style="display:grid;gap:10px;">
            ${soState.iamRequests.map((req) => `
              <div class="settings-overlay-card">
                <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
                  <strong>${req.actor} → ${req.role}</strong>
                  <span class="cs-badge tone-${req.status === "approved" ? "live" : req.status === "rejected" ? "sec" : "sre"}">${req.status === "approved" ? "승인됨" : req.status === "rejected" ? "반려됨" : "검토 대기"}</span>
                </div>
                <div class="wb-item-sub">사유 (${req.reason.length}자): ${req.reason}</div>
                ${req.selfOwned ? `<div class="wb-item-sub">본인 요청은 헌법 불변식에 따라 <strong>자가 승인 차단</strong> 상태입니다.</div>` : req.status === "pending" ? `
                  <div style="display:flex;gap:8px;">
                    <button type="button" class="cs-btn cs-btn-sm cs-btn-accent" data-so-iam-act="approve" data-req-id="${req.id}">승인</button>
                    <button type="button" class="cs-btn cs-btn-sm" data-so-iam-act="reject" data-req-id="${req.id}">반려</button>
                  </div>
                ` : ""}
              </div>
            `).join("")}
          </div>
        ` : soState.iamTab === "users" ? `
          <div class="settings-overlay-card">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
              <strong>사용자 · 15-판테온 담당자 배정</strong>
              <select class="cs-select" aria-label="역할 필터" id="soIamFilterSel">
                <option value="all"${soState.iamRoleFilter === "all" ? " selected" : ""}>전체 역할</option>
                <option value="Owner"${soState.iamRoleFilter === "Owner" ? " selected" : ""}>Owner</option>
                <option value="Operator"${soState.iamRoleFilter === "Operator" ? " selected" : ""}>Operator</option>
                <option value="Viewer"${soState.iamRoleFilter === "Viewer" ? " selected" : ""}>Viewer</option>
              </select>
            </div>
            <table class="data-table">
              <thead><tr><th>사용자</th><th>역할</th><th>담당 에이전트</th><th>범위</th></tr></thead>
              <tbody>
                ${roster.map((r) => `<tr><td>${r.user}</td><td><span class="cs-badge tone-neutral">${r.role}</span></td><td>${r.agents}</td><td>${r.scope}</td></tr>`).join("")}
              </tbody>
            </table>
          </div>
        ` : `
          <div class="settings-overlay-card">
            <strong>현재 로그인 계정 권한 요약</strong>
            <div class="settings-overlay-row"><div class="settings-overlay-row-meta"><strong>계정 · 역할</strong><span>admin@contoso-ops.example · Owner (전체 구독)</span></div><span class="cs-badge tone-live"><span class="cs-dot"></span>인증됨</span></div>
            <div class="settings-overlay-row"><div class="settings-overlay-row-meta"><strong>승인자 ≠ 실행자 분리</strong><span>인간 승인 ID와 격리 실행기 ID를 항상 분리합니다. 자가 승인 차단 유지.</span></div><span class="cs-badge tone-live"><span class="cs-dot"></span>잠금 · 불변식</span></div>
          </div>
        `}
      `;
    }

    if (panelId === "settings-integrations") {
      const maskedUrl = soState.webhookMasked
        ? "https://hooks.slack.com/services/T0000/B0000/••••••••••••9f2a"
        : "https://hooks.slack.com/services/T0000/B0000/demo-webhook-masked-token";
      return `
        <div class="settings-overlay-page-head">
          <div>
            <h3>외부 연동</h3>
            <p>Teams A1 양방향 승인, Teams/Slack Webhook 알림, 이메일 템플릿 및 문서 OCR 연동을 관리합니다.</p>
          </div>
          <span class="cs-badge tone-live"><span class="cs-dot"></span>전송 채널 정상</span>
        </div>
        <div class="settings-overlay-card">
          <strong>A1 양방향 승인 · Microsoft Teams 온보딩</strong>
          <div class="settings-overlay-grid-2">
            <div class="settings-overlay-card" style="background:var(--cs-bg);">
              <strong>1. 자동 프로비저닝 완료</strong>
              <div class="wb-item-sub">Bot 앱 등록 · HMAC 서명 검증 · 감사 릴레이 엔드포인트 연결됨</div>
            </div>
            <div class="settings-overlay-card" style="background:var(--cs-bg);">
              <strong>2. 테넌트 관리자 확인</strong>
              <div class="wb-item-sub">Teams 승인 채널 허용 목록 등록 완료 (A4 자동 파괴 작업은 항상 차단)</div>
            </div>
          </div>
        </div>
        <div class="settings-overlay-card">
          <strong>A2/A4 알림 · Teams / Slack Webhook</strong>
          <div class="settings-overlay-row">
            <div class="settings-overlay-row-meta"><strong>Webhook 엔드포인트</strong><span><code>${maskedUrl}</code> · 최근 진단: ${soState.webhookTestStatus}</span></div>
            <div class="settings-overlay-row-ctrl">
              <button type="button" class="cs-btn cs-btn-sm" id="soToggleWebhookMask">${soState.webhookMasked ? "표시" : "숨김"}</button>
              <button type="button" class="cs-btn cs-btn-sm cs-btn-accent" id="soTestWebhookBtn">테스트 발송</button>
            </div>
          </div>
        </div>
        <div class="settings-overlay-card">
          <strong>이메일 알림 수신자 · 템플릿 미리보기</strong>
          <div style="display:flex;flex-wrap:wrap;gap:12px;align-items:center;">
            <label style="display:inline-flex;align-items:center;gap:6px;cursor:pointer;"><input type="radio" name="soEmailTarget" value="account" ${soState.emailTarget === "account" ? "checked" : ""}> 로그인 계정</label>
            <label style="display:inline-flex;align-items:center;gap:6px;cursor:pointer;"><input type="radio" name="soEmailTarget" value="custom" ${soState.emailTarget === "custom" ? "checked" : ""}> 직접 지정</label>
            <input type="email" class="cs-input" style="width:240px" id="soEmailCustomInput" value="${soState.emailCustom}" ${soState.emailTarget === "custom" ? "" : "disabled"}>
            <div class="seg-group" role="group" aria-label="이메일 미리보기 형식">
              <button type="button" class="seg-btn${soState.emailPreviewMode === "html" ? " is-active" : ""}" data-so-email-mode="html">HTML</button>
              <button type="button" class="seg-btn${soState.emailPreviewMode === "text" ? " is-active" : ""}" data-so-email-mode="text">일반텍스트</button>
            </div>
          </div>
          <div class="settings-overlay-email-preview">
            ${soState.emailPreviewMode === "html"
              ? `<strong>[FDAI 승인 요청] prod-aks-02 노드 풀 확장 초안 (HIL-8841)</strong><div class="wb-item-sub">근거: EWMA +5m 포화 예측 91% · 롤백 검증 완료 · 승인 만료 30분</div>`
              : `<pre>Subject: [FDAI 승인 요청] prod-aks-02 노드 풀 확장 초안 (HIL-8841)\nEvidence: EWMA +5m saturation 91% | Rollback verified | TTL 30m</pre>`}
          </div>
        </div>
        <div class="settings-overlay-card">
          <strong>문서 OCR 공급자</strong>
          <div style="display:flex;flex-wrap:wrap;gap:14px;">
            <label style="display:inline-flex;align-items:center;gap:6px;cursor:pointer;"><input type="radio" name="soOcrProvider" value="azure-doc-intel" ${soState.ocrProvider === "azure-doc-intel" ? "checked" : ""}> Azure Document Intelligence (권장)</label>
            <label style="display:inline-flex;align-items:center;gap:6px;cursor:pointer;"><input type="radio" name="soOcrProvider" value="local-fallback" ${soState.ocrProvider === "local-fallback" ? "checked" : ""}> 로컬 결정론적 텍스트 추출기</label>
          </div>
        </div>
      `;
    }

    if (panelId === "settings-diagnostics") {
      const svcs = [
        [":8010", "core-control-plane", "정상", soState.diagP95],
        [":8011", "operator-service", "정상", "14ms"],
        [":8012", "ontology-engine", "정상", "9ms"],
        [":8013", "policy-evaluator", "정상", "6ms"],
        [":8014", "audit-ledger", "정상", "11ms"],
        [":8016", "observer-gateway", "정상", "22ms"]
      ];
      return `
        <div class="settings-overlay-page-head">
          <div>
            <h3>시스템 상태 진단</h3>
            <p>읽기 전용 런타임·인프라·인증 진단입니다. 이 화면에는 편집 컨트롤이 없습니다.</p>
          </div>
          <div class="settings-overlay-row-ctrl">
            <button type="button" class="cs-btn cs-btn-sm" id="soDiagReprobeBtn">전체 재진단 ↻</button>
            <button type="button" class="cs-btn cs-btn-sm" id="soDiagCopyBtn">마스킹된 지원 요약 복사</button>
          </div>
        </div>
        <div class="settings-overlay-card">
          <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
            <strong>Pure-Rust 6개 핵심 서비스 상태 매트릭스</strong>
            <span class="wb-item-sub">최근 프로브: ${soState.diagTimestamp}</span>
          </div>
          <table class="data-table">
            <thead><tr><th>포트</th><th>서비스</th><th>상태</th><th>p95 응답</th></tr></thead>
            <tbody>
              ${svcs.map(([p, n, s, l]) => `<tr><td><code>${p}</code></td><td>${n}</td><td><span class="cs-badge tone-live"><span class="cs-dot"></span>${s}</span></td><td>${l}</td></tr>`).join("")}
            </tbody>
          </table>
        </div>
        <div class="settings-overlay-grid-2">
          <div class="settings-overlay-card"><strong>PostgreSQL (5432 Durable)</strong><span class="cs-badge tone-live"><span class="cs-dot"></span>연결 정상 · WAL 12MB</span></div>
          <div class="settings-overlay-card"><strong>Event Bus (Pub/Sub)</strong><span class="cs-badge tone-live"><span class="cs-dot"></span>정상 · 지연 4ms</span></div>
          <div class="settings-overlay-card"><strong>Ontology Cache</strong><span class="cs-badge tone-live"><span class="cs-dot"></span>신선도 99.6%</span></div>
          <div class="settings-overlay-card is-unmeasured"><strong>Key Vault 진단 프로파일</strong><span class="cs-badge tone-neutral"><span class="cs-dot"></span>미수집 (로컬 베뉴 분리)</span></div>
        </div>
      `;
    }

    // settings-memory
    const filteredMem = soState.opMemories.filter((m) => {
      if (soState.memScope !== "all" && m.scope !== soState.memScope) return false;
      if (soState.memSearch && !`${m.target} ${m.body}`.toLowerCase().includes(soState.memSearch.toLowerCase())) return false;
      return true;
    });
    return `
      <div class="settings-overlay-page-head">
        <div>
          <h3>저장된 운영 메모</h3>
          <p>메모는 운영 참고 맥락만 제공하며, 어떠한 실행 권한도 부여하지 않습니다.</p>
        </div>
        <span class="cs-badge tone-neutral">권한 부여 불가</span>
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between;">
        <div class="seg-group" role="group" aria-label="메모 범위 필터">
          ${[["all", "전체"], ["구독", "구독"], ["리소스 그룹", "리소스 그룹"], ["리소스", "리소스"]].map(([v, l]) =>
            `<button type="button" class="seg-btn${soState.memScope === v ? " is-active" : ""}" data-so-mem-scope="${v}">${l}</button>`
          ).join("")}
        </div>
        <input type="search" class="cs-input" style="width:220px" id="soMemSearch" placeholder="대상·내용 검색..." value="${soState.memSearch}">
      </div>
      <div style="display:grid;gap:10px;">
        ${filteredMem.map((m) => `
          <div class="settings-overlay-card">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;">
              <span><span class="cs-badge tone-neutral">${m.scope}</span> <strong>${m.target}</strong></span>
              <span class="wb-item-sub">만료 D-${m.expiresDays}일</span>
            </div>
            <div>${m.body}</div>
            <div style="display:flex;gap:8px;align-items:center;">
              <button type="button" class="cs-btn cs-btn-sm" data-so-mem-extend="${m.id}">+14일 연장</button>
              ${soState.memPendingDelete === m.id
                ? `<button type="button" class="cs-btn cs-btn-sm cs-btn-accent" data-so-mem-confirm-del="${m.id}">삭제 확정</button><button type="button" class="cs-btn cs-btn-sm" id="soMemCancelDel">취소</button>`
                : `<button type="button" class="cs-btn cs-btn-sm" data-so-mem-ask-del="${m.id}">삭제</button>`}
            </div>
          </div>
        `).join("") || `<div class="wb-item-sub">조건에 일치하는 운영 메모가 없습니다.</div>`}
      </div>
      <details class="settings-overlay-card">
        <summary style="cursor:pointer;font-weight:600;">압축 이력 (Compactions · 3건)</summary>
        <div class="wb-item-sub" style="margin-top:8px;">2026-11-24: 만료 메모 4건 정리 (해시 보존) · 2026-11-18: 중복 메모 2건 병합 · 2026-11-10: 정기 스냅샷 압축</div>
      </details>
    `;
  }

  function renderSettingsOverlay() {
    const navList = document.getElementById("soNavList");
    const content = document.getElementById("soContent");
    const fullLink = document.getElementById("soOpenFullPageLink");
    if (!navList || !content) return;
    const activeGroup = findSettingsGroupForPanel(soState.activePanel);
    if (fullLink) fullLink.setAttribute("href", panelUrl(soState.activePanel));

    navList.innerHTML = SETTINGS_GROUPS.map((g) => {
      const isCur = g.id === activeGroup.id;
      return `
        <li>
          <button type="button" class="settings-overlay-nav-btn${isCur ? " is-active" : ""}" data-so-group="${g.id}" ${isCur ? 'aria-current="page"' : ""}>
            <strong>${g.label}</strong>
            <small>${g.hint}</small>
          </button>
        </li>
      `;
    }).join("");

    const subtabsHtml = activeGroup.tabs.length > 1
      ? `<nav class="settings-overlay-subtabs" aria-label="세부 보기 탭">${activeGroup.tabs.map((t) =>
          `<button type="button" class="settings-overlay-subtab${t.id === soState.activePanel ? " is-active" : ""}" data-so-subtab="${t.id}" ${t.id === soState.activePanel ? 'aria-current="page"' : ""}>${t.label}</button>`
        ).join("")}</nav>`
      : "";

    const isReadonlyDiag = soState.activePanel === "settings-diagnostics";
    const highImpact = soState.activePanel === "settings-runtime"
      && (soState.autonomyProfile !== "standard-shadow" || Number(soState.approvalExpiryMin) >= 60);
    const saveDisabled = highImpact && !soState.riskConfirmed;
    const saveBarHtml = isReadonlyDiag ? "" : `
      <div class="settings-overlay-save-bar" id="soSaveBar" ${soState.dirtyCount > 0 ? "" : "hidden"}>
        <span><strong>저장되지 않은 변경 ${soState.dirtyCount}건</strong> · 저장 전까지 운영 설정은 변경되지 않습니다.</span>
        <div class="settings-overlay-row-ctrl">
          <button type="button" class="cs-btn cs-btn-sm" id="soDiscardBtn">변경 취소</button>
          <button type="button" class="cs-btn cs-btn-sm cs-btn-accent" id="soSaveBtn" ${saveDisabled ? "disabled" : ""}>변경 저장</button>
        </div>
      </div>
    `;

    content.innerHTML = `
      <div class="settings-overlay-unsaved" id="soUnsavedPrompt" role="alert" ${soState.pendingAction ? "" : "hidden"}>
        <span>저장되지 않은 설정 변경 사항이 있습니다. 변경을 취소하고 이동할까요?</span>
        <div class="settings-overlay-row-ctrl">
          <button type="button" class="cs-btn cs-btn-sm" id="soStayBtn">현재 화면 유지</button>
          <button type="button" class="cs-btn cs-btn-sm cs-btn-accent" id="soDiscardGoBtn">변경 취소 후 이동</button>
        </div>
      </div>
      ${subtabsHtml}
      ${renderSettingsPanelBody(soState.activePanel)}
      ${saveBarHtml}
    `;

    navList.querySelectorAll("[data-so-group]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const g = SETTINGS_GROUPS.find((x) => x.id === btn.getAttribute("data-so-group"));
        if (!g) return;
        requestSettingsPanelSwitch(g.tabs[0].id);
      });
    });
    content.querySelectorAll("[data-so-subtab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const pid = btn.getAttribute("data-so-subtab");
        if (pid) requestSettingsPanelSwitch(pid);
      });
    });
    document.getElementById("soStayBtn")?.addEventListener("click", () => {
      soState.pendingAction = null;
      renderSettingsOverlay();
    });
    document.getElementById("soDiscardGoBtn")?.addEventListener("click", () => {
      const act = soState.pendingAction;
      soState.dirtyCount = 0;
      soState.pendingAction = null;
      if (act === "__CLOSE__") closeSettingsOverlay(true);
      else if (act) { soState.activePanel = act; renderSettingsOverlay(); }
    });
    document.getElementById("soDiscardBtn")?.addEventListener("click", () => {
      soState.dirtyCount = 0;
      soState.pendingAction = null;
      showToast("저장되지 않은 변경을 취소했습니다.");
      renderSettingsOverlay();
    });
    document.getElementById("soSaveBtn")?.addEventListener("click", () => {
      soState.dirtyCount = 0;
      soState.pendingAction = null;
      showToast("설정 변경 사항이 저장되었습니다.");
      renderSettingsOverlay();
    });

    // Wire per-panel interactive controls
    content.querySelectorAll("[data-so-jump]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = document.getElementById(btn.getAttribute("data-so-jump") || "");
        target?.scrollIntoView({ behavior: "smooth", block: "start" });
        content.querySelectorAll("[data-so-jump]").forEach((b) => b.classList.toggle("is-active", b === btn));
      });
    });
    content.querySelectorAll("[data-so-theme]").forEach((btn) => {
      btn.addEventListener("click", () => {
        setLiveTheme(btn.getAttribute("data-so-theme") || "light");
        showToast(`테마가 ${getCurrentTheme() === "dark" ? "다크" : "라이트"} 모드로 즉시 적용되었습니다.`);
        renderSettingsOverlay();
      });
    });
    content.querySelectorAll("[data-so-locale]").forEach((btn) => {
      btn.addEventListener("click", () => {
        soState.locale = btn.getAttribute("data-so-locale") || "ko";
        showToast(`표시 언어가 ${soState.locale === "en" ? "English" : "한국어"}로 선택되었습니다.`);
        renderSettingsOverlay();
      });
    });
    content.querySelectorAll("[data-so-browser-switch]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.getAttribute("data-so-browser-switch");
        if (key && key in soState) {
          soState[key] = !soState[key];
          showToast("브라우저 표시 설정이 즉시 적용되었습니다.");
          renderSettingsOverlay();
        }
      });
    });
    content.querySelectorAll("[data-so-acct-seg]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.getAttribute("data-so-acct-seg");
        const val = btn.getAttribute("data-val");
        if (key && val) { soState[key] = val; soState.dirtyCount += 1; renderSettingsOverlay(); }
      });
    });
    content.querySelectorAll("[data-so-acct-switch]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const key = btn.getAttribute("data-so-acct-switch");
        if (key && key in soState) { soState[key] = !soState[key]; soState.dirtyCount += 1; renderSettingsOverlay(); }
      });
    });
    document.getElementById("soTzInput")?.addEventListener("change", (e) => {
      soState.timezone = e.target.value;
      soState.dirtyCount += 1;
      renderSettingsOverlay();
    });
    document.getElementById("soToggleOpeningBriefing")?.addEventListener("click", () => {
      soState.openingBriefing = !soState.openingBriefing;
      showToast(soState.openingBriefing ? "대화 시작 브리핑이 활성화되었습니다." : "대화 시작 브리핑이 비활성화되었습니다.");
      renderSettingsOverlay();
    });
    document.getElementById("soBriefingHour")?.addEventListener("change", (e) => {
      soState.briefingHour = e.target.value;
      renderSettingsOverlay();
    });
    document.getElementById("soAddBriefingBtn")?.addEventListener("click", () => {
      const hr = String(Math.max(0, Math.min(23, Number(soState.briefingHour) || 0))).padStart(2, "0");
      soState.briefings.push({ id: `br-${Date.now()}`, name: "맞춤 운영 브리핑", hour: `${hr}:00`, tz: soState.timezone, nextRun: `내일 ${hr}:00` });
      showToast(`매일 ${hr}:00 일일 브리핑이 추가되었습니다.`);
      renderSettingsOverlay();
    });
    content.querySelectorAll("[data-so-del-briefing]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-so-del-briefing");
        soState.briefings = soState.briefings.filter((b) => b.id !== id);
        showToast("일일 브리핑 구독이 해제되었습니다.");
        renderSettingsOverlay();
      });
    });
    content.querySelectorAll("[data-so-del-pmem]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-so-del-pmem");
        soState.personalMemories = soState.personalMemories.filter((m) => m.id !== id);
        showToast("개인 메모리가 삭제되었습니다.");
        renderSettingsOverlay();
      });
    });
    document.getElementById("soResetPrefsBtn")?.addEventListener("click", () => {
      soState.answerDetail = "standard";
      soState.answerFormat = "mixed";
      soState.timezone = "Asia/Seoul";
      soState.shareWithLearner = false;
      soState.dirtyCount = 0;
      setLiveTheme("light");
      showToast("환경 설정이 기본값으로 초기화되었습니다.");
      renderSettingsOverlay();
    });
    document.getElementById("soEnvRefreshBtn")?.addEventListener("click", () => {
      soState.envRefreshedAt = `방금 전 (${new Date().toTimeString().slice(0, 8)} KST)`;
      showToast("실행 환경 및 수집기 근거를 새로고침했습니다.");
      renderSettingsOverlay();
    });
    content.querySelectorAll("[data-so-env-filter]").forEach((btn) => {
      btn.addEventListener("click", () => { soState.envFilter = btn.getAttribute("data-so-env-filter") || "all"; renderSettingsOverlay(); });
    });
    document.getElementById("soEnvSearch")?.addEventListener("input", (e) => {
      soState.envSearch = e.target.value;
      renderSettingsOverlay();
    });
    content.querySelectorAll("[data-so-models-tab]").forEach((btn) => {
      btn.addEventListener("click", () => { soState.modelsTab = btn.getAttribute("data-so-models-tab") || "overview"; renderSettingsOverlay(); });
    });
    document.getElementById("soCopyT2DraftBtn")?.addEventListener("click", () => {
      showToast("T2 모델 바인딩 정책 PR 초안을 클립보드에 복사했습니다.");
    });
    document.getElementById("soNarratorSel")?.addEventListener("change", (e) => { soState.narratorModel = e.target.value; soState.dirtyCount += 1; renderSettingsOverlay(); });
    document.getElementById("soT2PrimarySel")?.addEventListener("change", (e) => { soState.t2Primary = e.target.value; soState.dirtyCount += 1; renderSettingsOverlay(); });
    document.getElementById("soT2SecondarySel")?.addEventListener("change", (e) => { soState.t2Secondary = e.target.value; soState.dirtyCount += 1; renderSettingsOverlay(); });
    document.getElementById("soAddDomainBtn")?.addEventListener("click", () => {
      const inp = document.getElementById("soDomainInput");
      const val = (inp?.value || "").trim().toLowerCase();
      if (val && !soState.allowedDomains.includes(val)) { soState.allowedDomains.push(val); soState.dirtyCount += 1; renderSettingsOverlay(); }
    });
    content.querySelectorAll("[data-so-del-domain]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const d = btn.getAttribute("data-so-del-domain");
        soState.allowedDomains = soState.allowedDomains.filter((x) => x !== d);
        soState.dirtyCount += 1;
        renderSettingsOverlay();
      });
    });
    document.getElementById("soAutonomySel")?.addEventListener("change", (e) => { soState.autonomyProfile = e.target.value; soState.riskConfirmed = false; soState.dirtyCount += 1; renderSettingsOverlay(); });
    document.getElementById("soExpirySel")?.addEventListener("change", (e) => { soState.approvalExpiryMin = e.target.value; soState.riskConfirmed = false; soState.dirtyCount += 1; renderSettingsOverlay(); });
    document.getElementById("soRuntimeRiskCheck")?.addEventListener("change", (e) => { soState.riskConfirmed = Boolean(e.target.checked); renderSettingsOverlay(); });
    document.getElementById("soTurnBudget")?.addEventListener("change", (e) => { soState.turnBudget = e.target.value; soState.dirtyCount += 1; renderSettingsOverlay(); });
    document.getElementById("soBatchConc")?.addEventListener("change", (e) => { soState.batchConcurrency = e.target.value; soState.dirtyCount += 1; renderSettingsOverlay(); });
    document.getElementById("soRuntimeJson")?.addEventListener("change", (e) => { soState.runtimeJson = e.target.value; soState.dirtyCount += 1; renderSettingsOverlay(); });
    content.querySelectorAll("[data-so-iam-tab]").forEach((btn) => {
      btn.addEventListener("click", () => { soState.iamTab = btn.getAttribute("data-so-iam-tab") || "my-access"; renderSettingsOverlay(); });
    });
    document.getElementById("soIamFilterSel")?.addEventListener("change", (e) => { soState.iamRoleFilter = e.target.value; renderSettingsOverlay(); });
    content.querySelectorAll("[data-so-iam-act]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const act = btn.getAttribute("data-so-iam-act");
        const id = btn.getAttribute("data-req-id");
        const req = soState.iamRequests.find((r) => r.id === id);
        if (req && !req.selfOwned) {
          req.status = act === "approve" ? "approved" : "rejected";
          showToast(act === "approve" ? "권한 요청이 승인되었습니다." : "권한 요청이 반려되었습니다.");
          renderSettingsOverlay();
        }
      });
    });
    document.getElementById("soToggleWebhookMask")?.addEventListener("click", () => { soState.webhookMasked = !soState.webhookMasked; renderSettingsOverlay(); });
    document.getElementById("soTestWebhookBtn")?.addEventListener("click", () => {
      soState.webhookTestStatus = `HTTP 200 OK · ${new Date().toTimeString().slice(0, 8)} KST`;
      showToast("웹훅 테스트 발송 성공 (HTTP 200 OK)");
      renderSettingsOverlay();
    });
    content.querySelectorAll('input[name="soEmailTarget"]').forEach((r) => {
      r.addEventListener("change", (e) => { soState.emailTarget = e.target.value; soState.dirtyCount += 1; renderSettingsOverlay(); });
    });
    document.getElementById("soEmailCustomInput")?.addEventListener("change", (e) => { soState.emailCustom = e.target.value; soState.dirtyCount += 1; renderSettingsOverlay(); });
    content.querySelectorAll("[data-so-email-mode]").forEach((btn) => {
      btn.addEventListener("click", () => { soState.emailPreviewMode = btn.getAttribute("data-so-email-mode") || "html"; renderSettingsOverlay(); });
    });
    content.querySelectorAll('input[name="soOcrProvider"]').forEach((r) => {
      r.addEventListener("change", (e) => { soState.ocrProvider = e.target.value; soState.dirtyCount += 1; renderSettingsOverlay(); });
    });
    document.getElementById("soDiagReprobeBtn")?.addEventListener("click", () => {
      soState.diagTimestamp = `${new Date().toTimeString().slice(0, 8)} KST`;
      soState.diagP95 = "15ms";
      showToast("전체 시스템 상태 재진단 완료 (6/6 서비스 정상)");
      renderSettingsOverlay();
    });
    document.getElementById("soDiagCopyBtn")?.addEventListener("click", () => {
      showToast("비밀 값이 제거된 지원 진단 요약을 복사했습니다.");
    });
    content.querySelectorAll("[data-so-mem-scope]").forEach((btn) => {
      btn.addEventListener("click", () => { soState.memScope = btn.getAttribute("data-so-mem-scope") || "all"; renderSettingsOverlay(); });
    });
    document.getElementById("soMemSearch")?.addEventListener("input", (e) => { soState.memSearch = e.target.value; renderSettingsOverlay(); });
    content.querySelectorAll("[data-so-mem-extend]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const item = soState.opMemories.find((m) => m.id === btn.getAttribute("data-so-mem-extend"));
        if (item) { item.expiresDays += 14; showToast(`${item.target} 메모 만료가 14일 연장되었습니다.`); renderSettingsOverlay(); }
      });
    });
    content.querySelectorAll("[data-so-mem-ask-del]").forEach((btn) => {
      btn.addEventListener("click", () => { soState.memPendingDelete = btn.getAttribute("data-so-mem-ask-del"); renderSettingsOverlay(); });
    });
    document.getElementById("soMemCancelDel")?.addEventListener("click", () => { soState.memPendingDelete = null; renderSettingsOverlay(); });
    content.querySelectorAll("[data-so-mem-confirm-del]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-so-mem-confirm-del");
        soState.opMemories = soState.opMemories.filter((m) => m.id !== id);
        soState.memPendingDelete = null;
        showToast("운영 메모가 삭제되었습니다.");
        renderSettingsOverlay();
      });
    });
  }

  function requestSettingsPanelSwitch(nextPanelId) {
    if (nextPanelId === soState.activePanel) return;
    if (soState.dirtyCount > 0) {
      soState.pendingAction = nextPanelId;
      renderSettingsOverlay();
      return;
    }
    soState.activePanel = nextPanelId;
    renderSettingsOverlay();
  }

  function openSettingsOverlay(panelId, triggerEl) {
    closeFloatingDrawer();
    const explorer = document.getElementById("fdaiExplorer");
    if (explorer && !explorerPinned) explorer.hidden = true;
    soState.lastTrigger = triggerEl || document.activeElement;
    if (panelId && panelId.startsWith("settings-")) soState.activePanel = panelId;
    soState.pendingAction = null;
    const scrim = ensureSettingsOverlay();
    scrim.hidden = false;
    document.getElementById("railSettingsBtn")?.setAttribute("aria-expanded", "true");
    document.getElementById("railSettingsBtn")?.classList.add("is-active");
    renderSettingsOverlay();
    document.getElementById("soCloseBtn")?.focus();
  }

  function closeSettingsOverlay(force) {
    const scrim = document.getElementById("fdaiSettingsOverlayScrim");
    if (!scrim || scrim.hidden) return;
    if (!force && soState.dirtyCount > 0) {
      soState.pendingAction = "__CLOSE__";
      renderSettingsOverlay();
      return;
    }
    scrim.hidden = true;
    soState.pendingAction = null;
    const railBtn = document.getElementById("railSettingsBtn");
    railBtn?.setAttribute("aria-expanded", "false");
    if (!(activeDomain === "settings_labs" && currentPanelId.startsWith("settings-"))) {
      railBtn?.classList.remove("is-active");
    }
    soState.lastTrigger?.focus?.();
  }

  window.fdaiOpenSettingsOverlay = openSettingsOverlay;
  window.fdaiCloseSettingsOverlay = closeSettingsOverlay;


  window.addEventListener("popstate", () => {
    closeFloatingDrawer();
    const pid = panelFromLocation();
    if (pid && document.querySelector(`.panel-view[data-panel-id="${pid}"]`)) {
      activatePanel(pid);
      window.dispatchEvent(new CustomEvent("fdai:panelchange", { detail: { panelId: pid, url: location.pathname } }));
    }
  });
  window.addEventListener("hashchange", () => {
    closeFloatingDrawer();
    const m = location.hash.match(/tab=([a-z0-9-]+)/i);
    if (m) navigatePanel(m[1], true);
  });
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openCommandPalette();
    } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "j") {
      e.preventDefault();
      toggleChatSidebar();
    } else if ((e.ctrlKey || e.metaKey) && e.key === ",") {
      e.preventDefault();
      const scrim = document.getElementById("fdaiSettingsOverlayScrim");
      if (scrim && !scrim.hidden) closeSettingsOverlay();
      else openSettingsOverlay("settings-general");
    } else if (e.key === "Escape") {
      const soScrim = document.getElementById("fdaiSettingsOverlayScrim");
      if (soScrim && !soScrim.hidden) { closeSettingsOverlay(); return; }
      const cmd = document.getElementById("fdaiCmdBackdrop");
      if (cmd && !cmd.hidden) { cmd.hidden = true; return; }
      const helpPop = document.getElementById("fdaiPageHelpPop");
      if (helpPop && !helpPop.hidden) {
        helpPop.hidden = true;
        document.getElementById("fdaiPageHelpBtn")?.setAttribute("aria-expanded", "false");
        return;
      }
      const fd = document.getElementById("fdaiFloatDrawer");
      if ((fd && !fd.hidden) || activeInlineInspector) { closeFloatingDrawer(); return; }
      const bd = document.getElementById("fdaiDrawerBackdrop");
      if (bd && !bd.hidden) { closeDrawer(); return; }
      if (chatOpen && !chatFullscreen && dockHistoryOpen) { dockHistoryOpen = false; syncChatVisibility(); return; }
      if (chatFullscreen) { setChatFullscreen(false); return; }
      if (chatOpen) toggleChatSidebar(false);
    }
  });

  // Component-First Crisp 1:1 SVG Chart Reflow & Max-Font Scale Guard
  // Guarantees 12px <= rendered SVG text <= 16px across 1280px, 1440px, 1920px, 2560px & 390px
  function mapSvgPathD(d, mx, my) {
    const tokens = d.match(/[a-zA-Z]|[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?/g);
    if (!tokens) return d;
    let out = [];
    let cmd = "";
    let i = 0;
    const isCmd = (t) => /^[a-zA-Z]$/.test(t);
    while (i < tokens.length) {
      if (isCmd(tokens[i])) {
        cmd = tokens[i++];
        out.push(cmd);
        continue;
      }
      if (cmd === "M" || cmd === "L" || cmd === "T") {
        const x = parseFloat(tokens[i++]), y = parseFloat(tokens[i++]);
        out.push(`${mx(x).toFixed(1)},${my(y).toFixed(1)}`);
      } else if (cmd === "H") {
        out.push(mx(parseFloat(tokens[i++])).toFixed(1));
      } else if (cmd === "V") {
        out.push(my(parseFloat(tokens[i++])).toFixed(1));
      } else if (cmd === "Q" || cmd === "S") {
        const x1 = parseFloat(tokens[i++]), y1 = parseFloat(tokens[i++]);
        const x2 = parseFloat(tokens[i++]), y2 = parseFloat(tokens[i++]);
        out.push(`${mx(x1).toFixed(1)},${my(y1).toFixed(1)} ${mx(x2).toFixed(1)},${my(y2).toFixed(1)}`);
      } else if (cmd === "C") {
        const x1 = parseFloat(tokens[i++]), y1 = parseFloat(tokens[i++]);
        const x2 = parseFloat(tokens[i++]), y2 = parseFloat(tokens[i++]);
        const x3 = parseFloat(tokens[i++]), y3 = parseFloat(tokens[i++]);
        out.push(`${mx(x1).toFixed(1)},${my(y1).toFixed(1)} ${mx(x2).toFixed(1)},${my(y2).toFixed(1)} ${mx(x3).toFixed(1)},${my(y3).toFixed(1)}`);
      } else {
        out.push(tokens[i++]);
      }
    }
    return out.join(" ");
  }

  function snapshotChartSvgBase(svg) {
    if (!svg.hasAttribute("data-orig-vb")) {
      const vb = (svg.getAttribute("viewBox") || "").trim();
      const parts = vb.split(/[\s,]+/).map(Number);
      if (parts.length !== 4 || !parts[2] || !parts[3]) return false;
      svg.setAttribute("data-orig-vb", vb);
      svg.setAttribute("data-orig-vbw", String(parts[2]));
      svg.setAttribute("data-orig-vbh", String(parts[3]));
    }
    svg.querySelectorAll("g.forecast-marker").forEach((g) => {
      if (!g.hasAttribute("data-fg-cx")) {
        const c = g.querySelector("circle");
        if (c) {
          g.setAttribute("data-fg-cx", c.getAttribute("cx") || "0");
          g.setAttribute("data-fg-cy", c.getAttribute("cy") || "0");
        }
      }
    });
    svg.querySelectorAll("line, rect, circle, text, polyline, polygon, path").forEach((el) => {
      if (el.closest("defs") || el.closest("g.forecast-marker") || el.hasAttribute("data-ut-overlay")) return;
      ["x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "width", "height", "points", "d"].forEach((attr) => {
        const key = `data-o-${attr}`;
        if (!el.hasAttribute(key) && el.hasAttribute(attr)) {
          el.setAttribute(key, el.getAttribute(attr));
        }
      });
    });
    return true;
  }

  function reflowChartSvg1to1(svg) {
    if (svg._reflowing) return;
    if (!snapshotChartSvgBase(svg)) return;
    const vbW = parseFloat(svg.getAttribute("data-orig-vbw") || "0");
    const vbH = parseFloat(svg.getAttribute("data-orig-vbh") || "0");
    if (vbW < 300 || vbH < 100) return;
    const host = svg.parentElement;
    if (!host) return;
    const hcs = window.getComputedStyle(host);
    const padX = (parseFloat(hcs.paddingLeft) || 0) + (parseFloat(hcs.paddingRight) || 0)
      + (parseFloat(hcs.borderLeftWidth) || 0) + (parseFloat(hcs.borderRightWidth) || 0);
    const availW = Math.floor(host.getBoundingClientRect().width - padX);
    if (availW < 240) return;

    svg._reflowing = true;
    try {
      const targetW = availW > vbW * 1.01 ? availW : vbW;
      const targetH = availW > vbW * 1.01
        ? Math.round(vbH * Math.min(1.22, 1 + (availW - vbW) / 4200))
        : vbH;
      const padL = vbW <= 600 ? 54 : 46;
      const padR = 20;
      const kx = targetW > vbW ? (targetW - padL - padR) / Math.max(1, vbW - padL - padR) : 1;
      const ky = targetH / vbH;
      const mx = (x) => (x <= padL ? x : padL + (x - padL) * kx);
      const my = (y) => y * ky;

      svg.setAttribute("viewBox", `0 0 ${targetW} ${targetH}`);
      svg.style.width = "100%";
      svg.style.maxWidth = "none";
      svg.style.height = availW > vbW * 1.01 ? `${targetH}px` : "auto";
      svg.style.maxHeight = `${Math.round(targetH * 1.08)}px`;

      svg.querySelectorAll("g.forecast-marker").forEach((g) => {
        const ax = parseFloat(g.getAttribute("data-fg-cx") || "0");
        const ay = parseFloat(g.getAttribute("data-fg-cy") || "0");
        const dx = mx(ax) - ax;
        const dy = my(ay) - ay;
        g.setAttribute("transform", Math.abs(dx) < 0.2 && Math.abs(dy) < 0.2 ? "" : `translate(${dx.toFixed(1)}, ${dy.toFixed(1)})`);
      });

      svg.querySelectorAll("line").forEach((el) => {
        if (el.closest("defs") || el.closest("g.forecast-marker") || el.hasAttribute("data-ut-overlay")) return;
        const x1 = el.getAttribute("data-o-x1"), x2 = el.getAttribute("data-o-x2");
        const y1 = el.getAttribute("data-o-y1"), y2 = el.getAttribute("data-o-y2");
        if (x1 !== null) el.setAttribute("x1", mx(parseFloat(x1)).toFixed(1));
        if (x2 !== null) el.setAttribute("x2", mx(parseFloat(x2)).toFixed(1));
        if (y1 !== null) el.setAttribute("y1", my(parseFloat(y1)).toFixed(1));
        if (y2 !== null) el.setAttribute("y2", my(parseFloat(y2)).toFixed(1));
      });

      svg.querySelectorAll("circle").forEach((el) => {
        if (el.closest("defs") || el.closest("g.forecast-marker") || el.hasAttribute("data-ut-overlay")) return;
        const cx = el.getAttribute("data-o-cx"), cy = el.getAttribute("data-o-cy");
        if (cx !== null) el.setAttribute("cx", mx(parseFloat(cx)).toFixed(1));
        if (cy !== null) el.setAttribute("cy", my(parseFloat(cy)).toFixed(1));
      });

      svg.querySelectorAll("rect").forEach((el) => {
        if (el.closest("defs") || el.closest("g.forecast-marker") || el.hasAttribute("data-ut-overlay")) return;
        const ox = el.getAttribute("data-o-x"), oy = el.getAttribute("data-o-y");
        const ow = el.getAttribute("data-o-width"), oh = el.getAttribute("data-o-height");
        if (ox === null || ow === null) return;
        const x = parseFloat(ox), w = parseFloat(ow);
        if (w > vbW * 0.14) {
          const nx = mx(x);
          const nw = Math.max(1, mx(x + w) - nx);
          el.setAttribute("x", nx.toFixed(1));
          el.setAttribute("width", nw.toFixed(1));
        } else {
          const nw = targetW > vbW ? Math.min(Math.round(w * Math.min(1.45, Math.sqrt(kx))), 68) : w;
          const center = mx(x + w / 2);
          el.setAttribute("x", (center - nw / 2).toFixed(1));
          el.setAttribute("width", nw.toFixed(1));
        }
        if (oy !== null) el.setAttribute("y", my(parseFloat(oy)).toFixed(1));
        if (oh !== null) el.setAttribute("height", (parseFloat(oh) * ky).toFixed(1));
      });

      svg.querySelectorAll("text").forEach((el) => {
        if (el.closest("defs") || el.closest("g.forecast-marker") || el.hasAttribute("data-ut-overlay")) return;
        const ox = el.getAttribute("data-o-x"), oy = el.getAttribute("data-o-y");
        if (ox !== null) {
          const x = parseFloat(ox);
          const anchor = el.getAttribute("text-anchor") || "";
          const nx = (anchor === "end" && x <= padL) ? x : mx(x);
          el.setAttribute("x", nx.toFixed(1));
        }
        if (oy !== null) el.setAttribute("y", my(parseFloat(oy)).toFixed(1));
      });

      svg.querySelectorAll("polyline, polygon").forEach((el) => {
        if (el.closest("defs") || el.closest("g.forecast-marker") || el.hasAttribute("data-ut-overlay")) return;
        const op = el.getAttribute("data-o-points");
        if (!op) return;
        const mapped = op.trim().split(/\s+/).map((pair) => {
          const [px, py] = pair.split(",").map(Number);
          if (Number.isNaN(px) || Number.isNaN(py)) return pair;
          return `${mx(px).toFixed(1)},${my(py).toFixed(1)}`;
        }).join(" ");
        el.setAttribute("points", mapped);
      });

      svg.querySelectorAll("path").forEach((el) => {
        if (el.closest("defs") || el.closest("g.forecast-marker") || el.hasAttribute("data-ut-overlay")) return;
        const od = el.getAttribute("data-o-d");
        if (!od) return;
        el.setAttribute("d", mapSvgPathD(od, mx, my));
      });
    } finally {
      svg._reflowing = false;
    }
  }

  function capDiagramSvgScale(svg) {
    const vb = (svg.getAttribute("viewBox") || "").trim().split(/[\s,]+/).map(Number);
    if (vb.length !== 4 || vb[2] < 300 || vb[3] < 100) return;
    if (!svg.hasAttribute("data-orig-vbw")) {
      svg.setAttribute("data-orig-vbw", String(vb[2]));
      svg.setAttribute("data-orig-vbh", String(vb[3]));
    }
    const vbW = parseFloat(svg.getAttribute("data-orig-vbw"));
    const vbH = parseFloat(svg.getAttribute("data-orig-vbh"));
    const zoom = parseFloat(svg.getAttribute("data-zoom") || "1");
    const baseCap = window.innerWidth >= 1680 ? 1.15 : 1.10;
    const cap = baseCap * zoom;
    svg.style.flex = "0 0 auto";
    svg.style.maxWidth = `${Math.round(vbW * cap)}px`;
    svg.style.maxHeight = `${Math.round(vbH * cap)}px`;
    svg.style.minHeight = `${Math.round(vbH * Math.min(1, zoom))}px`;
    svg.style.height = "auto";
    svg.style.margin = "0 auto";
    svg.style.display = "block";
    if (zoom <= 1) svg.style.width = "100%";
  }

  function isReflowableChartSvg(svg) {
    if (svg.classList.contains("main-chart-svg") || svg.classList.contains("sl-cal-svg")) return true;
    const aria = svg.getAttribute("aria-label") || "";
    return aria.includes("추이 차트") || aria.includes("누적 막대") || aria.includes("보정 곡선");
  }

  function initCrispSvgScaleGuard() {
    const chartSvgs = new Set();
    const bindSvg = (svg) => {
      if (!(svg instanceof SVGSVGElement)) return;
      if (svg.classList.contains("kpi-spark")) {
        svg.querySelectorAll("path, polyline, line").forEach((el) => el.setAttribute("vector-effect", "non-scaling-stroke"));
        return;
      }
      const vb = (svg.getAttribute("viewBox") || "").trim().split(/[\s,]+/).map(Number);
      if (vb.length !== 4 || vb[2] < 300 || vb[3] < 100) return;
      if (isReflowableChartSvg(svg)) {
        if (!chartSvgs.has(svg)) {
          chartSvgs.add(svg);
          const mo = new MutationObserver(() => {
            if (svg._reflowing) return;
            window.requestAnimationFrame(() => reflowChartSvg1to1(svg));
          });
          mo.observe(svg, { childList: true });
        }
        reflowChartSvg1to1(svg);
      } else if (svg.querySelector("text")) {
        capDiagramSvgScale(svg);
      }
    };

    const scanAll = () => {
      document.querySelectorAll("svg").forEach(bindSvg);
    };
    scanAll();
    const main = document.getElementById("fdaiMain") || document.body;
    const domObs = new MutationObserver(() => scanAll());
    domObs.observe(main, { childList: true, subtree: true });
    window.addEventListener("resize", () => {
      chartSvgs.forEach((svg) => reflowChartSvg1to1(svg));
    });
    const refreshCharts = () => {
      window.requestAnimationFrame(() => {
        scanAll();
        chartSvgs.forEach((svg) => reflowChartSvg1to1(svg));
      });
    };
    window.addEventListener("hashchange", refreshCharts);
    window.addEventListener("popstate", refreshCharts);
    window.addEventListener("fdai:panelchange", refreshCharts);
    document.addEventListener("click", (e) => {
      if (e.target instanceof Element && e.target.closest(".seg-btn, .hub-tab, [data-graph-view-btn], [data-mode-switch-btn], [data-rail-collapse], [data-rail-restore], [data-float-pin]")) {
        window.requestAnimationFrame(() => {
          scanAll();
          chartSvgs.forEach((svg) => reflowChartSvg1to1(svg));
        });
      }
    });
  }

  /* ==========================================================================
     Component-First Ultra-Fast Tooltip Engine (initUltraFastTooltips + fdaiTip)
     - 0ms open latency, singleton GPU translate3d layer, smart viewport clamp
     - First-class SVG chart crosshair/bar/scatter/donut/graph support
     - HTML heatmap/waterfall/bar/hex-tile/badge/icon/KPI/auto-truncation coverage
     ========================================================================== */
  function initUltraFastTooltips() {
    if (window.__fdaiUltraTipReady) return;
    window.__fdaiUltraTipReady = true;
    document.documentElement.classList.add("has-ut-engine");

    const SVG_NS = "http://www.w3.org/2000/svg";
    let tipEl = document.getElementById("fdaiUltraTip");
    if (!tipEl) {
      tipEl = document.createElement("div");
      tipEl.id = "fdaiUltraTip";
      tipEl.className = "cs-ut-tip";
      tipEl.setAttribute("role", "tooltip");
      tipEl.setAttribute("aria-hidden", "true");
      document.body.appendChild(tipEl);
    }

    const escTip = (v) => String(v == null ? "" : v)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");

    const GLOSSARY = [
      { re: /\bT0\b/, title: "T0 결정론적 규칙 계층", body: "LLM 호출 없이 검증된 규칙·정책으로 즉시 처리하는 0ms 경로입니다.", tone: "live" },
      { re: /\bT1\b/, title: "T1 경량 분류·요약 계층", body: "저지연 경량 모델로 분류·정규화를 수행하며 위험 변경 권한은 없습니다.", tone: "auto" },
      { re: /\bT2\b/, title: "T2 심층 추론 계층", body: "잔여 모호성 해소에 한해 혼합 모델·검증기·승인 관문을 거쳐 실행됩니다.", tone: "human" },
      { re: /\bA4\b/, title: "A4 금지/즉시 차단 등급", body: "정책 위반 또는 비가역 위험으로 자동 실행이 전면 차단되는 등급입니다.", tone: "sec" },
      { re: /\bA3-H\b|\bA3\b/, title: "A3 고위험 승인 필수 등급", body: "운영자의 명시적 승인 없이는 절대 실행되지 않습니다(침묵 시 자동 거부).", tone: "human" },
      { re: /\bA2\b/, title: "A2 제한적 자동 복구 등급", body: "7대 안전장치와 롤백 검증이 통과된 범위에서만 제한 자동 실행됩니다.", tone: "live" },
      { re: /\bA1\b/, title: "A1 조회·진단 전용 등급", body: "상태 변경 없이 원천 지표·로그·토폴로지만 읽기 전용으로 조사합니다.", tone: "auto" },
      { re: /\bShadow\b|모의 검증/, title: "Shadow (관찰·모의 검증 모드)", body: "실제 인프라 변경 없이 판단·계획만 시뮬레이션하고 감사 기록으로 축적합니다.", tone: "sre" },
      { re: /\bEnforce\b|실제 적용/, title: "Enforce (실제 적용 모드)", body: "승격 심사를 통과한 작업만 7대 안전장치와 독립 효과 검증을 거쳐 적용합니다.", tone: "live" },
      { re: /\bHIL\b|승인 대기|승인 요청/, title: "사람 확인·승인 관문 (HIL)", body: "고위험 조치는 승인자와 실행자 분리 원칙에 따라 명시적 승인이 필요합니다.", tone: "human" },
      { re: /\bEWMA\b/, title: "EWMA 지수 가중 이동 평균", body: "최근 관측값에 높은 가중치를 부여해 +5분 임계치 도달을 선행 예측합니다.", tone: "sre" },
      { re: /\bMTTR\b/, title: "MTTR (평균 복구 시간)", body: "장애 탐지 시점부터 독립 관측으로 서비스 정상 회복이 검증될 때까지의 시간입니다.", tone: "live" },
      { re: /\bECE\b/, title: "ECE (예측 보정 오차)", body: "예측 확률과 실제 발생 빈도의 평균 차이로 0.05 이하를 양호 기준으로 봅니다.", tone: "live" },
      { re: /\bMCSB\b/, title: "MCSB (Microsoft Cloud Security Benchmark)", body: "Azure 보안 통제 표준 프레임워크 기준입니다.", tone: "auto" },
      { re: /\bCAF\b/, title: "CAF (Cloud Adoption Framework)", body: "클라우드 거버넌스·아키텍처 운영 모범 사례 기준입니다.", tone: "auto" },
      { re: /\bWARA\b/, title: "WARA (Well-Architected Reliability)", body: "복원력·가용성·장애 격리 검증 기준입니다.", tone: "auto" },
      { re: /\bMSRC\b/, title: "MSRC 보안 권고", body: "취약점·CVE 대응 보안 패치 및 완화 기준입니다.", tone: "sec" },
      { re: /\bSLO\b/, title: "SLO (서비스 수준 목표)", body: "가용성·응답 지연·오류 예산의 정량적 운영 목표입니다.", tone: "live" },
      { re: /\bRCA\b/, title: "RCA (원인 분석)", body: "검증된 시간·관계 근거를 연결해 근본 원인과 무관 이벤트를 분리합니다.", tone: "sre" },
      { re: /\bFOCUS\b/, title: "FOCUS 원가 표준 스키마", body: "클라우드 비용 귀속·구독별 원가 정산을 위한 표준 데이터 포맷입니다.", tone: "auto" },
      { re: /SHA-256|원장|봉인/, title: "SHA-256 해시 체인 감사 봉인", body: "변조 방지를 위해 이전 기록 해시와 연결된 2단계 감사 증적입니다.", tone: "live" },
      { re: /미수집|데이터 없음|미연결/, title: "미측정 · 데이터 없음 보존 원칙", body: "수집되지 않은 값은 0이나 정상으로 대체하지 않고 미수집 상태로 명시합니다.", tone: "neutral" },
      { re: /조회 전용|읽기 전용|READ-ONLY/i, title: "조회 전용 안전 경계", body: "이 경로는 어떠한 인프라 상태 변경도 수행하지 않는 읽기 전용 관측입니다.", tone: "auto" }
    ];

    const AGENT_ROLES = {
      Odin: ["총괄 오케스트레이터", "전체 제어 루프 조율 및 우선순위 중재", "live"],
      Heimdall: ["실시간 이상 탐지", "메트릭·로그 스트림 감시 및 초기 경보 분류", "live"],
      Huginn: ["원천 관측·수집", "Azure/K8s/비용 원천 텔레메트리 수집", "auto"],
      Freyr: ["예측·용량 선행 추정", "EWMA 포화 예측 및 시계열 보정", "sre"],
      Forseti: ["정책·위험 거버넌스", "Rego/OPA 정책 검증 및 A1~A4 위험 판정", "sre"],
      Njord: ["비용 거버넌스 (FinOps)", "구독 원가·유휴 자원·예산 이상 감시", "auto"],
      Loki: ["카오스·내성 리허설", "격리 실험 환경 장애 주입 및 복원력 검증", "sec"],
      Var: ["승인 관문 관리 (HIL)", "고위험 조치 사람 승인 요청 및 만료·거부 통제", "human"],
      Thor: ["격리 실행기", "승인·7대 안전장치 통과 작업의 멱등 실행 및 롤백", "human"],
      Vidar: ["독립 효과 검증", "실행 후 독립 관측 지표로 실제 회복 여부 확인", "live"],
      Bragi: ["운영 설명·대화", "근거 기반 한국어·영어 자연어 브리핑 생성", "auto"],
      Saga: ["감사 원장·증적", "2단계 SHA-256 해시 체인 감사 기록 및 리플레이", "live"],
      Mimir: ["온톨로지·원인 추론", "관계 그래프 탐색 및 근본 원인(RCA) 상관 분석", "auto"],
      Tyr: ["보안·취약점 통제", "보안 기준선·키 볼트·네트워크 노출 차단", "sec"],
      Freya: ["승격·품질 보증", "Shadow→Enforce 승격 심사 및 회귀 강등 감시", "live"]
    };

    let visible = false;
    let lastPayloadKey = "";
    let tipWidth = 220;
    let tipHeight = 48;

    function parseUtRows(raw) {
      if (!raw) return [];
      return String(raw).split(";").map((pair) => {
        const idx = pair.indexOf("|");
        if (idx < 0) return null;
        const k = pair.slice(0, idx).trim();
        const v = pair.slice(idx + 1).trim();
        return k && v ? { k, v } : null;
      }).filter(Boolean);
    }

    function enrichChartTooltipPayload(el, base) {
      const p = Object.assign({}, base);
      let rows = Array.isArray(p.rows) ? [...p.rows] : [];
      if (!rows.length && el instanceof Element) {
        const attrRows = el.getAttribute("data-ut-rows")
          || el.getAttribute("data-drawer-facts")
          || el.closest(".forecast-marker[data-drawer-facts]")?.getAttribute("data-drawer-facts");
        if (attrRows) rows = parseUtRows(attrRows);
      }

      // Auto-enrich scatter plot points (e.g. "19:38 · SRE 이상 · pg-orders-kr 연결 풀 78% 접근 (위험도 62)")
      const rawTip = (el instanceof Element ? (el.getAttribute("data-tip-text") || "") : "") || p.body || "";
      if (el instanceof Element && el.classList.contains("scatter-pt") && rawTip) {
        const parts = rawTip.split("·").map((s) => s.trim()).filter(Boolean);
        const ts = parts[0] || "";
        const cat = parts[1] || "관측 이벤트";
        const detailRaw = parts.slice(2).join(" · ");
        const riskM = detailRaw.match(/\(위험도\s*(\d+)\)/);
        const riskScore = riskM ? riskM[1] : "";
        const detail = detailRaw.replace(/\s*\(위험도\s*\d+\)\s*/, "").trim();
        const resM = detail.match(/([a-z0-9]+-[a-z0-9-]+|HIL-\d+|CVE-\d+-\d+)/i);
        const targetRes = resM ? resM[1] : "구독 전체";
        const isHuman = /사람|HIL|승인/.test(cat);
        const isSec = /보안|취약|CVE|만료/.test(cat);
        const isSre = /SRE|이상|포화|지연/.test(cat);
        const tone = isHuman ? "human" : isSec ? "sec" : isSre ? "sre" : "live";
        const agent = isHuman ? "Var (승인 관문)" : isSec ? "Tyr · Forseti" : isSre ? "Heimdall · Freyr" : "Heimdall (자동 감시)";
        const auth = isHuman ? "승인 후 조치 (HIL)" : isSec ? "감시 · 승인 검토" : isSre ? "감시 전용 · 사전 예측" : "자동 조치 · 알림 억제";
        p.title = `${cat} · ${targetRes}`;
        p.val = riskScore ? `위험도 ${riskScore}` : (p.val || "");
        p.body = detail || rawTip;
        p.tone = tone;
        rows = [
          { k: "관측 시각", v: ts || "실시간" },
          { k: "대상 리소스", v: targetRes },
          { k: "담당 에이전트", v: agent },
          { k: "조치 권한", v: auth, tone }
        ];
        p.meta = "클릭 시 우측 상세 드로어에서 감사 근거와 이동 링크를 확인합니다";
      } else if (el instanceof Element && el.tagName.toLowerCase() === "rect" && el.closest("svg") && !rows.length) {
        const utTitle = el.getAttribute("data-ut-title") || p.title || "";
        const utVal = el.getAttribute("data-ut-val") || p.val || "";
        const utMeta = el.getAttribute("data-ut-meta") || p.meta || "";
        const segParts = utTitle.split("·").map((s) => s.trim());
        const bucket = segParts[0] || "구간";
        const series = segParts[1] || seriesNameFromTone(p.tone);
        const totalM = utMeta.match(/구간 총\s*([\d,]+건)\s*중\s*([\d.]+%)/);
        const suppressM = utMeta.match(/사람 핵심 알림\s*(\d+건)\s*·\s*억제\s*(\d+건)/);
        if (totalM) {
          rows = [
            { k: "시간 구간", v: bucket },
            { k: "이벤트 분류", v: series, tone: p.tone || "auto" },
            { k: "건수 / 점유율", v: `${utVal} (${totalM[2]})` },
            { k: "구간 전체 합계", v: totalM[1] }
          ];
          p.meta = "클릭 시 해당 구간의 상세 분석 드로어를 엽니다";
        } else if (suppressM) {
          rows = [
            { k: "기간 구간", v: bucket },
            { k: "규칙 탐지 문제", v: utVal, tone: "live" },
            { k: "사람 핵심 알림", v: suppressM[1], tone: "human" },
            { k: "노이즈 억제", v: suppressM[2] }
          ];
          p.meta = "클릭 시 해당 기간의 규칙별 상세 드로어를 엽니다";
        }
      } else if (el instanceof Element && el.closest(".domain-bar-row") && !rows.length) {
        const dRow = el.closest(".domain-bar-row");
        const spans = dRow.querySelectorAll(":scope > span");
        const name = spans[0]?.textContent?.trim() || p.title || "운영 영역";
        const total = spans[spans.length - 1]?.textContent?.trim() || "";
        const segs = Array.from(dRow.querySelectorAll(".bar-track > span"));
        p.title = `${name} 이벤트 분해`;
        p.val = total ? (total.endsWith("건") ? `총 ${total}` : `총 ${total}건`) : "";
        rows = segs.map((s) => {
          const t = toneFromColorStr(s.style.background || "");
          return { k: seriesNameFromTone(t), v: s.style.width || "-", tone: t };
        });
        p.meta = "클릭 시 해당 영역 상세 드로어를 엽니다";
      }

      if (rows.length) p.rows = rows;
      return p;
    }

    function normalizePayload(raw) {
      if (!raw) return null;
      if (typeof raw === "string") {
        const s = raw.trim();
        if (!s) return null;
        return { title: s };
      }
      if (!raw.title && !raw.body && !raw.meta && !(raw.rows && raw.rows.length)) return null;
      return raw;
    }

    function renderTipContent(p) {
      const key = JSON.stringify(p);
      if (key === lastPayloadKey) return;
      lastPayloadKey = key;
      const parts = [];
      if (p.title || p.val || p.value || p.kbd) {
        const dot = p.tone ? `<span class="cs-ut-dot" data-tone="${escTip(p.tone)}"></span>` : "";
        const val = p.val || p.value ? `<span class="cs-ut-val">${escTip(p.val || p.value)}</span>` : "";
        const kbd = p.kbd ? `<kbd class="cs-ut-kbd">${escTip(p.kbd)}</kbd>` : "";
        parts.push(
          `<div class="cs-ut-head"><span class="cs-ut-title-wrap">${dot}<span class="cs-ut-title">${escTip(p.title || "")}</span></span>${val}${kbd}</div>`
        );
      }
      if (p.body) parts.push(`<div class="cs-ut-body">${escTip(p.body)}</div>`);
      if (p.rows && p.rows.length) {
        parts.push(
          `<div class="cs-ut-rows">${p.rows.map((r) => {
            const rd = r.tone ? `<span class="cs-ut-dot" data-tone="${escTip(r.tone)}"></span>` : "";
            return `<div class="cs-ut-row"><span class="cs-ut-row-k">${rd}${escTip(r.k)}</span><span class="cs-ut-row-v">${escTip(r.v)}</span></div>`;
          }).join("")}</div>`
        );
      }
      if (p.meta) parts.push(`<div class="cs-ut-meta">${escTip(p.meta)}</div>`);
      tipEl.innerHTML = parts.join("");
      const rect = tipEl.getBoundingClientRect();
      tipWidth = rect.width || 220;
      tipHeight = rect.height || 44;
    }

    function positionTip(x, y, preferAbove = true) {
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const pad = 10;
      const offset = 14;
      let tx = x + offset;
      let ty = preferAbove ? y - tipHeight - offset : y + offset;
      if (tx + tipWidth + pad > vw) tx = x - tipWidth - offset;
      if (tx < pad) tx = Math.max(pad, Math.min(vw - tipWidth - pad, x - tipWidth / 2));
      if (ty < pad) ty = y + offset + 4;
      if (ty + tipHeight + pad > vh) ty = Math.max(pad, y - tipHeight - offset);
      tipEl.style.transform = `translate3d(${Math.round(tx)}px, ${Math.round(ty)}px, 0)`;
    }

    function showTip(payload, anchor) {
      const p = normalizePayload(payload);
      if (!p) return hideTip();
      renderTipContent(p);
      if (!visible) {
        visible = true;
        tipEl.classList.add("is-visible");
        tipEl.setAttribute("aria-hidden", "false");
        const r = tipEl.getBoundingClientRect();
        tipWidth = r.width || tipWidth;
        tipHeight = r.height || tipHeight;
      }
      if (anchor && typeof anchor.x === "number" && typeof anchor.y === "number") {
        positionTip(anchor.x, anchor.y, true);
      } else if (anchor instanceof Element) {
        const r = anchor.getBoundingClientRect();
        positionTip(r.left + r.width / 2, r.top, true);
      } else if (anchor && typeof anchor.left === "number") {
        positionTip(anchor.left + (anchor.width || 0) / 2, anchor.top, true);
      }
    }

    function moveTip(x, y) {
      if (!visible) return;
      positionTip(x, y, true);
    }

    function hideTip() {
      if (!visible) return;
      visible = false;
      tipEl.classList.remove("is-visible");
      tipEl.setAttribute("aria-hidden", "true");
    }

    function toneFromColorStr(c) {
      const s = (c || "").toLowerCase();
      if (s.includes("sec") || s.includes("a63446") || s.includes("ef4444")) return "sec";
      if (s.includes("sre") || s.includes("c86d18") || s.includes("f59e0b") || s.includes("d97706")) return "sre";
      if (s.includes("human") || s.includes("4a2574") || s.includes("7c3aed")) return "human";
      if (s.includes("live") || s.includes("0f766e") || s.includes("14b8a6")) return "live";
      if (s.includes("auto") || s.includes("5a9a92")) return "auto";
      return "neutral";
    }

    function seriesNameFromTone(t) {
      if (t === "live") return "정상·자동 처리";
      if (t === "auto") return "자동 억제·경량(T1)";
      if (t === "sre") return "SRE 주의·예측";
      if (t === "sec") return "보안·차단";
      if (t === "human") return "사람 확인·심층(T2)";
      return "측정 항목";
    }

    function parsePointsAttr(str) {
      if (!str) return [];
      return str.trim().split(/\s+/).map((pair) => {
        const [x, y] = pair.split(",").map(Number);
        return (Number.isFinite(x) && Number.isFinite(y)) ? { x, y } : null;
      }).filter(Boolean);
    }

    function parseLinePathPoints(d) {
      if (!d) return [];
      const pts = [];
      const re = /([ML])\s*(-?[\d.]+)[,\s]+(-?[\d.]+)/gi;
      let m;
      while ((m = re.exec(d)) !== null) {
        const x = parseFloat(m[2]), y = parseFloat(m[3]);
        if (Number.isFinite(x) && Number.isFinite(y)) pts.push({ x, y });
      }
      return pts;
    }

    function findNearestAxisLabel(svg, targetX) {
      const vb = (svg.getAttribute("viewBox") || "").trim().split(/[\s,]+/).map(Number);
      const vbH = vb[3] || 200;
      let best = null;
      let bestDist = Infinity;
      svg.querySelectorAll("text").forEach((t) => {
        const y = parseFloat(t.getAttribute("y") || "0");
        const x = parseFloat(t.getAttribute("x") || "0");
        if (y < vbH * 0.72) return;
        const txt = (t.textContent || "").trim();
        if (!txt || txt.length > 20) return;
        const dist = Math.abs(x - targetX);
        if (dist < bestDist) { bestDist = dist; best = txt; }
      });
      return bestDist < 120 ? best : null;
    }

    function inferYValue(svg, yVal) {
      const ticks = [];
      svg.querySelectorAll("text").forEach((t) => {
        const anchor = t.getAttribute("text-anchor") || "";
        const x = parseFloat(t.getAttribute("x") || "999");
        if (anchor === "end" || x < 64) {
          const raw = (t.textContent || "").trim();
          const num = parseFloat(raw.replace(/[^0-9.\-]/g, ""));
          const ty = parseFloat(t.getAttribute("y") || "0");
          if (Number.isFinite(num) && Number.isFinite(ty)) {
            ticks.push({ y: ty, val: num, unit: raw.replace(/[-0-9.,\s]/g, "") });
          }
        }
      });
      if (ticks.length < 2) return null;
      ticks.sort((a, b) => a.y - b.y);
      const top = ticks[0], bot = ticks[ticks.length - 1];
      if (Math.abs(bot.y - top.y) < 10) return null;
      const ratio = (bot.y - yVal) / (bot.y - top.y);
      const est = bot.val + ratio * (top.val - bot.val);
      if (!Number.isFinite(est)) return null;
      const decimals = Math.abs(top.val - bot.val) <= 2 ? 2 : Math.abs(top.val - bot.val) <= 20 ? 1 : 0;
      const formatted = est.toFixed(decimals);
      return top.unit === "$" ? `$${formatted}` : `${formatted}${top.unit || ""}`;
    }

    function bindLineSparkCrosshair(svg) {
      if (svg.dataset.utCrosshairBound === "1") return;
      svg.dataset.utCrosshairBound = "1";
      svg.classList.add("cs-ut-interactive-svg");

      const ensureOverlay = () => {
        let line = svg.querySelector("line[data-ut-overlay='1']");
        let halo = svg.querySelector("circle[data-ut-overlay='1']");
        if (!line) {
          line = document.createElementNS(SVG_NS, "line");
          line.setAttribute("data-ut-overlay", "1");
          line.setAttribute("class", "cs-ut-crosshair");
          line.style.display = "none";
          svg.appendChild(line);
        }
        if (!halo) {
          halo = document.createElementNS(SVG_NS, "circle");
          halo.setAttribute("data-ut-overlay", "1");
          halo.setAttribute("class", "cs-ut-halo");
          halo.setAttribute("r", svg.classList.contains("kpi-spark") ? "3.2" : "5.2");
          halo.style.display = "none";
          svg.appendChild(halo);
        }
        return { line, halo };
      };

      const collectPoints = () => {
        const circles = Array.from(svg.querySelectorAll("circle:not([data-ut-overlay])")).filter((c) => {
          const r = parseFloat(c.getAttribute("r") || "0");
          return r >= 2.5 && r <= 9;
        });
        if (circles.length >= 2) {
          return circles.map((c, idx) => ({
            el: c,
            x: parseFloat(c.getAttribute("cx") || "0"),
            y: parseFloat(c.getAttribute("cy") || "0"),
            idx,
            tone: toneFromColorStr(c.getAttribute("fill") || c.getAttribute("stroke") || "live"),
            tip: c.getAttribute("data-ut-tip") || c.getAttribute("data-cal-tip") || c.getAttribute("data-tip-text") || "",
            title: c.getAttribute("data-ut-title") || "",
            val: c.getAttribute("data-ut-val") || "",
            meta: c.getAttribute("data-ut-meta") || ""
          }));
        }
        const poly = svg.querySelector("polyline:not([data-ut-overlay])");
        if (poly) {
          const tone = toneFromColorStr(poly.getAttribute("stroke") || "live");
          return parsePointsAttr(poly.getAttribute("points")).map((pt, idx) => ({ ...pt, idx, tone }));
        }
        const paths = Array.from(svg.querySelectorAll("path:not([data-ut-overlay])")).filter((p) => {
          const f = (p.getAttribute("fill") || "").toLowerCase();
          return f === "none" || !f;
        });
        if (paths.length) {
          const tone = toneFromColorStr(paths[0].getAttribute("stroke") || "live");
          return parseLinePathPoints(paths[0].getAttribute("d")).map((pt, idx) => ({ ...pt, idx, tone }));
        }
        return [];
      };

      svg.addEventListener("pointermove", (e) => {
        const pts = collectPoints();
        if (!pts.length) return;
        const rect = svg.getBoundingClientRect();
        if (rect.width < 10) return;
        const vb = (svg.getAttribute("viewBox") || `0 0 ${rect.width} ${rect.height}`).trim().split(/[\s,]+/).map(Number);
        const vbW = vb[2] || rect.width;
        const vbH = vb[3] || rect.height;
        const svgX = ((e.clientX - rect.left) / rect.width) * vbW;

        let nearest = pts[0];
        let minDx = Math.abs(pts[0].x - svgX);
        for (let i = 1; i < pts.length; i++) {
          const dx = Math.abs(pts[i].x - svgX);
          if (dx < minDx) { minDx = dx; nearest = pts[i]; }
        }

        const { line, halo } = ensureOverlay();
        line.setAttribute("x1", nearest.x.toFixed(1));
        line.setAttribute("x2", nearest.x.toFixed(1));
        line.setAttribute("y1", "4");
        line.setAttribute("y2", String(Math.max(8, vbH - 18)));
        line.style.display = "";
        halo.setAttribute("cx", nearest.x.toFixed(1));
        halo.setAttribute("cy", nearest.y.toFixed(1));
        halo.style.display = "";

        const card = svg.closest(".kpi-card, .cs-kpi, .surface-card, .specimen-box, .card");
        const chartTitle = svg.getAttribute("data-ut-chart-title")
          || card?.querySelector(".kpi-label, .card-title, .specimen-title span:first-child, h3")?.textContent?.trim()
          || svg.getAttribute("aria-label")
          || "시계열 추이";

        if (nearest.el && (nearest.tip || nearest.title || nearest.val)) {
          const enriched = enrichChartTooltipPayload(nearest.el, {
            title: nearest.title || chartTitle,
            body: nearest.tip || "",
            val: nearest.val,
            meta: nearest.meta,
            tone: nearest.tone
          });
          showTip(enriched, { x: e.clientX, y: e.clientY });
          return;
        }
        if (nearest.tip) {
          showTip({ title: nearest.title || chartTitle, body: nearest.tip, val: nearest.val, meta: nearest.meta, tone: nearest.tone }, { x: e.clientX, y: e.clientY });
          return;
        }
        if (nearest.title || nearest.val) {
          showTip({ title: nearest.title || chartTitle, val: nearest.val, meta: nearest.meta, tone: nearest.tone }, { x: e.clientX, y: e.clientY });
          return;
        }

        const axisLabel = findNearestAxisLabel(svg, nearest.x);
        const yEst = inferYValue(svg, nearest.y);
        if (svg.classList.contains("kpi-spark") || vbH <= 70) {
          const kpiVal = card?.querySelector(".kpi-val, .kpi-value, .cs-kpi-val")?.textContent?.trim() || "";
          const kpiFootSpans = card ? Array.from(card.querySelectorAll(".kpi-foot > span")).map((s) => s.textContent.trim()).filter(Boolean) : [];
          const kpiSub = kpiFootSpans.length ? kpiFootSpans.join(" · ") : (card?.querySelector(".kpi-sub, .kpi-delta, .kpi-meta")?.textContent?.trim() || "");
          const relPct = Math.round(((vbH - nearest.y) / Math.max(1, vbH)) * 100);
          const stepLabel = `구간 ${nearest.idx + 1} / ${pts.length}`;
          const prevY = nearest.idx > 0 ? pts[nearest.idx - 1].y : nearest.y;
          const deltaDir = nearest.y < prevY - 1 ? "상승 추세" : nearest.y > prevY + 1 ? "완화 추세" : "안정 유지";
          showTip({
            title: chartTitle,
            val: kpiVal || `지수 ${relPct}%`,
            tone: nearest.tone,
            rows: [
              { k: "관측 구간", v: stepLabel },
              { k: "상대 강도", v: `${relPct}%`, tone: nearest.tone },
              { k: "직전 대비", v: deltaDir },
              { k: "요약 지표", v: kpiSub || "실시간 집계" }
            ],
            meta: "클릭 시 KPI 상세 드로어에서 근거와 연관 화면으로 이동합니다"
          }, { x: e.clientX, y: e.clientY });
        } else {
          showTip({
            title: axisLabel ? `${chartTitle} · ${axisLabel}` : `${chartTitle} · #${nearest.idx + 1}`,
            val: yEst || "",
            tone: nearest.tone,
            rows: [
              { k: "관측 시점", v: axisLabel || `지점 ${nearest.idx + 1} / ${pts.length}` },
              { k: "측정값", v: yEst || "-", tone: nearest.tone }
            ],
            meta: nearest.meta || "클릭 시 해당 차트의 상세 분석 드로어를 엽니다"
          }, { x: e.clientX, y: e.clientY });
        }
      });

      svg.addEventListener("pointerleave", () => {
        svg.querySelectorAll("[data-ut-overlay='1']").forEach((el) => { el.style.display = "none"; });
        hideTip();
      });
    }

    function enhanceSvgChartsAndGraphs(root) {
      root.querySelectorAll("svg").forEach((svg) => {
        if (svg.closest(".topbar, .icon-rail, .rail-btn, .icon-btn, button.cs-btn")) return;
        const vb = (svg.getAttribute("viewBox") || "").trim().split(/[\s,]+/).map(Number);
        const vbW = vb[2] || 0;
        const vbH = vb[3] || 0;
        if (vbW < 80 && vbH < 30) return;

        // 1. Donut / ring SVG (100x100)
        if (vbW === 100 && vbH === 100) {
          const wrap = svg.closest(".ov-ring-wrap");
          if (wrap && !wrap.hasAttribute("data-ut-title")) {
            const lbl = wrap.getAttribute("aria-label") || "자동 해결률 링 차트";
            const val = wrap.querySelector(".ov-ring-val")?.textContent?.trim() || "72%";
            wrap.setAttribute("data-ut-title", "자동 해결률 · 기준선 대비");
            wrap.setAttribute("data-ut-val", val);
            wrap.setAttribute("data-ut-body", lbl);
            wrap.setAttribute("data-ut-meta", "검정 눈금선: 기준선 48% · Shadow 62.0% · 정책 위반 0건");
            wrap.setAttribute("data-ut-tone", "live");
          }
          return;
        }

        // 2. Interactive Graph / Topology / Constellation / Org-Tree / Lineage / Schema / Blast-Radius / DAG / RCA
        const isGraph = svg.classList.contains("graph-canvas-svg")
          || svg.classList.contains("ag-svg-stage")
          || svg.classList.contains("ag-org-svg")
          || svg.classList.contains("ev-rca-svg");
        if (isGraph) {
          svg.querySelectorAll("g.graph-node, g[data-ag-node], g[data-org-node], g.ev-rca-node").forEach((node) => {
            if (node.hasAttribute("data-ut-title")) return;
            const agName = node.getAttribute("data-ag-node") || node.getAttribute("data-org-node");
            if (agName) {
              const info = AGENT_ROLES[agName] || ["전담 에이전트", "이벤트 버스 기반 자율 운영 에이전트", "live"];
              node.setAttribute("data-ut-title", `${agName} · ${info[0]}`);
              node.setAttribute("data-ut-body", info[1]);
              node.setAttribute("data-ut-meta", "클릭하여 우측 에이전트 상세·계약 열기");
              node.setAttribute("data-ut-tone", info[2]);
              return;
            }
            const gName = node.getAttribute("data-gnode-name");
            if (gName) {
              const gType = node.getAttribute("data-gnode-type") || "";
              const gStatus = node.getAttribute("data-gnode-status") || "";
              const gLineage = node.getAttribute("data-gnode-lineage") || "";
              const gNote = node.getAttribute("data-gnode-note") || "";
              const tone = /위험|장애|차단|초과|경고/.test(gStatus) ? "sec" : /주의|예측|승인|A3|Shadow/.test(gStatus) ? "sre" : "live";
              node.setAttribute("data-ut-title", gName);
              if (gStatus) node.setAttribute("data-ut-val", gStatus);
              node.setAttribute("data-ut-body", [gType, gNote].filter(Boolean).join(" - "));
              node.setAttribute("data-ut-meta", gLineage ? `${gLineage} · 클릭하여 상세 보기` : "클릭하여 우측 상세 인스펙터 열기");
              node.setAttribute("data-ut-tone", tone);
              return;
            }
            const texts = Array.from(node.querySelectorAll("text")).map((t) => (t.textContent || "").trim()).filter(Boolean);
            if (texts.length) {
              node.setAttribute("data-ut-title", texts[0]);
              if (texts.length > 1) node.setAttribute("data-ut-body", texts.slice(1).join(" · "));
              node.setAttribute("data-ut-meta", "클릭하여 상세 근거 확인");
              node.setAttribute("data-ut-tone", "live");
            }
          });
          svg.querySelectorAll("g.svg-edge-group, line[data-edge], path[data-org-edge]").forEach((edge) => {
            if (edge.hasAttribute("data-ut-title")) return;
            const kind = edge.getAttribute("data-edge-kind");
            const src = edge.getAttribute("data-edge-src");
            const dst = edge.getAttribute("data-edge-dst");
            const pair = edge.getAttribute("data-edge") || edge.getAttribute("data-org-edge");
            if (src && dst) {
              edge.style.cursor = "pointer";
              edge.setAttribute("data-ut-title", `관계 경로: ${src} → ${dst}`);
              edge.setAttribute("data-ut-body", `유형: ${kind || "dependency"} (검증된 방향성 엣지)`);
              edge.setAttribute("data-ut-tone", kind === "alert" ? "sre" : kind === "access" ? "auto" : "live");
            } else if (pair) {
              const [a, b] = pair.split(",");
              edge.style.cursor = "pointer";
              edge.setAttribute("data-ut-title", `협력 버스: ${a} ↔ ${b}`);
              edge.setAttribute("data-ut-body", "스키마 검증 이벤트 버스 pub/sub 경계 (직접 호출 없음)");
              edge.setAttribute("data-ut-tone", "auto");
            }
          });
          return;
        }

        // 3. Scatter Plot SVGs
        const aria = svg.getAttribute("aria-label") || "";
        if (svg.id === "ovScatterSvg" || aria.includes("산점도")) {
          svg.querySelectorAll("circle").forEach((c, idx) => {
            if (c.hasAttribute("data-ut-title") || c.hasAttribute("data-ut-tip")) return;
            const raw = c.getAttribute("data-tip-text");
            const tone = toneFromColorStr(c.getAttribute("fill") || c.getAttribute("stroke") || "");
            c.classList.add("cs-ut-chart-pt");
            if (raw) {
              const segs = raw.split(" · ");
              c.setAttribute("data-ut-title", segs.slice(0, 2).join(" · "));
              c.setAttribute("data-ut-body", segs.slice(2).join(" · ") || raw);
              c.setAttribute("data-ut-tone", tone);
              c.setAttribute("data-ut-meta", "산점도 이벤트 지점");
            } else {
              const r = parseFloat(c.getAttribute("r") || "3");
              if (r >= 8) {
                c.setAttribute("data-ut-title", "SRE 포화 예측 구간 (+5분)");
                c.setAttribute("data-ut-body", "EWMA 신뢰 반경 내 임계치 도달 가능성 표시");
                c.setAttribute("data-ut-tone", "sre");
              } else {
                c.setAttribute("data-ut-title", `${seriesNameFromTone(tone)} #${idx + 1}`);
                c.setAttribute("data-ut-body", "실시간 위험도 분포 관측 지점");
                c.setAttribute("data-ut-tone", tone);
              }
            }
          });
          svg.querySelectorAll("g.forecast-marker, polygon").forEach((el) => {
            if (el.hasAttribute("data-ut-title")) return;
            const lbl = el.getAttribute("aria-label") || "SRE 포화 예측 마커 (+5분)";
            el.setAttribute("data-ut-title", "SRE 선행 예측 마커");
            el.setAttribute("data-ut-body", lbl);
            el.setAttribute("data-ut-tone", "sre");
            el.setAttribute("data-ut-meta", "클릭하여 예측 상세 및 대응 조치 열기");
          });
          return;
        }

        // 4. Stacked Bar / Column Bar SVGs
        const dataRects = Array.from(svg.querySelectorAll("rect:not([data-ut-overlay])")).filter((r) => {
          const w = parseFloat(r.getAttribute("width") || "0");
          const h = parseFloat(r.getAttribute("height") || "0");
          return w >= 8 && w <= 120 && h >= 4 && !r.getAttribute("stroke-dasharray");
        });
        if (dataRects.length >= 4 && (aria.includes("막대") || aria.includes("스택") || aria.includes("알림 노이즈") || svg.id === "ovLlmTrendSvg")) {
          const chartTitle = aria || "막대 차트";
          dataRects.forEach((r) => {
            if (r.hasAttribute("data-ut-title")) return;
            r.classList.add("cs-ut-chart-bar");
            const rx = parseFloat(r.getAttribute("x") || "0") + parseFloat(r.getAttribute("width") || "0") / 2;
            const ry = parseFloat(r.getAttribute("y") || "0");
            const rh = parseFloat(r.getAttribute("height") || "0");
            const bucket = findNearestAxisLabel(svg, rx) || "구간";
            const tone = toneFromColorStr(r.getAttribute("fill") || "");
            let series = seriesNameFromTone(tone);
            let valueStr = "";
            if (svg.id === "ovLlmTrendSvg") {
              series = tone === "human" ? "T2 심층 추론 토큰" : "T1 경량 모델 토큰";
              valueStr = `${Math.max(1, Math.round(rh * 1.4))}k 토큰`;
            } else if (aria.includes("알림 노이즈")) {
              series = tone === "human" ? "사람 알림 전달" : "자동 노이즈 억제";
              valueStr = `${Math.max(1, Math.round(rh * 2))}건`;
            } else {
              const est = inferYValue(svg, ry);
              valueStr = est || `${Math.max(1, Math.round(rh * 0.85))}건`;
            }
            r.setAttribute("data-ut-title", `${bucket} · ${series}`);
            r.setAttribute("data-ut-val", valueStr);
            r.setAttribute("data-ut-meta", chartTitle);
            r.setAttribute("data-ut-tone", tone);
          });
          svg.querySelectorAll("circle:not([data-ut-overlay])").forEach((c) => {
            if (c.hasAttribute("data-ut-title")) return;
            c.classList.add("cs-ut-chart-pt");
            const cx = parseFloat(c.getAttribute("cx") || "0");
            const bucket = findNearestAxisLabel(svg, cx) || "현재";
            c.setAttribute("data-ut-title", `${bucket} · 사람 알림 추이선`);
            c.setAttribute("data-ut-tone", "human");
            c.setAttribute("data-ut-meta", chartTitle);
          });
          return;
        }

        // 5. Line / Area / Calibration / Sparkline SVGs → Crosshair Engine
        const hasLineOrCurve = Boolean(svg.querySelector("polyline, path, circle[data-cal-tip]"));
        if (hasLineOrCurve) {
          bindLineSparkCrosshair(svg);
        }
      });
    }

    function upgradeNativeTitles(root) {
      root.querySelectorAll("[title]").forEach((el) => {
        const t = (el.getAttribute("title") || "").trim();
        if (t && !el.hasAttribute("data-ut-tip") && !el.hasAttribute("data-ut-title")) {
          el.setAttribute("data-ut-tip", t);
        }
        el.removeAttribute("title");
      });
    }

    function enhanceHtmlVisuals(root) {
      // Heatmaps
      root.querySelectorAll(".hm-cell-btn, .sl-hm-btn, .hm-cell, .heatmap-cell, .ag-hm-cell").forEach((el) => {
        if (el.hasAttribute("data-ut-title")) return;
        const lbl = el.getAttribute("data-hm-label") || el.getAttribute("aria-label") || "";
        const peak = el.getAttribute("data-hm-peak") || "";
        if (!lbl) return;
        const cls = el.className || "";
        const tone = cls.includes("hm-4") ? "sec" : cls.includes("hm-3") || cls.includes("hm-fc") ? "sre" : cls.includes("unmeasured") ? "neutral" : "live";
        const parts = lbl.split(/\s*[-·]\s*/);
        el.setAttribute("data-ut-title", parts[0] || "활동 히트맵 셀");
        el.setAttribute("data-ut-body", parts.slice(1).join(" · ") || lbl);
        if (peak) el.setAttribute("data-ut-meta", `주요 대상: ${peak}`);
        el.setAttribute("data-ut-tone", tone);
      });

      // Waterfall rows
      root.querySelectorAll(".wf-row, .ev-wf-row").forEach((row) => {
        if (row.hasAttribute("data-ut-title")) return;
        const lbl = row.querySelector(".ev-wf-label, strong")?.textContent?.trim() || "";
        const time = row.querySelector(".ev-wf-time")?.textContent?.trim() || "";
        const bar = row.querySelector(".wf-bar");
        if (!lbl) return;
        row.setAttribute("data-ut-title", lbl);
        if (time) row.setAttribute("data-ut-val", time);
        row.setAttribute("data-ut-meta", "분산 실행 워터폴 스팬 · 클릭하여 상세 근거 확인");
        row.setAttribute("data-ut-tone", toneFromColorStr(bar?.style.background || ""));
      });

      // Horizontal / stacked / distribution / token / domain bars
      root.querySelectorAll(".ov-bar-row, .domain-bar-row, .sl-token-bar-wrap").forEach((row) => {
        if (row.hasAttribute("data-ut-title")) return;
        const txt = (row.innerText || "").replace(/\s+/g, " ").trim();
        if (!txt) return;
        const parts = txt.split(/\s{2,}|\n/).filter(Boolean);
        row.setAttribute("data-ut-title", parts[0] || txt.slice(0, 48));
        if (parts.length > 1) row.setAttribute("data-ut-body", parts.slice(1).join(" · "));
        row.setAttribute("data-ut-tone", "live");
      });

      root.querySelectorAll(".gov-stack-seg, .dist-bar > span").forEach((seg) => {
        if (seg.hasAttribute("data-ut-title")) return;
        const w = seg.style.width || "";
        const cls = seg.className || "";
        const tone = cls.includes("t0") ? "live" : cls.includes("t1") ? "auto" : cls.includes("t2") ? "human" : toneFromColorStr(seg.style.background || "");
        const label = cls.includes("t0") ? "T0 규칙 자동 처리" : cls.includes("t1") ? "T1 경량 분류" : cls.includes("t2") ? "T2 심층 추론" : seriesNameFromTone(tone);
        seg.setAttribute("data-ut-title", label);
        if (w) seg.setAttribute("data-ut-val", w);
        seg.setAttribute("data-ut-tone", tone);
      });

      root.querySelectorAll(".bar-track").forEach((track) => {
        if (track.hasAttribute("data-ut-title")) return;
        const parentRow = track.closest("tr, .card, .surface-card, .ov-bar-row, div");
        const fill = track.querySelector(".bar-fill, [style*='width']");
        const pct = fill?.style?.width || "";
        const lbl = parentRow?.querySelector("strong, .card-title, td:first-child, span:first-child")?.textContent?.trim() || "진행률 지표";
        track.setAttribute("data-ut-title", lbl);
        if (pct) track.setAttribute("data-ut-val", pct);
        track.setAttribute("data-ut-tone", toneFromColorStr(fill?.style?.background || "live"));
      });

      // Hex tiles & resource tiles
      root.querySelectorAll(".ov-hex-tile").forEach((tile) => {
        if (tile.hasAttribute("data-ut-title")) return;
        const name = tile.querySelector(".ov-hex-tile-name")?.textContent?.trim() || "";
        const rawMeta = tile.querySelector(".ov-hex-tile-sub, .ov-hex-tile-meta")?.textContent?.trim() || tile.getAttribute("aria-label") || "";
        const meta = rawMeta.replace(new RegExp(`^${name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}[,\\s·-]*`), "").trim();
        if (!name) return;
        tile.setAttribute("data-ut-title", name);
        if (meta && meta !== name) tile.setAttribute("data-ut-body", meta);
        tile.setAttribute("data-ut-meta", "클릭하여 리소스 상세 사이드바 열기");
        tile.setAttribute("data-ut-tone", /보안|취약|차단/.test(meta) ? "sec" : /주의|예측/.test(meta) ? "sre" : /승인|사람/.test(meta) ? "human" : "live");
      });

      // ? inline help buttons (.ov-tip-btn)
      root.querySelectorAll(".ov-tip-btn").forEach((btn) => {
        if (btn.hasAttribute("data-ut-title")) return;
        const pop = btn.parentElement?.querySelector(".ov-tip-pop")?.textContent?.trim() || "";
        const aria = btn.getAttribute("aria-label") || "용어 설명";
        btn.setAttribute("data-ut-title", aria.replace(/\s*뜻 보기$/, ""));
        if (pop) btn.setAttribute("data-ut-body", pop);
        btn.setAttribute("data-ut-tone", "auto");
      });

      // KPI cards
      root.querySelectorAll(".kpi-card, .cs-kpi").forEach((card) => {
        if (card.hasAttribute("data-ut-kpi-ready")) return;
        card.setAttribute("data-ut-kpi-ready", "1");
        const head = card.querySelector(".kpi-head, .kpi-label, .cs-kpi-label");
        if (head && !head.hasAttribute("data-ut-title")) {
          const lbl = card.querySelector(".kpi-label, .cs-kpi-label")?.textContent?.trim() || "";
          const val = card.querySelector(".kpi-val, .kpi-value, .cs-kpi-val")?.textContent?.trim() || "";
          const sub = card.querySelector(".kpi-sub, .kpi-delta, .kpi-meta")?.textContent?.trim() || "";
          if (lbl) {
            head.setAttribute("data-ut-title", lbl);
            if (val) head.setAttribute("data-ut-val", val);
            if (sub) head.setAttribute("data-ut-body", sub);
            head.setAttribute("data-ut-meta", "실시간 집계 KPI · 클릭 또는 스파크라인 호버로 추이 확인");
            head.setAttribute("data-ut-tone", "live");
          }
        }
      });

      // Topbar & Chrome icon controls shortcut hints
      const shortcutMap = [
        ["#fdaiThemeToggle", "라이트 / 다크 테마 전환", "순수 무채색 라이트·다크 테마 즉시 전환", ""],
        ["#fdaiChatTrigger", "AI 운영 어시스턴트 채팅", "현재 화면 컨텍스트와 연동된 우측 AI 채팅 패널 토글", "Ctrl+J"],
        ["#fdaiQuickJumpBtn", "전체 메뉴 빠른 검색", "63개 메뉴·리소스·규칙을 키보드로 즉시 이동", "Ctrl+K"],
        ["#railLabsBtn", "실험실 · 격리 검증", "개발 전용 카오스·예측 학습·대화 품질 실험실", ""],
        ["#railSettingsBtn", "시스템 설정 오버레이", "일반·실행 환경·모델·권한·연동·진단·메모 설정", ""],
        ["[data-data-mode='live']", "Live 실시간 데이터 모드", "실제 수집기·권위 소스 기준 관측 상태를 표시합니다.", ""],
        ["[data-data-mode='sample']", "Sample 시연 데이터 모드", "데모·교육용 경계 배너를 표시하고 샘플 시나리오를 확인합니다.", ""]
      ];
      shortcutMap.forEach(([sel, title, body, kbd]) => {
        const el = document.querySelector(sel);
        if (el && !el.hasAttribute("data-ut-title")) {
          el.setAttribute("data-ut-title", title);
          if (body) el.setAttribute("data-ut-body", body);
          if (kbd) el.setAttribute("data-ut-kbd", kbd);
          el.setAttribute("data-ut-tone", "auto");
        }
      });
    }

    function resolveTooltipForTarget(startEl) {
      let el = startEl;
      for (let depth = 0; el && el !== document.body && depth < 6; depth++, el = el.parentElement) {
        if (!(el instanceof Element)) break;
        if (el.id === "fdaiUltraTip") return null;

        // Explicit structured attributes (with rich multi-row chart enrichment)
        const utTitle = el.getAttribute("data-ut-title");
        const utTip = el.getAttribute("data-ut-tip") || el.getAttribute("data-tip") || el.getAttribute("data-tip-text") || el.getAttribute("data-cal-tip");
        if (utTitle || utTip || el.classList.contains("domain-bar-row")) {
          const base = {
            title: utTitle || utTip || "",
            val: el.getAttribute("data-ut-val") || "",
            body: utTitle ? (el.getAttribute("data-ut-body") || utTip || "") : (el.getAttribute("data-ut-body") || ""),
            meta: el.getAttribute("data-ut-meta") || "",
            kbd: el.getAttribute("data-ut-kbd") || "",
            tone: el.getAttribute("data-ut-tone") || ""
          };
          return {
            el,
            payload: enrichChartTooltipPayload(el, base)
          };
        }

        // Icon-only buttons or controls with aria-label
        if ((el.tagName === "BUTTON" || el.tagName === "A") && !el.closest("svg")) {
          const txt = (el.textContent || "").trim();
          const aria = (el.getAttribute("aria-label") || "").trim();
          if (aria && (txt.length <= 2 || el.classList.contains("icon-btn") || el.classList.contains("topbar-icon-btn") || el.classList.contains("page-help-btn") || el.classList.contains("cs-rail-collapse-btn"))) {
            const kbdMatch = aria.match(/\((Ctrl\+[A-Z]|Esc)\)/i);
            return {
              el,
              payload: {
                title: aria.replace(/\s*\((Ctrl\+[A-Z]|Esc)\)/i, "").trim(),
                kbd: kbdMatch ? kbdMatch[1] : "",
                tone: "auto"
              }
            };
          }
        }

        // Domain glossary badges / pills
        if (el.matches(".cs-badge, .badge, .pill, .tag, .tier-pill, .status-pill")) {
          const txt = (el.textContent || "").trim();
          for (const g of GLOSSARY) {
            if (g.re.test(txt)) {
              return { el, payload: { title: g.title, body: g.body, tone: g.tone } };
            }
          }
        }

        // Automatic overflow / ellipsis truncation detection on leaf text
        if (depth === 0 && el.children.length === 0) {
          const txt = (el.textContent || "").trim();
          if (txt.length > 4 && el.scrollWidth > el.clientWidth + 2) {
            const cs = window.getComputedStyle(el);
            if (cs.overflowX === "hidden" || cs.textOverflow === "ellipsis" || cs.whiteSpace === "nowrap") {
              return { el, payload: { title: txt, meta: "말줄임 전체 원문" } };
            }
          }
        }
      }
      return null;
    }

    let activeHoverEl = null;

    document.addEventListener("pointerover", (e) => {
      if (!(e.target instanceof Element)) return;
      if (e.target.closest("svg.cs-ut-interactive-svg, canvas#fdaiOntologyKgCanvas")) return;
      const found = resolveTooltipForTarget(e.target);
      if (found) {
        activeHoverEl = found.el;
        showTip(found.payload, { x: e.clientX, y: e.clientY });
      } else if (activeHoverEl) {
        activeHoverEl = null;
        hideTip();
      }
    }, true);

    document.addEventListener("pointermove", (e) => {
      if (!activeHoverEl || !visible) return;
      if (e.target instanceof Element && e.target.closest("svg.cs-ut-interactive-svg, canvas#fdaiOntologyKgCanvas")) return;
      moveTip(e.clientX, e.clientY);
    }, { passive: true });

    document.addEventListener("pointerout", (e) => {
      if (!activeHoverEl) return;
      const rel = e.relatedTarget;
      if (rel instanceof Node && activeHoverEl.contains(rel)) return;
      activeHoverEl = null;
      hideTip();
    }, true);

    document.addEventListener("focusin", (e) => {
      if (!(e.target instanceof Element)) return;
      const found = resolveTooltipForTarget(e.target);
      if (found) {
        activeHoverEl = found.el;
        showTip(found.payload, found.el);
      }
    }, true);

    document.addEventListener("focusout", () => {
      activeHoverEl = null;
      hideTip();
    }, true);

    window.addEventListener("scroll", hideTip, { capture: true, passive: true });
    window.addEventListener("keydown", (e) => { if (e.key === "Escape") hideTip(); });

    let enhanceScheduled = false;
    const runEnhance = (root = document) => {
      upgradeNativeTitles(root);
      enhanceSvgChartsAndGraphs(root);
      enhanceHtmlVisuals(root);
    };
    const scheduleEnhance = () => {
      if (enhanceScheduled) return;
      enhanceScheduled = true;
      window.requestAnimationFrame(() => {
        enhanceScheduled = false;
        runEnhance(document);
      });
    };

    runEnhance(document);
    const obsRoot = document.getElementById("fdaiMain") || document.body;
    const utObs = new MutationObserver((muts) => {
      for (const m of muts) {
        if (m.target instanceof Element && (m.target.id === "fdaiUltraTip" || m.target.hasAttribute("data-ut-overlay"))) continue;
        if (m.addedNodes && m.addedNodes.length) {
          scheduleEnhance();
          return;
        }
      }
    });
    utObs.observe(obsRoot, { childList: true, subtree: true });
    window.addEventListener("hashchange", scheduleEnhance);
    document.addEventListener("click", (e) => {
      if (e.target instanceof Element && e.target.closest(".seg-btn, .hub-tab, [data-graph-view-btn], [data-mode-switch-btn], [data-subtab], [data-ont-view], [data-view-tab]")) {
        scheduleEnhance();
      }
    });

    window.fdaiTip = {
      show: showTip,
      move: moveTip,
      hide: hideTip,
      enhance: runEnhance
    };
  }

  /* ==========================================================================
     Component-First Diagram Canvas UX (Google Maps Ctrl+Scroll Zoom & Deselect)
     ========================================================================== */
  const zoomHintTimers = new WeakMap();
  const isMacPlatform = typeof navigator !== "undefined" && /Mac|iPhone|iPad/i.test(navigator.platform || navigator.userAgent || "");

  function showCanvasZoomHint(host) {
    if (!(host instanceof Element)) return;
    host.classList.add("cs-zoom-host");
    let layer = host.querySelector(":scope > .cs-zoom-hint-layer");
    if (!layer) {
      layer = document.createElement("div");
      layer.className = "cs-zoom-hint-layer";
      layer.setAttribute("role", "status");
      layer.setAttribute("aria-live", "polite");
      const keyLbl = isMacPlatform ? "⌘" : "Ctrl";
      layer.innerHTML = `<div class="cs-zoom-hint-pill"><kbd>${keyLbl}</kbd> + 스크롤로 다이어그램을 확대 · 축소할 수 있습니다</div>`;
      host.appendChild(layer);
    }
    layer.classList.add("is-visible");
    const prev = zoomHintTimers.get(host);
    if (prev) window.clearTimeout(prev);
    const tid = window.setTimeout(() => {
      layer?.classList.remove("is-visible");
    }, 1700);
    zoomHintTimers.set(host, tid);
  }

  function hideCanvasZoomHint(host) {
    if (!(host instanceof Element)) return;
    const prev = zoomHintTimers.get(host);
    if (prev) window.clearTimeout(prev);
    host.querySelector(":scope > .cs-zoom-hint-layer")?.classList.remove("is-visible");
  }

  function releaseDiagramSelection(container, skipDrawerClose) {
    const scope = container instanceof Element ? container : document;
    scope.querySelectorAll(".graph-node.is-selected, [data-ag-node].is-selected, [data-org-node].is-selected, .ev-rca-node.is-selected").forEach((el) => {
      el.classList.remove("is-selected");
      if (el.hasAttribute("aria-pressed")) el.setAttribute("aria-pressed", "false");
    });
    scope.querySelectorAll(".is-connected, .is-dimmed, .is-highlighted").forEach((el) => {
      el.classList.remove("is-connected", "is-dimmed", "is-highlighted");
    });
    scope.querySelectorAll(".svg-graph-stage.has-focus").forEach((st) => st.classList.remove("has-focus"));
    if (scope.classList?.contains("svg-graph-stage")) scope.classList.remove("has-focus");
    if (!skipDrawerClose && !drawerPinned) closeFloatingDrawer(true);
    window.fdaiTip?.hide?.();
  }

  function initDiagramCanvasUx() {
    if (window.__fdaiDiagramCanvasUxReady) return;
    window.__fdaiDiagramCanvasUxReady = true;

    const NODE_INTERACTIVE_SEL = "g.graph-node, g[data-ag-node], g[data-org-node], g.ev-rca-node, .svg-edge-group, button, a, input, select, textarea, .svg-graph-controls, .graph-toolbar, .inst-timeline, .inst-coverage, .cs-zoom-badge";

    const applySvgTransform = (host, svg) => {
      const z = parseFloat(svg.getAttribute("data-zoom") || "1");
      const px = parseFloat(svg.getAttribute("data-pan-x") || "0");
      const py = parseFloat(svg.getAttribute("data-pan-y") || "0");
      svg.classList.add("cs-pan-target");
      if (Math.abs(z - 1) < 0.005 && Math.abs(px) < 0.5 && Math.abs(py) < 0.5) {
        svg.style.transform = "";
      } else {
        svg.style.transform = `translate3d(${px.toFixed(1)}px, ${py.toFixed(1)}px, 0) scale(${z.toFixed(4)})`;
      }
      updateZoomBadge(host, svg);
    };

    const resetSvgView = (host, svg) => {
      svg.setAttribute("data-zoom", "1");
      svg.setAttribute("data-pan-x", "0");
      svg.setAttribute("data-pan-y", "0");
      applySvgTransform(host, svg);
    };

    const updateZoomBadge = (host, svg) => {
      const z = parseFloat(svg.getAttribute("data-zoom") || "1");
      const px = parseFloat(svg.getAttribute("data-pan-x") || "0");
      const py = parseFloat(svg.getAttribute("data-pan-y") || "0");
      let badge = host.querySelector(":scope > .cs-zoom-badge");
      if (Math.abs(z - 1) < 0.03 && Math.abs(px) < 4 && Math.abs(py) < 4) {
        if (badge) badge.hidden = true;
        return;
      }
      if (!badge) {
        badge = document.createElement("button");
        badge.type = "button";
        badge.className = "cs-zoom-badge";
        badge.setAttribute("data-ut-tip", "클릭하여 위치·배율 100%로 초기화");
        badge.addEventListener("click", (ev) => {
          ev.stopPropagation();
          resetSvgView(host, svg);
        });
        host.appendChild(badge);
      }
      badge.hidden = false;
      badge.textContent = `${Math.round(z * 100)}% · 위치 초기화`;
    };

    const bindDiagramSvg = (svg) => {
      if (!(svg instanceof SVGSVGElement) || svg.dataset.utCanvasUx === "1") return;
      const isDiagram = svg.classList.contains("graph-canvas-svg")
        || svg.classList.contains("ag-svg-stage")
        || svg.classList.contains("ag-org-svg")
        || svg.classList.contains("ev-rca-svg");
      if (!isDiagram) return;
      svg.dataset.utCanvasUx = "1";
      if (!svg.hasAttribute("data-zoom")) svg.setAttribute("data-zoom", "1");
      if (!svg.hasAttribute("data-pan-x")) svg.setAttribute("data-pan-x", "0");
      if (!svg.hasAttribute("data-pan-y")) svg.setAttribute("data-pan-y", "0");

      const host = svg.closest(".svg-graph-scroll, .ag-org-svg-wrap, #evRcaSvgWrap, .graph-canvas-stage") || svg.parentElement;
      if (!host) return;
      host.classList.add("cs-zoom-host");

      let panState = null;
      host.addEventListener("pointerdown", (e) => {
        if (e.button !== 0) return;
        if (e.target instanceof Element && e.target.closest("button, a, input, select, textarea, .svg-graph-controls, .graph-toolbar, .inst-timeline, .inst-coverage, .cs-zoom-badge")) return;
        const onNode = e.target instanceof Element && Boolean(e.target.closest("g.graph-node, g[data-ag-node], g[data-org-node], g.ev-rca-node, .svg-edge-group"));
        const px = parseFloat(svg.getAttribute("data-pan-x") || "0");
        const py = parseFloat(svg.getAttribute("data-pan-y") || "0");
        panState = { pointerId: e.pointerId, x: e.clientX, y: e.clientY, px, py, moved: false, onNode };
      });
      host.addEventListener("pointermove", (e) => {
        if (!panState) return;
        const dx = e.clientX - panState.x;
        const dy = e.clientY - panState.y;
        if (!panState.moved && Math.hypot(dx, dy) > 4) {
          panState.moved = true;
          host.classList.add("is-panning");
          window.fdaiTip?.hide?.();
          try { host.setPointerCapture(panState.pointerId); } catch (_err) {}
        }
        if (panState.moved) {
          svg.setAttribute("data-pan-x", String(+(panState.px + dx).toFixed(1)));
          svg.setAttribute("data-pan-y", String(+(panState.py + dy).toFixed(1)));
          applySvgTransform(host, svg);
        }
      });
      const endPan = () => {
        if (!panState) return;
        const wasMoved = panState.moved;
        const pid = panState.pointerId;
        panState = null;
        host.classList.remove("is-panning");
        try { if (host.hasPointerCapture(pid)) host.releasePointerCapture(pid); } catch (_err) {}
        if (wasMoved) host.dataset.recentPan = String(Date.now());
      };
      host.addEventListener("pointerup", endPan);
      host.addEventListener("pointercancel", endPan);

      // Prevent accidental node click immediately after drag-pan
      host.addEventListener("click", (e) => {
        if (e.target instanceof Element && e.target.closest(".cs-zoom-badge")) return;
        const recentPan = Number(host.dataset.recentPan || "0");
        if (Date.now() - recentPan < 180) {
          e.stopPropagation();
          e.preventDefault();
          return;
        }
        if (e.target instanceof Element && e.target.closest(NODE_INTERACTIVE_SEL)) return;
        const stage = svg.closest(".svg-graph-stage, .graph-canvas-wrap, .panel-view") || host;
        releaseDiagramSelection(stage, false);
      }, true);

      host.addEventListener("dblclick", (e) => {
        if (e.target instanceof Element && e.target.closest(NODE_INTERACTIVE_SEL)) return;
        resetSvgView(host, svg);
      });

      host.addEventListener("wheel", (e) => {
        if (!(e.ctrlKey || e.metaKey)) {
          showCanvasZoomHint(host);
          return;
        }
        e.preventDefault();
        hideCanvasZoomHint(host);
        const curZ = parseFloat(svg.getAttribute("data-zoom") || "1");
        const curPx = parseFloat(svg.getAttribute("data-pan-x") || "0");
        const curPy = parseFloat(svg.getAttribute("data-pan-y") || "0");
        const factor = e.deltaY < 0 ? 1.14 : 0.88;
        const nextZ = Math.max(0.5, Math.min(2.8, +(curZ * factor).toFixed(4)));
        // Anchor zoom around cursor position relative to SVG's unscaled origin
        const svgRect = svg.getBoundingClientRect();
        const originX = svgRect.left - curPx;
        const originY = svgRect.top - curPy;
        const cursorRelX = e.clientX - originX;
        const cursorRelY = e.clientY - originY;
        const ratio = nextZ / curZ;
        const nextPx = cursorRelX - (cursorRelX - curPx) * ratio;
        const nextPy = cursorRelY - (cursorRelY - curPy) * ratio;
        svg.setAttribute("data-zoom", String(nextZ));
        svg.setAttribute("data-pan-x", String(+nextPx.toFixed(1)));
        svg.setAttribute("data-pan-y", String(+nextPy.toFixed(1)));
        applySvgTransform(host, svg);
      }, { passive: false });
    };

    const scanDiagrams = () => {
      document.querySelectorAll("svg").forEach(bindDiagramSvg);
    };
    scanDiagrams();
    const obsRoot = document.getElementById("fdaiMain") || document.body;
    const obs = new MutationObserver(() => scanDiagrams());
    obs.observe(obsRoot, { childList: true, subtree: true });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        const active = document.querySelector(".panel-view[data-panel-id]:not([hidden])");
        if (active) releaseDiagramSelection(active);
      }
    });

    window.fdaiReleaseDiagramSelection = releaseDiagramSelection;

    // Collapsible Ontology Instance Timeline (default collapsed to maximize canvas height)
    document.querySelectorAll(".inst-timeline").forEach((tl) => {
      if (tl.dataset.tlEnhanced === "1") return;
      tl.dataset.tlEnhanced = "1";
      tl.classList.add("is-collapsed");
      const head = tl.firstElementChild;
      if (head) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "inst-timeline-toggle";
        btn.setAttribute("aria-expanded", "false");
        btn.textContent = "타임라인 펼치기 ▾";
        btn.addEventListener("click", (ev) => {
          ev.stopPropagation();
          const nextCollapsed = !tl.classList.contains("is-collapsed");
          tl.classList.toggle("is-collapsed", nextCollapsed);
          btn.setAttribute("aria-expanded", String(!nextCollapsed));
          btn.textContent = nextCollapsed ? "타임라인 펼치기 ▾" : "타임라인 접기 ▴";
          window.requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
        });
        head.appendChild(btn);
      }
    });

    // Enhance Semantic Map with top flow summary + clickable concept badges -> Right Detail Drawer
    document.querySelectorAll('[data-graph-view-pane="semantic"]').forEach((pane) => {
      if (pane.dataset.semEnhanced === "1") return;
      pane.dataset.semEnhanced = "1";
      const flow = document.createElement("div");
      flow.className = "semantic-flow-strip";
      flow.innerHTML = `
        <div class="semantic-flow-step"><span>1. 비즈니스 · 운영 맥락</span><span>4개 개념 →</span></div>
        <div class="semantic-flow-step"><span>2. 인프라 · 런타임 리소스</span><span>6개 개념 →</span></div>
        <div class="semantic-flow-step"><span>3. 관측 · 데이터 계통</span><span>4개 개념 →</span></div>
        <div class="semantic-flow-step"><span>4. 정책 · 안전 · 감사</span><span>4개 개념</span></div>
      `;
      pane.prepend(flow);
      pane.querySelectorAll(".semantic-pills .cs-badge").forEach((badge) => {
        badge.setAttribute("role", "button");
        badge.setAttribute("tabindex", "0");
        const openConcept = () => {
          const concept = (badge.textContent || "").trim();
          const bandTitle = badge.closest(".semantic-band")?.querySelector(".semantic-band-head span:first-child")?.textContent?.trim() || "시맨틱 계층";
          openFloatingDrawer({
            title: concept,
            meta: `${bandTitle} · FDAI 정규 운영 온톨로지`,
            body: `${concept} 개념은 온톨로지 의미 계층에 등록되어 리소스·관측·정책·감사 근거를 정규화합니다. 온톨로지는 의미와 관계만 검증하며 실행 권한을 부여하지 않습니다.`,
            facts: [
              ["소속 계층", bandTitle],
              ["정규 개념", concept],
              ["권한 경계", "의미 검증 전용 (권한 부여 불가)"],
              ["연계 근거", "데이터 계통 · 2단계 SHA-256 감사 원장"]
            ],
            href: panelUrl("rules"),
            hrefLabel: "연계 운영 규칙 보기 →"
          }, badge);
        };
        badge.addEventListener("click", openConcept);
        badge.addEventListener("keydown", (ev) => {
          if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); openConcept(); }
        });
      });
    });
  }

  /* ==========================================================================
     Component-First Universal Chart Click -> Right Detail Drawer & Drilldown
     ========================================================================== */
  function initChartDrilldown() {
    if (window.__fdaiChartDrilldownReady) return;
    window.__fdaiChartDrilldownReady = true;

    const drilldownForContext = (svgOrEl, titleText) => {
      const id = svgOrEl?.id || "";
      const txt = (titleText || "").toLowerCase();
      if (id === "ovLlmTrendSvg" || txt.includes("토큰") || txt.includes("t1") || txt.includes("t2")) {
        return { href: panelUrl("settings-models"), label: "AI 모델 바인딩 설정 →" };
      }
      if (id === "ovCostTrendSvg" || txt.includes("비용") || txt.includes("예산")) {
        return { href: panelUrl("cost-governance"), label: "비용 거버넌스 상세 →" };
      }
      if (id === "ovOutcomeTrendSvg" || txt.includes("해결률") || txt.includes("mttr") || txt.includes("성과")) {
        return { href: panelUrl("audit"), label: "감사 원장 근거 보기 →" };
      }
      if (txt.includes("보안") || txt.includes("cve") || txt.includes("취약점")) {
        return { href: panelUrl("code-security"), label: "코드 보안 화면 열기 →" };
      }
      if (txt.includes("승인") || txt.includes("hil") || txt.includes("사람")) {
        return { href: panelUrl("hil-queue"), label: "승인 요청 검토하기 →" };
      }
      if (txt.includes("알림") || txt.includes("억제") || txt.includes("노이즈")) {
        return { href: panelUrl("rules"), label: "관련 운영 규칙 보기 →" };
      }
      if (txt.includes("보정") || txt.includes("예측") || txt.includes("sre") || txt.includes("위험")) {
        return { href: panelUrl("incidents"), label: "장애 대응 화면 열기 →" };
      }
      return { href: panelUrl("live"), label: "실시간 모니터링 열기 →" };
    };

    document.addEventListener("click", (e) => {
      if (!(e.target instanceof Element)) return;
      if (e.target.closest("a, [data-drawer-title], [data-jump-panel], [data-gnode-name], [data-ag-node], [data-org-node], .ev-rca-node, .cs-zoom-badge")) return;

      // 1. Direct clickable SVG chart points/bars/segments (scatter, stacked bar, LLM stack, alert quality, calibration)
      const shape = e.target.closest("svg circle[data-ut-title], svg circle[data-tip-text], svg circle[data-cal-tip], svg rect[data-ut-title], svg g.ov-llm-bar");
      if (shape) {
        const svg = shape.closest("svg");
        const title = shape.getAttribute("data-ut-title")
          || shape.getAttribute("data-tip-text")
          || shape.getAttribute("data-cal-tip")
          || shape.getAttribute("data-llm-msg")
          || svg?.getAttribute("aria-label")
          || "차트 항목 상세";
        const val = shape.getAttribute("data-ut-val") || "";
        const body = shape.getAttribute("data-ut-body")
          || shape.getAttribute("data-tip-text")
          || shape.getAttribute("data-cal-tip")
          || shape.getAttribute("data-llm-msg")
          || "선택한 차트 지점의 측정 근거와 드릴다운 경로입니다.";
        const meta = shape.getAttribute("data-ut-meta") || svg?.getAttribute("aria-label") || "실시간 관측 차트";
        const dd = drilldownForContext(svg, `${title} ${body} ${meta}`);
        const facts = [["차트", svg?.getAttribute("aria-label") || "운영 차트"], ["선택 항목", title]];
        if (val) facts.push(["측정값", val]);
        if (meta) facts.push(["상세 기준", meta]);
        openFloatingDrawer({
          title,
          meta,
          body,
          facts,
          href: dd.href,
          hrefLabel: dd.label
        }, shape);
        return;
      }

      // 2. Interactive Line / Area / Calibration SVG click (snap to nearest data point on crosshair chart)
      const lineSvg = e.target.closest("svg.cs-ut-interactive-svg:not(.kpi-spark)");
      if (lineSvg) {
        const circles = Array.from(lineSvg.querySelectorAll("circle:not([data-ut-overlay])")).filter((c) => {
          const r = parseFloat(c.getAttribute("r") || "0");
          return r >= 2.5 && r <= 9;
        });
        if (circles.length) {
          const rect = lineSvg.getBoundingClientRect();
          const vb = (lineSvg.getAttribute("viewBox") || `0 0 ${rect.width} ${rect.height}`).trim().split(/[\s,]+/).map(Number);
          const svgX = ((e.clientX - rect.left) / Math.max(1, rect.width)) * (vb[2] || rect.width);
          let nearest = circles[0];
          let minD = Math.abs(parseFloat(nearest.getAttribute("cx") || "0") - svgX);
          circles.forEach((c) => {
            const d = Math.abs(parseFloat(c.getAttribute("cx") || "0") - svgX);
            if (d < minD) { minD = d; nearest = c; }
          });
          const title = nearest.getAttribute("data-ut-title") || lineSvg.getAttribute("aria-label") || "시계열 지점";
          const val = nearest.getAttribute("data-ut-val") || "";
          const body = nearest.getAttribute("data-ut-body") || nearest.getAttribute("data-cal-tip") || nearest.getAttribute("data-ut-meta") || "선택한 시계열 지점의 실측·예측 상세 정보입니다.";
          const meta = nearest.getAttribute("data-ut-meta") || lineSvg.getAttribute("aria-label") || "시계열 차트";
          const dd = drilldownForContext(lineSvg, `${title} ${body} ${meta}`);
          const facts = [["차트", lineSvg.getAttribute("aria-label") || "시계열 추이"], ["선택 지점", title]];
          if (val) facts.push(["측정값", val]);
          if (meta) facts.push(["기준 비교", meta]);
          openFloatingDrawer({ title, meta, body, facts, href: dd.href, hrefLabel: dd.label }, lineSvg);
          return;
        }
      }

      // 3. Posture Donut Ring (.ov-ring-wrap) & HTML Bar/Distribution Charts
      const htmlChart = e.target.closest(".ov-ring-wrap, .ov-bar-row, .domain-bar-row, .gov-stack-seg, .dist-bar > span");
      if (htmlChart) {
        const title = htmlChart.getAttribute("data-ut-title") || htmlChart.getAttribute("aria-label") || "지표 상세";
        const val = htmlChart.getAttribute("data-ut-val") || "";
        const body = htmlChart.getAttribute("data-ut-body") || (htmlChart.textContent || "").replace(/\s+/g, " ").trim();
        const meta = htmlChart.getAttribute("data-ut-meta") || "운영 분포 · 비율 지표";
        const dd = drilldownForContext(htmlChart, `${title} ${body}`);
        const facts = [["항목", title]];
        if (val) facts.push(["값/비율", val]);
        if (meta) facts.push(["근거", meta]);
        openFloatingDrawer({ title, meta, body, facts, href: dd.href, hrefLabel: dd.label }, htmlChart);
      }
    });
  }

  /* ==========================================================================
     UX Auto-Close Drawers/Sidebars on Navigation + WCAG 2.1 AA Invariants
     ========================================================================== */
  function closeSidebarAndDrawersOnNav() {
    if (window.__fdaiAutoCloseNavWired) return;
    window.__fdaiAutoCloseNavWired = true;
    document.addEventListener("click", (e) => {
      if (!(e.target instanceof Element)) return;
      const link = e.target.closest("#fdaiDrawerBackdrop a[href], #fdaiFloatDrawer a[href], [data-float-inspector='panel'] a[href], #fdaiChatSidebar a[href], #evAuditDrawer a[href]");
      if (!link) return;
      const rawHref = (link.getAttribute("href") || "").trim();
      closeDrawer();
      closeFloatingDrawer(false);
      document.getElementById("evAuditDrawer")?.classList.remove("is-open");
      if (chatOpen) toggleChatSidebar(false);
      if (!rawHref || rawHref.startsWith("http") || rawHref.startsWith("mailto:")) return;
      let targetPanel = "";
      const hm = rawHref.match(/#tab=([a-z0-9-]+)/i);
      if (hm) {
        targetPanel = hm[1];
      } else if (rawHref.startsWith("/")) {
        const clean = rawHref.replace(/\/+$/, "");
        if (clean.startsWith("/settings/")) targetPanel = `settings-${clean.slice("/settings/".length)}`;
        else if (clean.startsWith("/labs/")) targetPanel = clean.slice("/labs/".length);
        else if (!clean.slice(1).includes("/")) targetPanel = clean.slice(1);
      }
      if (targetPanel && document.querySelector(`.panel-view[data-panel-id="${targetPanel}"]`)) {
        e.preventDefault();
        navigatePanel(targetPanel, false);
      }
    }, true);
  }

  function ensureAccessibilityInvariants() {
    // 1. WCAG 2.4.1 Skip-to-main-content link
    const root = document.getElementById("fdaiShellRoot") || document.body;
    const main = document.getElementById("fdaiMain") || document.querySelector("main");
    if (main && !main.hasAttribute("tabindex")) main.setAttribute("tabindex", "-1");
    if (root && main && !document.querySelector("a.skip-link")) {
      const skip = document.createElement("a");
      skip.className = "skip-link";
      skip.href = `#${main.id || "fdaiMain"}`;
      skip.textContent = "본문으로 바로가기";
      root.prepend(skip);
    }

    // 2. WCAG 1.3.1 / 2.4.6 Semantic <h1> landmark (promote .page-breadcrumb h2 -> h1, zero visual change)
    if (!document.querySelector("h1")) {
      const bc = document.querySelector("h2.page-breadcrumb");
      if (bc && bc.parentElement) {
        const h1 = document.createElement("h1");
        Array.from(bc.attributes).forEach((attr) => h1.setAttribute(attr.name, attr.value));
        while (bc.firstChild) h1.appendChild(bc.firstChild);
        bc.parentElement.replaceChild(h1, bc);
      }
    }

    // 3. WCAG 2.1.1 Keyboard access on clickable table rows & visual chart bars
    const enhanceKeyboard = (scope = document) => {
      scope.querySelectorAll("tr.row-active, tr[data-rule-id], tr[data-doc-id], tr[data-vuln-id], tr[data-code-id], tr[data-base-id], tr[data-conv-id], .gov-stack-seg, .ov-ring-wrap, .ov-bar-row, .domain-bar-row").forEach((el) => {
        if (el.dataset.a11yKb === "1") return;
        el.dataset.a11yKb = "1";
        if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "0");
        if (!el.hasAttribute("role") && el.tagName !== "TR") el.setAttribute("role", "button");
        el.addEventListener("keydown", (ev) => {
          if (ev.key === "Enter" || ev.key === " ") {
            if (ev.target instanceof Element && ev.target.closest("button, a, input, select, textarea")) return;
            ev.preventDefault();
            el.click();
          }
        });
      });
    };
    enhanceKeyboard(document);
    if (!window.__fdaiA11yObs && main) {
      window.__fdaiA11yObs = new MutationObserver(() => enhanceKeyboard(main));
      window.__fdaiA11yObs.observe(main, { childList: true, subtree: true });
    }
  }

  function initViewportFitDisclosures() {
    const sync = () => {
      document.querySelectorAll("details[data-auto-fit-disclosure]").forEach((el) => {
        if (el.dataset.afWired !== "1") {
          el.dataset.afWired = "1";
          const sum = el.querySelector(":scope > summary");
          sum?.addEventListener("click", () => { el.dataset.userToggled = "1"; });
        }
        const panel = el.closest(".panel-view");
        if (panel && panel.hidden) return;
        const scroller = el.closest(".main-canvas") || document.documentElement;
        const bentoMin = parseInt(el.getAttribute("data-auto-fit-bento") || "0", 10) || 0;
        const mainW = scroller === document.documentElement ? window.innerWidth : scroller.clientWidth;
        const inBentoSide = bentoMin > 0 && mainW >= bentoMin;
        if (el.dataset.lastBentoSide !== String(inBentoSide)) {
          el.dataset.lastBentoSide = String(inBentoSide);
          delete el.dataset.userToggled;
        }
        if (el.dataset.userToggled === "1") return;
        if (inBentoSide) {
          el.open = true;
          return;
        }
        const sRect = scroller === document.documentElement ? { top: 0 } : scroller.getBoundingClientRect();
        const viewH = scroller === document.documentElement ? window.innerHeight : scroller.clientHeight;
        const scrollTop = scroller === document.documentElement ? window.scrollY : scroller.scrollTop;
        const topInFlow = el.getBoundingClientRect().top - sRect.top + scrollTop;
        const remaining = Math.round(viewH - topInFlow);
        const minSpace = parseInt(el.getAttribute("data-auto-fit-disclosure") || "220", 10) || 220;
        el.open = remaining >= minSpace;
      });
    };
    let rafId = 0;
    const schedule = () => {
      if (rafId) cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => { rafId = 0; sync(); });
    };
    schedule();
    window.setTimeout(sync, 120);
    window.addEventListener("resize", schedule, { passive: true });
    if (typeof window.ResizeObserver === "function") {
      const main = document.getElementById("fdaiMain");
      if (main) new ResizeObserver(schedule).observe(main);
    }
    window.addEventListener("fdai:panelchange", () => {
      document.querySelectorAll("details[data-auto-fit-disclosure]").forEach((el) => {
        delete el.dataset.userToggled;
      });
      schedule();
    });
  }

  /* ==========================================================================
     Component-First Skeleton Pre-Render & Container ResizeObserver Chart Engine
     ========================================================================== */
  const prefersReducedMotion = () =>
    typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function showPanelSkeleton(panelEl, durationMs) {
    if (!panelEl || prefersReducedMotion()) return;
    const prev = panelEl.querySelector(":scope > .cs-skel-overlay");
    if (prev) prev.remove();
    const ov = document.createElement("div");
    ov.className = "cs-skel-overlay";
    ov.setAttribute("aria-hidden", "true");
    ov.innerHTML = `
      <div class="cs-skel-kpi-row">
        <div class="cs-skel-kpi-cell"><span class="cs-skeleton cs-skel-line is-short"></span><span class="cs-skeleton cs-skel-line is-med" style="height:22px"></span></div>
        <div class="cs-skel-kpi-cell"><span class="cs-skeleton cs-skel-line is-short"></span><span class="cs-skeleton cs-skel-line is-med" style="height:22px"></span></div>
        <div class="cs-skel-kpi-cell"><span class="cs-skeleton cs-skel-line is-short"></span><span class="cs-skeleton cs-skel-line is-med" style="height:22px"></span></div>
        <div class="cs-skel-kpi-cell"><span class="cs-skeleton cs-skel-line is-short"></span><span class="cs-skeleton cs-skel-line is-med" style="height:22px"></span></div>
      </div>
      <span class="cs-skeleton cs-skel-chart"></span>
    `;
    panelEl.setAttribute("aria-busy", "true");
    panelEl.appendChild(ov);
    window.setTimeout(() => {
      ov.classList.add("is-fading");
      window.setTimeout(() => {
        ov.remove();
        panelEl.removeAttribute("aria-busy");
      }, 140);
    }, Math.max(80, durationMs || 140));
  }

  function showChartSkeleton(chartBox, durationMs) {
    if (!chartBox || prefersReducedMotion()) return;
    const prev = chartBox.querySelector(":scope > .cs-skel-chart-overlay");
    if (prev) prev.remove();
    const ov = document.createElement("div");
    ov.className = "cs-skel-chart-overlay";
    ov.setAttribute("aria-hidden", "true");
    ov.innerHTML = `
      <span class="cs-skeleton cs-skel-line is-short"></span>
      <span class="cs-skeleton" style="width:100%;height:100%"></span>
      <span class="cs-skeleton cs-skel-line is-med"></span>
    `;
    chartBox.appendChild(ov);
    window.setTimeout(() => {
      ov.classList.add("is-fading");
      window.setTimeout(() => ov.remove(), 120);
    }, Math.max(70, durationMs || 110));
  }

  window.fdaiSkeleton = {
    showPanel: showPanelSkeleton,
    showChart: showChartSkeleton
  };

  function initResponsiveChartEngine() {
    if (window.__fdaiResponsiveChartEngine) return;
    window.__fdaiResponsiveChartEngine = true;

    const compactAxisTicks = (svg) => {
      const w = svg.getBoundingClientRect().width;
      if (w <= 0) return;
      const texts = Array.from(svg.querySelectorAll("text"));
      // Group bottom X-axis labels (near maximum Y) and hide odd ticks on narrow containers
      let maxY = -Infinity;
      texts.forEach((t) => {
        const y = parseFloat(t.getAttribute("y") || "0");
        if (y > maxY) maxY = y;
      });
      const xTicks = texts.filter((t) => {
        const y = parseFloat(t.getAttribute("y") || "0");
        return maxY > 80 && Math.abs(y - maxY) <= 14;
      });
      if (xTicks.length >= 6) {
        xTicks.forEach((t, idx) => {
          const hide = w < 620 && idx % 2 === 1 && idx !== xTicks.length - 1;
          t.classList.toggle("is-tick-hidden", hide);
        });
      }
    };

    const reflowAllVisibleCharts = () => {
      document.querySelectorAll(".panel-view:not([hidden]) svg").forEach((svg) => {
        if (!(svg instanceof SVGSVGElement)) return;
        if (svg.classList.contains("kpi-spark")) return;
        const vb = (svg.getAttribute("viewBox") || "").trim().split(/[\s,]+/).map(Number);
        if (vb.length !== 4 || vb[2] < 300 || vb[3] < 100) return;
        if (isReflowableChartSvg(svg)) {
          reflowChartSvg1to1(svg);
          compactAxisTicks(svg);
        }
      });
    };

    if (typeof window.ResizeObserver === "function") {
      let roRaf = 0;
      const scheduleReflow = () => {
        if (roRaf) cancelAnimationFrame(roRaf);
        roRaf = requestAnimationFrame(() => {
          roRaf = 0;
          reflowAllVisibleCharts();
        });
      };
      const ro = new ResizeObserver(scheduleReflow);
      const main = document.getElementById("fdaiMain");
      if (main) ro.observe(main);
      document.querySelectorAll(".chart-box").forEach((box) => ro.observe(box));
    }

    // Brief skeleton pre-render feedback on panel transitions & chart mode/timeframe toggles
    let lastSkelPanel = currentPanelId;
    window.addEventListener("fdai:panelchange", (ev) => {
      const pid = ev?.detail?.panelId;
      if (pid && pid !== lastSkelPanel) {
        lastSkelPanel = pid;
        const panelEl = document.querySelector(`.panel-view[data-panel-id="${pid}"]`);
        if (panelEl && !panelEl.closest('[data-layout-tier="fullbleed"]')) {
          showPanelSkeleton(panelEl, 130);
        }
      }
    });

    document.addEventListener("click", (e) => {
      if (!(e.target instanceof Element)) return;
      const ctl = e.target.closest(".seg-btn, [role='tab']");
      if (!ctl) return;
      const card = ctl.closest(".surface-card, section");
      const chartBox = card?.querySelector(".chart-box");
      if (chartBox) {
        showChartSkeleton(chartBox, 110);
        window.requestAnimationFrame(reflowAllVisibleCharts);
      }
    });
  }

  function initOntologyInstanceSearch() {
    const inp = document.getElementById("ontoInstSearch");
    const listbox = document.getElementById("ontoInstListbox");
    const resetBtn = document.getElementById("ontoInstResetRoot");
    const countEl = document.getElementById("ontoInstSearchCount");
    const pane = inp?.closest("[data-graph-view-pane='instance']");
    if (!inp || !listbox || !pane || inp.dataset.searchWired === "1") return;
    inp.dataset.searchWired = "1";

    const nodes = Array.from(pane.querySelectorAll("g.graph-node[data-gnode-name]"));
    const edges = Array.from(pane.querySelectorAll("g.svg-edge-group"));
    const centerNode = pane.querySelector('g.graph-node[data-gnode-id="aks"]');
    const origCenterSnapshot = centerNode ? {
      name: centerNode.getAttribute("data-gnode-name") || "prod-aks-02",
      type: centerNode.getAttribute("data-gnode-type") || "",
      status: centerNode.getAttribute("data-gnode-status") || "",
      lineage: centerNode.getAttribute("data-gnode-lineage") || "",
      note: centerNode.getAttribute("data-gnode-note") || "",
      icon: centerNode.querySelector("image")?.getAttribute("href") || "/azure-icons/kubernetes-services.svg",
      t1: centerNode.querySelectorAll("text")[0]?.textContent || "prod-aks-02",
      t2: centerNode.querySelectorAll("text")[1]?.textContent || "AKS · prod-core-kr · 18노드"
    } : null;

    const iconForType = (typeStr) => {
      const s = (typeStr || "").toLowerCase();
      if (s.includes("kubernetes") || s.includes("aks")) return "/azure-icons/kubernetes-services.svg";
      if (s.includes("postgres")) return "/azure-icons/postgresql.svg";
      if (s.includes("cosmos")) return "/azure-icons/cosmos-db.svg";
      if (s.includes("sql")) return "/azure-icons/sql-database.svg";
      if (s.includes("redis")) return "/azure-icons/cache-redis.svg";
      if (s.includes("key vault") || s.includes("keyvault")) return "/azure-icons/key-vault.svg";
      if (s.includes("service bus") || s.includes("servicebus")) return "/azure-icons/service-bus.svg";
      if (s.includes("event hub")) return "/azure-icons/event-hubs.svg";
      if (s.includes("storage")) return "/azure-icons/storage-account.svg";
      if (s.includes("registry") || s.includes("acr")) return "/azure-icons/container-registry.svg";
      if (s.includes("application gateway") || s.includes("gateway")) return "/azure-icons/application-gateway.svg";
      if (s.includes("load balancer")) return "/azure-icons/load-balancer.svg";
      if (s.includes("firewall")) return "/azure-icons/firewall.svg";
      if (s.includes("bastion")) return "/azure-icons/bastion.svg";
      if (s.includes("network security") || s.includes("nsg")) return "/azure-icons/network-security-group.svg";
      if (s.includes("virtual network") || s.includes("vnet")) return "/azure-icons/virtual-network.svg";
      if (s.includes("public ip") || s.includes("waf")) return "/azure-icons/public-ip.svg";
      if (s.includes("identity")) return "/azure-icons/managed-identity.svg";
      if (s.includes("container app")) return "/azure-icons/container-apps.svg";
      if (s.includes("scale set") || s.includes("vmss")) return "/azure-icons/vm-scale-sets.svg";
      if (s.includes("openai")) return "/azure-icons/azure-openai.svg";
      if (s.includes("foundry")) return "/azure-icons/ai-foundry.svg";
      if (s.includes("disk")) return "/azure-icons/disks.svg";
      if (s.includes("virtual machine") || s.includes("gpu") || s.includes("vm")) return "/azure-icons/virtual-machine.svg";
      return "/azure-icons/monitor.svg";
    };

    // Full multi-subscription Azure resource directory (canvas nodes + all off-canvas subscription resources)
    const FULL_INVENTORY_FALLBACK = [
      { id: "prod-aks-02", gnodeId: "aks", name: "prod-aks-02", type: "Azure Kubernetes Service", sub: "prod-core-kr", rg: "rg-orders-prod", status: "CPU 예측 +5m", tone: "sre", icon: "/azure-icons/kubernetes-services.svg", note: "기록 상태 3축: 운영 running · 가용성 주의(Freyr CPU 91% 예측) · 구성 변경 없음." },
      { id: "pg-orders-kr", gnodeId: "pg", name: "pg-orders-kr", type: "Azure PostgreSQL Flexible", sub: "prod-core-kr", rg: "rg-orders-prod", status: "연결 풀 92% 주의", tone: "sre", icon: "/azure-icons/postgresql.svg", note: "Private Endpoint 1.8ms 경로. 연결 풀 138/150 포화로 HIL-8841 승인 대기 중." },
      { id: "kv-prod-kr", gnodeId: "kv", name: "kv-prod-kr", type: "Azure Key Vault", sub: "sec-shared-hub", rg: "rg-sec-vault", status: "임시 예외 2건 만료", tone: "sec", icon: "/azure-icons/key-vault.svg", note: "Managed Identity 비밀키 접근 관계. 만료된 임시 IP 2건 회수 대기 중." },
      { id: "prod-gw-kr", gnodeId: "gw", name: "prod-gw-kr", type: "Application Gateway", sub: "prod-core-kr", rg: "rg-edge-kr", status: "정상 · 2.4k RPS", tone: "live", icon: "/azure-icons/application-gateway.svg", note: "외부 TLS 1.3 종단 및 WAF 통과 후 검증된 트래픽 경로로 AKS에 전달합니다." },
      { id: "kr-central-redis", gnodeId: "redis", name: "kr-central-redis", type: "Azure Cache for Redis", sub: "prod-core-kr", rg: "rg-orders-prod", status: "정상 · 적중 98.4%", tone: "live", icon: "/azure-icons/cache-redis.svg", note: "19:41 일시적 지연 142ms 후 자동 회복 검증 완료." },
      { id: "sb-orders-events", gnodeId: "sb", name: "sb-orders-events", type: "Azure Service Bus", sub: "prod-core-kr", rg: "rg-orders-prod", status: "정상 · 180/s", tone: "live", icon: "/azure-icons/service-bus.svg", note: "주문·결제 비동기 이벤트 브로커. Dead-letter 0건 유지 중." },
      { id: "acr-prod-kr", gnodeId: "acr", name: "acr-prod-kr", type: "Azure Container Registry", sub: "prod-core-kr", rg: "rg-platform-shared", status: "서명 이미지 검증됨", tone: "live", icon: "/azure-icons/container-registry.svg", note: "다이제스트 고정 서명 이미지만 Pull 허용." },
      { id: "law-prod-monitor", gnodeId: "law", name: "law-prod-monitor", type: "Azure Monitor / Log Analytics", sub: "prod-core-kr", rg: "rg-observability", status: "지연 12s · 정상", tone: "live", icon: "/azure-icons/monitor.svg", note: "Heimdall과 Huginn의 관측 시계열 및 진단 로그 수집 대상입니다." },
      { id: "mi-orders-workload", gnodeId: "mi", name: "mi-orders-workload", type: "Managed Identity", sub: "prod-core-kr", rg: "rg-orders-prod", status: "최소 권한 검증", tone: "live", icon: "/azure-icons/managed-identity.svg", note: "OIDC 워크로드 자격 증명으로 Key Vault와 ACR에 인증합니다." },
      { id: "vnet-prod-kr", gnodeId: "vnet", name: "vnet-prod-kr", type: "Virtual Network", sub: "prod-core-kr", rg: "rg-network-kr", status: "10.24.0.0/16 Private", tone: "live", icon: "/azure-icons/virtual-network.svg", note: "사설 네트워크 경계 및 NSG 정책 적용 중." },
      { id: "public-ip-gw", gnodeId: "pip", name: "public-ip-gw · waf-policy", type: "Public IP + WAF Policy", sub: "prod-core-kr", rg: "rg-edge-kr", status: "WAF 14규칙 활성", tone: "live", icon: "/azure-icons/public-ip.svg", note: "유일한 공용 진입 IP이며 WAF 14개 규칙이 적용되어 있습니다." },
      { id: "cosmos-catalog-kr", name: "cosmos-catalog-kr", type: "Azure Cosmos DB", sub: "prod-data-platform", rg: "rg-catalog-data", status: "정상 · RU 42%", tone: "live", icon: "/azure-icons/cosmos-db.svg", note: "상품 카탈로그 다중 리전 읽기 복제본. orders-api 및 search-api가 참조합니다." },
      { id: "sql-billing-prod", name: "sql-billing-prod", type: "Azure SQL Database", sub: "prod-data-platform", rg: "rg-billing-data", status: "정상 · DTU 38%", tone: "live", icon: "/azure-icons/sql-database.svg", note: "정산 원장 DB. Private Endpoint 전용 접근 및 TDE 고객 관리 키 적용." },
      { id: "eh-telemetry-ingest", name: "eh-telemetry-ingest", type: "Azure Event Hubs", sub: "prod-data-platform", rg: "rg-streaming-kr", status: "정상 · 4.2k msg/s", tone: "live", icon: "/azure-icons/event-hubs.svg", note: "실시간 텔레메트리 수집 허브. Huginn·Heimdall 컨슈머 그룹 연결." },
      { id: "st-orders-archive", name: "st-orders-archive", type: "Storage Account", sub: "prod-data-platform", rg: "rg-audit-archive", status: "정상 · 불변 WORM", tone: "live", icon: "/azure-icons/storage-account.svg", note: "감사 증적 및 장기 로그 보관용 불변 스토리지(Private Endpoint 전용)." },
      { id: "azfw-hub-kr", name: "azfw-hub-kr", type: "Azure Firewall", sub: "sec-shared-hub", rg: "rg-hub-network", status: "정상 · IDPS 활성", tone: "live", icon: "/azure-icons/firewall.svg", note: "전 구독 이그레스 중앙 통제 방화벽. 허용 목록 외 외부 통신 차단." },
      { id: "bas-ops-kr", name: "bas-ops-kr", type: "Azure Bastion", sub: "sec-shared-hub", rg: "rg-hub-network", status: "정상 · JIT 연동", tone: "live", icon: "/azure-icons/bastion.svg", note: "공인 IP 없는 사설 관리 접속 전용 Bastion 호스트." },
      { id: "lb-internal-orders", name: "lb-internal-orders", type: "Azure Load Balancer", sub: "prod-core-kr", rg: "rg-network-kr", status: "정상 · 헬스 100%", tone: "live", icon: "/azure-icons/load-balancer.svg", note: "사설 서브넷 내부 트래픽 분산용 표준 로드 밸런서." },
      { id: "aoai-fdai-kr", name: "aoai-fdai-kr", type: "Azure OpenAI", sub: "prod-core-kr", rg: "rg-ai-platform", status: "정상 · T1/T2 모델", tone: "live", icon: "/azure-icons/azure-openai.svg", note: "잔여 모호성 T1/T2 추론 전용 Private Endpoint 모델 배포." },
      { id: "foundry-eval-kr", name: "foundry-eval-kr", type: "Azure AI Foundry", sub: "prod-core-kr", rg: "rg-ai-platform", status: "정상 · 평가 파이프라인", tone: "live", icon: "/azure-icons/ai-foundry.svg", note: "대화 품질 및 예측 보정 평가용 AI Foundry 프로젝트." },
      { id: "ca-orders-worker", name: "ca-orders-worker", type: "Azure Container Apps", sub: "prod-core-kr", rg: "rg-orders-prod", status: "정상 · 4 레플리카", tone: "live", icon: "/azure-icons/container-apps.svg", note: "비동기 주문 후처리 워커. sb-orders-events 큐 기반 오토스케일." },
      { id: "kr-batch-gpu01", name: "kr-batch-gpu01", type: "Azure Virtual Machine (GPU)", sub: "prod-data-platform", rg: "rg-ml-batch", status: "유휴 14일 · 비용 주의", tone: "sre", icon: "/azure-icons/virtual-machine.svg", note: "14일 이상 GPU 사용률 5% 미만. 월 $1,420 절감 권고 대상." },
      { id: "disk-orphan-east-09", name: "disk-orphan-east-09", type: "Managed Disk (Premium P30)", sub: "prod-data-platform", rg: "rg-ml-batch", status: "미연결 · 승인 대기", tone: "human", icon: "/azure-icons/disks.svg", note: "30일 이상 미연결 고아 디스크. 스냅샷 후 회수 승인 요청 연결." },
      { id: "nsg-prod-edge", name: "nsg-prod-edge", type: "Network Security Group", sub: "sec-shared-hub", rg: "rg-hub-network", status: "포트 변경 감지", tone: "sec", icon: "/azure-icons/network-security-group.svg", note: "기준선 외 포트 개방 변경이 감지되어 보안 담당자에게 알림 전송됨." },
      { id: "pg-analytics-dev-02", name: "pg-analytics-dev-02", type: "Azure PostgreSQL Flexible", sub: "prod-data-platform", rg: "rg-analytics-dev", status: "과프로비저닝 권고", tone: "sre", icon: "/azure-icons/postgresql.svg", note: "E8ds_v4 → D4ds_v4 축소 시 월 $940 절감 가능." },
      { id: "aks-batch-pool-03", name: "aks-batch-pool-03", type: "AKS Node Pool (VMSS)", sub: "prod-data-platform", rg: "rg-ml-batch", status: "사용률 14% · 권고", tone: "sre", icon: "/azure-icons/vm-scale-sets.svg", note: "야간 배치 외 저활용 노드 풀. 8→2 축소 권고." },
      { id: "kv-sec-shared", name: "kv-sec-shared", type: "Azure Key Vault", sub: "sec-shared-hub", rg: "rg-sec-vault", status: "정상 · RBAC 전용", tone: "live", icon: "/azure-icons/key-vault.svg", note: "중앙 인증서·HSM 키 관리용 공용 Key Vault." },
      { id: "redis-dev-cache-01", name: "redis-dev-cache-01", type: "Azure Cache for Redis", sub: "prod-data-platform", rg: "rg-analytics-dev", status: "검증 완료 · 절감", tone: "live", icon: "/azure-icons/cache-redis.svg", note: "Premium P2 → Standard C2 하향 조정 검증 완료." },
      { id: "vnet-hub-sec", name: "vnet-hub-sec", type: "Virtual Network", sub: "sec-shared-hub", rg: "rg-hub-network", status: "10.10.0.0/16 Hub", tone: "live", icon: "/azure-icons/virtual-network.svg", note: "중앙 보안 허브 VNet. 전 구독 피어링 및 방화벽 라우팅 관문." },
      { id: "law-sec-sentinel", name: "law-sec-sentinel", type: "Azure Monitor / Log Analytics", sub: "sec-shared-hub", rg: "rg-observability", status: "미관측 2건 분리", tone: "neutral", icon: "/azure-icons/monitor.svg", note: "보안 감사 전용 워크스페이스. 미수집 커넥터 2건은 0 대체 없이 분리 표기." }
    ];

    let liveInventory = null;
    let liveSourceLabel = "전체 인벤토리 (30개 대표 · Live 오프라인 프리뷰)";
    let activeIdx = -1;
    let currentItems = [];
    let fetchTimer = 0;

    function normalizeLiveRecords(payload) {
      const data = payload && (payload.data || payload);
      const arr = Array.isArray(data?.resources) ? data.resources
        : Array.isArray(data?.items) ? data.items
        : Array.isArray(data) ? data : [];
      return arr.map((r) => {
        const id = String(r.id || r.resource_id || r.name || "");
        const name = String(r.name || r.display_name || id.split("/").pop() || id);
        const type = String(r.resource_type || r.type || r.kind || "Azure Resource");
        const sub = String(r.subscription_name || r.subscription_id || r.subscription || "Azure");
        const rg = String(r.resource_group || r.rg || "");
        const st = String(r.operational_state || r.status || r.availability_state || "관측됨");
        const tone = /fail|err|crit|차단|이상|만료/i.test(st) ? "sec" : /warn|degrad|주의|예측|지연/i.test(st) ? "sre" : /unknown|unmeas|미관측/i.test(st) ? "neutral" : "live";
        return {
          id: id || name,
          gnodeId: nodes.find((n) => (n.getAttribute("data-gnode-name") || "").toLowerCase() === name.toLowerCase())?.getAttribute("data-gnode-id") || "",
          name,
          type,
          sub,
          rg,
          status: st,
          tone,
          icon: iconForType(type),
          note: r.summary || `${sub}${rg ? ` / ${rg}` : ""} 소속 ${type} 실측 온톨로지 인스턴스입니다.`
        };
      }).filter((x) => x.name);
    }

    async function queryLiveInventory(q) {
      if (IS_STATIC_MOCK) return;
      const isLive = window.fdaiV4Live && typeof window.fdaiV4Live.isLiveMode === "function" ? window.fdaiV4Live.isLiveMode() : true;
      if (!isLive) { liveInventory = null; liveSourceLabel = "전체 인벤토리 (Sample 모드)"; return; }
      const url = `/api/v4/governance/ontology/instances?limit=200${q ? `&search=${encodeURIComponent(q)}` : ""}`;
      try {
        const resp = await fetch(url, { headers: { Accept: "application/json" } });
        if (!resp.ok) return;
        const json = await resp.json();
        if (json && (json.measurement_state === "measured" || json.measurement_state === "partial")) {
          const parsed = normalizeLiveRecords(json);
          if (parsed.length) {
            liveInventory = parsed;
            liveSourceLabel = `Live 전체 인벤토리 (${parsed.length}건 응답)`;
            renderListbox(inp.value || "");
          }
        }
      } catch (_e) {}
    }

    function filterInventory(rawQ) {
      const q = (rawQ || "").trim().toLowerCase();
      const src = liveInventory && liveInventory.length ? liveInventory : FULL_INVENTORY_FALLBACK;
      if (!q) return src.slice(0, 24);
      return src.filter((item) =>
        [item.name, item.id, item.type, item.sub, item.rg, item.status].join(" ").toLowerCase().includes(q)
      ).slice(0, 30);
    }

    function closeListbox() {
      listbox.hidden = true;
      inp.setAttribute("aria-expanded", "false");
      activeIdx = -1;
    }

    function selectInventoryItem(item) {
      if (!item) return;
      inp.value = item.name;
      closeListbox();
      nodes.forEach((n) => n.classList.remove("is-search-match", "is-search-dim"));
      edges.forEach((e) => e.classList.remove("is-search-dim"));

      const matchNode = (item.gnodeId && pane.querySelector(`g.graph-node[data-gnode-id="${item.gnodeId}"]`))
        || nodes.find((n) => (n.getAttribute("data-gnode-name") || "").toLowerCase() === item.name.toLowerCase());

      const syncInspectorText = (nodeEl) => {
        if (!nodeEl) return;
        pane.querySelectorAll("g.graph-node").forEach((n) => n.classList.toggle("is-selected", n === nodeEl));
        const setT = (id, v) => { const e = document.getElementById(id); if (e && v) e.textContent = v; };
        setT("govGraphInspName", nodeEl.getAttribute("data-gnode-name"));
        setT("govGraphInspType", nodeEl.getAttribute("data-gnode-type"));
        setT("govGraphInspStatus", nodeEl.getAttribute("data-gnode-status"));
        setT("govGraphInspLineage", nodeEl.getAttribute("data-gnode-lineage"));
        setT("govGraphInspNote", nodeEl.getAttribute("data-gnode-note"));
      };

      if (matchNode) {
        matchNode.classList.add("is-search-match");
        syncInspectorText(matchNode);
        if (countEl) { countEl.hidden = false; countEl.textContent = `캔버스 포커스: ${item.name}`; }
        return;
      }

      // Off-canvas resource selected -> dynamically refocus center root & inspector without blocking canvas!
      if (centerNode) {
        centerNode.setAttribute("data-gnode-name", item.name);
        centerNode.setAttribute("data-gnode-type", `${item.type} (검색 중심)`);
        centerNode.setAttribute("data-gnode-status", item.status);
        centerNode.setAttribute("data-gnode-lineage", `${item.sub}${item.rg ? ` / ${item.rg}` : ""} → ${item.name}`);
        centerNode.setAttribute("data-gnode-note", item.note || `${item.type} 리소스 중심 탐색 뷰입니다.`);
        const img = centerNode.querySelector("image");
        if (img && item.icon) img.setAttribute("href", item.icon);
        const texts = centerNode.querySelectorAll("text");
        if (texts[0]) texts[0].textContent = item.name;
        if (texts[1]) texts[1].textContent = `${item.type} · ${item.sub}`;
        centerNode.classList.add("is-search-match");
        syncInspectorText(centerNode);
      }
      if (resetBtn) resetBtn.hidden = false;
      if (countEl) { countEl.hidden = false; countEl.textContent = `중심 전환: ${item.name}`; }

      // Trigger live explore query when connected
      if (!IS_STATIC_MOCK) {
        fetch(`/api/v4/governance/ontology/instances/explore?root=${encodeURIComponent(item.id)}&depth=8&limit=200&activity_limit=30`, { headers: { Accept: "application/json" } }).catch(() => {});
      }
    }

    function renderListbox(rawQ) {
      const src = liveInventory && liveInventory.length ? liveInventory : FULL_INVENTORY_FALLBACK;
      currentItems = filterInventory(rawQ);
      activeIdx = currentItems.length ? 0 : -1;
      const head = `<div class="cs-res-listbox-head"><span>${liveSourceLabel}</span><strong>${currentItems.length} / ${src.length}건</strong></div>`;
      if (!currentItems.length) {
        listbox.innerHTML = `${head}<div class="cs-res-empty">"${(rawQ || "").replace(/</g, "&lt;")}"에 일치하는 리소스가 없습니다.</div>`;
      } else {
        listbox.innerHTML = head + currentItems.map((it, i) => {
          const onCanvas = Boolean(it.gnodeId);
          const badge = onCanvas ? `<span class="cs-badge tone-live">현재 캔버스</span>` : `<span class="cs-badge tone-${it.tone || "neutral"}">${it.status}</span>`;
          return `<button type="button" class="cs-res-opt${i === activeIdx ? " is-active" : ""}" role="option" aria-selected="${i === activeIdx}" data-res-opt-idx="${i}">
            <img src="${it.icon}" alt="" aria-hidden="true">
            <span style="display:grid;min-width:0">
              <span class="cs-res-opt-name">${it.name.replace(/</g, "&lt;")}</span>
              <span class="cs-res-opt-meta">${it.type.replace(/</g, "&lt;")} · ${it.sub.replace(/</g, "&lt;")}${it.rg ? ` / ${it.rg.replace(/</g, "&lt;")}` : ""}</span>
            </span>
            ${badge}
          </button>`;
        }).join("");
      }
      listbox.hidden = false;
      inp.setAttribute("aria-expanded", "true");
    }

    listbox.addEventListener("mousedown", (e) => {
      if (!(e.target instanceof Element)) return;
      const opt = e.target.closest("[data-res-opt-idx]");
      if (!opt) return;
      e.preventDefault();
      const idx = parseInt(opt.getAttribute("data-res-opt-idx") || "-1", 10);
      if (idx >= 0 && currentItems[idx]) selectInventoryItem(currentItems[idx]);
    });

    inp.addEventListener("focus", () => {
      renderListbox(inp.value || "");
      queryLiveInventory(inp.value || "");
    });
    inp.addEventListener("input", () => {
      const q = (inp.value || "").trim();
      renderListbox(q);
      // Also live-highlight matching nodes already on canvas
      if (!q) {
        nodes.forEach((n) => n.classList.remove("is-search-match", "is-search-dim"));
        edges.forEach((e) => e.classList.remove("is-search-dim"));
        if (countEl) countEl.hidden = true;
      } else {
        const ql = q.toLowerCase();
        const mIds = new Set();
        nodes.forEach((n) => {
          const hit = [n.getAttribute("data-gnode-name"), n.getAttribute("data-gnode-type"), n.getAttribute("data-gnode-status"), n.textContent].join(" ").toLowerCase().includes(ql);
          n.classList.toggle("is-search-match", hit);
          n.classList.toggle("is-search-dim", !hit);
          if (hit && n.getAttribute("data-gnode-id")) mIds.add(n.getAttribute("data-gnode-id"));
        });
        edges.forEach((e) => {
          e.classList.toggle("is-search-dim", !(mIds.has(e.getAttribute("data-edge-src") || "") || mIds.has(e.getAttribute("data-edge-dst") || "")));
        });
      }
      if (fetchTimer) window.clearTimeout(fetchTimer);
      fetchTimer = window.setTimeout(() => queryLiveInventory(q), 160);
    });
    inp.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (listbox.hidden) renderListbox(inp.value || "");
        if (currentItems.length) {
          activeIdx = (activeIdx + 1) % currentItems.length;
          listbox.querySelectorAll(".cs-res-opt").forEach((o, i) => {
            o.classList.toggle("is-active", i === activeIdx);
            o.setAttribute("aria-selected", String(i === activeIdx));
          });
          listbox.querySelector(".cs-res-opt.is-active")?.scrollIntoView({ block: "nearest" });
        }
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        if (currentItems.length) {
          activeIdx = (activeIdx - 1 + currentItems.length) % currentItems.length;
          listbox.querySelectorAll(".cs-res-opt").forEach((o, i) => {
            o.classList.toggle("is-active", i === activeIdx);
            o.setAttribute("aria-selected", String(i === activeIdx));
          });
          listbox.querySelector(".cs-res-opt.is-active")?.scrollIntoView({ block: "nearest" });
        }
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (currentItems.length) selectInventoryItem(currentItems[Math.max(0, activeIdx)]);
      } else if (e.key === "Escape") {
        closeListbox();
      }
    });
    document.addEventListener("click", (e) => {
      if (e.target instanceof Element && !e.target.closest(".cs-res-combo")) closeListbox();
    });
    resetBtn?.addEventListener("click", () => {
      if (centerNode && origCenterSnapshot) {
        centerNode.setAttribute("data-gnode-name", origCenterSnapshot.name);
        centerNode.setAttribute("data-gnode-type", origCenterSnapshot.type);
        centerNode.setAttribute("data-gnode-status", origCenterSnapshot.status);
        centerNode.setAttribute("data-gnode-lineage", origCenterSnapshot.lineage);
        centerNode.setAttribute("data-gnode-note", origCenterSnapshot.note);
        const img = centerNode.querySelector("image");
        if (img) img.setAttribute("href", origCenterSnapshot.icon);
        const texts = centerNode.querySelectorAll("text");
        if (texts[0]) texts[0].textContent = origCenterSnapshot.t1;
        if (texts[1]) texts[1].textContent = origCenterSnapshot.t2;
        pane.querySelectorAll("g.graph-node").forEach((n) => n.classList.toggle("is-selected", n === centerNode));
      }
      inp.value = "";
      nodes.forEach((n) => n.classList.remove("is-search-match", "is-search-dim"));
      edges.forEach((e) => e.classList.remove("is-search-dim"));
      resetBtn.hidden = true;
      if (countEl) countEl.hidden = true;
    });
  }

  function initArchitectureResourceSearch() {
    const inp = document.getElementById("archResSearch");
    const listbox = document.getElementById("archResListbox");
    const countEl = document.getElementById("archResSearchCount");
    const pane = inp?.closest("[data-graph-view-pane='topo']");
    if (!inp || !listbox || !pane || inp.dataset.searchWired === "1") return;
    inp.dataset.searchWired = "1";

    const nodes = Array.from(pane.querySelectorAll("g.graph-node[data-gnode-name]"));
    const edges = Array.from(pane.querySelectorAll("g.svg-edge-group"));
    const items = nodes.map((n) => ({
      node: n,
      id: n.getAttribute("data-gnode-id") || "",
      name: n.getAttribute("data-gnode-name") || "",
      type: n.getAttribute("data-gnode-type") || "",
      status: n.getAttribute("data-gnode-status") || "",
      lineage: n.getAttribute("data-gnode-lineage") || "",
      icon: n.querySelector("image")?.getAttribute("href") || "/azure-icons/monitor.svg",
      tone: /만료|차단|이상/.test(n.getAttribute("data-gnode-status") || "") ? "sec" : /예측|주의|92%/.test(n.getAttribute("data-gnode-status") || "") ? "sre" : "live"
    }));
    let filtered = items;
    let activeIdx = -1;

    const close = () => { listbox.hidden = true; inp.setAttribute("aria-expanded", "false"); activeIdx = -1; };
    const selectItem = (it) => {
      if (!it) return;
      inp.value = it.name;
      close();
      nodes.forEach((n) => {
        n.classList.remove("is-search-dim");
        n.classList.toggle("is-search-match", n === it.node);
        n.classList.toggle("is-selected", n === it.node);
      });
      edges.forEach((e) => {
        const conn = e.getAttribute("data-edge-src") === it.id || e.getAttribute("data-edge-dst") === it.id;
        e.classList.toggle("is-search-dim", !conn);
        e.classList.toggle("is-connected", conn);
      });
      if (countEl) { countEl.hidden = false; countEl.textContent = `포커스: ${it.name}`; }
    };
    const render = (rawQ) => {
      const q = (rawQ || "").trim().toLowerCase();
      filtered = !q ? items : items.filter((it) => [it.name, it.type, it.status, it.lineage, it.node.textContent].join(" ").toLowerCase().includes(q));
      activeIdx = filtered.length ? 0 : -1;
      const head = `<div class="cs-res-listbox-head"><span>구성도 리소스 · 서브넷 전체</span><strong>${filtered.length} / ${items.length}건</strong></div>`;
      listbox.innerHTML = filtered.length ? head + filtered.map((it, i) => `
        <button type="button" class="cs-res-opt${i === activeIdx ? " is-active" : ""}" role="option" aria-selected="${i === activeIdx}" data-arch-opt="${i}">
          <img src="${it.icon}" alt="" aria-hidden="true">
          <span style="display:grid;min-width:0">
            <span class="cs-res-opt-name">${it.name.replace(/</g, "&lt;")}</span>
            <span class="cs-res-opt-meta">${it.type.replace(/</g, "&lt;")} · ${it.lineage.replace(/</g, "&lt;")}</span>
          </span>
          <span class="cs-badge tone-${it.tone}">${it.status.replace(/</g, "&lt;")}</span>
        </button>`).join("") : `${head}<div class="cs-res-empty">일치하는 구성도 리소스가 없습니다.</div>`;
      listbox.hidden = false;
      inp.setAttribute("aria-expanded", "true");
    };

    listbox.addEventListener("mousedown", (e) => {
      if (!(e.target instanceof Element)) return;
      const btn = e.target.closest("[data-arch-opt]");
      if (!btn) return;
      e.preventDefault();
      const idx = parseInt(btn.getAttribute("data-arch-opt") || "-1", 10);
      if (idx >= 0 && filtered[idx]) selectItem(filtered[idx]);
    });
    inp.addEventListener("focus", () => render(inp.value || ""));
    inp.addEventListener("input", () => {
      const q = (inp.value || "").trim().toLowerCase();
      render(q);
      if (!q) {
        nodes.forEach((n) => n.classList.remove("is-search-match", "is-search-dim"));
        edges.forEach((e) => e.classList.remove("is-search-dim"));
        if (countEl) countEl.hidden = true;
      } else {
        const hitIds = new Set(filtered.map((f) => f.id));
        nodes.forEach((n) => {
          const hit = hitIds.has(n.getAttribute("data-gnode-id") || "");
          n.classList.toggle("is-search-match", hit);
          n.classList.toggle("is-search-dim", !hit);
        });
        edges.forEach((e) => e.classList.toggle("is-search-dim", !(hitIds.has(e.getAttribute("data-edge-src") || "") || hitIds.has(e.getAttribute("data-edge-dst") || ""))));
      }
    });
    inp.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" && filtered.length) {
        e.preventDefault();
        activeIdx = (activeIdx + 1) % filtered.length;
        listbox.querySelectorAll(".cs-res-opt").forEach((o, i) => o.classList.toggle("is-active", i === activeIdx));
      } else if (e.key === "ArrowUp" && filtered.length) {
        e.preventDefault();
        activeIdx = (activeIdx - 1 + filtered.length) % filtered.length;
        listbox.querySelectorAll(".cs-res-opt").forEach((o, i) => o.classList.toggle("is-active", i === activeIdx));
      } else if (e.key === "Enter" && filtered.length) {
        e.preventDefault();
        selectItem(filtered[Math.max(0, activeIdx)]);
      } else if (e.key === "Escape") {
        close();
      }
    });
    document.addEventListener("click", (e) => {
      if (e.target instanceof Element && !e.target.closest("#archResSearch, #archResListbox")) close();
    });
  }

  /* ==========================================================================
     End-to-End Forensic Data Lineage Workbench (Palantir Foundry+ Grade)
     5-Stage Source -> Snapshot -> FDAI Pipeline -> Ontology Instance -> Audit/Events
     ========================================================================== */
  function initForensicDataLineage() {
    const searchInp = document.getElementById("linResSearch");
    const typeSel = document.getElementById("linTypeFilter");
    const statusSel = document.getElementById("linStatusFilter");
    const listEl = document.getElementById("linInstanceList");
    const svg = document.getElementById("linStageSvg");
    const inspBody = document.getElementById("linInspBody");
    if (!searchInp || !listEl || !svg || !inspBody || searchInp.dataset.linWired === "1") return;
    searchInp.dataset.linWired = "1";

    const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[m]));

    const LINEAGE_INSTANCES = [
      {
        id: "prod-aks-02", name: "prod-aks-02", typeKey: "kubernetes-cluster", typeLabel: "Resource / kubernetes-cluster",
        sub: "prod-core-kr", rg: "rg-orders-prod", state: "stopped", rev: "rev #19", tone: "sec", statusBucket: "alert", hasMissing: true,
        icon: "/azure-icons/kubernetes-services.svg",
        propsKeywords: "powerState operational_state availability managedClusters/stop cpu_utilization",
        summary: "14:02:11 Activity Log의 managedClusters/stop 호출과 14:02:19 Resource Graph powerState=Stopped를 Huginn·Heimdall이 교차 검증하여 rev #19(stopped)로 갱신했습니다.",
        sources: [
          { id: "src-arg", title: "Azure Resource Graph", sub: "클라우드 인벤토리", icon: "/azure-icons/subscriptions.svg", snap: "powerState=Stopped", snapSub: "14:02:19 · g42", fresh: "fresh", owner: "Huginn", edge: "수집 8s" },
          { id: "src-act", title: "Azure Activity Log", sub: "제어 평면 감사", icon: "/azure-icons/monitor.svg", snap: "managedClusters/stop", snapSub: "14:02:11 · a904", fresh: "fresh", owner: "Huginn", edge: "원천 발생" },
          { id: "src-k8s", title: "Kubernetes API", sub: "AKS Observer", icon: "/azure-icons/kubernetes-services.svg", snap: "노드 18/18 미응답", snapSub: "14:02:22 · s19", fresh: "warn", owner: "Heimdall", edge: "교차 확인" },
          { id: "src-law", title: "Log Analytics", sub: "컨테이너 로그", icon: "/azure-icons/monitor.svg", snap: "로그 윈도우 미수집", snapSub: "Unavailable (0 대체 금지)", fresh: "missing", owner: "Heimdall", edge: "결손 분리", missing: true }
        ],
        pipes: [
          { id: "p-huginn", title: "Huginn 정규화", sub: "ARM ID · UID 결합 (#h412)", icon: "/agent-icons/huginn.svg", owner: "Huginn", fresh: "fresh", ts: "14:02:21" },
          { id: "p-heimdall", title: "Heimdall 자격 검증", sub: "Stop 교차 일치 · 결손 분리", icon: "/agent-icons/heimdall.svg", owner: "Heimdall", fresh: "warn", ts: "14:02:24" },
          { id: "p-muninn", title: "Muninn 온톨로지 갱신", sub: "Resource@1.0 rev #18→#19", icon: "/agent-icons/muninn.svg", owner: "Muninn", fresh: "fresh", ts: "14:02:25" }
        ],
        downstream: [
          { id: "d-rule", title: "AKS 클러스터 중지 감지", sub: "Rule · 감시 전용 · 발동", icon: "/agent-icons/mimir.svg", owner: "Mimir", tone: "sec", ts: "14:02:26" },
          { id: "d-alert", title: "Teams · Pager 핵심 알림", sub: "운영자 확인 완료 (2분)", icon: "/agent-icons/forseti.svg", owner: "Forseti", tone: "sre", ts: "14:02:27" },
          { id: "d-saga", title: "Saga 감사 원장 #86712", sub: "sha256:9f4a...c10e 봉인", icon: "/agent-icons/saga.svg", owner: "Saga", tone: "live", ts: "14:02:28" }
        ],
        diffs: [
          { raw: 'properties.powerState.code = "Stopped"', canon: 'recorded_state.operational = "stopped"', rule: "normalize_arm_aks_power_state@1.4" },
          { raw: 'k8s.apiserver.ready_nodes = 0 / 18', canon: 'recorded_state.availability = "unavailable"', rule: "qualify_k8s_cross_check@1.2" },
          { raw: 'log_analytics.window = null (timeout)', canon: 'evidence_gaps = ["log_window_unavailable"]', rule: "preserve_missing_no_zero@1.0" }
        ],
        code: `// Huginn -> Heimdall -> Muninn 정제 변환 규칙 (Pure-Rust)
fn project_aks_state(arg: &ArmSnapshot, act: &ActivityEvent) -> RecordedState {
  let op = match arg.power_state_code.as_str() {
    "Stopped" | "Deallocated" => OperationalState::Stopped,
    _ => OperationalState::Running,
  };
  RecordedState { operational: op, revision: 19, source_event: act.operation_id }
}`,
        history: [
          { ts: "14:02:11", stage: "① 원천 발생", actor: "Azure Activity Log", desc: "Microsoft.ContainerService/managedClusters/stop/action (호출 주체: ops-maint-sp)" },
          { ts: "14:02:19", stage: "② 원천 수집", actor: "Resource Graph (Huginn)", desc: "ARM 인벤토리 스냅샷 g42에서 powerState.code=\"Stopped\" 포착 (수집 지연 8초)" },
          { ts: "14:02:21", stage: "③ 정규화", actor: "Huginn (#h412)", desc: "ARM Resource ID와 AKS 클러스터 UID 결합 → Resource@1.0.0 표준 스키마 변환" },
          { ts: "14:02:24", stage: "③ 교차 검증", actor: "Heimdall (#e09)", desc: "K8s API 미응답과 ARM Stopped 일치 검증 · Log Analytics 미수집 공백은 0 대체 없이 보존" },
          { ts: "14:02:25", stage: "④ 온톨로지 갱신", actor: "Muninn", desc: "prod-aks-02 인스턴스 rev #18(running) → rev #19(stopped) 원자적 커밋 완료" }
        ],
        events: [
          { ts: "14:02:11", kind: "Activity Log", tone: "sec", title: "managedClusters/stop 실행", meta: "caller=ops-maint-sp · sub=prod-core-kr · status=Succeeded" },
          { ts: "14:02:26", kind: "규칙 탐지", tone: "sec", title: "AKS 클러스터 중지 감지 발동", meta: "rule.aks.cluster_stopped · 조치 권한: 감시 전용" },
          { ts: "14:02:27", kind: "핵심 알림", tone: "sre", title: "Teams · Pager 운영자 에스컬레이션", meta: "2분 내 확인 완료 · 영향 서비스 orders-api/billing-api" }
        ],
        audits: [
          { id: "#86712", ts: "14:02:28", hash: "sha256:9f4a...c10e", title: "온톨로지 상태 전이 봉인 (running → stopped)", detail: "원천 3건 일치 + 미수집 1건 명시 · 조회 전용(변경 실행 없음)" },
          { id: "#86641", ts: "19:36:14", hash: "sha256:3b18...77d2", title: "이전 정상 상태 rev #18 스냅샷 기록", detail: "CPU 포화 예측 +5m · HIL-8841 승인 대기 연계" }
        ]
      },
      {
        id: "nsg-prod-edge", name: "nsg-prod-edge", typeKey: "network-security-group", typeLabel: "Resource / network-security-group",
        sub: "sec-shared-hub", rg: "rg-hub-network", state: "포트 변경 감지", rev: "rev #42", tone: "sec", statusBucket: "alert", hasMissing: false,
        icon: "/azure-icons/network-security-group.svg",
        propsKeywords: "nsg securityRules inboundRules port 22 ssh open_port_drift firewall",
        summary: "18:44:05 Activity Log에서 TCP 22 인바운드 규칙 추가가 포착되어 Huginn·Heimdall·Mimir 정제를 거쳐 방화벽 개방 포트 변경 감지 알림과 감사 원장 #86694에 기록되었습니다.",
        sources: [
          { id: "src-arg", title: "Azure Resource Graph", sub: "NSG 규칙 구성", icon: "/azure-icons/network-security-group.svg", snap: "securityRules[14]: Allow-SSH", snapSub: "18:44:12 · g51", fresh: "fresh", owner: "Huginn", edge: "규칙 수집" },
          { id: "src-act", title: "Azure Activity Log", sub: "NSG 변경 이벤트", icon: "/azure-icons/monitor.svg", snap: "securityRules/write (22)", snapSub: "18:44:05 · a918", fresh: "fresh", owner: "Huginn", edge: "변경 포착" },
          { id: "src-cat", title: "운영 규칙 카탈로그", sub: "MCSB-NS-01 기준선", icon: "/agent-icons/mimir.svg", snap: "DenyPublicSSH@v7", snapSub: "버전 고정", fresh: "fresh", owner: "Mimir", edge: "기준 대조" }
        ],
        pipes: [
          { id: "p-huginn", title: "Huginn 정규화", sub: "NSG 5-Tuple 규칙 파싱", icon: "/agent-icons/huginn.svg", owner: "Huginn", fresh: "fresh", ts: "18:44:14" },
          { id: "p-heimdall", title: "Heimdall 기준선 대조", sub: "기준선 외 포트 22 드리프트", icon: "/agent-icons/heimdall.svg", owner: "Heimdall", fresh: "warn", ts: "18:44:16" },
          { id: "p-muninn", title: "Muninn 온톨로지 갱신", sub: "Resource@1.0 rev #41→#42", icon: "/agent-icons/muninn.svg", owner: "Muninn", fresh: "fresh", ts: "18:44:17" }
        ],
        downstream: [
          { id: "d-rule", title: "방화벽 개방 포트 변경 감지", sub: "Rule · 감시 전용 · 보안", icon: "/agent-icons/mimir.svg", owner: "Mimir", tone: "sec", ts: "18:44:18" },
          { id: "d-alert", title: "Slack 보안 담당자 알림", sub: "변경 이력 첨부 전송됨", icon: "/agent-icons/forseti.svg", owner: "Forseti", tone: "sre", ts: "18:44:19" },
          { id: "d-saga", title: "Saga 감사 원장 #86694", sub: "sha256:7d12...e409 봉인", icon: "/agent-icons/saga.svg", owner: "Saga", tone: "live", ts: "18:44:20" }
        ],
        diffs: [
          { raw: 'securityRules[14].destinationPortRange = "22"', canon: 'exposure.public_mgmt_ports = [22]', rule: "normalize_nsg_inbound_rules@1.3" },
          { raw: 'sourceAddressPrefix = "*" (Any)', canon: 'recorded_state.configuration = "drifted"', rule: "check_mcsb_ns_01@2.1" }
        ],
        code: `// Huginn NSG 규칙 정규화 + MCSB-NS-01 드리프트 판정
fn evaluate_nsg_rule(rule: &NsgRule) -> ConfigDrift {
  if rule.access == "Allow" && rule.src == "*" && matches!(rule.dst_port, 22 | 3389) {
    return ConfigDrift::PublicManagementPortExposed;
  }
  ConfigDrift::Compliant
}`,
        history: [
          { ts: "18:44:05", stage: "① 원천 발생", actor: "Azure Activity Log", desc: "networkSecurityGroups/securityRules/write (TCP 22 Allow 규칙 추가)" },
          { ts: "18:44:12", stage: "② 원천 수집", actor: "Resource Graph", desc: "nsg-prod-edge 전체 15개 보안 규칙 스냅샷 g51 수집" },
          { ts: "18:44:14", stage: "③ 정규화", actor: "Huginn", desc: "NSG 5-Tuple 및 연결 서브넷(snet-hub-edge) 관계 매핑" },
          { ts: "18:44:17", stage: "④ 온톨로지 갱신", actor: "Muninn", desc: "nsg-prod-edge rev #42 반영 (configuration: drifted)" }
        ],
        events: [
          { ts: "18:44:05", kind: "Activity Log", tone: "sec", title: "Allow-Temp-SSH (TCP 22) 규칙 생성", meta: "actor=net-temp-admin · rg=rg-hub-network" },
          { ts: "18:44:18", kind: "규칙 탐지", tone: "sec", title: "방화벽 개방 포트 변경 감지 발동", meta: "rule.nsg.open_port_drift · MCSB-NS-01 위반" },
          { ts: "18:44:19", kind: "핵심 알림", tone: "sre", title: "Slack #sec-ops 핵심 알림 전송", meta: "담당자 확인 중 · 회수 초안 준비됨" }
        ],
        audits: [
          { id: "#86694", ts: "18:44:20", hash: "sha256:7d12...e409", title: "NSG 기준선 이탈 탐지 · 알림 감사 봉인", detail: "Activity Log a918 + ARM 스냅샷 g51 연결" },
          { id: "#86510", ts: "09:00:02", hash: "sha256:1c88...04ab", title: "일일 기준선 일치 확인 (rev #41)", detail: "개방 관리 포트 0건 정상 검증" }
        ]
      },
      {
        id: "nsg-aks-nodes", name: "nsg-aks-nodes", typeKey: "network-security-group", typeLabel: "Resource / network-security-group",
        sub: "prod-core-kr", rg: "rg-orders-prod", state: "정상 · DenyPublic", rev: "rev #17", tone: "live", statusBucket: "healthy", hasMissing: false,
        icon: "/azure-icons/network-security-group.svg",
        propsKeywords: "nsg aks subnet DenyPublic inboundRules",
        summary: "AKS 노드 풀 서브넷에 바인딩된 NSG로 공용 인바운드 0건·기준선 일치 상태가 rev #17로 검증 유지 중입니다."
      },
      {
        id: "nsg-ingress", name: "nsg-ingress", typeKey: "network-security-group", typeLabel: "Resource / network-security-group",
        sub: "prod-core-kr", rg: "rg-edge-kr", state: "정상 · 443 Only", rev: "rev #12", tone: "live", statusBucket: "healthy", hasMissing: false,
        icon: "/azure-icons/network-security-group.svg",
        propsKeywords: "nsg ingress 443 https waf",
        summary: "App Gateway 진입 서브넷 전용 NSG로 443/HTTPS 외 모든 인바운드 차단 기준선을 유지하고 있습니다."
      },
      {
        id: "nsg-pe-data", name: "nsg-pe-data", typeKey: "network-security-group", typeLabel: "Resource / network-security-group",
        sub: "prod-data-platform", rg: "rg-catalog-data", state: "정상 · Private Link", rev: "rev #9", tone: "live", statusBucket: "healthy", hasMissing: false,
        icon: "/azure-icons/network-security-group.svg",
        propsKeywords: "nsg private endpoint data subnet",
        summary: "데이터 플랫폼 Private Endpoint 전용 NSG로 내부 VNet 대역(10.24.0.0/16)만 허용합니다."
      },
      {
        id: "pg-orders-kr", name: "pg-orders-kr", typeKey: "postgresql-flexible", typeLabel: "Resource / postgresql-flexible",
        sub: "prod-core-kr", rg: "rg-orders-prod", state: "연결 풀 92% 주의", rev: "rev #31", tone: "sre", statusBucket: "alert", hasMissing: false,
        icon: "/azure-icons/postgresql.svg",
        propsKeywords: "postgresql pool_pct active_connections hil-8841",
        summary: "Azure Monitor 메트릭(active_connections=138/150)과 Resource Graph 구성을 결합해 연결 풀 포화(92%) 상태를 rev #31로 갱신하고 승인 요청 HIL-8841을 연결했습니다."
      },
      {
        id: "kv-prod-kr", name: "kv-prod-kr", typeKey: "key-vault", typeLabel: "Resource / key-vault",
        sub: "sec-shared-hub", rg: "rg-sec-vault", state: "임시 예외 2건 만료", rev: "rev #26", tone: "sec", statusBucket: "alert", hasMissing: false,
        icon: "/azure-icons/key-vault.svg",
        propsKeywords: "key vault firewall ipRules expiry secret",
        summary: "Key Vault 방화벽 임시 IP 예외 2건의 만료 시각 초과를 정제·탐지해 보안 알림과 회수 승인 요청(HIL-8839)으로 연결했습니다."
      },
      {
        id: "kr-central-redis", name: "kr-central-redis", typeKey: "cache-redis", typeLabel: "Resource / cache-redis",
        sub: "prod-core-kr", rg: "rg-orders-prod", state: "자동 회복 · 정상", rev: "rev #14", tone: "live", statusBucket: "healthy", hasMissing: false,
        icon: "/azure-icons/cache-redis.svg",
        propsKeywords: "redis latency hit_rate auto_recovery",
        summary: "일시적 응답 지연(142ms) 후 자동 회복이 독립 관측으로 검증되어 정상 상태로 갱신되었습니다."
      },
      {
        id: "azfw-hub-kr", name: "azfw-hub-kr", typeKey: "firewall", typeLabel: "Resource / firewall",
        sub: "sec-shared-hub", rg: "rg-hub-network", state: "정상 · IDPS 활성", rev: "rev #22", tone: "live", statusBucket: "healthy", hasMissing: false,
        icon: "/azure-icons/firewall.svg",
        propsKeywords: "firewall idps egress peering hub",
        summary: "중앙 허브 방화벽의 IDPS 정책 48개 및 Egress 로그 수집 파이프라인이 정상 동기화 중입니다."
      },
      {
        id: "aks-batch-pool-03", name: "aks-batch-pool-03", typeKey: "kubernetes-cluster", typeLabel: "Resource / kubernetes-cluster",
        sub: "prod-data-platform", rg: "rg-ml-batch", state: "저활용 14% · 권고", rev: "rev #11", tone: "sre", statusBucket: "alert", hasMissing: false,
        icon: "/azure-icons/kubernetes-services.svg",
        propsKeywords: "aks batch idle finops cpu",
        summary: "14일 평균 CPU 사용률 14% 측정 근거로 유휴 축소 권고 후보로 분류되었습니다."
      },
      {
        id: "pg-analytics-dev-02", name: "pg-analytics-dev-02", typeKey: "postgresql-flexible", typeLabel: "Resource / postgresql-flexible",
        sub: "prod-data-platform", rg: "rg-analytics-dev", state: "정상 · 과프로비저닝", rev: "rev #8", tone: "live", statusBucket: "healthy", hasMissing: false,
        icon: "/azure-icons/postgresql.svg",
        propsKeywords: "postgresql sku finops",
        summary: "E8ds_v4 대비 평균 사용률 18%로 관측되어 우측 사이징 후보로 연결되었습니다."
      },
      {
        id: "kv-sec-shared", name: "kv-sec-shared", typeKey: "key-vault", typeLabel: "Resource / key-vault",
        sub: "sec-shared-hub", rg: "rg-sec-vault", state: "정상 · RBAC 전용", rev: "rev #15", tone: "live", statusBucket: "healthy", hasMissing: false,
        icon: "/azure-icons/key-vault.svg",
        propsKeywords: "key vault rbac hsm cert",
        summary: "중앙 인증서·HSM 키 관리 Key Vault. 공용 접근 차단 및 RBAC 전용 경계 유지 중."
      },
      {
        id: "cosmos-catalog-kr", name: "cosmos-catalog-kr", typeKey: "data-storage", typeLabel: "Resource / cosmos-db",
        sub: "prod-data-platform", rg: "rg-catalog-data", state: "정상 · RU 42%", rev: "rev #19", tone: "live", statusBucket: "healthy", hasMissing: false,
        icon: "/azure-icons/cosmos-db.svg",
        propsKeywords: "cosmos db ru partition catalog",
        summary: "상품 카탈로그 Cosmos DB의 RU 사용률 및 다중 리전 복제 지연이 정상 범위로 수집되고 있습니다."
      },
      {
        id: "st-orders-archive", name: "st-orders-archive", typeKey: "data-storage", typeLabel: "Resource / storage-account",
        sub: "prod-data-platform", rg: "rg-audit-archive", state: "비용 원천 미수집", rev: "rev #7", tone: "neutral", statusBucket: "missing", hasMissing: true,
        icon: "/azure-icons/storage-account.svg",
        propsKeywords: "storage worm archive focus cost missing",
        summary: "불변 WORM 스토리지 구성은 정상이나 FOCUS 원가 내보내기가 미연결되어 비용 속성은 0 대체 없이 미수집으로 분리되었습니다."
      }
    ];

    function buildDefaultProfile(inst) {
      if (inst.sources && inst.pipes && inst.downstream) return inst;
      const isAlert = inst.tone === "sec" || inst.tone === "sre";
      const isMiss = Boolean(inst.hasMissing);
      return Object.assign({}, inst, {
        sources: [
          { id: "src-arg", title: "Azure Resource Graph", sub: "구성 인벤토리", icon: inst.icon, snap: `${inst.name} 구성 스냅샷`, snapSub: `19:40:12 · ${inst.rev}`, fresh: "fresh", owner: "Huginn", edge: "인벤토리 수집" },
          { id: "src-mon", title: "Azure Monitor", sub: "상태 · 메트릭", icon: "/azure-icons/monitor.svg", snap: inst.state, snapSub: "19:40:30 · 지연 18s", fresh: isAlert ? "warn" : "fresh", owner: "Heimdall", edge: "관측 수집" },
          isMiss
            ? { id: "src-cost", title: "FOCUS Cost Export", sub: "원가 귀속 (미연결)", icon: "/azure-icons/storage-account.svg", snap: "원가 데이터 미수집", snapSub: "Unavailable (0 대체 금지)", fresh: "missing", owner: "Njord", edge: "결손 분리", missing: true }
            : { id: "src-act", title: "Azure Activity Log", sub: "변경 이력 스트림", icon: "/azure-icons/monitor.svg", snap: "최근 변경 검증됨", snapSub: "19:38:04 · 정상", fresh: "fresh", owner: "Huginn", edge: "변경 추적" }
        ],
        pipes: [
          { id: "p-huginn", title: "Huginn 정규화", sub: "ARM ID · 속성 스키마 변환", icon: "/agent-icons/huginn.svg", owner: "Huginn", fresh: "fresh", ts: "19:40:32" },
          { id: "p-heimdall", title: "Heimdall 신선도 검증", sub: isMiss ? "결손 분리 · 가용 증적 통과" : "신선도 18s · 완전성 통과", icon: "/agent-icons/heimdall.svg", owner: "Heimdall", fresh: isMiss || isAlert ? "warn" : "fresh", ts: "19:40:34" },
          { id: "p-muninn", title: "Muninn 온톨로지 갱신", sub: `${inst.typeLabel.split("/")[0].trim()}@1.0 ${inst.rev}`, icon: "/agent-icons/muninn.svg", owner: "Muninn", fresh: "fresh", ts: "19:40:35" }
        ],
        downstream: [
          { id: "d-rule", title: isAlert ? "관련 운영 규칙 발동" : "기준선 정상 검증", sub: isAlert ? "감시/승인 정책 대조" : "위반 0건 유지", icon: "/agent-icons/mimir.svg", owner: "Mimir", tone: inst.tone, ts: "19:40:36" },
          { id: "d-saga", title: `Saga 감사 원장 (${inst.rev})`, sub: "sha256 해시 체인 봉인", icon: "/agent-icons/saga.svg", owner: "Saga", tone: "live", ts: "19:40:37" }
        ],
        diffs: [
          { raw: `arm.id = "/subscriptions/${inst.sub}/.../providers/${inst.typeKey}/${inst.name}"`, canon: `ontology.resource_id = "${inst.id}"`, rule: "canonical_arm_identity@1.0" },
          { raw: `observed.status = "${inst.state}"`, canon: `recorded_state.summary = "${inst.state}"`, rule: "project_recorded_state@1.2" }
        ],
        code: `// ${inst.name} (${inst.typeLabel}) 정제 투영 파이프라인
fn project_instance(raw: &ArmSnapshot) -> OntologyInstance {
  OntologyInstance::from_arm(raw)
    .with_revision("${inst.rev}")
    .preserve_missing_without_zero()
}`,
        history: [
          { ts: "19:40:12", stage: "② 원천 수집", actor: "Resource Graph", desc: `${inst.name} 최신 구성 스냅샷 수집 (${inst.sub}/${inst.rg})` },
          { ts: "19:40:32", stage: "③ 정규화", actor: "Huginn", desc: `${inst.typeLabel} 표준 속성 스키마 정규화 완료` },
          { ts: "19:40:35", stage: "④ 온톨로지 갱신", actor: "Muninn", desc: `${inst.rev} 커밋 (${inst.state})` }
        ],
        events: [
          { ts: "19:40:30", kind: "관측 수집", tone: inst.tone, title: `${inst.name} 상태 갱신 (${inst.state})`, meta: `${inst.sub} · ${inst.rg}` },
          { ts: "19:40:36", kind: "규칙 평가", tone: isAlert ? "sre" : "live", title: isAlert ? "주의/보안 규칙 매칭 · 핵심 알림 연계" : "기준선 정책 위반 0건 확인", meta: "조회 전용 · 안전 경계 준수" }
        ],
        audits: [
          { id: "#86680", ts: "19:40:37", hash: "sha256:5e21...9a4c", title: `${inst.name} ${inst.rev} 계통 스냅샷 봉인`, detail: `출처: Resource Graph + Azure Monitor · 정책 위반 0건` }
        ]
      });
    }

    function buildFleetInventory(targetTotal) {
      const fleet = LINEAGE_INSTANCES.map((it) => Object.assign({}, it));
      const blueprints = [
        { typeKey: "kubernetes-cluster", typeLabel: "Resource / kubernetes-cluster", prefix: "aks-prod-kr", target: 24, icon: "/azure-icons/kubernetes-services.svg", subs: ["prod-core-kr", "prod-data-platform"], rgs: ["rg-orders-prod", "rg-ml-batch"], kw: "aks kubernetes cluster node pod cpu" },
        { typeKey: "network-security-group", typeLabel: "Resource / network-security-group", prefix: "nsg-prod-kr", target: 318, icon: "/azure-icons/network-security-group.svg", subs: ["prod-core-kr", "sec-shared-hub", "prod-data-platform"], rgs: ["rg-network-kr", "rg-hub-network", "rg-edge-kr"], kw: "nsg security group firewall inboundRules subnet" },
        { typeKey: "postgresql-flexible", typeLabel: "Resource / postgresql-flexible", prefix: "pg-svc-kr", target: 86, icon: "/azure-icons/postgresql.svg", subs: ["prod-core-kr", "prod-data-platform"], rgs: ["rg-orders-prod", "rg-analytics-dev"], kw: "postgresql database pool_pct sql" },
        { typeKey: "key-vault", typeLabel: "Resource / key-vault", prefix: "kv-svc-kr", target: 142, icon: "/azure-icons/key-vault.svg", subs: ["sec-shared-hub", "prod-core-kr"], rgs: ["rg-sec-vault", "rg-platform-shared"], kw: "key vault secret cert rbac" },
        { typeKey: "cache-redis", typeLabel: "Resource / cache-redis", prefix: "redis-svc-kr", target: 94, icon: "/azure-icons/cache-redis.svg", subs: ["prod-core-kr", "prod-data-platform"], rgs: ["rg-orders-prod", "rg-catalog-data"], kw: "redis cache latency hit_rate" },
        { typeKey: "firewall", typeLabel: "Resource / firewall", prefix: "azfw-edge-kr", target: 28, icon: "/azure-icons/firewall.svg", subs: ["sec-shared-hub"], rgs: ["rg-hub-network"], kw: "firewall idps egress peering" },
        { typeKey: "data-storage", typeLabel: "Resource / storage-cosmos-data", prefix: "st-data-kr", target: targetTotal - (24 + 318 + 86 + 142 + 94 + 28), icon: "/azure-icons/storage-account.svg", subs: ["prod-data-platform", "prod-core-kr", "sec-shared-hub"], rgs: ["rg-audit-archive", "rg-catalog-data", "rg-ml-batch"], kw: "storage cosmos disk blob worm focus" }
      ];
      const counts = {};
      fleet.forEach((it) => { counts[it.typeKey] = (counts[it.typeKey] || 0) + 1; });
      blueprints.forEach((bp) => {
        const have = counts[bp.typeKey] || 0;
        const need = Math.max(0, bp.target - have);
        for (let i = 1; i <= need; i++) {
          const num = String(i).padStart(4, "0");
          const isMissing = (i % 157 === 0);
          const isWarn = !isMissing && (i % 73 === 0);
          const sub = bp.subs[i % bp.subs.length];
          const rg = bp.rgs[i % bp.rgs.length];
          fleet.push({
            id: `${bp.prefix}-${num}`,
            name: `${bp.prefix}-${num}`,
            typeKey: bp.typeKey,
            typeLabel: bp.typeLabel,
            sub,
            rg,
            state: isMissing ? "원천 미수집" : isWarn ? "주의 · 지연 감지" : "정상 관측",
            rev: `rev #${(i % 24) + 3}`,
            tone: isMissing ? "neutral" : isWarn ? "sre" : "live",
            statusBucket: isMissing ? "missing" : isWarn ? "alert" : "healthy",
            hasMissing: isMissing,
            icon: bp.icon,
            propsKeywords: bp.kw,
            summary: `${sub}/${rg} 소속 ${bp.typeLabel} 온톨로지 인스턴스입니다. Resource Graph와 Azure Monitor 원천이 Huginn·Heimdall 파이프라인으로 정제되었습니다.`
          });
        }
      });
      // Pre-compute flat search string once for <2ms filtering across 2,213+ resources
      fleet.forEach((it) => {
        it._hay = [it.name, it.id, it.typeKey, it.typeLabel, it.sub, it.rg, it.state, it.propsKeywords || ""].join(" ").toLowerCase();
      });
      return fleet;
    }

    let activeId = "__all__";
    let activeTab = "transform";
    let activeScope = "all";
    let colorMode = "default";
    let showAncestors = true;
    let showDescendants = true;
    let selectedStageNode = null;
    let allInstances = buildFleetInventory(2213);
    let virtualRows = [];
    const ROW_H = 44;
    const OVERSCAN = 8;

    try {
      const sp = new URLSearchParams(location.search);
      const tParam = sp.get("lineage_target");
      if (tParam && (tParam === "__all__" || allInstances.some((x) => x.id === tParam))) activeId = tParam;
    } catch (_e) {}

    function buildFleetOverviewProfile() {
      const counts = { "kubernetes-cluster": 0, "network-security-group": 0, "postgresql-flexible": 0, "key-vault": 0, "cache-redis": 0, "firewall": 0, "data-storage": 0 };
      let alertCnt = 0, missingCnt = 0;
      allInstances.forEach((it) => {
        counts[it.typeKey] = (counts[it.typeKey] || 0) + 1;
        if (it.statusBucket === "alert") alertCnt++;
        if (it.hasMissing) missingCnt++;
      });
      const total = allInstances.length;
      return {
        isFleet: true,
        id: "__all__",
        name: `전체 ${total.toLocaleString()}개 Azure 온톨로지 통합 계통`,
        typeLabel: `7개 표준 리소스 유형 · 3개 구독`,
        sub: "전체 구독 (3)",
        rg: "전 리소스 그룹",
        state: `관측 ${total - missingCnt} · 미수집 ${missingCnt}`,
        rev: "스냅샷 rev #4812",
        tone: "live",
        icon: "/azure-icons/subscriptions.svg",
        summary: `전체 ${total.toLocaleString()}개 Azure 리소스가 4대 원천 수집기에서 Huginn(정규화)·Heimdall(신선도·결손 검증)·Muninn(온톨로지 갱신) 파이프라인을 거쳐 7개 리소스 유형 인스턴스로 정제되는 전체 계통입니다. 좌측 목록이나 유형 노드를 클릭하면 개별 리소스 단위로 즉시 드릴다운됩니다.`,
        sources: [
          { id: "src-arg", title: "Azure Resource Graph", sub: `인벤토리 ${total.toLocaleString()}개`, icon: "/azure-icons/subscriptions.svg", snap: `ARM 구성 ${total.toLocaleString()}건`, snapSub: "최신 · 지연 14s", fresh: "fresh", owner: "Huginn" },
          { id: "src-act", title: "Azure Activity Log", sub: "제어 평면 변경 1,284/일", icon: "/azure-icons/monitor.svg", snap: "Stop·NSG 변경 스트림", snapSub: "실시간 · 18s 전", fresh: "fresh", owner: "Huginn" },
          { id: "src-k8s", title: "Kubernetes · Monitor", sub: `AKS ${counts["kubernetes-cluster"]} · 메트릭`, icon: "/azure-icons/kubernetes-services.svg", snap: `주의·중지 ${alertCnt}건 포착`, snapSub: "교차 검증 활성", fresh: "warn", owner: "Heimdall" },
          { id: "src-miss", title: "Log · FOCUS 원천", sub: `미수집 ${missingCnt}건 분리`, icon: "/azure-icons/storage-account.svg", snap: `결손 ${missingCnt}건 (0 대체 금지)`, snapSub: "Unavailable 보존", fresh: "missing", owner: "Heimdall", missing: true }
        ],
        pipes: [
          { id: "p-huginn", title: "Huginn 정규화 엔진", sub: `${total.toLocaleString()}건 ARM·UID 매칭`, icon: "/agent-icons/huginn.svg", owner: "Huginn", fresh: "fresh", ts: "상시" },
          { id: "p-heimdall", title: "Heimdall 자격·신선도", sub: `커버리지 99.2% · 결손 ${missingCnt}`, icon: "/agent-icons/heimdall.svg", owner: "Heimdall", fresh: "warn", ts: "상시" },
          { id: "p-muninn", title: "Muninn 온톨로지 갱신", sub: `Resource@1.0 ${total.toLocaleString()}개`, icon: "/agent-icons/muninn.svg", owner: "Muninn", fresh: "fresh", ts: "rev #4812" }
        ],
        fleetClusters: [
          { id: "fc-aks", filterType: "kubernetes-cluster", title: `AKS (${counts["kubernetes-cluster"]})`, sub: "prod-aks-02 stopped", icon: "/azure-icons/kubernetes-services.svg", tone: "sec" },
          { id: "fc-nsg", filterType: "network-security-group", title: `NSG (${counts["network-security-group"]})`, sub: "nsg-prod-edge 변경", icon: "/azure-icons/network-security-group.svg", tone: "sec" },
          { id: "fc-db", filterType: "postgresql-flexible", title: `DB · 캐시 (${counts["postgresql-flexible"] + counts["cache-redis"]})`, sub: "PG 86 · Redis 94", icon: "/azure-icons/postgresql.svg", tone: "sre" },
          { id: "fc-sec", filterType: "key-vault", title: `KV · 방화벽 (${counts["key-vault"] + counts["firewall"]})`, sub: "KV 142 · FW 28", icon: "/azure-icons/key-vault.svg", tone: "live" },
          { id: "fc-st", filterType: "data-storage", title: `스토리지 (${counts["data-storage"].toLocaleString()})`, sub: `미수집 ${missingCnt}건 분리`, icon: "/azure-icons/storage-account.svg", tone: "neutral" }
        ],
        downstream: [
          { id: "d-rule", title: "활성 운영 규칙 52개", sub: "T0 결정론 95.2% · 위반 0", icon: "/agent-icons/mimir.svg", owner: "Mimir", tone: "live", ts: "상시" },
          { id: "d-alert", title: "핵심 알림 25건 (30일)", sub: "노이즈 88.1% 자동 억제", icon: "/agent-icons/forseti.svg", owner: "Forseti", tone: "sre", ts: "실시간" },
          { id: "d-saga", title: "Saga 감사 원장 #86712", sub: "SHA-256 해시 체인 봉인", icon: "/agent-icons/saga.svg", owner: "Saga", tone: "live", ts: "연속" }
        ],
        diffs: [
          { raw: `ARM Resource Graph (${total.toLocaleString()} raw objects)`, canon: `Ontology Resource@1.0.0 (${total.toLocaleString()} instances)`, rule: "batch_arm_projection@2.0" },
          { raw: `Uncollected log/cost sources (${missingCnt} gaps)`, canon: `evidence_gaps preserved (0-substitution forbidden)`, rule: "preserve_missing_no_zero@1.0" }
        ],
        code: `// 대규모 2,213+ 리소스 스트리밍 정제 파이프라인 (Pure-Rust)
// 좌측 가상 스크롤 목록(Windowed Virtualizer)에서 개별 리소스를 클릭하면
// 해당 리소스의 원천 이벤트 -> 가공 Diff -> 감사 원장 상세로 즉시 전환됩니다.
stream::iter(arm_inventory_pages) // 2,213+ Azure Resources
  .map(Huginn::normalize_identity)
  .map(Heimdall::verify_freshness_and_gaps)
  .for_each(Muninn::commit_ontology_revision).await;`,
        history: [
          { ts: "14:02:25", stage: "④ 상태 전이", actor: "prod-aks-02", desc: "rev #18(running) → rev #19(stopped) 반영 (Activity Log 교차검증)" },
          { ts: "18:44:17", stage: "④ 구성 드리프트", actor: "nsg-prod-edge", desc: "rev #41 → rev #42 반영 (TCP 22 Allow 규칙 감지)" },
          { ts: "19:40:35", stage: "③ 배치 동기화", actor: "Huginn · Muninn", desc: `전체 ${total.toLocaleString()}개 리소스 인벤토리 신선도 99.2% 동기화 완료` }
        ],
        events: [
          { ts: "14:02:11", kind: "Activity Log", tone: "sec", title: "prod-aks-02 · managedClusters/stop 실행", meta: "클릭 시 prod-aks-02 상세 계통 확인 가능" },
          { ts: "18:44:05", kind: "보안 드리프트", tone: "sec", title: "nsg-prod-edge · Allow-Temp-SSH (TCP 22)", meta: "MCSB-NS-01 기준선 위반 · Slack 알림 전송" },
          { ts: "19:36:14", kind: "승인 요청", tone: "sre", title: "pg-orders-kr · 연결 풀 92% 포화 (HIL-8841)", meta: "읽기 복제본 분산 / 풀 증설 승인 대기" }
        ],
        audits: [
          { id: "#86712", ts: "14:02:28", hash: "sha256:9f4a...c10e", title: "prod-aks-02 상태 전이(stopped) 감사 봉인", detail: "Activity Log + Resource Graph 교차 일치" },
          { id: "#86694", ts: "18:44:20", hash: "sha256:7d12...e409", title: "nsg-prod-edge 포트 변경 감지 감사 봉인", detail: "MCSB-NS-01 위반 알림 증적" }
        ]
      };
    }

    function getActiveInst() {
      if (activeId === "__all__") return buildFleetOverviewProfile();
      const found = allInstances.find((x) => x.id === activeId) || allInstances[0];
      return buildDefaultProfile(found);
    }

    let vSpacer = null;
    let vWindow = null;
    function ensureVirtualDom() {
      if (!vSpacer || !listEl.contains(vSpacer)) {
        listEl.innerHTML = `<div class="lin-vscroll-spacer"><div class="lin-vscroll-window"></div></div>`;
        vSpacer = listEl.querySelector(".lin-vscroll-spacer");
        vWindow = listEl.querySelector(".lin-vscroll-window");
      }
    }

    function renderVirtualSlice() {
      ensureVirtualDom();
      const totalRows = virtualRows.length;
      if (!totalRows) {
        vSpacer.style.height = "64px";
        vWindow.style.transform = "translate3d(0,0,0)";
        vWindow.innerHTML = `<div class="cs-res-empty">조건에 일치하는 온톨로지 인스턴스가 없습니다.</div>`;
        return;
      }
      const viewH = listEl.clientHeight || 520;
      const scrollTop = listEl.scrollTop || 0;
      const start = Math.max(0, Math.floor(scrollTop / ROW_H) - OVERSCAN);
      const end = Math.min(totalRows, Math.ceil((scrollTop + viewH) / ROW_H) + OVERSCAN);
      vSpacer.style.height = `${totalRows * ROW_H}px`;
      vWindow.style.transform = `translate3d(0, ${start * ROW_H}px, 0)`;

      const parts = [];
      for (let i = start; i < end; i++) {
        const row = virtualRows[i];
        if (row.kind === "all") {
          const on = activeId === "__all__";
          parts.push(`<div class="lin-vrow"><button type="button" class="lin-inst-btn${on ? " is-active" : ""}" role="option" aria-selected="${on}" data-lin-pick="__all__">
            <img src="/azure-icons/subscriptions.svg" alt="" aria-hidden="true">
            <span style="display:grid;min-width:0"><span class="lin-inst-name">전체 통합 계통 (${allInstances.length.toLocaleString()}개)</span><span class="lin-inst-sub">7개 유형 · 전체 파이프라인 요약</span></span>
            <span class="cs-dot" style="background:var(--sig-live)"></span>
          </button></div>`);
        } else if (row.kind === "group") {
          parts.push(`<div class="lin-vrow"><div class="lin-type-head"><span>${esc(row.label)}</span><span>${row.count.toLocaleString()}</span></div></div>`);
        } else {
          const it = row.item;
          const on = it.id === activeId;
          parts.push(`<div class="lin-vrow"><button type="button" class="lin-inst-btn${on ? " is-active" : ""}" role="option" aria-selected="${on}" data-lin-pick="${esc(it.id)}">
            <img src="${esc(it.icon)}" alt="" aria-hidden="true">
            <span style="display:grid;min-width:0"><span class="lin-inst-name">${esc(it.name)}</span><span class="lin-inst-sub">${esc(it.sub)} · ${esc(it.state)}</span></span>
            <span class="cs-dot" style="background:var(--sig-${it.tone === "neutral" ? "auto" : it.tone})"></span>
          </button></div>`);
        }
      }
      vWindow.innerHTML = parts.join("");
    }

    function renderExplorer() {
      const q = (searchInp.value || "").trim().toLowerCase();
      const tf = typeSel?.value || "all";
      const sf = statusSel?.value || "all";
      const filtered = [];
      for (let i = 0; i < allInstances.length; i++) {
        const it = allInstances[i];
        if (tf !== "all" && it.typeKey !== tf) continue;
        if (sf !== "all") {
          if (sf === "missing" && !it.hasMissing) continue;
          if (sf === "alert" && it.statusBucket !== "alert") continue;
          if (sf === "healthy" && it.statusBucket !== "healthy") continue;
        }
        if (q && !it._hay.includes(q)) continue;
        filtered.push(it);
      }
      const countEl = document.getElementById("linInstanceCount");
      if (countEl) countEl.textContent = `${filtered.length.toLocaleString()} / ${allInstances.length.toLocaleString()}개`;

      const groups = new Map();
      for (let i = 0; i < filtered.length; i++) {
        const it = filtered[i];
        let arr = groups.get(it.typeLabel);
        if (!arr) { arr = []; groups.set(it.typeLabel, arr); }
        arr.push(it);
      }

      virtualRows = [];
      if (!q && tf === "all" && sf === "all") virtualRows.push({ kind: "all" });
      groups.forEach((items, label) => {
        virtualRows.push({ kind: "group", label, count: items.length });
        for (let j = 0; j < items.length; j++) virtualRows.push({ kind: "item", item: items[j] });
      });
      listEl.scrollTop = 0;
      renderVirtualSlice();
    }

    function nodeAccentColor(n) {
      if (colorMode === "freshness") {
        if (n.missing || n.fresh === "missing") return "var(--sig-sec)";
        if (n.fresh === "warn") return "var(--sig-sre)";
        return "var(--sig-live)";
      }
      if (colorMode === "health") {
        if (n.missing || n.tone === "sec") return "var(--sig-sec)";
        if (n.tone === "sre" || n.fresh === "warn") return "var(--sig-sre)";
        return "var(--sig-live)";
      }
      if (colorMode === "owner") {
        if (n.owner === "Huginn") return "var(--sig-live)";
        if (n.owner === "Heimdall") return "var(--sig-sre)";
        if (n.owner === "Muninn" || n.owner === "Mimir") return "var(--sig-human)";
        if (n.owner === "Saga" || n.owner === "Forseti") return "var(--sig-sec)";
        return "var(--sig-auto)";
      }
      return n.missing ? "var(--sig-sec)" : n.tone ? `var(--sig-${n.tone === "neutral" ? "auto" : n.tone})` : n.fresh === "warn" ? "var(--sig-sre)" : "var(--sig-live)";
    }

    function renderStageSvg() {
      const inst = getActiveInst();
      const badge = document.getElementById("linActiveTargetBadge");
      if (badge) {
        badge.className = `cs-badge tone-${inst.tone === "neutral" ? "neutral" : inst.tone}`;
        badge.innerHTML = inst.isFleet
          ? `<span class="cs-dot"></span>전체 ${allInstances.length.toLocaleString()}개 · ${esc(inst.state)}`
          : `<span class="cs-dot"></span>${esc(inst.name)} · ${esc(inst.state)} (${esc(inst.rev)})`;
      }

      const colX = [16, 256, 502, 748, 992];
      const nodeW = 192;
      const nodeH = 62;
      const placeCol = (arr, x) => {
        const gap = Math.min(26, Math.max(12, Math.floor((408 - arr.length * nodeH) / Math.max(1, arr.length + 1))));
        const totalH = arr.length * nodeH + (arr.length - 1) * gap;
        const startY = Math.max(18, Math.round((436 - totalH) / 2));
        return arr.map((item, i) => ({ ...item, x, y: startY + i * (nodeH + gap), cy: startY + i * (nodeH + gap) + nodeH / 2 }));
      };

      const s1 = showAncestors ? placeCol(inst.sources.map((s) => ({ id: s.id, title: s.title, sub: s.sub, icon: s.icon, owner: s.owner, fresh: s.fresh, missing: s.missing, stage: 1, detail: `${s.title} 원천 소스 (${s.sub})` })), colX[0]) : [];
      const s2 = showAncestors ? placeCol(inst.sources.map((s) => ({ id: `snap-${s.id}`, srcId: s.id, title: s.snap, sub: s.snapSub, icon: s.icon, owner: s.owner, fresh: s.fresh, missing: s.missing, edgeLbl: s.edge, stage: 2, detail: `${s.title} → ${s.snap} (${s.snapSub})` })), colX[1]) : [];
      const s3 = placeCol(inst.pipes.map((p) => ({ id: p.id, title: p.title, sub: `${p.sub}`, icon: p.icon, owner: p.owner, fresh: p.fresh, stage: 3, detail: `${p.title} (${p.ts}) - ${p.sub}` })), colX[2]);
      const s4 = inst.isFleet && Array.isArray(inst.fleetClusters)
        ? placeCol(inst.fleetClusters.map((c) => ({
            id: c.id, title: c.title, sub: c.sub, icon: c.icon, owner: "Muninn",
            tone: c.tone, fresh: c.tone === "sec" ? "warn" : "fresh",
            stage: 4, isCenter: true, filterType: c.filterType,
            detail: `${c.title} - 클릭하여 좌측 목록을 해당 유형으로 필터링합니다.`
          })), colX[3])
        : [{
            id: "onto-root", title: inst.name, sub: `${inst.typeLabel.replace("Resource / ", "")} · ${inst.state}`,
            icon: inst.icon, owner: "Muninn", tone: inst.tone, fresh: inst.tone === "sec" ? "warn" : "fresh",
            x: colX[3], y: 174, cy: 218, h: 88, stage: 4, isCenter: true, detail: inst.summary
          }];
      const s5 = showDescendants ? placeCol(inst.downstream.map((d) => ({ id: d.id, title: d.title, sub: `${d.sub}`, icon: d.icon, owner: d.owner, tone: d.tone, stage: 5, detail: `${d.title} (${d.ts}) - ${d.sub}` })), colX[4]) : [];

      const edges = [];
      if (showAncestors) {
        s1.forEach((n, i) => {
          const t = s2[i];
          if (t) edges.push({ from: n, to: t, dashed: n.missing, tone: n.missing ? "sec" : "auto", kind: n.missing ? "missing" : "state" });
        });
        s2.forEach((n) => {
          const tgt = n.owner === "Heimdall" ? (s3[1] || s3[0]) : s3[0];
          if (tgt) edges.push({ from: n, to: tgt, dashed: n.missing, tone: n.missing ? "sec" : "live", kind: n.missing ? "missing" : "state" });
        });
      }
      for (let i = 0; i < s3.length - 1; i++) {
        edges.push({ from: s3[i], to: s3[i + 1], vertical: true, tone: "live", kind: "state" });
      }
      if (s3.length) {
        s4.forEach((cNode) => {
          edges.push({ from: s3[s3.length - 1], to: cNode, tone: cNode.tone === "sec" ? "sec" : "live", kind: "state" });
        });
      }
      if (showDescendants) {
        if (inst.isFleet) {
          s4.forEach((cNode, idx) => {
            const d = s5[idx % s5.length];
            if (d) edges.push({ from: cNode, to: d, tone: d.tone || "live", kind: "downstream" });
          });
        } else {
          s5.forEach((d) => {
            edges.push({ from: s4[0], to: d, tone: d.tone || "live", kind: "downstream" });
          });
        }
      }

      const allNodes = [...s1, ...s2, ...s3, ...s4, ...s5];
      const dimForScope = (item) => {
        if (activeScope === "missing") return !item.missing && !item.isCenter && item.owner !== "Heimdall";
        if (activeScope === "state") return item.missing || item.stage === 5;
        return false;
      };

      const markerFor = (t) => t === "sec" ? "linf-arr-sec" : t === "sre" ? "linf-arr-sre" : t === "auto" ? "linf-arr-auto" : "linf-arr-live";
      const strokeFor = (t) => t === "sec" ? "var(--sig-sec)" : t === "sre" ? "var(--sig-sre)" : t === "auto" ? "var(--sig-auto)" : "var(--sig-live)";

      const edgesHtml = edges.map((e) => {
        const isDim = (selectedStageNode && e.from.id !== selectedStageNode && e.to.id !== selectedStageNode)
          || (activeScope === "missing" && !e.dashed)
          || (activeScope === "state" && (e.dashed || e.kind === "downstream"));
        let d;
        if (e.vertical) {
          const vx = e.from.x + nodeW / 2;
          d = `M${vx} ${e.from.y + nodeH} L${vx} ${e.to.y - 8}`;
        } else {
          const x1 = e.from.x + nodeW;
          const y1 = e.from.cy;
          const x2 = e.to.x - 8;
          const y2 = e.to.cy;
          const midX = (x1 + x2) / 2;
          d = Math.abs(y1 - y2) < 2 ? `M${x1} ${y1} L${x2} ${y2}` : `M${x1} ${y1} C${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`;
        }
        return `<g class="lin-edge svg-edge-group${isDim ? " is-dim" : ""}">
          <path d="${d}" fill="none" stroke="${strokeFor(e.tone)}" stroke-width="1.2" stroke-opacity="0.78"${e.dashed ? ' stroke-dasharray="4 3"' : ""} marker-end="url(#${markerFor(e.tone)})"/>
        </g>`;
      }).join("");

      const nodesHtml = allNodes.map((n) => {
        const h = n.h || nodeH;
        const accent = nodeAccentColor(n);
        const sel = selectedStageNode ? n.id === selectedStageNode : n.isCenter;
        const isDim = (selectedStageNode && n.id !== selectedStageNode && !edges.some((e) => (e.from.id === selectedStageNode && e.to.id === n.id) || (e.to.id === selectedStageNode && e.from.id === n.id)))
          || dimForScope(n);
        const bgTint = colorMode !== "default" ? `fill="${accent}" fill-opacity="0.06"` : `fill="var(--cs-card)"`;
        const strokeAttr = colorMode !== "default" ? `stroke="${accent}"` : (sel ? `stroke="var(--sig-live)"` : `stroke="var(--cs-hairline)"`);
        return `<g class="lin-node graph-node${sel ? " is-selected" : ""}${n.missing ? " is-missing" : ""}${isDim ? " is-dim" : ""}" tabindex="0" role="button" data-lin-node="${esc(n.id)}"${n.filterType ? ` data-lin-filter-type="${esc(n.filterType)}"` : ""} data-ut-title="${esc(n.title)}" data-ut-val="${esc(n.owner || "")}" data-ut-body="${esc(n.detail || n.sub)}" data-ut-meta="${n.filterType ? "클릭하여 해당 유형 리소스 필터링" : "클릭하여 우측 포렌식 상세 고정"}">
          <rect x="${n.x}" y="${n.y}" width="${nodeW}" height="${h}" rx="5" ${bgTint} ${strokeAttr} stroke-width="${sel ? "1.6" : "1"}"/>
          <circle cx="${n.x + nodeW - 11}" cy="${n.y + 12}" r="3.4" fill="${accent}"/>
          <image href="${esc(n.icon)}" x="${n.x + 10}" y="${n.y + Math.round((h - 24) / 2)}" width="24" height="24"/>
          <text x="${n.x + 42}" y="${n.y + (h > 70 ? 32 : 26)}" font-size="12.5" font-weight="700" fill="var(--cs-text)">${esc(n.title.length > 18 ? `${n.title.slice(0, 17)}...` : n.title)}</text>
          <text x="${n.x + 42}" y="${n.y + (h > 70 ? 52 : 46)}" font-size="12" fill="${n.missing ? "var(--sig-sec-text)" : "var(--cs-text-soft)"}">${esc(n.sub.length > 20 ? `${n.sub.slice(0, 19)}...` : n.sub)}</text>
          ${h > 70 ? `<text x="${n.x + 42}" y="${n.y + 72}" font-size="12" font-weight="600" fill="var(--sig-live-text)">${esc(inst.rev)} · ${esc(inst.sub)}</text>` : ""}
        </g>`;
      }).join("");

      svg.innerHTML = `
        <defs>
          <marker id="linf-arr-live" markerUnits="userSpaceOnUse" markerWidth="10" markerHeight="10" refX="1.2" refY="5" orient="auto"><path d="M0 1.4 L8.6 5 L0 8.6 L1.6 5 Z" fill="var(--sig-live)"/></marker>
          <marker id="linf-arr-sre" markerUnits="userSpaceOnUse" markerWidth="10" markerHeight="10" refX="1.2" refY="5" orient="auto"><path d="M0 1.4 L8.6 5 L0 8.6 L1.6 5 Z" fill="var(--sig-sre)"/></marker>
          <marker id="linf-arr-sec" markerUnits="userSpaceOnUse" markerWidth="10" markerHeight="10" refX="1.2" refY="5" orient="auto"><path d="M0 1.4 L8.6 5 L0 8.6 L1.6 5 Z" fill="var(--sig-sec)"/></marker>
          <marker id="linf-arr-auto" markerUnits="userSpaceOnUse" markerWidth="10" markerHeight="10" refX="1.2" refY="5" orient="auto"><path d="M0 1.4 L8.6 5 L0 8.6 L1.6 5 Z" fill="var(--sig-auto)"/></marker>
        </defs>
        ${edgesHtml}
        ${nodesHtml}
      `;
    }

    function renderInspector() {
      const inst = getActiveInst();
      const tEl = document.getElementById("linInspTitle");
      const bEl = document.getElementById("linInspBadge");
      const sEl = document.getElementById("linInspSub");
      if (tEl) tEl.textContent = inst.name;
      if (bEl) {
        bEl.className = `cs-badge tone-${inst.tone === "neutral" ? "neutral" : inst.tone}`;
        bEl.innerHTML = `<span class="cs-dot"></span>${esc(inst.state)} · ${esc(inst.rev)}`;
      }
      if (sEl) sEl.textContent = `${inst.typeLabel} · ${inst.sub} / ${inst.rg}`;

      if (activeTab === "transform") {
        inspBody.innerHTML = `
          <div style="font-size:12.5px;color:var(--cs-text);line-height:1.5">${esc(inst.summary)}</div>
          <div class="lin-diff-card">
            <strong style="font-size:12.5px">원본 소스 → 온톨로지 속성 가공 Diff</strong>
            ${inst.diffs.map((d) => `
              <div class="lin-diff-row">
                <span class="cell-mono" style="color:var(--cs-text-soft)">원본: ${esc(d.raw)}</span>
                <span class="cell-mono" style="color:var(--sig-live-text);font-weight:600">정제: ${esc(d.canon)}</span>
                <span style="font-size:12px;color:var(--cs-text-soft)">매핑 규칙: ${esc(d.rule)}</span>
              </div>
            `).join("")}
          </div>
          <div style="display:grid;gap:5px">
            <strong style="font-size:12.5px">변환 파이프라인 로직 (정제 코드)</strong>
            <pre class="lin-code-pre">${esc(inst.code)}</pre>
          </div>
        `;
      } else if (activeTab === "history") {
        inspBody.innerHTML = `
          <strong style="font-size:12.5px">언제 · 어느 원천에서 갱신되었는가 (${esc(inst.rev)})</strong>
          ${inst.history.map((h) => `
            <div class="lin-tl-item">
              <div class="lin-tl-head"><span class="cs-badge tone-live">${esc(h.stage)}</span><span class="cell-mono">${esc(h.ts)}</span></div>
              <strong>${esc(h.actor)}</strong>
              <span style="color:var(--cs-text-soft)">${esc(h.desc)}</span>
            </div>
          `).join("")}
        `;
      } else if (activeTab === "events") {
        inspBody.innerHTML = `
          <strong style="font-size:12.5px">연결된 Activity Log · 탐지 · 알림 이벤트 (${inst.events.length}건)</strong>
          ${inst.events.map((ev) => `
            <div class="lin-tl-item">
              <div class="lin-tl-head"><span class="cs-badge tone-${ev.tone}">${esc(ev.kind)}</span><span class="cell-mono">${esc(ev.ts)}</span></div>
              <strong>${esc(ev.title)}</strong>
              <span class="cell-mono" style="color:var(--cs-text-soft)">${esc(ev.meta)}</span>
            </div>
          `).join("")}
        `;
      } else {
        inspBody.innerHTML = `
          <strong style="font-size:12.5px">Saga 2단계 SHA-256 감사 원장 (${inst.audits.length}건)</strong>
          ${inst.audits.map((a) => `
            <div class="lin-tl-item">
              <div class="lin-tl-head"><span class="cs-badge tone-live">${esc(a.id)}</span><span class="cell-mono">${esc(a.ts)}</span></div>
              <strong>${esc(a.title)}</strong>
              <span class="cell-mono" style="color:var(--sig-live-text)">${esc(a.hash)}</span>
              <span style="color:var(--cs-text-soft)">${esc(a.detail)}</span>
            </div>
          `).join("")}
        `;
      }
    }

    function renderAll() {
      renderExplorer();
      renderStageSvg();
      renderInspector();
      const allBtn = document.getElementById("linShowAllFleetBtn");
      if (allBtn) {
        allBtn.textContent = `전체 ${allInstances.length.toLocaleString()}개 통합`;
        allBtn.classList.toggle("is-active", activeId === "__all__");
      }
    }

    let vScrollRaf = 0;
    listEl.addEventListener("scroll", () => {
      if (vScrollRaf) return;
      vScrollRaf = requestAnimationFrame(() => {
        vScrollRaf = 0;
        renderVirtualSlice();
      });
    }, { passive: true });

    listEl.addEventListener("click", (e) => {
      if (!(e.target instanceof Element)) return;
      const btn = e.target.closest("[data-lin-pick]");
      if (!btn) return;
      activeId = btn.getAttribute("data-lin-pick") || activeId;
      selectedStageNode = null;
      renderVirtualSlice();
      renderStageSvg();
      renderInspector();
      const allBtn = document.getElementById("linShowAllFleetBtn");
      if (allBtn) allBtn.classList.toggle("is-active", activeId === "__all__");
      if (!IS_STATIC_MOCK && activeId !== "__all__") {
        fetch(`/api/v4/governance/ontology/lineage?resource_id=${encodeURIComponent(activeId)}&include_audit=true`, { headers: { Accept: "application/json" } }).catch(() => {});
      }
    });
    document.getElementById("linShowAllFleetBtn")?.addEventListener("click", () => {
      activeId = "__all__";
      selectedStageNode = null;
      if (searchInp) searchInp.value = "";
      if (typeSel) typeSel.value = "all";
      if (statusSel) statusSel.value = "all";
      renderAll();
    });
    svg.addEventListener("click", (e) => {
      if (!(e.target instanceof Element)) return;
      const g = e.target.closest("[data-lin-node]");
      const ft = g?.getAttribute("data-lin-filter-type");
      if (ft && typeSel) {
        typeSel.value = ft;
        if (searchInp) searchInp.value = "";
        renderExplorer();
        showToast(`${g.getAttribute("data-ut-title") || ft} 유형으로 좌측 가상 목록을 필터링했습니다. 개별 리소스를 클릭해 계통을 추적하세요.`);
        return;
      }
      selectedStageNode = g ? (selectedStageNode === g.getAttribute("data-lin-node") ? null : g.getAttribute("data-lin-node")) : null;
      renderStageSvg();
    });
    searchInp.addEventListener("input", renderExplorer);
    typeSel?.addEventListener("change", renderExplorer);
    statusSel?.addEventListener("change", renderExplorer);
    document.querySelectorAll("[data-lin-scope]").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeScope = btn.getAttribute("data-lin-scope") || "all";
        document.querySelectorAll("[data-lin-scope]").forEach((b) => {
          const on = b === btn;
          b.classList.toggle("is-active", on);
          b.setAttribute("aria-pressed", String(on));
        });
        renderStageSvg();
      });
    });
    document.getElementById("linColorMode")?.addEventListener("change", (e) => {
      colorMode = e.target.value || "default";
      renderStageSvg();
    });
    document.getElementById("linToggleAncestors")?.addEventListener("click", (e) => {
      showAncestors = !showAncestors;
      e.currentTarget.setAttribute("aria-pressed", String(showAncestors));
      renderStageSvg();
    });
    document.getElementById("linToggleDescendants")?.addEventListener("click", (e) => {
      showDescendants = !showDescendants;
      e.currentTarget.setAttribute("aria-pressed", String(showDescendants));
      renderStageSvg();
    });
    document.getElementById("linCopySnapshot")?.addEventListener("click", () => {
      const shareUrl = `${location.origin}${location.pathname}?lineage_target=${encodeURIComponent(activeId)}&color=${encodeURIComponent(colorMode)}${location.hash}`;
      if (navigator.clipboard?.writeText) navigator.clipboard.writeText(shareUrl).catch(() => {});
      showToast(`데이터 계통 스냅샷 링크를 복사했습니다 (${activeId}).`);
    });
    document.querySelectorAll("[data-lin-tab]").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeTab = btn.getAttribute("data-lin-tab") || "transform";
        document.querySelectorAll("[data-lin-tab]").forEach((b) => {
          const on = b === btn;
          b.classList.toggle("is-active", on);
          b.setAttribute("aria-selected", String(on));
        });
        renderInspector();
      });
    });
    document.getElementById("linJumpInstance")?.addEventListener("click", () => {
      document.querySelector('[data-graph-view-btn="instance"]')?.click();
    });

    renderAll();
  }

  renderTopbar();
  renderRailAndExplorer();
  renderChatSidebar();
  wirePageInteractions();
  initFloatingInspectors();
  initCollapsibleLeftRails();
  initCrispSvgScaleGuard();
  initDiagramCanvasUx();
  initUltraFastTooltips();
  initChartDrilldown();
  closeSidebarAndDrawersOnNav();
  ensureAccessibilityInvariants();
  initViewportFitDisclosures();
  initResponsiveChartEngine();
  initOntologyInstanceSearch();
  initArchitectureResourceSearch();
  initForensicDataLineage();
  window.activatePanel = activatePanel;
  const initialPanel = panelFromLocation();
  if (initialPanel && document.querySelector(`.panel-view[data-panel-id="${initialPanel}"]`)) {
    navigatePanel(initialPanel, true);
  } else {
    const first = document.querySelector(".panel-view[data-panel-id]");
    if (first) navigatePanel(first.getAttribute("data-panel-id"), true);
  }
})();
