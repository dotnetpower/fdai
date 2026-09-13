/** Filters a frozen synthetic approval snapshot. Missing evidence stays explicitly unrecorded. */
(function () {
  "use strict";
  var input = document.querySelector("[data-approval-search]");
  var status = document.querySelector("[data-approval-status]");
  var cards = Array.from(document.querySelectorAll("[data-approval]"));
  var missingFacts = [
    ["Dry-run receipt", "Not recorded - required before dispatch"],
    ["Logical-target lock", "Not recorded - no lock held by this preview"],
    ["Stable idempotency key", "Not recorded - duplicate protection is not established"],
    ["Two-phase audit", "Intent and terminal receipts not recorded"],
    ["Requester / independent approvers", "Not recorded - self-approval is never allowed"],
    ["Required quorum", "Not recorded - no approval eligibility established"],
    ["Independent effect observation", "Not recorded - no execution or success claimed"]
  ];
  cards.forEach(function (card) {
    var path = document.createElement("ol");
    path.className = "flow-state-path";
    path.style.setProperty("--flow-steps", "4");
    path.setAttribute("aria-label", "Proposal authority and effect lifecycle");
    var expired = card.dataset.approvalState === "expired";
    [
      ["Proposal", "Recorded", "complete"],
      ["Approval", expired ? "Expired" : "Pending", "current"],
      ["Execution", "Not started", "not-started"],
      ["Observation", "Not started", "not-started"]
    ].forEach(function (step, index) {
      var item = document.createElement("li");
      item.dataset.state = step[2];
      item.innerHTML = "<span>" + (index + 1) + "</span><strong>" + step[0] + "</strong><small>" + step[1] + "</small>";
      path.appendChild(item);
    });
    card.querySelector(".approval-reason").after(path);
    var facts = card.querySelector("dl");
    missingFacts.forEach(function (fact) {
      var item = document.createElement("div");
      var term = document.createElement("dt");
      var value = document.createElement("dd");
      term.textContent = fact[0];
      value.textContent = fact[1];
      item.append(term, value);
      facts.appendChild(item);
    });
    var note = document.createElement("p");
    note.className = "approval-authority-note";
    note.textContent = "Seven safeguards and current independent human authority must be rechecked by the owning runtime. These synthetic facts cannot authorize a change.";
    card.querySelector("details").appendChild(note);
  });
  document.querySelectorAll("[data-approval-total]").forEach(function (count) {
    count.textContent = cards.filter(function (card) { return card.dataset.approvalState === count.dataset.approvalTotal; }).length;
  });

  function filter(persist) {
    var query = input.value.trim().normalize("NFC").toLowerCase();
    var shown = 0;
    cards.forEach(function (card) {
      var matchesStatus = status.value === "all" || status.value === card.dataset.approvalState;
      card.hidden = !matchesStatus || !card.textContent.normalize("NFC").toLowerCase().includes(query);
      if (!card.hidden) shown++;
    });
    document.querySelector("[data-approval-count]").textContent = shown + " of " + cards.length + " shown";
    document.querySelector("[data-approval-empty]").hidden = shown !== 0;
    if (persist) {
      var url = new URL(window.location.href);
      if (input.value.trim()) url.searchParams.set("q", input.value.trim()); else url.searchParams.delete("q");
      if (status.value !== "all") url.searchParams.set("status", status.value); else url.searchParams.delete("status");
      window.history.replaceState(null, "", url);
      if (window.fdaiPublishMockRoute) window.fdaiPublishMockRoute();
    }
  }
  function restore() {
    var params = new URLSearchParams(window.location.search);
    input.value = (params.get("q") || "").slice(0, 200);
    status.value = ["pending", "expired"].includes(params.get("status")) ? params.get("status") : "all";
    filter(false);
  }
  input.addEventListener("input", function () { filter(true); });
  status.addEventListener("change", function () { filter(true); });
  document.querySelector("[data-clear-approvals]").addEventListener("click", function () {
    input.value = "";
    status.value = "all";
    filter(true);
    input.focus();
  });
  window.addEventListener("popstate", restore);
  restore();
})();
