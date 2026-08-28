(function () {
  "use strict";

  var details = {
    "api-compute": {
      name: "api-compute-01",
      meta: "컴퓨팅 · 프로덕션 · 축소 검토",
      current: "D8s_v5",
      target: "D4s_v5",
      summary: "P95 CPU와 P99 메모리가 목표 여유 용량 안에 있으며 SKU 기능 호환성이 확인되었습니다.",
      njord: "상각 약정 반영 후 월 $524 절감 예상",
      freyr: "제안 SKU에서 예측 CPU P95 68%",
      forseti: "상위 제약을 위반하지 않는 대안 1개",
      gates: [["서비스·워크로드 매핑", "확인"], ["SLO 및 오류 예산", "정상"], ["의존성 포괄 범위", "완전"], ["롤백 계약", "준비"]]
    },
    "orders-db": {
      name: "orders-db",
      meta: "PostgreSQL · 프로덕션 · 확대 검토",
      current: "8 vCore",
      target: "12 vCore",
      summary: "IO 포화와 연결 대기가 반복되어 비용 절감보다 서비스 목표 보호가 우선됩니다.",
      njord: "월 $806 추가 비용, 주문당 단위 비용 +4.1%",
      freyr: "현재 구성의 14일 내 포화 가능성 82%",
      forseti: "유지와 축소 대안을 SLO 위반으로 제외",
      gates: [["서비스·워크로드 매핑", "확인"], ["SLO 및 오류 예산", "위험"], ["의존성 포괄 범위", "완전"], ["롤백 계약", "준비"]]
    },
    "dev-aks": {
      name: "dev-aks-pool",
      meta: "AKS 노드 풀 · 개발 · 확장·일정 검토",
      current: "3 × D4s_v5",
      target: "1-3 자동 확장",
      summary: "야간 수요가 낮고 Pod 중단 예산을 충족하여 고정 SKU 축소보다 자동 확장이 적합합니다.",
      njord: "월 $286 절감 예상, 약정 중복 없음",
      freyr: "최소 1개 노드에서 요청량 여유 41%",
      forseti: "예약 종료보다 자동 확장을 가역 대안으로 선택",
      gates: [["서비스·워크로드 매핑", "확인"], ["중단 예산", "정상"], ["노드·Pod 관계", "완전"], ["롤백 계약", "준비"]]
    },
    "shared-cache": {
      name: "shared-cache",
      meta: "Azure Cache · 소유자 미확인 · 판단 보류",
      current: "Premium P2",
      target: "대안 없음",
      summary: "서비스 매핑과 연결 정보가 불완전하여 사용률이 낮아도 변경 대안을 만들 수 없습니다.",
      njord: "정가 기준 잠재 절감액만 존재, 귀속 불가",
      freyr: "메모리 여유는 있으나 연결 피크 미관측",
      forseti: "미매핑 리소스이므로 분석 전용으로 보류",
      gates: [["서비스·워크로드 매핑", "미확인"], ["SLO 및 오류 예산", "알 수 없음"], ["의존성 포괄 범위", "불완전"], ["롤백 계약", "미평가"]]
    },
    "orphan-disk": {
      name: "build-disk-legacy",
      meta: "Managed Disk · 테스트 · 폐기 검토",
      current: "Premium SSD P30",
      target: "분리 후 삭제",
      summary: "47일 동안 연결과 IO가 없지만 삭제는 별도 파괴적 ActionType과 사람 승인을 사용합니다.",
      njord: "최종 청구 기준 월 $122 절감 가능",
      freyr: "용량 영향 없음, 연결 대상 미관측",
      forseti: "탐지는 완료했지만 삭제 실행은 별도 승인 대상",
      gates: [["서비스·워크로드 매핑", "확인"], ["보존 정책", "확인"], ["연결 관계", "없음 증명"], ["스냅샷 복구", "필수"]]
    },
    "gateway-app": {
      name: "gateway-app-plan",
      meta: "App Service · 프로덕션 · 유지",
      current: "P1v3",
      target: "P1v3 유지",
      summary: "현재 비용과 용량이 목표 범위에 있고 더 작은 SKU는 P99 지연 시간 목표를 위반합니다.",
      njord: "현재 월 $318, 유효한 절감 대안 없음",
      freyr: "CPU P95 61%, 예측 최대 74%",
      forseti: "현상 유지가 유일한 적격 대안",
      gates: [["서비스·워크로드 매핑", "확인"], ["SLO 및 오류 예산", "정상"], ["의존성 포괄 범위", "완전"], ["롤백 계약", "해당 없음"]]
    }
  };

  var rows = Array.prototype.slice.call(document.querySelectorAll("#resource-body tr"));
  var filters = Array.prototype.slice.call(document.querySelectorAll("[data-filter]"));
  var search = document.getElementById("resource-search");
  var empty = document.getElementById("resource-empty");
  var visibleCount = document.getElementById("visible-count");
  var costChartTooltip = document.getElementById("cost-chart-tooltip");
  var costTrendCard = document.querySelector(".fr-cost-trend");
  var workspaceTabs = Array.prototype.slice.call(document.querySelectorAll("[data-workspace-tab]"));
  var workspaceViews = Array.prototype.slice.call(document.querySelectorAll("[data-workspace-view]"));
  var workspaceCopy = {
    overview: {
      title: "비용 거버넌스",
      subtitle: "실제 비용, 월말 예측, 예산, 검증된 절감 효과를 하나의 근거 구간에서 비교합니다."
    },
    "resource-efficiency": {
      title: "리소스 효율",
      subtitle: "비용, 사용률, 서비스 목표를 함께 검토하여 현재 SKU의 적정성과 안전한 대안을 판단합니다."
    },
    "optimization-cases": {
      title: "최적화 사례",
      subtitle: "발견된 기회를 판단, 승인, 적용, 검증 단계와 함께 추적합니다."
    },
    outcomes: {
      title: "성과",
      subtitle: "예상 절감과 실제 청구 효과를 정산하고 서비스 목표 및 복구 결과를 함께 확인합니다."
    }
  };
  var activeFilter = "all";

  function activateWorkspace(viewId, updateHash) {
    var copy = workspaceCopy[viewId];
    if (!copy) return;
    workspaceTabs.forEach(function (tab) {
      var active = tab.dataset.workspaceTab === viewId;
      tab.classList.toggle("is-active", active);
      if (active) tab.setAttribute("aria-current", "page");
      else tab.removeAttribute("aria-current");
    });
    workspaceViews.forEach(function (view) {
      view.hidden = view.dataset.workspaceView !== viewId;
    });
    document.getElementById("workspace-title").textContent = copy.title;
    document.getElementById("workspace-subtitle").textContent = copy.subtitle;
    if (updateHash) history.replaceState(null, "", "#" + viewId);
  }

  function renderDetails(key) {
    var detail = details[key];
    if (!detail) return;
    document.getElementById("detail-name").textContent = detail.name;
    document.getElementById("detail-meta").textContent = detail.meta;
    document.getElementById("detail-current").textContent = detail.current;
    document.getElementById("detail-target").textContent = detail.target;
    document.getElementById("detail-summary").textContent = detail.summary;
    document.getElementById("detail-njord").textContent = detail.njord;
    document.getElementById("detail-freyr").textContent = detail.freyr;
    document.getElementById("detail-forseti").textContent = detail.forseti;
    document.getElementById("detail-gates").innerHTML = detail.gates.map(function (gate) {
      var held = /미확인|알 수 없음|불완전|미평가|위험/.test(gate[1]) ? " class=\"is-held\"" : "";
      return "<li" + held + "><span>" + gate[0] + "</span><strong>" + gate[1] + "</strong></li>";
    }).join("");
    rows.forEach(function (row) {
      row.classList.toggle("is-selected", row.dataset.resource === key);
    });
    document.querySelectorAll("[data-scatter-resource]").forEach(function (point) {
      point.classList.toggle("is-selected", point.dataset.scatterResource === key);
    });
  }

  function applyFilters() {
    var query = search.value.trim().toLocaleLowerCase("ko");
    var shown = 0;
    rows.forEach(function (row) {
      var kindMatches = activeFilter === "all" || row.dataset.kind === activeFilter;
      var searchMatches = !query || row.dataset.search.toLocaleLowerCase("ko").indexOf(query) >= 0;
      row.hidden = !(kindMatches && searchMatches);
      if (!row.hidden) shown += 1;
    });
    empty.hidden = shown !== 0;
    visibleCount.textContent = shown + "개 대표 리소스 표시 · 전체 128개";
  }

  filters.forEach(function (button) {
    button.addEventListener("click", function () {
      activeFilter = button.dataset.filter;
      filters.forEach(function (candidate) {
        candidate.classList.toggle("is-active", candidate === button);
      });
      applyFilters();
    });
  });

  document.querySelectorAll("[data-select]").forEach(function (button) {
    button.addEventListener("click", function () {
      renderDetails(button.dataset.select);
    });
  });

  workspaceTabs.forEach(function (tab) {
    tab.addEventListener("click", function (event) {
      event.preventDefault();
      activateWorkspace(tab.dataset.workspaceTab, true);
    });
  });

  document.querySelectorAll("[data-go-view]").forEach(function (button) {
    button.addEventListener("click", function () {
      activateWorkspace(button.dataset.goView, true);
      document.querySelector(".fr-workspace-tabs").scrollIntoView({ block: "start" });
    });
  });

  document.querySelectorAll("[data-scatter-resource]").forEach(function (button) {
    button.addEventListener("click", function () {
      search.value = "";
      activeFilter = "all";
      filters.forEach(function (candidate) {
        candidate.classList.toggle("is-active", candidate.dataset.filter === "all");
      });
      applyFilters();
      renderDetails(button.dataset.scatterResource);
      document.querySelector(".fr-workspace").scrollIntoView({ block: "start" });
    });
  });

  function positionCostTooltip(target, clientX) {
    var cardBounds = costTrendCard.getBoundingClientRect();
    var pointBounds = target.getBoundingClientRect();
    var x = clientX || pointBounds.left + pointBounds.width / 2;
    var left = Math.max(12, Math.min(x - cardBounds.left - 74, cardBounds.width - 172));
    var top = Math.max(138, pointBounds.top - cardBounds.top - 66);
    costChartTooltip.style.left = left + "px";
    costChartTooltip.style.top = top + "px";
  }

  function showCostTooltip(target, clientX) {
    costChartTooltip.querySelector("strong").textContent = target.dataset.date;
    costChartTooltip.querySelector("[data-tooltip-actual]").textContent = target.dataset.actual;
    costChartTooltip.querySelector("[data-tooltip-prior]").textContent =
      "이전 기간 " + target.dataset.prior;
    costChartTooltip.hidden = false;
    positionCostTooltip(target, clientX);
  }

  document.querySelectorAll("[data-cost-point]").forEach(function (point) {
    point.setAttribute("tabindex", "0");
    point.setAttribute(
      "aria-label",
      point.dataset.date + ", 현재 " + point.dataset.actual + ", 이전 기간 " + point.dataset.prior
    );
    point.addEventListener("pointerenter", function (event) {
      showCostTooltip(point, event.clientX);
    });
    point.addEventListener("pointermove", function (event) {
      positionCostTooltip(point, event.clientX);
    });
    point.addEventListener("pointerleave", function () {
      costChartTooltip.hidden = true;
    });
    point.addEventListener("focus", function () {
      showCostTooltip(point);
    });
    point.addEventListener("blur", function () {
      costChartTooltip.hidden = true;
    });
  });

  search.addEventListener("input", applyFilters);
  var initialView = location.hash.slice(1);
  activateWorkspace(workspaceCopy[initialView] ? initialView : "overview", false);
  renderDetails("api-compute");
})();
