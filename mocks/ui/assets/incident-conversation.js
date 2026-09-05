// Presentation-only interactions. No provider reads, model requests, or state-changing operations.
(function () {
  "use strict";

  const form = document.getElementById("incident-question-form");
  const question = document.getElementById("incident-question");
  const messages = document.getElementById("incident-messages");
  const feedback = document.getElementById("preview-status");

  function revealTarget(target) {
    // A citation can sit inside both the evidence disclosure and a source-record disclosure.
    let disclosure = target.closest("details");
    while (disclosure) {
      disclosure.open = true;
      disclosure = disclosure.parentElement.closest("details");
    }
    const focusTarget = target.matches("details") ? target.querySelector("summary") : target;
    focusTarget.focus({ preventScroll: true });
    target.scrollIntoView({ block: "start" });
  }

  document.querySelectorAll('a[href^="#"]').forEach(function (link) {
    link.addEventListener("click", function (event) {
      const target = document.getElementById(link.hash.slice(1));
      if (!target) {
        console.error("Incident preview link has no target:", link.hash);
        return;
      }
      event.preventDefault();
      revealTarget(target);
    });
  });

  window.addEventListener("load", function () {
    if (window.location.hash) {
      const target = document.getElementById(window.location.hash.slice(1));
      if (target) revealTarget(target);
    }
  }, { once: true });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    const text = question.value.trim();
    if (!text) {
      question.setCustomValidity("Enter a question to preview.");
      question.reportValidity();
      return;
    }
    const entry = document.createElement("article");
    entry.className = "ic-preview-question";
    entry.setAttribute("aria-label", "Local preview question");
    const label = document.createElement("p");
    label.className = "ic-message-meta";
    label.textContent = "Operator / Local preview / Not sent";
    const body = document.createElement("p");
    body.textContent = text;
    entry.append(label, body);
    messages.appendChild(entry);
    question.value = "";
    feedback.textContent = "Question added locally. No request was sent and no incident state changed.";
    entry.scrollIntoView({ block: "end" });
    question.focus({ preventScroll: true });
  });
  question.addEventListener("input", function () {
    question.setCustomValidity("");
  });
  question.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
})();
