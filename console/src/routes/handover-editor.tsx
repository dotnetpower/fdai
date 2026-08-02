import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import { loadConfig } from "../config";
import {
  IngestionApiClient,
  IngestionApiError,
  type HandoverDraftResult,
  type IngestionCapabilities,
} from "../ingestion-api";
import { t } from "../i18n";
import { PANTHEON } from "./agents.model";
import { waitForTerminal } from "./document-ingestion";

export type HandoverSubjectKind = "user" | "group";
export type HandoverResponsibility = "accountable" | "informed";

export interface HandoverAssignmentInput {
  readonly agent: string;
  readonly kind: HandoverSubjectKind;
  readonly responsibility: HandoverResponsibility;
  readonly identity: string;
}

interface HandoverAssignmentRow extends HandoverAssignmentInput {
  readonly id: number;
}

interface Props {
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
}

const PROPOSER_ROLES = new Set(["Contributor", "Approver", "Owner"]);
const MAX_ASSIGNMENTS = 60;
const DEFAULT_AGENT = PANTHEON[0]!;

export function canProposeHandover(auth: AuthContext): boolean {
  if (auth.devMode && auth.account === null) return true;
  const roles = auth.account?.idTokenClaims?.roles;
  return Array.isArray(roles) && roles.some(
    (role) => typeof role === "string" && PROPOSER_ROLES.has(role),
  );
}

export function buildHandoverDocument(
  assignments: readonly HandoverAssignmentInput[],
): string {
  if (assignments.length === 0) {
    throw new Error("At least one handover assignment is required.");
  }
  const agentNames = new Set(PANTHEON.map((agent) => agent.name));
  const lines = assignments.map((assignment) => {
    const identity = assignment.identity.trim();
    if (!agentNames.has(assignment.agent as (typeof PANTHEON)[number]["name"])) {
      throw new Error(`Unknown pantheon agent: ${assignment.agent}`);
    }
    if (!identity || /[;\r\n]/.test(identity)) {
      throw new Error("Identity must be non-empty and contain no semicolons or line breaks.");
    }
    return [
      `Agent: ${assignment.agent}`,
      `responsibility: ${assignment.responsibility}`,
      `subject: ${assignment.kind}`,
      `identity: ${identity}`,
    ].join("; ");
  });
  return ["FDAI agent ownership handover proposal", ...lines, ""].join("\n");
}

export function safeProposalUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password) return null;
    return url.href;
  } catch {
    return null;
  }
}

export function HandoverProposalEditor({ client, auth }: Props) {
  const api = useMemo(() => new IngestionApiClient(loadConfig(), client), [client]);
  const mounted = useRef(true);
  const nextRowId = useRef(2);
  const [capabilities, setCapabilities] = useState<IngestionCapabilities | null>(null);
  const [capabilityError, setCapabilityError] = useState<string | null>(null);
  const [rows, setRows] = useState<readonly HandoverAssignmentRow[]>([
    { id: 1, agent: DEFAULT_AGENT.name, kind: "user", responsibility: "accountable", identity: "" },
  ]);
  const [submitting, setSubmitting] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<HandoverDraftResult | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api.capabilities().then(
      (value) => {
        if (cancelled) return;
        if (!value.supported_formats.includes("text")) {
          setCapabilityError(t("handover.editor.textUnsupported"));
          return;
        }
        setCapabilities(value);
      },
      (reason: unknown) => {
        if (cancelled) return;
        setCapabilityError(capabilityFailure(reason));
      },
    );
    return () => {
      cancelled = true;
      mounted.current = false;
    };
  }, [api]);

  if (!canProposeHandover(auth)) {
    return (
      <section class="handover-editor handover-editor--locked" aria-labelledby="handover-editor-title">
        <div>
          <h3 id="handover-editor-title">{t("handover.editor.title")}</h3>
          <p>{t("handover.editor.permissionRequired")}</p>
        </div>
      </section>
    );
  }

  const valid = rows.length > 0 && rows.every(
    (row) => row.identity.trim().length > 0 && !/[;\r\n]/.test(row.identity),
  );

  const updateRow = (id: number, update: Partial<HandoverAssignmentInput>) => {
    setRows((current) => current.map((row) => row.id === id ? { ...row, ...update } : row));
    setResult(null);
    setError(null);
  };

  const addRow = () => {
    if (rows.length >= MAX_ASSIGNMENTS) return;
    const assigned = new Set(rows.map((row) => row.agent));
    const agent = PANTHEON.find((candidate) => !assigned.has(candidate.name)) ?? DEFAULT_AGENT;
    setRows((current) => [...current, {
      id: nextRowId.current++,
      agent: agent.name,
      kind: "user",
      responsibility: "accountable",
      identity: "",
    }]);
    setResult(null);
  };

  const removeRow = (id: number) => {
    setRows((current) => current.filter((row) => row.id !== id));
    setResult(null);
    setError(null);
  };

  const submit = async (event: SubmitEvent) => {
    event.preventDefault();
    setAttempted(true);
    if (!valid || capabilities === null || submitting) return;
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const content = buildHandoverDocument(rows);
      const file = new File([content], "agent-handover-raci.txt", { type: "text/plain" });
      if (file.size > capabilities.max_file_size) {
        throw new Error(t("handover.editor.fileTooLarge"));
      }
      const storageMode = capabilities.storage_modes.includes("managed_copy")
        ? "managed_copy"
        : capabilities.storage_modes[0];
      if (!storageMode) throw new Error(t("handover.editor.storageUnavailable"));
      const created = await api.createUpload({
        source_name: file.name,
        collection_id: "stewardship-handover",
        media_type_hint: file.type,
        expected_size: file.size,
        expected_sha256: await sha256(file),
        storage_mode: storageMode,
        purposes: ["handover_bootstrap"],
        access_descriptor_ref: "collection:stewardship-handover",
        retention_policy_version: capabilities.policy_versions[0] ?? "default",
        reader_groups: [],
      });
      const uploadId = created.session.upload_id;
      if (!mounted.current) {
        await api.cancel(uploadId).catch(() => undefined);
        return;
      }
      await api.uploadContent(created.upload.target, file);
      await api.completeUpload(uploadId);
      const terminal = await waitForTerminal(api, uploadId, () => mounted.current);
      if (terminal.state !== "ready" && terminal.state !== "ready_with_warnings") {
        throw new Error(t("handover.editor.processingFailed", { state: terminal.state }));
      }
      const draft = await api.handoverDraft(uploadId);
      if (mounted.current) setResult(draft);
    } catch (reason) {
      if (mounted.current) setError(proposalFailure(reason));
    } finally {
      if (mounted.current) setSubmitting(false);
    }
  };

  return (
    <section class="handover-editor" aria-labelledby="handover-editor-title">
      <header class="handover-editor__header">
        <div>
          <h3 id="handover-editor-title">{t("handover.editor.title")}</h3>
          <p>{t("handover.editor.description")}</p>
        </div>
        <span class="status-pill">{t("handover.editor.ownerReview")}</span>
      </header>

      <form onSubmit={(event) => void submit(event)}>
        <div class="handover-editor__labels" aria-hidden="true">
          <span>{t("handover.editor.agent")}</span>
          <span>{t("handover.editor.identity")}</span>
          <span>{t("handover.editor.kind")}</span>
          <span>{t("handover.editor.responsibility")}</span>
          <span />
        </div>
        <div class="handover-editor__rows">
          {rows.map((row) => (
            <div class="handover-editor__row" key={row.id}>
              <label>
                <span>{t("handover.editor.agent")}</span>
                <select
                  value={row.agent}
                  disabled={submitting}
                  onChange={(event) => updateRow(row.id, { agent: event.currentTarget.value })}
                >
                  {PANTHEON.map((agent) => <option value={agent.name}>{agent.name}</option>)}
                </select>
              </label>
              <label>
                <span>{t("handover.editor.identity")}</span>
                <input
                  value={row.identity}
                  maxLength={256}
                  disabled={submitting}
                  placeholder={t("handover.editor.identityPlaceholder")}
                  aria-invalid={attempted && !row.identity.trim() ? "true" : undefined}
                  onInput={(event) => updateRow(row.id, { identity: event.currentTarget.value })}
                />
              </label>
              <label>
                <span>{t("handover.editor.kind")}</span>
                <select
                  value={row.kind}
                  disabled={submitting}
                  onChange={(event) => updateRow(row.id, { kind: event.currentTarget.value as HandoverSubjectKind })}
                >
                  <option value="user">{t("handover.editor.user")}</option>
                  <option value="group">{t("handover.editor.group")}</option>
                </select>
              </label>
              <label>
                <span>{t("handover.editor.responsibility")}</span>
                <select
                  value={row.responsibility}
                  disabled={submitting}
                  onChange={(event) => updateRow(row.id, { responsibility: event.currentTarget.value as HandoverResponsibility })}
                >
                  <option value="accountable">{t("handover.editor.accountable")}</option>
                  <option value="informed">{t("handover.editor.informed")}</option>
                </select>
              </label>
              <button
                type="button"
                class="handover-editor__remove"
                aria-label={t("handover.editor.remove")}
                disabled={submitting}
                onClick={() => removeRow(row.id)}
              >
                <span aria-hidden="true">{"\u00d7"}</span>
              </button>
            </div>
          ))}
        </div>

        {rows.length === 0 ? <p class="muted">{t("handover.editor.empty")}</p> : null}
        {attempted && !valid ? <p class="error" role="alert">{t("handover.editor.validation")}</p> : null}
        {capabilityError ? <p class="error" role="alert">{capabilityError}</p> : null}
        {error ? <p class="error" role="alert">{error}</p> : null}

        <footer class="handover-editor__actions">
          <button type="button" class="secondary" disabled={submitting || rows.length >= MAX_ASSIGNMENTS} onClick={addRow}>
            <span aria-hidden="true">+</span> {t("handover.editor.add")}
          </button>
          <button type="submit" class="primary" disabled={!valid || capabilities === null || submitting}>
            {t(submitting ? "handover.editor.submitting" : "handover.editor.submit")}
          </button>
        </footer>
      </form>

      {result ? <HandoverProposalResult result={result} /> : null}
    </section>
  );
}

function HandoverProposalResult({ result }: { readonly result: HandoverDraftResult }) {
  const proposal = result.proposal;
  const proposalUrl = safeProposalUrl(proposal?.url);
  return (
    <div class="handover-editor__result" role="status">
      <div>
        <strong>{proposal ? t("handover.editor.proposalCreated") : t("handover.editor.draftCreated")}</strong>
        <p>{t("handover.editor.resultSummary", {
          mappings: result.draft.mappings.length,
          unresolved: result.draft.unresolved_people.length,
          unmapped: result.draft.unmapped_agents.length,
        })}</p>
      </div>
      {proposal && proposalUrl ? (
        <a class="handover-editor__proposal-link" href={proposalUrl} target="_blank" rel="noreferrer">
          {t("handover.editor.openProposal", { ref: proposal.pr_ref })}
        </a>
      ) : proposal ? <span class="status-pill">{proposal.pr_ref}</span> : null}
      <details>
        <summary>{t("handover.editor.reviewYaml")}</summary>
        <pre><code>{result.yaml}</code></pre>
      </details>
    </div>
  );
}

function capabilityFailure(reason: unknown): string {
  if (reason instanceof IngestionApiError && (reason.status === 404 || reason.status === 501)) {
    return t("handover.editor.serviceUnavailable");
  }
  return reason instanceof Error ? reason.message : t("handover.editor.serviceUnavailable");
}

function proposalFailure(reason: unknown): string {
  if (reason instanceof IngestionApiError && reason.status === 403) {
    return t("handover.editor.permissionDenied");
  }
  return reason instanceof Error ? reason.message : t("handover.editor.submitFailed");
}

async function sha256(file: File): Promise<string> {
  const { createSHA256 } = await import("hash-wasm");
  const hasher = await createSHA256();
  const reader = file.stream().getReader();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    hasher.update(value);
  }
  return hasher.digest("hex");
}
