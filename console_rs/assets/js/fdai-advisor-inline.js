/* FDAI Console — Zero-Bloat In-Place Advisor Integration & Shared Drilldown Drawer
 * Embeds Well-Architected 5-Pillar posture, recommendations, retirements, What-If score,
 * IQL workbooks, alerts, digests, and configuration directly inside the existing 8 domains
 * (65 panels) without adding any new top-level rail menu or redundant page bloat.
 * Invariants: >=12px typography, 0 colored left/top rails, 0 native browser tooltip attrs, AbortController,
 * honest not-measured fidelity, Fail-Closed 7-Safeguard Review+Fix drawer.
 */
(function () {
  "use strict";

  const st = {
    rg: "all",
    pillar: "all",
    viewing: "active",
    impact: "all",
    resourceType: "all",
    sort: "score_desc",
    groupBy: "none",
    riTerm: "P3Y",
    riLookback: 30,
    search: "",
    inFlight: new Map(),
    overview: null,
    score: null,
    simSelected: new Set(),
    activeRule: null,
    detailTab: "active",
    selectedResIds: new Set(),
    expandedResId: null,
    reviewFixPlan: null,
    lastConfig: null,
  };

  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c]));
  const fmtUsd = (n) => (n && n > 0 ? "$" + Number(n).toLocaleString("en-US") : "-");

  function advShowError(msg) {
    let host = document.getElementById("advInlineErrorToast");
    if (!host) {
      host = document.createElement("div");
      host.id = "advInlineErrorToast";
      host.setAttribute("role", "alert");
      host.setAttribute("aria-live", "assertive");
      host.style.cssText =
        "position:fixed;bottom:18px;right:18px;z-index:160;max-width:440px;padding:10px 14px;border:1px solid var(--sig-sec);border-radius:8px;background:var(--cs-card);color:var(--cs-text);box-shadow:var(--cs-shadow-lg);font-size:12.5px;display:flex;gap:10px;align-items:center;justify-content:space-between;";
      document.body.appendChild(host);
    }
    host.hidden = false;
    host.innerHTML = `<span><strong style="color:var(--sig-sec-text);">Advisor 요청 오류:</strong> ${esc(msg)}</span><button type="button" class="cs-btn cs-btn-sm" id="advErrCloseBtn">닫기</button>`;
    document.getElementById("advErrCloseBtn")?.addEventListener("click", () => {
      host.hidden = true;
    });
  }

  async function fetchJson(url, opts, slotKey) {
    const key = slotKey || url.split("?")[0];
    if (!opts || !opts.method || opts.method === "GET") {
      const prev = st.inFlight.get(key);
      if (prev) {
        try { prev.abort(); } catch (_e) {}
      }
    }
    const ctrl = new AbortController();
    st.inFlight.set(key, ctrl);
    try {
      const res = await fetch(url, Object.assign({}, opts || {}, { signal: ctrl.signal }));
      const ct = res.headers.get("content-type") || "";
      const data = ct.includes("application/json") ? await res.json() : { error: await res.text() };
      if (!res.ok) {
        const msg = data?.error || `HTTP ${res.status}`;
        advShowError(msg);
        throw new Error(msg);
      }
      return data;
    } catch (err) {
      if (err && err.name === "AbortError") return null;
      advShowError(err?.message || "네트워크 오류가 발생했습니다.");
      return null;
    } finally {
      if (st.inFlight.get(key) === ctrl) st.inFlight.delete(key);
    }
  }

  function syncAdvisorUrlState() {
    try {
      const sp = new URLSearchParams(location.search || "");
      const put = (k, v, defVal) => {
        if (!v || v === defVal) sp.delete(k);
        else sp.set(k, String(v));
      };
      put("adv_pillar", st.pillar, "all");
      put("adv_viewing", st.viewing, "active");
      put("adv_sort", st.sort, "score_desc");
      put("adv_rule", st.activeRule?.id || "", "");
      const qs = sp.toString();
      const next = qs ? `${location.pathname}?${qs}` : location.pathname;
      history.replaceState(history.state, "", next);
    } catch (_e) {}
  }

  function hydrateFromUrl() {
    try {
      const sp = new URLSearchParams(location.search || "");
      if (sp.get("adv_pillar")) st.pillar = sp.get("adv_pillar");
      if (sp.get("adv_viewing")) st.viewing = sp.get("adv_viewing");
      if (sp.get("adv_sort")) st.sort = sp.get("adv_sort");
      return sp.get("adv_rule") || "";
    } catch (_e) {
      return "";
    }
  }

  function impactPill(imp) {
    if (imp === "high") return `<span class="adv-pill is-high"><span class="adv-dot is-risk" style="margin:0;"></span>High</span>`;
    if (imp === "medium") return `<span class="adv-pill is-medium"><span class="adv-dot is-warn" style="margin:0;"></span>Medium</span>`;
    return `<span class="adv-pill is-low"><span class="adv-dot" style="margin:0;"></span>Low</span>`;
  }

  function costPill(tier) {
    const map = {
      no_cost_impact: ["비용 영향 없음", "is-low"],
      low: ["비용 파급: Low", "is-low"],
      medium: ["비용 파급: Medium", "is-medium"],
      high: ["비용 파급: High", "is-high"],
    };
    const [t, cls] = map[tier] || ["비용 데이터 없음", ""];
    return `<span class="adv-pill ${cls}">${t}</span>`;
  }

  function progressHtml(pct, active, total) {
    const p = Math.max(0, Math.min(100, Number(pct || 0)));
    const tone = p >= 75 ? "" : p >= 40 ? "is-warn" : "is-risk";
    return `<div class="adv-progress" data-ut-title="준수 진행률" data-ut-body="${total - active}/${total} 준수 (${p}%)"><div class="adv-progress-track"><div class="adv-progress-fill ${tone}" style="width:${p}%"></div></div><span class="adv-progress-label">${Math.round(p)}%</span></div>`;
  }

  function ensureDrawerDom() {
    let scrim = document.getElementById("advSharedDrawerScrim");
    if (scrim) return scrim;
    scrim = document.createElement("div");
    scrim.id = "advSharedDrawerScrim";
    scrim.className = "adv-drawer-scrim";
    scrim.hidden = true;
    scrim.setAttribute("role", "presentation");
    scrim.innerHTML = `
      <section class="adv-drawer" role="dialog" aria-modal="true" aria-labelledby="advSharedDrawerTitle">
        <header class="adv-drawer-head">
          <div>
            <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:4px;" id="advSharedDrawerBadges"></div>
            <h2 id="advSharedDrawerTitle" style="margin:0;font-size:16.5px;line-height:1.35;">권장사항 상세</h2>
            <div id="advSharedDrawerSub" style="font-size:12px;color:var(--cs-text-soft);margin-top:3px;"></div>
          </div>
          <div>
            <button type="button" class="cs-btn cs-btn-sm" id="advSharedAskBragiBtn">Bragi에게 질문</button>
            <button type="button" class="cs-btn cs-btn-sm" id="advSharedCreateAlertBtn">알림 규칙 만들기</button>
            <button type="button" class="cs-btn cs-btn-sm" id="advSharedCloseBtn" aria-label="상세 드로어 닫기">닫기 (Esc)</button>
          </div>
        </header>
        <div class="adv-drawer-body" id="advSharedDrawerBody"></div>
      </section>
    `;
    document.body.appendChild(scrim);
    const close = () => {
      scrim.hidden = true;
      st.activeRule = null;
      syncAdvisorUrlState();
    };
    document.getElementById("advSharedCloseBtn")?.addEventListener("click", close);
    scrim.addEventListener("click", (e) => { if (e.target === scrim) close(); });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !scrim.hidden) close();
    });
    document.getElementById("advSharedAskBragiBtn")?.addEventListener("click", () => {
      const r = st.activeRule;
      close();
      const chatBtn = document.querySelector("[data-open-chat-context], #fdaiChatToggleBtn");
      if (chatBtn) chatBtn.click();
      setTimeout(() => {
        const input = document.querySelector("#chatInput, textarea[data-chat-input]");
        if (input && r) {
          input.value = `Advisor 규칙 ${r.id}(${r.title_ko}) 활성 리소스 ${r.active_count}건의 비용·신뢰성 트레이드오프와 안전한 Fix PR 순서를 분석해줘.`;
          input.focus();
        }
      }, 120);
    });
    document.getElementById("advSharedCreateAlertBtn")?.addEventListener("click", () => {
      const r = st.activeRule;
      close();
      const qs = r ? `?adv_alert_rule=${encodeURIComponent(r.id)}&adv_alert_cat=${encodeURIComponent(r.pillar)}` : "";
      location.href = `/operations/alert-quality${qs}`;
    });
    return scrim;
  }

  async function openRuleDrawer(ruleId) {
    if (!ruleId) return;
    const scrim = ensureDrawerDom();
    st.detailTab = "active";
    st.selectedResIds.clear();
    st.expandedResId = null;
    st.reviewFixPlan = null;
    scrim.hidden = false;
    document.getElementById("advSharedDrawerTitle").textContent = "온톨로지 근거 불러오는 중...";
    document.getElementById("advSharedDrawerBody").innerHTML = `<div style="padding:20px;text-align:center;color:var(--cs-text-soft);font-size:13px;">실측 리소스·이웃 링크·권장 조치를 로드하고 있습니다...</div>`;

    const qs = new URLSearchParams({ rg: st.rg, ri_term: st.riTerm, ri_lookback: String(st.riLookback) });
    const data = await fetchJson(`/api/v4/advisor/recommendations/${encodeURIComponent(ruleId)}?${qs}`, null, "adv_detail");
    if (!data || !data.rule) {
      document.getElementById("advSharedDrawerTitle").textContent = "권장사항 조회 실패";
      document.getElementById("advSharedDrawerBody").innerHTML = `<div style="padding:16px;color:var(--cs-text-soft);font-size:13px;">${esc(data?.reason || data?.error || "데이터 미측정")}</div>`;
      return;
    }
    st.activeRule = data.rule;
    syncAdvisorUrlState();
    renderDrawerBody();
  }

  function renderReviewFixHtml(plan) {
    if (!plan) return "";
    return `
      <div class="adv-tradeoff-box">
        <div class="adv-tradeoff-head">
          <strong>15-에이전트 결정론적 Review + Fix (${plan.target_count}개 대상)</strong>
          <span class="adv-pill ${plan.execution_blocked ? "is-high" : "is-human"}">${plan.execution_blocked ? "Fail-Closed 차단됨 (7대 안전장치 미충족)" : "Canary Wave 1→2 · IaC Fix PR"}</span>
        </div>
        <div style="font-size:12px;color:var(--cs-text-soft);">${esc(plan.execution_authority_notice)}</div>
        <div style="display:flex;flex-direction:column;gap:6px;">
          ${(plan.pantheon_pipeline || []).map((s) => `
            <div class="adv-step-row">
              <span class="adv-step-num">${s.step}</span>
              <strong>${esc(s.agent)}</strong>
              <span>${esc(s.role)} — <span style="color:var(--cs-text-soft);">${esc(s.detail)}</span></span>
              <span class="adv-pill ${s.status === "blocked" ? "is-high" : s.status === "pending_approval" ? "is-human" : "is-low"}">${esc(s.status)}</span>
            </div>
          `).join("")}
        </div>
        <div style="font-size:12.5px;font-weight:700;margin-top:4px;">FDAI 헌법 7대 안전장치 검증</div>
        <div class="adv-safeguard-grid">
          ${(plan.seven_safeguards || []).map((sg) => `
            <div class="adv-safeguard-item">
              <span class="adv-dot ${sg.satisfied ? "" : "is-risk"}"></span>
              <div><strong>${esc(sg.label)}</strong><div style="color:var(--cs-text-soft);margin-top:2px;">${esc(sg.detail)}</div></div>
            </div>
          `).join("")}
        </div>
        <pre class="adv-code-box">${esc(plan.iac_fix_pr_preview || "")}</pre>
      </div>
    `;
  }

  function renderDrawerBody() {
    const r = st.activeRule;
    if (!r) return;
    document.getElementById("advSharedDrawerBadges").innerHTML = `
      ${impactPill(r.impact)}
      <span class="adv-pill">${esc(r.pillar)} · ${esc(r.subcategory)}</span>
      <span class="adv-pill is-human">담당: ${esc(r.owner_agent)} · 위험 ${esc(r.risk_tier)}</span>
      <span class="adv-score-delta-pill">+${r.potential_score_increase_pct}%p</span>
      ${r.retirement_days_left !== null && r.retirement_days_left !== undefined ? `<span class="adv-dday-pill ${r.retirement_days_left <= 45 ? "is-urgent" : "is-soon"}">은퇴 D-${r.retirement_days_left} (${esc(r.retirement_date)})</span>` : ""}
    `;
    document.getElementById("advSharedDrawerTitle").textContent = r.title_ko;
    document.getElementById("advSharedDrawerSub").textContent = `${r.title_en} · ${r.waf_ref} · 관측 ${r.last_refreshed_at} · 다운타임: ${r.downtime_class}`;

    const filtered = (r.instances || []).filter((i) => i.effective_bucket === st.detailTab);
    const body = document.getElementById("advSharedDrawerBody");
    body.innerHTML = `
      <div class="adv-two-col">
        <div class="adv-tradeoff-box">
          <div class="adv-tradeoff-head"><strong>문제 요약 · 잠재 이점</strong><a class="cs-btn cs-btn-sm" href="${esc(r.learn_more_url)}" target="_blank" rel="noopener">공식 문서 ↗</a></div>
          <div style="font-size:13px;line-height:1.5;">${esc(r.description_ko)}</div>
          <div style="font-size:12.5px;"><strong>잠재 이점:</strong> ${esc(r.benefits_ko)}</div>
          <div style="font-size:12.5px;color:var(--cs-text-soft);"><strong>조치 가이드:</strong> ${esc(r.remediation_ko)}</div>
          <div class="adv-inline-bar" style="margin-top:4px;">
            <span style="font-size:12px;color:var(--cs-text-soft);">Norns 피드백:</span>
            <button type="button" class="cs-btn cs-btn-sm" data-adv-fb="yes">유용함</button>
            <button type="button" class="cs-btn cs-btn-sm" data-adv-fb="no">오탐 · 개선 필요</button>
            <span id="advSharedFbMsg" style="font-size:12px;color:var(--sig-live-text);"></span>
          </div>
        </div>
        <div style="display:flex;flex-direction:column;gap:10px;">
          <div class="adv-tradeoff-box">
            <div class="adv-tradeoff-head"><strong>비용 파급 · 절감 (Njord)</strong>${r.total_yearly_savings_usd > 0 ? `<span class="adv-carbon-pill">추정 연 ${fmtUsd(r.total_yearly_savings_usd)}</span>` : costPill(r.cost_implication_tier)}</div>
            <ul class="adv-tradeoff-list">${(r.cost_factors || []).map((f) => `<li>${esc(f)}</li>`).join("")}</ul>
            ${r.total_yearly_carbon_kg_co2e > 0 ? `<div><span class="adv-carbon-pill">탄소 감축: ${r.total_yearly_carbon_kg_co2e} kgCO2e/년</span></div>` : ""}
          </div>
          <div class="adv-tradeoff-box">
            <div class="adv-tradeoff-head"><strong>트레이드오프 &amp; Odin 중재</strong><span class="adv-pill is-human">Odin</span></div>
            <div style="font-size:12.5px;color:var(--cs-text-soft);">${esc(r.reliability_tradeoff_ko)}</div>
            <div style="font-size:12.5px;font-weight:600;">${esc(r.odin_verdict_ko)}</div>
          </div>
        </div>
      </div>

      ${(r.cluster_hints || []).length ? `
        <div class="adv-tradeoff-box">
          <div class="adv-tradeoff-head"><strong>온톨로지 동일 패턴 클러스터링</strong><span class="adv-pill is-human">상위 템플릿 1곳 수정 권고</span></div>
          ${r.cluster_hints.map((h) => `<div style="font-size:12.5px;color:var(--cs-text-soft);">• <strong>${esc(h.pattern)}</strong> (${h.count}개) — ${esc(h.suggestion)}</div>`).join("")}
        </div>
      ` : ""}

      ${renderReviewFixHtml(st.reviewFixPlan)}

      <div class="adv-tradeoff-box">
        <div class="adv-tradeoff-head">
          <strong>영향 리소스 (4-상태 거버넌스 · 행 클릭 시 실측 JSONB 근거 + 이웃 링크)</strong>
          <span class="adv-pill">ActionType: ${esc(r.action_type_ref)}</span>
        </div>
        <div class="adv-state-tabs" role="tablist">
          ${[
            ["active", "활성", r.active_count],
            ["completed", "완료·준수", r.completed_count],
            ["postponed", "연기됨", r.postponed_count],
            ["dismissed", "예외 처리", r.dismissed_count],
          ].map(([k, lbl, cnt]) => `<button type="button" role="tab" class="adv-state-tab ${st.detailTab === k ? "is-active" : ""}" aria-selected="${st.detailTab === k}" data-adv-dtab="${k}">${lbl} <span class="adv-state-count">${cnt}</span></button>`).join("")}
        </div>
        <div class="adv-bulk-bar">
          <span id="advSharedSelCnt">선택 ${st.selectedResIds.size}개</span>
          <div class="adv-inline-bar">
            <input type="text" class="cs-input" id="advSharedReasonInput" value="다음 변경 창(ChangeWindow) 승인 반영 예정" placeholder="연기/예외 사유 (최소 8자)" style="min-width:190px;height:30px;font-size:12px;">
            <button type="button" class="cs-btn cs-btn-sm cs-btn-primary" id="advSharedReviewFixBtn">15-에이전트 Review + Fix</button>
            <button type="button" class="cs-btn cs-btn-sm" data-adv-disp="complete">완료 표시</button>
            <button type="button" class="cs-btn cs-btn-sm" data-adv-disp="postpone">14일 연기</button>
            <button type="button" class="cs-btn cs-btn-sm" data-adv-disp="dismiss">예외 처리</button>
            ${st.detailTab !== "active" ? `<button type="button" class="cs-btn cs-btn-sm" data-adv-disp="reopen">재활성화</button>` : ""}
          </div>
        </div>
        <div class="adv-inline-table-wrap">
          <table class="adv-inline-table">
            <thead>
              <tr>
                <th style="width:30px;"><input type="checkbox" id="advSharedSelAll" aria-label="리소스 전체 선택"></th>
                <th>리소스</th>
                <th>상태</th>
                <th>RG · 리전</th>
                <th>이웃 링크</th>
                <th>조치</th>
              </tr>
            </thead>
            <tbody>
              ${filtered.length ? filtered.map((inst) => {
                const exp = st.expandedResId === inst.resource_id;
                const badge = inst.customer_state === "originally_compliant"
                  ? `<span class="adv-pill is-low">사전 준수</span>`
                  : inst.customer_state === "manually_completed"
                  ? `<span class="adv-pill is-medium">수동 완료</span>`
                  : inst.customer_state === "postponed"
                  ? `<span class="adv-pill is-medium">연기 ~${esc((inst.postponed_until || "").slice(0, 10))}</span>`
                  : inst.customer_state === "dismissed"
                  ? `<span class="adv-pill">예외</span>`
                  : `<span class="adv-pill is-high">활성</span>`;
                return `
                  <tr class="adv-click-row" data-adv-exp="${esc(inst.resource_id)}">
                    <td onclick="event.stopPropagation();"><input type="checkbox" class="adv-shared-rcb" value="${esc(inst.resource_id)}" ${st.selectedResIds.has(inst.resource_id) ? "checked" : ""}></td>
                    <td><strong>${esc(inst.resource_name)}</strong><div style="font-size:12px;color:var(--cs-text-soft);">${esc(inst.resource_type)} · env:${esc(inst.environment)}</div></td>
                    <td>${badge}</td>
                    <td>${esc(inst.resource_group)} (${esc(inst.location)})</td>
                    <td><span class="adv-pill">${inst.neighbors_count}개</span></td>
                    <td onclick="event.stopPropagation();"><button type="button" class="cs-btn cs-btn-sm" data-adv-sfix="${esc(inst.resource_id)}">Fix</button></td>
                  </tr>
                  ${exp ? `
                    <tr><td colspan="6" style="background:var(--cs-shade);">
                      <div class="adv-two-col">
                        <div><div style="font-size:12px;font-weight:700;margin-bottom:4px;">실측 JSONB 근거</div><pre class="adv-code-box">${esc(JSON.stringify(inst.evidence, null, 2))}</pre></div>
                        <div><div style="font-size:12px;font-weight:700;margin-bottom:4px;">온톨로지 이웃 (${inst.neighbors_count}건)</div>
                          ${(inst.neighbors || []).length ? `<ul class="adv-tradeoff-list">${inst.neighbors.map((n) => `<li><code>${esc(n.direction)}:${esc(n.link_type)}</code> → ${esc(n.target.split("/").slice(-2).join("/"))}</li>`).join("")}</ul>` : `<div style="font-size:12px;color:var(--cs-text-soft);">직접 연결된 이웃 링크 없음</div>`}
                        </div>
                      </div>
                    </td></tr>
                  ` : ""}
                `;
              }).join("") : `<tr><td colspan="6" style="text-align:center;padding:16px;color:var(--cs-text-soft);">해당 상태(${esc(st.detailTab)})의 리소스가 없습니다.</td></tr>`}
            </tbody>
          </table>
        </div>
      </div>
    `;

    body.querySelectorAll("[data-adv-dtab]").forEach((b) => {
      b.addEventListener("click", () => {
        st.detailTab = b.getAttribute("data-adv-dtab") || "active";
        st.selectedResIds.clear();
        renderDrawerBody();
      });
    });
    body.querySelectorAll("tr[data-adv-exp]").forEach((tr) => {
      tr.addEventListener("click", () => {
        const id = tr.getAttribute("data-adv-exp");
        st.expandedResId = st.expandedResId === id ? null : id;
        renderDrawerBody();
      });
    });
    body.querySelectorAll(".adv-shared-rcb").forEach((cb) => {
      cb.addEventListener("change", () => {
        if (cb.checked) st.selectedResIds.add(cb.value);
        else st.selectedResIds.delete(cb.value);
        const el = document.getElementById("advSharedSelCnt");
        if (el) el.textContent = `선택 ${st.selectedResIds.size}개`;
      });
    });
    document.getElementById("advSharedSelAll")?.addEventListener("change", (e) => {
      filtered.forEach((i) => {
        if (e.target.checked) st.selectedResIds.add(i.resource_id);
        else st.selectedResIds.delete(i.resource_id);
      });
      renderDrawerBody();
    });
    const runFix = async (ids) => {
      const plan = await fetchJson(`/api/v4/advisor/recommendations/${encodeURIComponent(r.id)}/review-fix`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resource_ids: ids || [] }),
      }, "adv_review_fix");
      if (plan) {
        st.reviewFixPlan = plan;
        renderDrawerBody();
      }
    };
    document.getElementById("advSharedReviewFixBtn")?.addEventListener("click", () => runFix(Array.from(st.selectedResIds)));
    body.querySelectorAll("[data-adv-sfix]").forEach((b) => {
      b.addEventListener("click", () => runFix([b.getAttribute("data-adv-sfix")]));
    });
    body.querySelectorAll("[data-adv-disp]").forEach((b) => {
      b.addEventListener("click", async () => {
        const action = b.getAttribute("data-adv-disp");
        const ids = st.selectedResIds.size ? Array.from(st.selectedResIds) : filtered.slice(0, 1).map((i) => i.resource_id);
        if (!ids.length) return;
        const reason = (document.getElementById("advSharedReasonInput")?.value || "").trim();
        if ((action === "postpone" || action === "dismiss") && reason.length < 8) {
          advShowError("연기 또는 예외 처리 시 최소 8자 이상의 거버넌스 사유를 입력하세요.");
          return;
        }
        const ok = await fetchJson(`/api/v4/advisor/recommendations/${encodeURIComponent(r.id)}/disposition`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ resource_ids: ids, action, reason, postpone_days: 14 }),
        }, "adv_disp");
        if (ok) {
          await openRuleDrawer(r.id);
          enhanceActivePanel(true);
        }
      });
    });
    body.querySelectorAll("[data-adv-fb]").forEach((b) => {
      b.addEventListener("click", async () => {
        const helpful = b.getAttribute("data-adv-fb") === "yes";
        const res = await fetchJson(`/api/v4/advisor/recommendations/${encodeURIComponent(r.id)}/feedback`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ helpful, reason: helpful ? "operator_helpful" : "needs_tuning" }),
        }, "adv_fb");
        if (res) {
          const el = document.getElementById("advSharedFbMsg");
          if (el) el.textContent = `Norns 학습 큐 등록 (누적 ${res.total_feedback_for_rule}건)`;
        }
      });
    });
  }

  /* ── 1. /overview/dashboard (1-line KPI parity + synced #fdaiDrawer Advisor section + compact bottom disclosure) ── */
  function syncGovCardFooterAndDrawer(govCard, data) {
    if (!govCard || !data) return;
    // Remove any legacy extra second line so all 4 KPI cards keep identical 1-line footer height
    govCard.querySelectorAll("[data-adv-kpi-line]").forEach((el) => el.remove());

    const s = data.summary || {};
    const foots = govCard.querySelectorAll(".kpi-foot span");
    if (foots[1]) {
      const nextText = data.measured
        ? `포스처 ${data.overall_score_pct}% · 은퇴 ${s.active_retirements ?? 0}건`
        : "포스처 미측정";
      if (foots[1].textContent !== nextText) {
        foots[1].textContent = nextText;
      }
      foots[1].setAttribute("data-ut-title", "Advisor 포스처 요약");
      foots[1].setAttribute(
        "data-ut-body",
        data.measured
          ? `종합 ${data.overall_score_pct}% · 활성 권장 ${s.active_recommendations}/${s.total_rules_evaluated} · 서비스 은퇴 ${s.active_retirements}건 · 연 추정 절감 ${fmtUsd(s.total_yearly_savings_usd)}`
          : "PostgreSQL 실측 인벤토리 미연결 — 미측정(not-measured) 유지"
      );
    }

    // Merge Advisor facts cleanly into govCard's data-drawer-facts without duplicating
    const baseFacts = (govCard.getAttribute("data-drawer-facts") || "")
      .split(";")
      .filter((p) => p && !p.startsWith("Advisor 포스처|") && !p.startsWith("개선 권장 · 은퇴|"));
    if (data.measured) {
      const pText = (data.pillars || [])
        .map((p) => `${p.label_ko} ${p.measured ? `${p.score_pct}%` : "미측정"}`)
        .join(" · ");
      baseFacts.push(`Advisor 포스처|${data.overall_score_pct}% (${pText})`);
      baseFacts.push(
        `개선 권장 · 은퇴|활성 ${s.active_recommendations}/${s.total_rules_evaluated}규칙 · 은퇴 ${s.active_retirements}건 · 연 추정 절감 ${fmtUsd(s.total_yearly_savings_usd)}`
      );
    } else {
      baseFacts.push("Advisor 포스처|미측정 (not-measured)");
    }
    const mergedFacts = baseFacts.join(";");
    if (govCard.getAttribute("data-drawer-facts") !== mergedFacts) {
      govCard.setAttribute("data-drawer-facts", mergedFacts);
    }
    govCard.setAttribute("data-adv-gov-card", "1");
  }

  function renderAdvisorInSharedOverviewDrawer(isGovCard) {
    const panel = document.querySelector("#fdaiDrawerPanel .drawer-body");
    if (!panel) return;
    let sec = document.getElementById("advOverviewDrawerSection");
    if (!isGovCard || !st.overview) {
      if (sec) sec.hidden = true;
      return;
    }
    if (!sec) {
      sec = document.createElement("div");
      sec.id = "advOverviewDrawerSection";
      sec.className = "adv-tradeoff-box";
      sec.style.marginTop = "12px";
      panel.appendChild(sec);
    }
    sec.hidden = false;
    const data = st.overview;
    const s = data.summary || {};
    const pillarsHtml = (data.pillars || [])
      .map(
        (p) =>
          `<a class="adv-pill" href="/governance/rules?adv_pillar=${encodeURIComponent(p.pillar)}">${esc(p.label_ko)} <strong>${p.measured ? `${p.score_pct}%` : "미측정"}</strong></a>`
      )
      .join("");
    const qw = (data.quick_wins || []).slice(0, 3);
    sec.innerHTML = `
      <div class="adv-tradeoff-head">
        <strong>Well-Architected Advisor 포스처 (${data.measured ? `${data.overall_score_pct}%` : "미측정"})</strong>
        <span class="adv-pill ${data.measured ? "is-low" : ""}">활성 ${s.active_recommendations ?? "-"}/${s.total_rules_evaluated ?? "-"} · 은퇴 ${s.active_retirements ?? 0}건</span>
      </div>
      <div class="adv-inline-bar">${pillarsHtml}</div>
      ${qw.length ? `
        <div style="display:flex;flex-direction:column;gap:6px;margin-top:4px;">
          <div style="font-size:12px;font-weight:700;color:var(--cs-text-soft);">우선 개선 Quick-Win (클릭 시 4-상태 · Review+Fix 드로어)</div>
          ${qw.map((r) => `
            <button type="button" class="adv-rec-btn" data-adv-drawer-jump="${esc(r.id)}" style="display:flex;align-items:center;justify-content:space-between;gap:8px;padding:7px 10px;border:1px solid var(--cs-hairline);border-radius:6px;background:var(--cs-card);width:100%;">
              <span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(r.title_ko)}</span>
              <span class="adv-score-delta-pill">+${r.potential_score_increase_pct}%p</span>
            </button>
          `).join("")}
        </div>
      ` : ""}
      <div class="adv-inline-bar" style="margin-top:4px;">
        <a class="cs-btn cs-btn-sm" href="/overview/verticals">점수 · What-If →</a>
        <a class="cs-btn cs-btn-sm" href="/governance/rules">전체 권장사항 · 은퇴 →</a>
      </div>
    `;
    sec.querySelectorAll("[data-adv-drawer-jump]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const ruleId = btn.getAttribute("data-adv-drawer-jump");
        document.getElementById("fdaiDrawerClose")?.click();
        if (ruleId) openRuleDrawer(ruleId);
      });
    });
  }

  function wireGovCardDrawerBridge(govCard) {
    if (!govCard || govCard.dataset.advBridgeWired === "1") return;
    govCard.dataset.advBridgeWired = "1";

    // Re-sync 1-line footer & drawer facts if overview.html live hydration updates cards[3]
    let syncing = false;
    const obs = new MutationObserver(() => {
      if (syncing || !st.overview) return;
      syncing = true;
      try {
        syncGovCardFooterAndDrawer(govCard, st.overview);
      } finally {
        syncing = false;
      }
    });
    obs.observe(govCard, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["data-drawer-facts"] });

    // Delegate click across dashboard triggers so #fdaiDrawer always matches the clicked card
    if (!document.body.dataset.advDrawerClickWired) {
      document.body.dataset.advDrawerClickWired = "1";
      document.addEventListener("click", (e) => {
        const trg = e.target instanceof Element ? e.target.closest("[data-drawer-title]") : null;
        if (!trg) return;
        const isGov = trg.getAttribute("data-adv-gov-card") === "1";
        setTimeout(() => renderAdvisorInSharedOverviewDrawer(isGov), 30);
      });
    }
  }

  async function enhanceDashboard(forceRefresh) {
    const panel = document.querySelector('.panel-view[data-panel-id="dashboard"]');
    if (!panel || panel.hidden) return;
    const qs = new URLSearchParams({ rg: st.rg, ri_term: st.riTerm, ri_lookback: String(st.riLookback) });
    if (forceRefresh) qs.set("refresh", "1");
    const data = await fetchJson(`/api/v4/advisor/overview?${qs}`, null, "adv_ov");
    if (!data) return;
    st.overview = data;

    // 1a. Keep all 4 KPI cards at identical 1-line footer height & sync #fdaiDrawer
    const kpiCards = panel.querySelectorAll(".kpi-grid > *");
    const govCard = kpiCards[3];
    if (govCard) {
      syncGovCardFooterAndDrawer(govCard, data);
      wireGovCardDrawerBridge(govCard);
    }

    // 1b. Attach full-width compact inline disclosure below the existing dashboard grid (zero disruption to 2-column chart layout)
    let box = panel.querySelector("#advDashInlineMount");
    if (!box) {
      box = document.createElement("details");
      box.id = "advDashInlineMount";
      box.className = "adv-inline-disclosure";
      box.style.gridColumn = "1 / -1";
      panel.appendChild(box);
    }
    const s = data.summary || {};
    const pills = (data.pillars || [])
      .map((p) => `<a class="adv-pill" href="/governance/rules?adv_pillar=${encodeURIComponent(p.pillar)}" onclick="event.stopPropagation();">${esc(p.label_ko)} <strong>${p.measured ? `${p.score_pct}%` : "미측정"}</strong></a>`)
      .join(" ");
    const qw = data.quick_wins || [];
    const shNote = data.service_health_status?.state === "not-measured"
      ? `<span class="adv-pill" data-ut-title="Service Health 상태" data-ut-body="${esc(data.service_health_status.message || "")}">Service Health: 미측정</span>`
      : "";
    box.innerHTML = `
      <summary>
        <span>Well-Architected 개선 권장 · 포스처 요약 (${data.measured ? `${data.overall_score_pct}% · 활성 ${s.active_recommendations}건 · 연 추정 절감 ${fmtUsd(s.total_yearly_savings_usd)}` : "미측정"})</span>
        <span class="adv-inline-bar">${pills} ${shNote}</span>
      </summary>
      <div class="adv-inline-body">
        <div class="adv-inline-bar" style="justify-content:space-between;">
          <span style="font-size:12.5px;color:var(--cs-text-soft);">Odin·Njord·Freyr 선별 우선 개선 항목(클릭 시 4-상태·근거·15-에이전트 Review+Fix 드로어)</span>
          <div class="adv-inline-bar">
            <a class="cs-btn cs-btn-sm" href="/overview/verticals">점수 · What-If →</a>
            <a class="cs-btn cs-btn-sm" href="/governance/rules">전체 32규칙 · 은퇴 →</a>
            <a class="cs-btn cs-btn-sm" href="/api/v4/advisor/export?format=csv">CSV</a>
          </div>
        </div>
        <div class="adv-inline-table-wrap">
          <table class="adv-inline-table">
            <thead><tr><th>권장사항 (Quick-Win Top 4)</th><th>필러 · 담당</th><th>활성 리소스</th><th>점수 상승</th><th>비용 파급 / 추정 절감</th></tr></thead>
            <tbody>
              ${qw.length ? qw.map((r) => `
                <tr class="adv-click-row" data-adv-open="${esc(r.id)}">
                  <td><button type="button" class="adv-rec-btn" data-adv-open="${esc(r.id)}">${esc(r.title_ko)}</button></td>
                  <td><span class="adv-pill">${esc(r.pillar_label_ko)} · ${esc(r.owner_agent)}</span></td>
                  <td><strong>${r.active_count}</strong> / ${r.total_evaluated}</td>
                  <td><span class="adv-score-delta-pill">+${r.potential_score_increase_pct}%p</span></td>
                  <td>${r.total_yearly_savings_usd > 0 ? `<span class="adv-carbon-pill">연 ${fmtUsd(r.total_yearly_savings_usd)}</span>` : costPill(r.cost_implication_tier)}</td>
                </tr>
              `).join("") : `<tr><td colspan="5" style="text-align:center;color:var(--cs-text-soft);padding:12px;">활성 Quick-Win 없음 또는 미측정 상태</td></tr>`}
            </tbody>
          </table>
        </div>
      </div>
    `;
    bindOpenTriggers(box);
  }

  /* ── 2. /overview/verticals (In-place 5-Pillar Advisor Score + Formula + What-If Simulator) ── */
  async function enhanceVerticals(forceRefresh) {
    const panel = document.querySelector('.panel-view[data-panel-id="verticals"]');
    if (!panel || panel.hidden) return;
    const qs = new URLSearchParams({ rg: st.rg, ri_term: st.riTerm, ri_lookback: String(st.riLookback) });
    if (forceRefresh) qs.set("refresh", "1");
    const data = await fetchJson(`/api/v4/advisor/score?${qs}`, null, "adv_score");
    if (!data) return;
    st.score = data;

    let box = panel.querySelector("#advVertScoreMount");
    if (!box) {
      box = document.createElement("details");
      box.id = "advVertScoreMount";
      box.className = "adv-inline-disclosure";
      box.open = true;
      panel.appendChild(box);
    }
    const measuredPillars = (data.pillars || []).filter((p) => p.measured && p.score_pct !== null);
    const measuredPillarsCount = measuredPillars.length;
    const ranked = (data.ranked_recommendations || []).slice(0, 12);
    const ft = data.formula_transparency || {};
    box.innerHTML = `
      <summary>
        <span>Advisor 5대 필러 점수 · What-If 시뮬레이터 (종합 ${data.measured ? `${data.overall_score_pct}%` : "미측정"} · 실측 앵커)</span>
        <span class="adv-inline-bar">
          ${(data.pillars || []).map((p) => `<span class="adv-pill">${esc(p.label_ko)} <strong>${p.measured ? `${p.score_pct}%` : "미측정"}</strong></span>`).join("")}
        </span>
      </summary>
      <div class="adv-inline-body">
        <div class="adv-inline-bar" style="justify-content:space-between;">
          <span style="font-size:12.5px;color:var(--cs-text-soft);">${esc(data.history_notice || "")} · 산식 <code>${esc(data.formula_version)}</code> (High 3 / Med 2 / Low 1 · 제외 ${ft.excluded_resources_count ?? 0}개)</span>
          <strong id="advVertWhatIfOut" style="font-size:13px;color:var(--sig-live-text);">체크박스로 목표 점수 시뮬레이션 (실측 ${measuredPillarsCount}필러)</strong>
        </div>
        <div class="adv-inline-table-wrap">
          <table class="adv-inline-table">
            <thead><tr><th style="width:32px;"></th><th>권장사항 (점수 상승 우선)</th><th>필러</th><th>잠재 점수 상승</th><th>활성 리소스</th><th>추정 절감 / 파급</th></tr></thead>
            <tbody>
              ${ranked.map((r) => `
                <tr class="adv-click-row" data-adv-open="${esc(r.id)}">
                  <td onclick="event.stopPropagation();"><input type="checkbox" class="adv-vsim-cb" value="${esc(r.id)}" ${st.simSelected.has(r.id) ? "checked" : ""}></td>
                  <td><button type="button" class="adv-rec-btn" data-adv-open="${esc(r.id)}">${esc(r.title_ko)}</button></td>
                  <td><span class="adv-pill">${esc(r.pillar_label_ko)}</span></td>
                  <td><span class="adv-score-delta-pill">+${r.potential_score_increase_pct}%p</span></td>
                  <td>${r.active_count} / ${r.total_evaluated}</td>
                  <td>${r.total_yearly_savings_usd > 0 ? `<span class="adv-carbon-pill">연 ${fmtUsd(r.total_yearly_savings_usd)}</span>` : costPill(r.cost_implication_tier)}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      </div>
    `;
    bindOpenTriggers(box);
    const recalc = () => {
      const chosen = (data.ranked_recommendations || []).filter((r) => st.simSelected.has(r.id));
      const out = document.getElementById("advVertWhatIfOut");
      if (!out) return;
      if (!chosen.length || measuredPillarsCount === 0) {
        out.textContent = `선택 0건 · 현재 종합 ${data.overall_score_pct ?? "미측정"}% (실측 ${measuredPillarsCount}필러)`;
        return;
      }
      const pmap = new Map(measuredPillars.map((p) => [p.pillar, Number(p.score_pct)]));
      for (const r of chosen) {
        if (pmap.has(r.pillar)) pmap.set(r.pillar, Math.min(100, pmap.get(r.pillar) + Number(r.potential_score_increase_pct || 0)));
      }
      const next = Array.from(pmap.values()).reduce((a, b) => a + b, 0) / measuredPillarsCount;
      const curr = Number(data.overall_score_pct || 0);
      const sav = chosen.reduce((a, r) => a + Number(r.total_yearly_savings_usd || 0), 0);
      const carb = chosen.reduce((a, r) => a + Number(r.total_yearly_carbon_kg_co2e || 0), 0);
      out.textContent = `선택 ${chosen.length}건 해결 시: 종합 ${curr.toFixed(1)}% → ${next.toFixed(1)}% (+${Math.max(0, next - curr).toFixed(1)}%p) · 추정 연 ${fmtUsd(sav)} · ${carb.toFixed(2)} kgCO2e`;
    };
    box.querySelectorAll(".adv-vsim-cb").forEach((cb) => {
      cb.addEventListener("change", () => {
        if (cb.checked) st.simSelected.add(cb.value);
        else st.simSelected.delete(cb.value);
        recalc();
      });
    });
    recalc();
  }

  /* ── 3. /overview/cost-governance & /overview/llm-cost ── */
  async function enhanceCost(panelId) {
    const panel = document.querySelector(`.panel-view[data-panel-id="${panelId}"]`);
    if (!panel || panel.hidden) return;
    const qs = new URLSearchParams({ pillar: "cost", viewing: "active", ri_term: st.riTerm, ri_lookback: String(st.riLookback) });
    const data = await fetchJson(`/api/v4/advisor/recommendations?${qs}`, null, `adv_${panelId}`);
    if (!data) return;
    const items = panelId === "llm-cost"
      ? (data.items || []).filter((r) => r.id === "adv.cost.llm-capacity-opt")
      : (data.items || []);

    let box = panel.querySelector(`#advInline_${panelId}`);
    if (!box) {
      box = document.createElement("details");
      box.id = `advInline_${panelId}`;
      box.className = "adv-inline-disclosure";
      box.open = true;
      panel.appendChild(box);
    }
    const k = data.kpi || {};
    box.innerHTML = `
      <summary>
        <span>${panelId === "llm-cost" ? "LLM 용량 · 라우팅 최적화 권장사항" : `Advisor 비용 · 탄소 최적화 권장사항 (${items.length}건 · 추정 연 ${fmtUsd(k.total_yearly_savings_usd)} · ${k.total_yearly_carbon_kg_co2e ?? 0} kgCO2e)`}</span>
        <span class="adv-inline-bar" onclick="event.stopPropagation();">
          ${panelId === "cost-governance" ? `
            <select class="cs-select" id="advCostRiSel" aria-label="RI 약정 기간" style="height:28px;font-size:12px;">
              <option value="P3Y" ${st.riTerm === "P3Y" ? "selected" : ""}>RI/SP: 3년 (P3Y)</option>
              <option value="P1Y" ${st.riTerm === "P1Y" ? "selected" : ""}>RI/SP: 1년 (P1Y)</option>
            </select>
            <select class="cs-select" id="advCostLbSel" aria-label="Lookback 기간" style="height:28px;font-size:12px;">
              <option value="30" ${st.riLookback === 30 ? "selected" : ""}>Lookback: 30일</option>
              <option value="7" ${st.riLookback === 7 ? "selected" : ""}>Lookback: 7일</option>
              <option value="60" ${st.riLookback === 60 ? "selected" : ""}>Lookback: 60일</option>
            </select>
          ` : ""}
        </span>
      </summary>
      <div class="adv-inline-body">
        <div class="adv-inline-table-wrap">
          <table class="adv-inline-table">
            <thead><tr><th>비용 권장사항 (SKU 휴리스틱 추정치 포함)</th><th>영향도</th><th>활성 리소스</th><th>연간 추정 절감</th><th>단가 기준 · 탄소</th></tr></thead>
            <tbody>
              ${items.map((r) => `
                <tr class="adv-click-row" data-adv-open="${esc(r.id)}">
                  <td><button type="button" class="adv-rec-btn" data-adv-open="${esc(r.id)}">${esc(r.title_ko)}</button></td>
                  <td>${impactPill(r.impact)}</td>
                  <td><strong>${r.active_count}</strong> / ${r.total_evaluated}</td>
                  <td><strong style="color:var(--sig-live-text);">${fmtUsd(r.total_yearly_savings_usd)}/년</strong></td>
                  <td><span class="adv-pill">${esc(r.pricing_basis || "Retail")}</span> ${r.total_yearly_carbon_kg_co2e > 0 ? `<span class="adv-carbon-pill">${r.total_yearly_carbon_kg_co2e} kgCO2e</span>` : ""}</td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      </div>
    `;
    bindOpenTriggers(box);
    box.querySelector("#advCostRiSel")?.addEventListener("change", (e) => { st.riTerm = e.target.value; enhanceCost(panelId); });
    box.querySelector("#advCostLbSel")?.addEventListener("change", (e) => { st.riLookback = Number(e.target.value || 30); enhanceCost(panelId); });
  }

  /* ── 4. /governance/rules (Unified Well-Architected 5-Pillar Rail Pane — Lazy Loaded on Tab Click) ── */
  async function enhanceGovernanceRules(explicitHost) {
    const panel = document.querySelector('.panel-view[data-panel-id="rules"]');
    if (!panel || panel.hidden) return;
    const host = explicitHost || panel.querySelector("#govAdvisorWafPane");
    // Only render into the dedicated rail tab pane (#govAdvisorWafPane) when active; never bolt onto bottom of rules table.
    if (!host || host.hidden) return;

    host.setAttribute("aria-busy", "true");
    const qs = new URLSearchParams({
      rg: st.rg,
      pillar: st.pillar,
      viewing: st.viewing,
      impact: st.impact,
      resource_type: st.resourceType,
      sort: st.sort,
      search: st.search,
      ri_term: st.riTerm,
      ri_lookback: String(st.riLookback),
    });
    const [recs, assess] = await Promise.all([
      fetchJson(`/api/v4/advisor/recommendations?${qs}`, null, "adv_gov_rules"),
      fetchJson("/api/v4/advisor/assessments", null, "adv_gov_assess"),
    ]);
    host.setAttribute("aria-busy", "false");
    if (!recs) return;
    syncAdvisorUrlState();

    const items = recs.items || [];
    const k = recs.kpi || {};
    const assessList = assess?.items || [];
    const railCnt = document.getElementById("govAdvWafCount");
    if (railCnt && typeof k.matching_recommendations === "number") {
      railCnt.textContent = `${Number(k.matching_recommendations).toLocaleString("ko-KR")}건`;
    }
    const maxBoost = items.reduce((mx, r) => Math.max(mx, Number(r.potential_score_increase_pct || 0)), 0);

    host.innerHTML = `
      <div class="card-head" style="margin-bottom:10px;">
        <div>
          <h3 class="card-title">Well-Architected 5대 필러 개선 권장 · 서비스 은퇴 · 워크로드 평가</h3>
          <p class="card-desc">Azure Well-Architected 5대 필러 기준 실측 개선 권장사항과 서비스 은퇴(D-Day)를 탐색하고, 항목 클릭 시 우측 Review+Fix 드로어에서 7대 안전장치 검증을 진행합니다.</p>
        </div>
        <div class="toolbar-inline">
          <a class="cs-btn cs-btn-sm" href="/api/v4/advisor/export?format=csv&pillar=${encodeURIComponent(st.pillar)}">CSV 내보내기</a>
          <a class="cs-btn cs-btn-sm" href="/api/v4/advisor/export?format=json&pillar=${encodeURIComponent(st.pillar)}">JSON 내보내기</a>
        </div>
      </div>

      <div class="gov-sec-kpi-grid" aria-label="Well-Architected 핵심 요약">
        <div class="gov-sec-kpi">
          <span class="gov-sec-kpi-label">매칭 개선 권장</span>
          <strong class="gov-sec-kpi-val">${Number(k.matching_recommendations ?? items.length).toLocaleString("ko-KR")}건</strong>
          <span class="gov-sec-kpi-sub">5대 필러 · 서비스 은퇴 포함</span>
        </div>
        <div class="gov-sec-kpi">
          <span class="gov-sec-kpi-label">활성 영향 리소스</span>
          <strong class="gov-sec-kpi-val">${Number(k.active_resources ?? 0).toLocaleString("ko-KR")} / ${Number(k.evaluated_resources ?? 0).toLocaleString("ko-KR")}</strong>
          <span class="gov-sec-kpi-sub">실시간 평가 기준</span>
        </div>
        <div class="gov-sec-kpi">
          <span class="gov-sec-kpi-label">최대 점수 상승 여력</span>
          <strong class="gov-sec-kpi-val">+${maxBoost.toFixed(1)}%p</strong>
          <span class="gov-sec-kpi-sub">우선 개선 항목 적용 시</span>
        </div>
        <div class="gov-sec-kpi">
          <span class="gov-sec-kpi-label">워크로드 평가 이력</span>
          <strong class="gov-sec-kpi-val">${Number(assessList.length).toLocaleString("ko-KR")}건</strong>
          <span class="gov-sec-kpi-sub">WARA 393 · WAF 59 실측</span>
        </div>
      </div>

      <div class="gov-facet-bar" role="search" aria-label="Well-Architected 필터" style="margin-bottom:12px;">
        <div class="gov-facet-search-row">
          <div class="search-wrap">
            <svg class="search-ico" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="7" cy="7" r="4.8"/><path d="M10.7 10.7L14 14"/></svg>
            <input type="search" class="cs-input search-input" id="advGovSearch" value="${esc(st.search)}" placeholder="규칙 · 은퇴 · 리소스 검색..." aria-label="권장사항 검색">
          </div>
          <button type="button" class="cs-btn cs-btn-sm" id="advGovResetBtn">초기화</button>
        </div>
        <select class="cs-select" id="advGovPillarSel" aria-label="필러 필터">
          <option value="all" ${st.pillar === "all" ? "selected" : ""}>필러: 전체 (5대)</option>
          <option value="cost" ${st.pillar === "cost" ? "selected" : ""}>비용 최적화</option>
          <option value="security" ${st.pillar === "security" ? "selected" : ""}>보안</option>
          <option value="reliability" ${st.pillar === "reliability" ? "selected" : ""}>신뢰성 · 은퇴</option>
          <option value="operational_excellence" ${st.pillar === "operational_excellence" ? "selected" : ""}>운영 우수성</option>
          <option value="performance" ${st.pillar === "performance" ? "selected" : ""}>성능</option>
        </select>
        <select class="cs-select" id="advGovViewSel" aria-label="상태 필터">
          <option value="active" ${st.viewing === "active" ? "selected" : ""}>상태: 활성 (Active)</option>
          <option value="completed" ${st.viewing === "completed" ? "selected" : ""}>완료 · 준수 (Completed)</option>
          <option value="postponed" ${st.viewing === "postponed" ? "selected" : ""}>연기됨 (Postponed)</option>
          <option value="dismissed" ${st.viewing === "dismissed" ? "selected" : ""}>예외 처리 (Dismissed)</option>
          <option value="all" ${st.viewing === "all" ? "selected" : ""}>전체 상태</option>
        </select>
        <select class="cs-select" id="advResourceTypeFilter" aria-label="리소스 유형 필터">
          <option value="all">리소스 유형: 전체 (${(recs.resource_types || []).length})</option>
          ${(recs.resource_types || []).map((rt) => `<option value="${esc(rt)}" ${st.resourceType === rt ? "selected" : ""}>${esc(rt)}</option>`).join("")}
        </select>
        <select class="cs-select" id="advSortFilter" aria-label="정렬 기준">
          <option value="score_desc" ${st.sort === "score_desc" ? "selected" : ""}>정렬: 점수 상승순</option>
          <option value="savings_desc" ${st.sort === "savings_desc" ? "selected" : ""}>정렬: 연간 절감순</option>
          <option value="active_desc" ${st.sort === "active_desc" ? "selected" : ""}>정렬: 활성 리소스순</option>
          <option value="impact_desc" ${st.sort === "impact_desc" ? "selected" : ""}>정렬: 영향도순</option>
          <option value="completion_asc" ${st.sort === "completion_asc" ? "selected" : ""}>정렬: 준수율 낮은순</option>
        </select>
      </div>

      <div class="table-wrap">
        <table class="cs-table" aria-label="Well-Architected 5대 필러 개선 권장 목록">
          <thead>
            <tr>
              <th>권장사항 (클릭 시 4-상태 · Review+Fix 드로어)</th>
              <th>영향도</th>
              <th>활성 / 평가</th>
              <th>준수율</th>
              <th>점수 상승</th>
              <th>비용 파급 / 추정 절감</th>
            </tr>
          </thead>
          <tbody>
            ${items.length ? items.map((r) => `
              <tr class="gov-rule-row adv-click-row" tabindex="0" data-adv-open="${esc(r.id)}">
                <td>
                  <button type="button" class="adv-rec-btn" data-adv-open="${esc(r.id)}">${esc(r.title_ko)}</button>
                  <div class="cell-muted" style="font-size:12px;margin-top:2px;">
                    <span class="cs-badge tone-neutral">${esc(r.pillar_label_ko)}</span> ${esc(r.waf_ref)} · ${esc(r.owner_agent)}
                    ${r.retirement_days_left !== null && r.retirement_days_left !== undefined ? `<span class="adv-dday-pill ${r.retirement_days_left <= 45 ? "is-urgent" : "is-soon"}">은퇴 D-${r.retirement_days_left}</span>` : ""}
                  </div>
                </td>
                <td>${impactPill(r.impact)}</td>
                <td class="cell-mono"><strong>${r.active_count}</strong> / ${r.total_evaluated}</td>
                <td>${progressHtml(r.completion_pct, r.active_count, r.total_evaluated)}</td>
                <td><span class="adv-score-delta-pill">+${r.potential_score_increase_pct}%p</span></td>
                <td>${r.total_yearly_savings_usd > 0 ? `<span class="adv-carbon-pill">연 ${fmtUsd(r.total_yearly_savings_usd)}</span>` : costPill(r.cost_implication_tier)}</td>
              </tr>
            `).join("") : `<tr><td colspan="6" class="cell-muted" style="text-align:center;padding:16px;">일치하는 권장사항이 없습니다.</td></tr>`}
          </tbody>
        </table>
      </div>

      <details class="adv-inline-disclosure" style="margin-top:12px;">
        <summary><span>워크로드 평가 실행 · 이력 (WARA 393 · WAF 59 · 현재 ${assessList.length}건)</span><span class="cs-badge tone-neutral">실측 기반 생성</span></summary>
        <div class="adv-inline-body">
          <form id="advGovAssessForm" class="adv-form-inline">
            <label class="adv-field-inline">평가명<input type="text" name="name" placeholder="예: Q4 핵심 워크로드 WARA 평가" required></label>
            <label class="adv-field-inline">프레임워크<select name="framework"><option value="azure-wara">WARA 393</option><option value="azure-waf">WAF 5대 필러</option><option value="azure-mcsb">MCSB</option><option value="finops">FinOps</option></select></label>
            <label class="adv-field-inline">워크로드<input type="text" name="workload" value="fdai-core-control-plane" required></label>
            <button type="submit" class="cs-btn cs-btn-sm cs-btn-primary">새 평가 생성</button>
          </form>
          ${assessList.length ? `<div class="table-wrap"><table class="cs-table"><thead><tr><th>평가명</th><th>프레임워크</th><th>워크로드</th><th>자동 검증</th><th>실측 점수</th></tr></thead><tbody>${assessList.map((a) => `<tr><td><strong>${esc(a.name)}</strong></td><td><code>${esc(a.framework)}</code></td><td>${esc(a.workload)}</td><td>${a.auto_checked}규칙 / 탐지 ${a.recommendations_found}건</td><td><strong>${a.score_pct !== null && a.score_pct !== undefined ? `${a.score_pct}%` : "미측정"}</strong></td></tr>`).join("")}</tbody></table></div>` : `<div class="cell-muted" style="font-size:12.5px;">아직 생성된 워크로드 평가가 없습니다 (가짜 시드 점수를 표시하지 않습니다).</div>`}
        </div>
      </details>
    `;

    bindOpenTriggers(host);
    host.querySelectorAll("tr.adv-click-row").forEach((tr) => {
      tr.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          const rid = tr.getAttribute("data-adv-open");
          if (rid) openRuleDrawer(rid);
        }
      });
    });
    host.querySelector("#advGovPillarSel")?.addEventListener("change", (e) => { st.pillar = e.target.value; enhanceGovernanceRules(host); });
    host.querySelector("#advGovViewSel")?.addEventListener("change", (e) => { st.viewing = e.target.value; enhanceGovernanceRules(host); });
    host.querySelector("#advResourceTypeFilter")?.addEventListener("change", (e) => { st.resourceType = e.target.value; enhanceGovernanceRules(host); });
    host.querySelector("#advSortFilter")?.addEventListener("change", (e) => { st.sort = e.target.value; enhanceGovernanceRules(host); });
    let advSearchTimer = 0;
    host.querySelector("#advGovSearch")?.addEventListener("input", (e) => {
      st.search = e.target.value;
      window.clearTimeout(advSearchTimer);
      advSearchTimer = window.setTimeout(() => enhanceGovernanceRules(host), 220);
    });
    host.querySelector("#advGovResetBtn")?.addEventListener("click", () => {
      st.pillar = "all"; st.viewing = "active"; st.resourceType = "all"; st.sort = "score_desc"; st.search = "";
      enhanceGovernanceRules(host);
    });
    host.querySelector("#advGovAssessForm")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const ok = await fetchJson("/api/v4/advisor/assessments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: fd.get("name"), framework: fd.get("framework"), workload: fd.get("workload") }),
      }, "adv_create_assess");
      if (ok) enhanceGovernanceRules(host);
    });
  }

  /* ── 5. /governance/ontology (Lazy IQL Workbooks) & /governance/scope (Lazy RG Inclusion/Exclusion) ── */
  async function enhanceOntologyWorkbooks() {
    const panel = document.querySelector('.panel-view[data-panel-id="ontology"]');
    if (!panel || panel.hidden) return;
    let box = panel.querySelector("#advOntoWbMount");
    if (!box) {
      box = document.createElement("details");
      box.id = "advOntoWbMount";
      box.className = "adv-inline-disclosure";
      box.innerHTML = `<summary><span>온톨로지 분석 워크북 · IQL 쿼리 실행기 (열면 로드 · 6대 템플릿)</span><span class="cs-badge tone-neutral">읽기 전용 IQL</span></summary><div class="adv-inline-body"><div class="cell-muted">펼치면 IQL 워크북을 불러옵니다.</div></div>`;
      panel.appendChild(box);
      box.addEventListener("toggle", async () => {
        if (!box.open || box.dataset.loaded === "1") return;
        box.dataset.loaded = "1";
        const wb = await fetchJson("/api/v4/advisor/workbooks", null, "adv_wb");
        if (!wb) { box.dataset.loaded = "0"; return; }
        const body = box.querySelector(".adv-inline-body");
        if (!body) return;
        body.innerHTML = `
          <div class="adv-inline-bar">
            <select class="cs-select" id="advIqlPresetSel" aria-label="워크북 프리셋" style="height:32px;font-size:12.5px;">
              ${(wb.templates || []).map((t) => `<option value="${esc(t.default_iql)}">${esc(t.title)}</option>`).join("")}
            </select>
            <input type="text" class="cs-input" id="advOntoIqlInput" value="pillar == 'reliability' and impact == 'high'" style="flex:1;min-width:220px;height:32px;font-family:var(--cs-font-mono);font-size:12px;">
            <button type="button" class="cs-btn cs-btn-sm cs-btn-primary" id="advOntoIqlRun">IQL 실행</button>
          </div>
          <div class="table-wrap"><table class="cs-table"><thead><tr><th>규칙</th><th>필러</th><th>영향도</th><th>활성 / 평가</th><th>점수 상승</th></tr></thead><tbody id="advOntoIqlTbody"></tbody></table></div>
        `;
        const runIql = async () => {
          const iql = box.querySelector("#advOntoIqlInput")?.value || "";
          const res = await fetchJson("/api/v4/advisor/workbooks/query", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ iql }),
          }, "adv_iql_run");
          if (!res) return;
          const tb = box.querySelector("#advOntoIqlTbody");
          tb.innerHTML = (res.rows || []).map((r) => `
            <tr class="adv-click-row" data-adv-open="${esc(r.id)}">
              <td><button type="button" class="adv-rec-btn" data-adv-open="${esc(r.id)}">${esc(r.title_ko)}</button></td>
              <td><span class="cs-badge tone-neutral">${esc(r.pillar_label_ko)}</span></td>
              <td>${impactPill(r.impact)}</td>
              <td>${r.active_count} / ${r.total_evaluated}</td>
              <td><span class="adv-score-delta-pill">+${r.potential_score_increase_pct}%p</span></td>
            </tr>
          `).join("") || `<tr><td colspan="5" class="cell-muted" style="text-align:center;padding:12px;">일치하는 결과 없음</td></tr>`;
          bindOpenTriggers(tb);
        };
        box.querySelector("#advIqlPresetSel")?.addEventListener("change", (e) => {
          box.querySelector("#advOntoIqlInput").value = e.target.value;
          runIql();
        });
        box.querySelector("#advOntoIqlRun")?.addEventListener("click", runIql);
        runIql();
      });
    }
  }

  async function enhanceScopeConfig() {
    const panel = document.querySelector('.panel-view[data-panel-id="scope"]');
    if (!panel || panel.hidden) return;
    let box = panel.querySelector("#advScopeRgMount");
    if (!box) {
      box = document.createElement("details");
      box.id = "advScopeRgMount";
      box.className = "adv-inline-disclosure";
      box.innerHTML = `<summary><span>Advisor 평가 포함 · 제외 리소스 그룹 설정 (열면 로드)</span><span class="cs-badge tone-neutral">즉시 재평가</span></summary><div class="adv-inline-body"><div class="cell-muted">펼치면 리소스 그룹 포함·제외 설정을 불러옵니다.</div></div>`;
      panel.appendChild(box);
      box.addEventListener("toggle", async () => {
        if (!box.open || box.dataset.loaded === "1") return;
        box.dataset.loaded = "1";
        const cfgData = await fetchJson("/api/v4/advisor/config", null, "adv_scope_cfg");
        if (!cfgData) { box.dataset.loaded = "0"; return; }
        st.lastConfig = cfgData;
        const sumSpan = box.querySelector("summary > span:first-child");
        if (sumSpan) sumSpan.textContent = `Advisor 평가 포함 · 제외 리소스 그룹 설정 (제외 ${cfgData.excluded_resources_count ?? 0}개 리소스)`;
        const body = box.querySelector(".adv-inline-body");
        if (!body) return;
        body.innerHTML = `
          <div class="table-wrap" style="max-height:240px;overflow-y:auto;">
            <table class="cs-table"><thead><tr><th style="width:48px;">포함</th><th>리소스 그룹</th><th>실측 리소스</th></tr></thead>
              <tbody>${(cfgData.resource_groups || []).map((g) => `<tr><td><input type="checkbox" class="adv-scope-rg-cb" value="${esc(g.name)}" ${g.included ? "checked" : ""}></td><td><strong>${esc(g.name)}</strong></td><td>${g.resource_count}개</td></tr>`).join("")}</tbody>
            </table>
          </div>
          <div class="adv-inline-bar">
            <button type="button" class="cs-btn cs-btn-sm cs-btn-primary" id="advScopeSaveBtn">범위 적용</button>
            <span id="advScopeMsg" style="font-size:12px;color:var(--sig-live-text);"></span>
          </div>
        `;
        box.querySelector("#advScopeSaveBtn")?.addEventListener("click", async () => {
          const excluded = Array.from(box.querySelectorAll(".adv-scope-rg-cb")).filter((c) => !c.checked).map((c) => c.value);
          const next = Object.assign({}, cfgData.config, { excluded_resource_groups: excluded });
          const res = await fetchJson("/api/v4/advisor/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(next),
          }, "adv_scope_save");
          if (res?.ok) {
            const msg = box.querySelector("#advScopeMsg");
            if (msg) msg.textContent = `적용 완료 (제외 RG ${excluded.length}개 · 세션 오버레이)`;
          }
        });
      });
    }
  }

  /* ── 6. /operations/vulnerability-risk (Security Pillar) & /operations/alert-quality (Advisor Alerts) ── */
  async function enhanceOpsSecurity() {
    const panel = document.querySelector('.panel-view[data-panel-id="vulnerability-risk"]');
    if (!panel || panel.hidden) return;
    const data = await fetchJson("/api/v4/advisor/recommendations?pillar=security&viewing=active", null, "adv_ops_sec");
    if (!data) return;
    let box = panel.querySelector("#advOpsSecMount");
    if (!box) {
      box = document.createElement("details");
      box.id = "advOpsSecMount";
      box.className = "adv-inline-disclosure";
      box.open = true;
      panel.appendChild(box);
    }
    const items = data.items || [];
    box.innerHTML = `
      <summary><span>Advisor 보안 하드닝 권장사항 (${items.length}건 · 활성 ${data.kpi?.active_resources ?? 0}/${data.kpi?.evaluated_resources ?? 0})</span><span class="adv-pill is-human">Forseti · Fix PR</span></summary>
      <div class="adv-inline-body">
        <div class="adv-inline-table-wrap"><table class="adv-inline-table"><thead><tr><th>보안 권장사항</th><th>영향도</th><th>활성 리소스</th><th>준수율</th></tr></thead><tbody>
          ${items.map((r) => `<tr class="adv-click-row" data-adv-open="${esc(r.id)}"><td><button type="button" class="adv-rec-btn" data-adv-open="${esc(r.id)}">${esc(r.title_ko)}</button></td><td>${impactPill(r.impact)}</td><td><strong>${r.active_count}</strong> / ${r.total_evaluated}</td><td>${progressHtml(r.completion_pct, r.active_count, r.total_evaluated)}</td></tr>`).join("")}
        </tbody></table></div>
      </div>
    `;
    bindOpenTriggers(box);
  }

  async function enhanceOpsAlerts() {
    const panel = document.querySelector('.panel-view[data-panel-id="alert-quality"]');
    if (!panel || panel.hidden) return;
    const data = await fetchJson("/api/v4/advisor/alerts", null, "adv_ops_alerts");
    if (!data) return;
    let box = panel.querySelector("#advOpsAlertsMount");
    if (!box) {
      box = document.createElement("details");
      box.id = "advOpsAlertsMount";
      box.className = "adv-inline-disclosure";
      box.open = true;
      panel.appendChild(box);
    }
    const sp = new URLSearchParams(location.search || "");
    const preRule = sp.get("adv_alert_rule") || "";
    const preCat = sp.get("adv_alert_cat") || "all";
    box.innerHTML = `
      <summary><span>Advisor 권장사항 · 점수 회귀 · 은퇴 알림 규칙 (${(data.items || []).length}건)</span><span class="adv-pill">Action Group · Steward</span></summary>
      <div class="adv-inline-body">
        <form id="advOpsAlertForm" class="adv-form-inline">
          <label class="adv-field-inline">알림 이름<input type="text" name="name" value="${preRule ? esc(`[Advisor] ${preRule}`) : ""}" placeholder="예: High 신뢰성·은퇴 알림" required></label>
          <label class="adv-field-inline">시그널<select name="signal"><option value="new_recommendation">신규 권장사항</option><option value="score_regression">점수 회귀</option><option value="retirement_approaching">은퇴 임박</option><option value="postpone_expired">연기 만료</option></select></label>
          <label class="adv-field-inline">카테고리<select name="category"><option value="all" ${preCat === "all" ? "selected" : ""}>전체</option><option value="cost" ${preCat === "cost" ? "selected" : ""}>비용</option><option value="security" ${preCat === "security" ? "selected" : ""}>보안</option><option value="reliability" ${preCat === "reliability" ? "selected" : ""}>신뢰성</option><option value="operational_excellence">운영 우수성</option><option value="performance">성능</option></select></label>
          <label class="adv-field-inline">Action Group<input type="text" name="action_group" value="ag-fdai-sre-stewards" required></label>
          <button type="submit" class="cs-btn cs-btn-sm cs-btn-primary">알림 생성</button>
        </form>
        <div class="adv-inline-table-wrap"><table class="adv-inline-table"><thead><tr><th>알림 이름</th><th>시그널</th><th>카테고리</th><th>Action Group</th><th>상태</th></tr></thead><tbody>
          ${(data.items || []).length ? data.items.map((a) => `<tr><td><strong>${esc(a.name)}</strong></td><td><code>${esc(a.signal)}</code></td><td>${esc(a.category)}</td><td>${esc(a.action_group)}</td><td><span class="adv-pill ${a.enabled ? "is-low" : ""}">${a.enabled ? "활성" : "비활성"}</span></td></tr>`).join("") : `<tr><td colspan="5" style="text-align:center;color:var(--cs-text-soft);padding:12px;">등록된 Advisor 알림 규칙이 없습니다.</td></tr>`}
        </tbody></table></div>
      </div>
    `;
    box.querySelector("#advOpsAlertForm")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const ok = await fetchJson("/api/v4/advisor/alerts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: fd.get("name"),
          signal: fd.get("signal"),
          scope: "전체 스코프",
          category: fd.get("category"),
          subcategory: "all",
          impact: "high",
          rule_id: preRule || null,
          action_group: fd.get("action_group"),
          channels: ["Teams", "Email"],
          enabled: true,
        }),
      }, "adv_create_alert");
      if (ok) enhanceOpsAlerts();
    });
  }

  /* ── 7. /evidence/reports (Recommendation Digests + Persona Preview + CSV/JSON Export) ── */
  async function enhanceEvidenceReports() {
    const panel = document.querySelector('.panel-view[data-panel-id="reports"]');
    if (!panel || panel.hidden) return;
    const data = await fetchJson("/api/v4/advisor/digests", null, "adv_ev_digests");
    if (!data) return;
    let box = panel.querySelector("#advEvDigestsMount");
    if (!box) {
      box = document.createElement("details");
      box.id = "advEvDigestsMount";
      box.className = "adv-inline-disclosure";
      box.open = true;
      panel.appendChild(box);
    }
    box.innerHTML = `
      <summary>
        <span>Advisor 정기 권장사항 다이제스트 (BriefingSubscription · ${(data.items || []).length}건)</span>
        <span class="adv-inline-bar" onclick="event.stopPropagation();">
          <a class="cs-btn cs-btn-sm" href="/api/v4/advisor/export?format=csv">CSV 다운로드</a>
          <a class="cs-btn cs-btn-sm" href="/api/v4/advisor/export?format=json">JSON 다운로드</a>
        </span>
      </summary>
      <div class="adv-inline-body">
        <form id="advEvDigestForm" class="adv-form-inline">
          <label class="adv-field-inline">다이제스트 이름<input type="text" name="name" placeholder="예: 주간 경영진 스코어카드" required></label>
          <label class="adv-field-inline">주기<select name="frequency"><option value="weekly">매주</option><option value="biweekly">격주</option><option value="monthly">매월</option></select></label>
          <label class="adv-field-inline">페르소나<select name="persona"><option value="executive">임원 요약</option><option value="engineering">엔지니어 실행 목록</option><option value="finops">FinOps · 탄소</option></select></label>
          <label class="adv-field-inline">타임존<select name="timezone"><option value="Asia/Seoul">Asia/Seoul</option><option value="UTC">UTC</option></select></label>
          <div class="adv-inline-bar"><button type="submit" class="cs-btn cs-btn-sm cs-btn-primary">구독 추가</button><button type="button" class="cs-btn cs-btn-sm" id="advDigestPreviewBtn">미리보기</button></div>
        </form>
        <div id="advEvDigestPrev" class="adv-tradeoff-box" hidden></div>
        <div class="adv-inline-table-wrap"><table class="adv-inline-table"><thead><tr><th>구독명</th><th>주기 · Cron</th><th>페르소나</th><th>다음 발송</th></tr></thead><tbody>
          ${(data.items || []).length ? data.items.map((d) => `<tr><td><strong>${esc(d.name)}</strong></td><td>${esc(d.frequency)} · <code>${esc(d.cron_expression)}</code></td><td><span class="adv-pill is-human">${esc(d.persona)}</span></td><td>${esc(d.next_run_at)}</td></tr>`).join("") : `<tr><td colspan="4" style="text-align:center;color:var(--cs-text-soft);padding:12px;">등록된 정기 다이제스트 구독이 없습니다.</td></tr>`}
        </tbody></table></div>
      </div>
    `;
    box.querySelector("#advDigestPreviewBtn")?.addEventListener("click", () => {
      const fd = new FormData(box.querySelector("#advEvDigestForm"));
      const p = String(fd.get("persona") || "executive");
      const map = {
        executive: "임원 스코어카드: 종합 Advisor 점수 · 5대 필러 변화 · 추정 절감액 · 긴급 은퇴 Top 3",
        engineering: "엔지니어 실행 목록: High 영향도 Fix PR 링크 · 은퇴 D-Day · 7대 안전장치 상태",
        finops: "FinOps · GreenOps 리포트: RI(P1Y/P3Y) · Savings Plan · 고아 디스크 · 탄소(kgCO2e)",
      };
      const prev = box.querySelector("#advEvDigestPrev");
      prev.hidden = false;
      prev.innerHTML = `<strong>페르소나 미리보기 (${esc(p)})</strong><div style="font-size:12.5px;color:var(--cs-text-soft);">${esc(map[p] || map.executive)}</div>`;
    });
    box.querySelector("#advEvDigestForm")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(e.target);
      const ok = await fetchJson("/api/v4/advisor/digests", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: fd.get("name"),
          scope: "전체 스코프",
          categories: ["cost", "security", "reliability", "operational_excellence", "performance"],
          frequency: fd.get("frequency"),
          timezone: fd.get("timezone"),
          locale: "ko",
          persona: fd.get("persona"),
          channels: ["Email", "Teams"],
          enabled: true,
        }),
      }, "adv_create_digest");
      if (ok) enhanceEvidenceReports();
    });
  }

  /* ── 8. /settings/runtime (VM Low-CPU Threshold · Lookback · RI Term · Environment Profile) ── */
  async function enhanceSettingsRuntime() {
    const panel = document.querySelector('.panel-view[data-panel-id="settings-runtime"]');
    if (!panel || panel.hidden) return;
    const cfgData = await fetchJson("/api/v4/advisor/config", null, "adv_set_cfg");
    if (!cfgData) return;
    st.lastConfig = cfgData;
    const c = cfgData.config || {};
    let box = panel.querySelector("#advSetRuntimeMount");
    if (!box) {
      box = document.createElement("details");
      box.id = "advSetRuntimeMount";
      box.className = "adv-inline-disclosure";
      box.open = true;
      panel.appendChild(box);
    }
    box.innerHTML = `
      <summary><span>Advisor 평가 임계치 · Right-sizing 정책 (저CPU ${c.low_cpu_threshold_p95 ?? 5}% · ${c.ri_term || "P3Y"})</span><span class="adv-pill">즉시 반영</span></summary>
      <div class="adv-inline-body">
        <form id="advSetCfgForm" class="adv-form-inline">
          <label class="adv-field-inline">VM 저CPU P95 임계치<select id="advSetLowCpu"><option value="5" ${c.low_cpu_threshold_p95 === 5 ? "selected" : ""}>5%</option><option value="10" ${c.low_cpu_threshold_p95 === 10 ? "selected" : ""}>10%</option><option value="15" ${c.low_cpu_threshold_p95 === 15 ? "selected" : ""}>15%</option><option value="20" ${c.low_cpu_threshold_p95 === 20 ? "selected" : ""}>20%</option></select></label>
          <label class="adv-field-inline">Lookback 기간<select id="advSetLb"><option value="7" ${c.lookback_days === 7 ? "selected" : ""}>7일</option><option value="14" ${c.lookback_days === 14 ? "selected" : ""}>14일</option><option value="30" ${c.lookback_days === 30 ? "selected" : ""}>30일</option><option value="60" ${c.lookback_days === 60 ? "selected" : ""}>60일</option></select></label>
          <label class="adv-field-inline">기본 RI 약정<select id="advSetRi"><option value="P3Y" ${c.ri_term === "P3Y" ? "selected" : ""}>3년 (P3Y)</option><option value="P1Y" ${c.ri_term === "P1Y" ? "selected" : ""}>1년 (P1Y)</option></select></label>
          <label class="adv-field-inline">환경 프로파일<select id="advSetProf"><option value="balanced" ${c.environment_profile === "balanced" ? "selected" : ""}>Balanced</option><option value="prod_strict" ${c.environment_profile === "prod_strict" ? "selected" : ""}>Prod Strict</option><option value="dev_cost_first" ${c.environment_profile === "dev_cost_first" ? "selected" : ""}>Dev Cost-First</option></select></label>
          <div class="adv-inline-bar">
            <button type="submit" class="cs-btn cs-btn-sm cs-btn-primary">적용</button>
            <button type="button" class="cs-btn cs-btn-sm" id="advDiscardConfigBtn">변경 취소</button>
          </div>
        </form>
        <div id="advSetCfgMsg" style="font-size:12px;color:var(--sig-live-text);"></div>
      </div>
    `;
    box.querySelector("#advDiscardConfigBtn")?.addEventListener("click", () => enhanceSettingsRuntime());
    box.querySelector("#advSetCfgForm")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const next = Object.assign({}, c, {
        low_cpu_threshold_p95: Number(box.querySelector("#advSetLowCpu").value || 5),
        lookback_days: Number(box.querySelector("#advSetLb").value || 30),
        ri_term: box.querySelector("#advSetRi").value || "P3Y",
        environment_profile: box.querySelector("#advSetProf").value || "balanced",
      });
      const res = await fetchJson("/api/v4/advisor/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(next),
      }, "adv_set_save");
      if (res?.ok) {
        box.querySelector("#advSetCfgMsg").textContent = `적용 완료 (저CPU ${res.config.low_cpu_threshold_p95}% · ${res.config.ri_term} · 세션 오버레이)`;
      }
    });
  }

  function bindOpenTriggers(root) {
    if (!root) return;
    root.querySelectorAll("[data-adv-open]").forEach((el) => {
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        openRuleDrawer(el.getAttribute("data-adv-open"));
      });
    });
  }

  function activePanelId() {
    const el = document.querySelector(".panel-view[data-panel-id]:not([hidden])");
    return el ? el.getAttribute("data-panel-id") : "";
  }

  function enhanceActivePanel(forceRefresh) {
    const pid = activePanelId();
    if (pid === "dashboard") enhanceDashboard(forceRefresh);
    else if (pid === "verticals") enhanceVerticals(forceRefresh);
    else if (pid === "cost-governance" || pid === "llm-cost") enhanceCost(pid);
    else if (pid === "rules") enhanceGovernanceRules();
    else if (pid === "ontology") enhanceOntologyWorkbooks();
    else if (pid === "scope") enhanceScopeConfig();
    else if (pid === "vulnerability-risk") enhanceOpsSecurity();
    else if (pid === "alert-quality") enhanceOpsAlerts();
    else if (pid === "reports") enhanceEvidenceReports();
    else if (pid === "settings-runtime") enhanceSettingsRuntime();
  }

  window.fdaiAdvisor = {
    openRule: openRuleDrawer,
    loadRulesPane: (host) => enhanceGovernanceRules(host),
    refresh: () => enhanceActivePanel(true),
  };

  window.addEventListener("fdai:panelchange", () => setTimeout(() => enhanceActivePanel(false), 60));
  document.addEventListener("DOMContentLoaded", () => {
    const deepRule = hydrateFromUrl();
    setTimeout(() => {
      enhanceActivePanel(false);
      if (deepRule) openRuleDrawer(deepRule);
    }, 120);
  });
})();
