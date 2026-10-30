"use strict";

(() => {
  const en = {
    skip: "Skip to setup", local: "Local setup", language: "Language", eyebrow: "INSTALLATION",
    title: "Set up FDAI in Azure",
    intro: "Connect your Azure account, choose an installation target, and review each exact plan before applying it.",
    standalone: "This local Hub starts without an FDAI Runtime or PostgreSQL.",
    status: "Installation status", refresh: "Refresh status", connecting: "Connecting",
    initializing: "Opening your authenticated setup session...", request: "Request", action: "Action",
    errorCode: "Error code", account: "Connect Azure",
    loginHelp: "Microsoft browser sign-in opens on the machine running this Hub. Complete sign-in there, then return here and list subscriptions. Never enter credentials on this setup screen.",
    login: "Sign in to Azure", accounts: "List subscriptions", configure: "Choose your installation",
    subscription: "Azure subscription", noAccounts: "List subscriptions to choose a target",
    subscriptionHelp: "Only subscriptions returned by your authenticated Azure session appear here.",
    region: "Azure region",
    regionHelp: "Enter the supported Azure location name for your target, using lowercase letters and digits.",
    cost: "Monthly cost ceiling (USD)", costHelp: "A planning limit, not a billing cap or a cost estimate.",
    artifacts: "Installation artifacts", hubMode: "Signed prebuilt images",
    hubHelp: "Default. Verify Release Hub artifacts using an independently trusted public key. No source-build fallback.",
    sourceMode: "Build from a clean source checkout",
    sourceHelp: "Explicit source installation, independent of Release Hub images.",
    publicKey: "Trusted Release Hub public key (Ed25519 PEM)",
    keyWarning: "Verify this public key through an independent trusted channel. Never paste or upload a private key, credential, or secret.",
    keyFile: "Or read a public PEM file (maximum 4 KiB)",
    sourceRoot: "Clean checkout path on this Hub host",
    sourcePathHelp: "Use an absolute local path. The backend verifies the committed source before preparing the plan.",
    baselineTitle: "Existing AKS resource baseline",
    baseline: "The read-only-console runtime profile still deploys the existing AKS infrastructure and its supporting resources. It is not a reduced-cost runtime. Review the actual resources and cost evidence in each plan.",
    prepareHelp: "Preparation may register required Azure providers after your authorization. Later stages require separate approval of their exact plans; this button does not approve every apply.",
    prepare: "Authorize preparation", decision: "YOUR DECISION", review: "Review the exact plan",
    reviewHelp: "Approval applies only to this request, review, and digest. Read every detail before continuing.",
    reviewId: "Review", digest: "Plan digest", expires: "Expires",
    confirmation: "Type this exact confirmation",
    expired: "This review has expired or its expiry cannot be verified. Refresh status and request a current plan before approving.",
    approve: "Approve this exact plan", decline: "Decline", recovery: "Inspect before resuming",
    recoveryHelp: "The job is not verified ready. Inspect the retained state, resolve the reported problem, then explicitly resume. Requests are never automatically replayed.",
    inspect: "Inspect retained state", resume: "Resume explicitly", readyTitle: "Installation verified ready",
    readyHelp: "The backend reports deployment readiness. Open Console only through the verified HTTPS destination below.",
    openConsole: "Open FDAI Console",
    consoleUnavailable: "A safe HTTPS Console destination is unavailable. Inspect the deployment before continuing.",
    next: "Review, apply, verify",
    nextReview: "Review the actual plan, immutable digest, scope, and confirmation.",
    nextApply: "Approve each stage separately and follow its reported progress.",
    nextVerify: "Open Console only after authoritative readiness verification.",
    disconnect: "You can reconnect to observe the same job. Closing this page does not cancel it or submit another installation.",
    scope: "Installation scope",
    enrollment: "Installation does not enroll this target in managed lifecycle or prove managed-lifecycle readiness.",
    offline: "Offline installation is not supported in this screen. The existing signed offline CLI workflow remains unchanged.",
    footer: "Local session. Explicit approvals. Verified outcomes.",
    idle: "Not started", working: "Working", reviewPhase: "Approval required", ready: "Verified ready", unverified: "Readiness not verified",
    blocked: "Blocked", failed: "Failed", interrupted: "Interrupted", disconnected: "Status unavailable",
    observed: "Last checked", network: "Cannot contact the local Hub. No request was automatically retried. Refresh status before taking another action.",
    uncertain: "The request response was lost. Its outcome is unknown. Refresh status or inspect the retained state before resuming; do not submit another installation.",
    auth: "Setup authentication failed. Reopen setup from the Hub launcher to establish a local session.",
    invalid: "The Hub returned an invalid status. No action is available until a valid status is received.",
    requestFailed: "The Hub rejected the request. Refresh status and inspect the reported problem.",
    tooLarge: "The request exceeds 16 KiB. Shorten the supplied input.",
    invalidKey: "Provide only a public PEM key, no larger than 4 KiB. Private keys and credentials are not accepted.",
    invalidCost: "Enter a positive whole-number monthly cost ceiling in USD.",
    keyRead: "The public key file could not be read. Choose a readable public PEM file.",
  };
  const ko = {
    skip: "설정으로 이동", local: "로컬 설치 설정", language: "언어", eyebrow: "설치",
    title: "Azure에 FDAI 설치",
    intro: "Azure 계정을 연결하고 설치 대상을 선택한 다음, 각 단계의 실제 계획을 검토하고 승인하세요.",
    standalone: "이 로컬 Hub는 FDAI Runtime이나 PostgreSQL 없이 시작됩니다.",
    status: "설치 상태", refresh: "상태 새로 고침", connecting: "연결 중",
    initializing: "인증된 로컬 설정 세션을 여는 중입니다...", request: "요청", action: "작업",
    errorCode: "오류 코드", account: "Azure 연결",
    loginHelp: "이 Hub를 실행하는 컴퓨터에서 Microsoft 로그인 창이 열립니다. 로그인을 완료한 다음 이 화면으로 돌아와 구독 목록을 조회하세요. 이 설정 화면에는 자격 증명을 입력하지 마세요.",
    login: "Azure 로그인", accounts: "구독 목록 조회", configure: "설치 대상 선택",
    subscription: "Azure 구독", noAccounts: "구독 목록을 조회한 후 대상을 선택하세요",
    subscriptionHelp: "인증된 Azure 세션에서 조회한 구독만 표시됩니다.",
    region: "Azure 지역", regionHelp: "대상에서 지원하는 Azure 위치 이름을 영문 소문자와 숫자로 입력하세요.",
    cost: "월 비용 상한 (USD)", costHelp: "계획 수립용 한도입니다. 청구 한도나 예상 비용이 아닙니다.",
    artifacts: "설치 아티팩트", hubMode: "서명된 사전 빌드 이미지",
    hubHelp: "기본 방식입니다. 별도로 신뢰를 확인한 공개 키로 Release Hub 아티팩트를 검증합니다. 실패해도 소스 빌드로 자동 전환하지 않습니다.",
    sourceMode: "정리된 소스 체크아웃에서 빌드",
    sourceHelp: "Release Hub 이미지에 의존하지 않는 소스 설치를 명시적으로 선택합니다.",
    publicKey: "신뢰할 수 있는 Release Hub 공개 키 (Ed25519 PEM)",
    keyWarning: "독립적으로 신뢰할 수 있는 경로에서 공개 키를 확인하세요. 개인 키, 자격 증명, 비밀 값은 붙여 넣거나 업로드하지 마세요.",
    keyFile: "또는 공개 PEM 파일 읽기 (최대 4 KiB)", sourceRoot: "이 Hub 호스트의 정리된 체크아웃 경로",
    sourcePathHelp: "로컬 절대 경로를 입력하세요. 백엔드는 계획을 준비하기 전에 커밋된 소스를 검증합니다.",
    baselineTitle: "기존 AKS 리소스 구성",
    baseline: "read-only-console 런타임 프로파일도 기존 AKS 인프라와 지원 리소스를 배포합니다. 비용을 줄인 런타임이 아닙니다. 각 계획에서 실제 리소스와 비용 근거를 검토하세요.",
    prepareHelp: "준비 작업을 승인하면 필요한 Azure 리소스 공급자가 등록될 수 있습니다. 이후 단계마다 실제 계획을 별도로 승인해야 합니다. 이 버튼은 모든 적용 작업을 일괄 승인하지 않습니다.",
    prepare: "준비 작업 승인", decision: "승인 검토", review: "실제 계획 검토",
    reviewHelp: "승인은 이 요청, 검토 항목, 다이제스트에만 적용됩니다. 모든 세부 정보를 읽고 진행하세요.",
    reviewId: "검토 항목", digest: "계획 다이제스트", expires: "만료 시각", confirmation: "다음 확인 문구를 정확히 입력하세요",
    expired: "검토 항목이 만료되었거나 만료 시각을 검증할 수 없습니다. 상태를 새로 고치고 유효한 계획을 요청한 후 승인하세요.",
    approve: "이 계획만 승인", decline: "거절", recovery: "재개 전에 상태 점검",
    recoveryHelp: "작업의 준비 완료가 검증되지 않았습니다. 저장된 상태를 점검하고 보고된 문제를 해결한 다음, 명시적으로 재개하세요. 요청은 자동으로 다시 실행되지 않습니다.",
    inspect: "저장된 상태 점검", resume: "작업 재개", readyTitle: "설치 준비 완료 검증됨",
    readyHelp: "백엔드에서 배포 준비 완료를 보고했습니다. 아래의 검증된 HTTPS 주소로만 Console을 여세요.",
    openConsole: "FDAI Console 열기",
    consoleUnavailable: "안전한 HTTPS Console 주소가 없습니다. 진행하기 전에 배포 상태를 점검하세요.",
    next: "검토, 적용, 검증", nextReview: "실제 계획, 변경 불가능한 다이제스트, 범위, 확인 문구를 검토합니다.",
    nextApply: "각 단계를 별도로 승인하고 보고된 진행 상황을 확인합니다.",
    nextVerify: "권위 있는 관측으로 준비 완료를 검증한 후에만 Console을 엽니다.",
    disconnect: "다시 연결해도 같은 작업을 조회합니다. 이 페이지를 닫아도 작업이 취소되거나 새 설치가 요청되지 않습니다.",
    scope: "설치 범위", enrollment: "설치만으로 이 대상이 관리형 수명 주기에 등록되거나 관리형 수명 주기의 준비 완료가 검증되지는 않습니다.",
    offline: "이 화면은 오프라인 설치를 지원하지 않습니다. 기존의 서명된 오프라인 CLI 설치 절차는 그대로 유지됩니다.",
    footer: "로컬 세션. 명시적 승인. 결과 검증.",
    idle: "시작 전", working: "진행 중", reviewPhase: "승인 필요", ready: "준비 완료 검증됨", unverified: "준비 완료 미검증",
    blocked: "차단됨", failed: "실패", interrupted: "중단됨", disconnected: "상태 조회 불가",
    observed: "마지막 조회", network: "로컬 Hub에 연결할 수 없습니다. 요청을 자동으로 재시도하지 않았습니다. 다른 작업을 실행하기 전에 상태를 새로 고치세요.",
    uncertain: "요청 응답을 받지 못해 결과를 알 수 없습니다. 재개하기 전에 상태를 새로 고치거나 저장된 상태를 점검하세요. 새 설치를 요청하지 마세요.",
    auth: "설정 세션 인증에 실패했습니다. Hub 실행기에서 설정 화면을 다시 열어 로컬 세션을 시작하세요.",
    invalid: "Hub가 유효하지 않은 상태를 반환했습니다. 유효한 상태를 받기 전에는 작업을 실행할 수 없습니다.",
    requestFailed: "Hub가 요청을 거절했습니다. 상태를 새로 고치고 보고된 문제를 점검하세요.",
    tooLarge: "요청이 16 KiB를 초과했습니다. 입력 내용을 줄이세요.",
    invalidKey: "최대 4 KiB의 공개 PEM 키만 입력하세요. 개인 키와 자격 증명은 허용되지 않습니다.",
    invalidCost: "월 비용 상한을 양의 정수로 입력하세요. 단위는 USD입니다.",
    keyRead: "공개 키 파일을 읽을 수 없습니다. 읽을 수 있는 공개 PEM 파일을 선택하세요.",
  };
  const $ = id => document.getElementById(id);
  let locale = navigator.language.toLowerCase().startsWith("ko") ? "ko" : "en";
  let status = null, csrf = "", connected = false, pending = false, loading = false;
  let authenticating = false, sessionVersion = 0, statusTask = null;
  let timer = null, observedAt = null, reviewKey = "", accountKey = "", noticeKey = "", noticeDetail = "";
  const text = key => (locale === "ko" && ko[key]) || en[key] || en.requestFailed;
  function setText(id, value) {
    if ($(id).textContent !== value) $(id).textContent = value;
  }
  function notice(key, detail = "") {
    noticeKey = key;
    noticeDetail = detail;
    $("notice").textContent = detail || (key ? text(key) : "");
    $("notice").hidden = !key && !detail;
  }
  function localize() {
    document.documentElement.lang = locale;
    document.title = `FDAI Lifecycle Hub - ${locale === "ko" ? "설치 설정" : "Setup"}`;
    $("locale").value = locale;
    document.querySelectorAll("[data-i18n]").forEach(node => { node.textContent = text(node.dataset.i18n); });
    if (noticeKey) notice(noticeKey, noticeDetail);
    if ($("subscription").options[0]) $("subscription").options[0].textContent = text("noAccounts");
    if (status) render();
  }
  function artifactFields() {
    const source = document.querySelector('input[name="artifact"]:checked').value === "source";
    $("hub-fields").hidden = source;
    $("source-fields").hidden = !source;
    $("public-key").disabled = source;
    $("public-key").required = !source;
    $("key-file").disabled = source;
    $("source-root").disabled = !source;
    $("source-root").required = source;
  }
  function safeConsole(value) {
    if (typeof value !== "string") return null;
    try {
      const url = new URL(value);
      return url.protocol === "https:" && !url.username && !url.password ? url.href : null;
    } catch { return null; }
  }
  function reviewCurrent() {
    return connected && status?.phase === "review" && status.request_id && status.review &&
      Number.isFinite(Date.parse(status.review.expires_at)) && Date.parse(status.review.expires_at) > Date.now();
  }
  function controls() {
    const available = connected && !pending && !loading && !authenticating;
    const active = status?.phase === "working" || status?.phase === "review";
    const fresh = available && !active && !status?.request_id;
    const recovery = ["failed", "blocked", "interrupted"].includes(status?.phase);
    $("login").disabled = !fresh && !(available && recovery);
    $("accounts").disabled = !fresh;
    $("configuration-fields").disabled = !fresh;
    $("refresh").disabled = loading;
    $("approve").disabled = !available || !reviewCurrent() ||
      $("confirmation").value !== (status?.review?.confirmation_required || "");
    $("decline").disabled = !available || !reviewCurrent();
    $("resume").disabled = !available || active || status?.phase === "ready";
    $("inspect").disabled = !available || active;
  }
  function render() {
    const phase = status.phase;
    $("skeleton").hidden = phase !== "working";
    $("status-live").setAttribute("aria-busy", String(phase === "working"));
    const phaseKey = phase === "review" ? "reviewPhase" :
      phase === "ready" && !status.deployment_ready ? "unverified" : phase;
    setText("phase", text(connected ? phaseKey : "disconnected"));
    $("phase").dataset.phase = connected ? phase : "disconnected";
    setText("message", status.message || text(phase === "review" ? "reviewPhase" : phase));
    $("request-meta").hidden = !status.request_id && !status.error_code;
    $("request-id").textContent = status.request_id || "-";
    $("action-name").textContent = status.action || "-";
    $("error-row").hidden = !status.error_code;
    $("error-code").textContent = status.error_code || "";
    $("observed").textContent = observedAt ? `${text("observed")}: ${observedAt.toLocaleString(locale === "ko" ? "ko-KR" : "en-US")}` : "";
    const accounts = JSON.stringify(status.accounts);
    if (accountKey !== accounts) {
      const selected = $("subscription").value;
      $("subscription").replaceChildren(new Option(text("noAccounts"), ""));
      for (const account of status.accounts) {
        $("subscription").add(new Option(`${account.name} (${account.id})`, account.id));
      }
      $("subscription").value = selected;
      accountKey = accounts;
    }
    const review = phase === "review" ? status.review : null;
    $("review-section").hidden = !review;
    const nextKey = review ? JSON.stringify([status.request_id, review]) : "";
    if (review && reviewKey !== nextKey) {
      $("review-title").textContent = review.title;
      $("review-id").textContent = review.id;
      $("review-digest").textContent = review.digest;
      $("review-expires").textContent = review.expires_at;
      $("review-details").replaceChildren(...review.details.map(detail => {
        const item = document.createElement("li"); item.textContent = detail; return item;
      }));
      $("confirmation-field").hidden = !review.confirmation_required;
      $("confirmation-required").textContent = review.confirmation_required;
      $("confirmation").value = "";
      $("review-heading").focus();
    }
    if (review) $("expired").hidden = Boolean(reviewCurrent());
    reviewKey = nextKey;
    const recovery = ["failed", "blocked", "interrupted"].includes(phase);
    const ready = connected && phase === "ready" && status.deployment_ready === true;
    $("ready-section").hidden = !ready;
    $("next-section").hidden = Boolean(review) || recovery || ready;
    const url = ready ? safeConsole(status.console_url) : null;
    $("recovery-section").hidden = !recovery && !(ready && !url);
    $("console-link").removeAttribute("href");
    $("console-link").hidden = !url;
    if (url) $("console-link").href = url;
    $("console-unavailable").hidden = Boolean(url);
    controls();
  }
  function validStatus(value) {
    const nullableString = item => item === null || typeof item === "string";
    if (!value || !["idle", "working", "review", "ready", "blocked", "failed", "interrupted"].includes(value.phase) ||
      typeof value.csrf_token !== "string" || !value.csrf_token ||
      !nullableString(value.request_id) || !nullableString(value.action) || !nullableString(value.error_code) ||
      !nullableString(value.console_url) || typeof value.message !== "string" ||
      typeof value.deployment_ready !== "boolean" || !Array.isArray(value.accounts) ||
      !value.accounts.every(item => item && ["id", "name", "tenant_id"].every(key => typeof item[key] === "string"))) return false;
    const review = value.review;
    return review === null || (review && ["id", "digest", "title", "confirmation_required", "expires_at"]
      .every(key => typeof review[key] === "string") && Array.isArray(review.details) &&
      review.details.every(detail => typeof detail === "string") && Boolean(value.request_id));
  }
  async function request(path, body) {
    const options = { credentials: "same-origin", cache: "no-store", redirect: "error", signal: AbortSignal.timeout(10000) };
    if (body !== undefined) {
      options.method = "POST";
      options.body = JSON.stringify(body);
      if (new TextEncoder().encode(options.body).byteLength > 16384) throw new Error(text("tooLarge"));
      options.headers = { "Content-Type": "application/json" };
      if (path !== "session") options.headers["X-FDAI-CSRF"] = csrf;
    }
    const response = await fetch(`/setup/api/${path}`, options);
    let data;
    try { data = await response.json(); } catch { throw new Error(text("invalid")); }
    if (!response.ok) {
      if (response.status === 401) throw new Error(text("auth"));
      throw new Error(typeof data.error === "string" ? data.error : text("requestFailed"));
    }
    return data;
  }
  function schedule() {
    clearTimeout(timer);
    if (!document.hidden && !pending && !authenticating) timer = setTimeout(loadStatus, 2000);
  }
  function loadStatus() {
    if (pending || authenticating) return Promise.resolve();
    if (statusTask) return statusTask;
    const version = sessionVersion;
    statusTask = (async () => {
      loading = true; controls();
      try {
        const data = await request("status");
        if (version !== sessionVersion) return;
        if (!validStatus(data)) throw new Error(text("invalid"));
        status = data; csrf = data.csrf_token; connected = true; observedAt = new Date();
        render();
      } catch (error) {
        if (version !== sessionVersion) return;
        connected = false;
        notice("network", error instanceof TypeError || error.name === "TimeoutError" ? "" : error.message);
        if (status) render();
        else {
          $("phase").textContent = text("disconnected"); $("message").textContent = text("network");
          $("skeleton").hidden = true; $("status-live").setAttribute("aria-busy", "false");
        }
      } finally { loading = false; statusTask = null; controls(); schedule(); }
    })();
    return statusTask;
  }
  async function mutate(path, body) {
    if (pending || !connected) return;
    pending = true; clearTimeout(timer); notice(""); controls();
    try { await request(path, body); }
    catch (error) { notice("uncertain", error instanceof TypeError || error.name === "TimeoutError" ? text("uncertain") : error.message); }
    finally { pending = false; await loadStatus(); controls(); }
  }
  const action = (name, payload = {}) => mutate("actions", { action: name, payload });
  function publicKey(value) {
    return new TextEncoder().encode(value).byteLength <= 4096 &&
      /^-----BEGIN PUBLIC KEY-----\r?\n[A-Za-z0-9+/=\r\n]+-----END PUBLIC KEY-----\s*$/.test(value);
  }
  $("install-form").addEventListener("submit", event => {
    event.preventDefault();
    const payload = {
      subscription_id: $("subscription").value, region: $("region").value,
      monthly_cost_ceiling: Number($("cost").value),
      artifact_source: document.querySelector('input[name="artifact"]:checked').value,
    };
    if (!Number.isSafeInteger(payload.monthly_cost_ceiling) || payload.monthly_cost_ceiling < 1) return notice("invalidCost");
    if (payload.artifact_source === "source") payload.source_root = $("source-root").value;
    else {
      if (!publicKey($("public-key").value.trim())) return notice("invalidKey");
      payload.hub_public_key = $("public-key").value.trim();
    }
    action("install", payload);
  });
  function decide(approved) {
    if (!reviewCurrent()) return;
    const review = status.review;
    mutate("decisions", {
      request_id: status.request_id, review_id: review.id, digest: review.digest,
      approved, confirmation: approved ? $("confirmation").value : "",
    });
  }
  $("decision-form").addEventListener("submit", event => { event.preventDefault(); if (!$("approve").disabled) decide(true); });
  $("decline").addEventListener("click", () => decide(false));
  $("confirmation").addEventListener("input", controls);
  for (const name of ["login", "accounts", "resume", "inspect"]) $(name).addEventListener("click", () => action(name));
  $("refresh").addEventListener("click", () => { notice(""); loadStatus(); });
  document.querySelectorAll('input[name="artifact"]').forEach(node => node.addEventListener("change", artifactFields));
  $("key-file").addEventListener("change", async () => {
    const file = $("key-file").files[0];
    if (!file) return;
    try {
      if (file.size > 4096) { notice("invalidKey"); return; }
      const value = await file.text();
      if (!publicKey(value.trim())) { notice("invalidKey"); return; }
      $("public-key").value = value.trim(); notice("");
    } catch { notice("keyRead"); }
    finally { $("key-file").value = ""; }
  });
  $("locale").addEventListener("change", () => { locale = $("locale").value === "ko" ? "ko" : "en"; localize(); });
  document.addEventListener("visibilitychange", () => { clearTimeout(timer); if (!document.hidden) loadStatus(); });
  async function initialize() {
    let token = new URLSearchParams(location.hash.slice(1)).get("session");
    if (location.hash) history.replaceState(null, "", location.pathname + location.search);
    if (token) {
      if (authenticating) { token = null; return; }
      authenticating = true; connected = false; csrf = ""; sessionVersion += 1;
      clearTimeout(timer); notice(""); controls();
      if (status) render();
      try {
        await request("session", { token });
        if (statusTask) await statusTask;
      } catch {
        notice("auth"); $("phase").textContent = text("disconnected"); $("message").textContent = text("auth");
        $("skeleton").hidden = true; $("status-live").setAttribute("aria-busy", "false");
        return;
      } finally { token = null; authenticating = false; controls(); }
    }
    await loadStatus();
  }
  window.addEventListener("hashchange", () => {
    if (new URLSearchParams(location.hash.slice(1)).has("session")) initialize();
  });
  localize(); artifactFields();
  initialize();
})();
