(function () {
  "use strict";

  function bindIngestionForm() {
    var form = document.querySelector("[data-kw-document-form]");
    if (!form) return;
    var file = form.querySelector("#document-file");
    var consent = form.querySelector("#document-consent");
    var submit = form.querySelector("[data-kw-document-submit]");
    var result = form.querySelector("#document-upload-result");

    function sync() {
      var hasFile = file.files.length > 0;
      var authorized = consent.checked;
      submit.disabled = !(hasFile && authorized);
      if (hasFile && authorized) {
        result.textContent = "Ready to validate this governed-upload preview. No request has been sent.";
      } else if (hasFile) {
        result.textContent = "Confirm that the selected document is authorized for ingestion.";
      } else if (authorized) {
        result.textContent = "Select an authorized document to continue.";
      } else {
        result.textContent = "Select a document and confirm authorization to validate this preview.";
      }
    }

    form.addEventListener("change", sync);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (submit.disabled) return;
      result.textContent = "Preview validated. No upload or retention request was sent.";
      result.focus();
    });
    form.addEventListener("reset", function () {
      window.setTimeout(sync, 0);
    });
    sync();
  }

  function showLibraryState(value) {
    var region = document.querySelector("[data-kw-library-region]");
    if (!region) return;
    region.setAttribute("aria-busy", String(value === "loading"));
    region.querySelectorAll("[data-kw-library-panel]").forEach(function (panel) {
      panel.hidden = panel.getAttribute("data-kw-library-panel") !== value;
    });
  }

  function bindLibraryStates() {
    var picker = document.querySelector("[data-kw-library-state]");
    if (!picker) return;
    picker.addEventListener("change", function () {
      showLibraryState(picker.value);
    });
    document.addEventListener("click", function (event) {
      if (!event.target.closest("[data-kw-library-retry]")) return;
      var region = document.querySelector("[data-kw-library-region]");
      picker.value = "loading";
      showLibraryState("loading");
      region.focus();
      window.setTimeout(function () {
        picker.value = "records";
        showLibraryState("records");
      }, 350);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    bindIngestionForm();
    bindLibraryStates();
  });
})();
