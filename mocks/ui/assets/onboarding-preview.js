(function () {
  "use strict";
  var control = document.getElementById("onboarding-preview-state");
  var fixtures = {
    blocked: { observed: true, ready: false, resources: "8", roles: "6", note: "Synthetic blocked snapshot: three resources and two role assignments are missing. No probe runs and no access is granted." },
    ready: { observed: true, ready: true, resources: "11", roles: "8", note: "Synthetic ready snapshot. This is a display example, not current deployment or authorization evidence." },
    unconfigured: { observed: false, ready: false, resources: "Unavailable", roles: "Unavailable", note: "Example unavailable state: the readiness probe is not configured. The lists describe requirements, not observed gaps." },
    failed: { observed: false, ready: false, resources: "Unavailable", roles: "Unavailable", note: "Example probe failure: no readiness conclusion is available. Inspect the probe error before making a readiness claim." }
  };
  function text(id, value) { document.getElementById(id).textContent = value; }
  function render() {
    if (!Object.hasOwn(fixtures, control.value)) throw new Error("Unknown onboarding preview state.");
    var state = fixtures[control.value];
    text("onboarding-readiness", state.observed ? state.ready ? "Ready" : "Blocked" : "Unavailable");
    document.getElementById("onboarding-readiness").dataset.state = state.observed ? state.ready ? "ready" : "blocked" : "unknown";
    text("onboarding-resources", state.resources);
    text("onboarding-roles", state.roles);
    text("onboarding-requirements", state.observed ? state.ready ? "No observed gaps" : "5 requirements remain" : "No authoritative observation");
    text("checked-at", state.observed ? "03:00 UTC" : "Not measured");
    text("checked-date", state.observed ? "06 Sep 2026 - fixed example" : "No observed timestamp");
    text("onboarding-preview-note", state.note);
    document.getElementById("onboarding-preview-note").setAttribute("role", control.value === "failed" ? "alert" : "status");
    text("missing-resources-title", state.observed ? "Missing resources" : "Required resources");
    text("missing-roles-title", state.observed ? "Missing role assignments" : "Required role assignments");
    text("onboarding-resource-gaps", state.ready ? "0" : "3");
    text("onboarding-role-gaps", state.ready ? "0" : "2");
    document.getElementById("onboarding-resource-list").hidden = state.ready;
    document.getElementById("onboarding-role-list").hidden = state.ready;
    document.getElementById("onboarding-no-resources").hidden = !state.ready;
    document.getElementById("onboarding-no-roles").hidden = !state.ready;
  }
  control.addEventListener("change", render);
  document.getElementById("refresh-button").addEventListener("click", function () { control.value = "blocked"; render(); });
  render();
})();
