/** Create isolated, non-submitting IAM preview editors with native dialog focus behavior. */
export function createIamEditor(root, options) {
  const request = root.querySelector("#iam-request-dialog");
  const review = root.querySelector("#iam-review-dialog");
  const role = request.querySelector("[data-role-request]");
  role.append(new Option("Choose a role", ""), ...options.roles.map((value) => new Option(value, value)));
  const contexts = new Map([[request, null], [review, null]]);

  function hint(dialog, touched = false) {
    const textarea = dialog.querySelector("textarea");
    const length = textarea.value.trim().length;
    const remaining = Math.max(0, 20 - length);
    const output = dialog.querySelector(".iam-validation");
    output.textContent = remaining ? remaining + " more characters required." : length + " / 2000 characters. Minimum met.";
    textarea.setAttribute("aria-invalid", String(touched && remaining > 0));
    output.classList.toggle("is-invalid", touched && remaining > 0);
  }

  [request, review].forEach((dialog) => {
    dialog.querySelector("form").addEventListener("submit", (event) => event.preventDefault());
    dialog.querySelector("[data-editor-cancel]").addEventListener("click", () => dialog.close());
    dialog.querySelector("textarea").addEventListener("input", () => hint(dialog));
    dialog.querySelector("textarea").addEventListener("blur", () => hint(dialog, true));
    dialog.querySelector("textarea").addEventListener("focus", (event) => event.target.scrollIntoView({ block: "nearest" }));
    dialog.addEventListener("keydown", (event) => {
      if (event.key !== "Tab") return;
      const controls = [...dialog.querySelectorAll("select, textarea, button:not(:disabled)")];
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
    dialog.addEventListener("close", () => {
      const context = contexts.get(dialog);
      dialog.querySelector("form").reset();
      hint(dialog);
      if (context?.row) delete context.row.dataset.editing;
      contexts.set(dialog, null);
      // The close event must not steal focus from a subsequent user action.
      const active = document.activeElement;
      if (context?.restoreFocus && (active === document.body || dialog.contains(active) || active === context.trigger)) {
        const target = context.trigger.getClientRects().length ? context.trigger : root.querySelector('[data-iam-tab][aria-selected="true"]');
        target.focus();
      }
    });
  });

  function show(dialog, row, trigger) {
    dialog.querySelector("form").reset();
    hint(dialog);
    contexts.set(dialog, { row, trigger, restoreFocus: true });
    row.dataset.editing = "true";
    dialog.showModal();
    dialog.querySelector("select, textarea").focus();
  }

  return {
    openRequest(row, trigger) {
      if (!options.canRequest()) {
        options.announce("A verified Owner and an available directory are required.");
        return;
      }
      request.querySelector("[data-draft-principal]").textContent = row.dataset.principalName;
      request.querySelector("[data-draft-account]").textContent = row.dataset.principalAccount;
      request.querySelector("[data-draft-current-role]").textContent = row.dataset.principalRoles;
      show(request, row, trigger);
    },
    openReview(row, trigger) {
      if (!options.canReview()) {
        options.announce("FDAI Owner access is required to review requests.");
        return;
      }
      review.querySelector("[data-review-target]").textContent = row.dataset.requestTarget;
      review.querySelector("[data-review-account]").textContent = row.dataset.requestAccount;
      review.querySelector("[data-review-role]").textContent = "Grant " + row.dataset.requestRole;
      review.querySelector("[data-review-requester]").textContent = row.dataset.requester;
      show(review, row, trigger);
    },
    closeAll() {
      [request, review].forEach((dialog) => {
        const context = contexts.get(dialog);
        if (context) context.restoreFocus = false;
        if (dialog.open) dialog.close();
      });
    }
  };
}
