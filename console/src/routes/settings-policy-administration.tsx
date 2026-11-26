import { useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import { SelectField, TextInput } from "../components/form-controls";
import { StatusPill } from "../components/ui";
import { postGovernedJson } from "../governed-command";
import { currentRoute, routeHref } from "../router";
import {
  buildPolicyRevisionRequestBody,
  decodePolicyRevisionReceipt,
  initialPolicyRevisionDraft,
  policyAdminText,
  validatePolicyRevisionDraft,
  type ApprovalProfileKind,
  type PolicyAdminKind,
  type PolicyModeKind,
  type PolicyRevisionDraft,
  type PolicyRevisionSubmissionReceipt,
} from "./settings-policy-administration.model";

interface Props {
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
}

export function PolicyAdministrationSection({ client, auth }: Props) {
  const initialExpanded = currentRoute().search.get("policy-admin") === "1";
  const [expanded, setExpanded] = useState(initialExpanded);
  const [draft, setDraft] = useState<PolicyRevisionDraft>(initialPolicyRevisionDraft);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<PolicyRevisionSubmissionReceipt | null>(null);

  const validationError = validatePolicyRevisionDraft(draft);

  const update = <K extends keyof PolicyRevisionDraft>(
    key: K,
    value: PolicyRevisionDraft[K],
  ) => {
    setError(null);
    setReceipt(null);
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const submit = async (event: SubmitEvent) => {
    event.preventDefault();
    if (submitting || validationError !== null) return;
    setSubmitting(true);
    setError(null);
    setReceipt(null);
    try {
      const response = await postGovernedJson(
        () => auth.getAuthorizationHeader(),
        client.operatorApiBaseUrl,
        "/policy/revisions",
        buildPolicyRevisionRequestBody(draft),
        `policy-${draft.policyKind}-${draft.revisionId.trim()}`,
      );
      setReceipt(decodePolicyRevisionReceipt(response));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section
      id="settings-policy-administration"
      class="settings-section settings-runtime-section"
      aria-labelledby="settings-policy-admin-heading"
    >
      <div class="settings-row settings-runtime-row">
        <div class="settings-runtime-copy">
          <h3 id="settings-policy-admin-heading">{policyAdminText("title")}</h3>
          <small class="muted">{policyAdminText("subtitle")}</small>
          <span class="settings-runtime-meta">
            <span>POST /policy/revisions</span>
            <span>policy-admin App Role</span>
            <span>Mimir single writer</span>
          </span>
        </div>
        <div class="settings-runtime-control">
          <button
            type="button"
            class="btn secondary"
            aria-expanded={expanded}
            onClick={() => setExpanded((current) => !current)}
          >
            {expanded ? policyAdminText("closeComposer") : policyAdminText("openComposer")}
          </button>
        </div>
      </div>

      <div class="state-block" role="note">
        <p>{policyAdminText("quorumNotice")}</p>
        <p>{policyAdminText("hardBoundsCallout")}</p>
      </div>

      <p>
        <a href={routeHref("promotion-gates")}>{policyAdminText("promotionsLink")}</a>
      </p>

      {expanded ? (
        <form class="stack" onSubmit={(event) => void submit(event)}>
          <h4>{policyAdminText("validationTitle")}</h4>
          <div class="settings-list">
            <div class="settings-row">
              <span>{policyAdminText("checkSchema")}</span>
              <StatusPill kind={validationError === null ? "success" : "warning"} label={validationError === null ? "Ready" : "Check input"} />
            </div>
            <div class="settings-row">
              <span>{policyAdminText("checkRego")}</span>
              <StatusPill kind="neutral" label="Mimir verified" />
            </div>
            <div class="settings-row">
              <span>{policyAdminText("checkReleaseMax")}</span>
              <StatusPill kind="neutral" label="Hard ceiling" />
            </div>
          </div>

          <div class="settings-filter-bar">
            <SelectField
              label={policyAdminText("kindLabel")}
              value={draft.policyKind}
              options={[
                { value: "approval", label: policyAdminText("kindApproval") },
                { value: "admission", label: policyAdminText("kindAdmission") },
              ]}
              onChange={(value) => update("policyKind", value as PolicyAdminKind)}
            />
            <TextInput
              label={policyAdminText("revisionIdLabel")}
              value={draft.revisionId}
              onInput={(value) => update("revisionId", value)}
            />
            <TextInput
              label={policyAdminText("parentRevisionIdLabel")}
              value={draft.parentRevisionId}
              onInput={(value) => update("parentRevisionId", value)}
            />
          </div>

          {draft.policyKind === "approval" ? (
            <div class="settings-filter-bar">
              <SelectField
                label={policyAdminText("profileLabel")}
                value={draft.approvalProfile}
                options={[
                  { value: "single-operator-production", label: policyAdminText("profileSingle") },
                  { value: "multi-operator", label: policyAdminText("profileMulti") },
                ]}
                onChange={(value) => update("approvalProfile", value as ApprovalProfileKind)}
              />
              <TextInput
                label={policyAdminText("operatorPrincipalLabel")}
                value={draft.operatorPrincipal}
                onInput={(value) => update("operatorPrincipal", value)}
              />
              <TextInput
                label={policyAdminText("executorPrincipalLabel")}
                value={draft.executorPrincipal}
                onInput={(value) => update("executorPrincipal", value)}
              />
            </div>
          ) : (
            <div class="settings-filter-bar">
              <TextInput
                className="is-wide"
                label={policyAdminText("regoLabel")}
                mono
                value={draft.rego}
                onInput={(value) => update("rego", value)}
              />
            </div>
          )}

          <div class="settings-filter-bar">
            <TextInput
              label={policyAdminText("actionTypeLabel")}
              value={draft.actionTypeName}
              onInput={(value) => update("actionTypeName", value)}
            />
            <SelectField
              label={policyAdminText("actionModeLabel")}
              value={draft.actionTypeMode}
              options={[
                { value: "shadow", label: "shadow" },
                { value: "enforce", label: "enforce" },
              ]}
              onChange={(value) => update("actionTypeMode", value as PolicyModeKind)}
            />
            <TextInput
              className="is-wide"
              label={policyAdminText("reasonLabel")}
              value={draft.reason}
              onInput={(value) => update("reason", value)}
            />
          </div>

          {validationError ? (
            <p class="error-text" role="alert">
              {validationError}
            </p>
          ) : null}
          {error ? (
            <div class="error" role="alert">
              {error}
            </div>
          ) : null}
          {receipt ? (
            <div class="state-block state-success" role="status" style={{ overflowWrap: "anywhere" }}>
              {policyAdminText("submittedNotice", {
                requestId: receipt.requestId,
                requestDigest: receipt.requestDigest,
              })}
            </div>
          ) : null}

          <div class="settings-actions">
            <button
              type="submit"
              class="btn primary"
              disabled={submitting || validationError !== null}
            >
              {submitting ? policyAdminText("submittingButton") : policyAdminText("submitButton")}
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
