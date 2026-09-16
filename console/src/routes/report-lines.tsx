import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import { AsyncBoundary, EmptyState, StatusPill, type AsyncState } from "../components/ui";
import { loadConfig } from "../config";
import {
  IngestionApiClient,
  type IngestionCapabilities,
  type ReportLineDraftResult,
} from "../ingestion-api";
import { formatConsoleTimestamp } from "../time-format";
import { waitForTerminal } from "./document-ingestion";
import { resolveHandoverAuthority } from "./handover-editor";
import { reportLineText as text } from "./i18n/report-lines";
import type {
  ReportingLineCase,
  ReportingLineProjection,
  ReportingLineState,
} from "./report-lines.model";
import { sha256 } from "./document-ingestion";

interface Props {
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
}

export function ReportLinesWorkspace({ client, auth }: Props) {
  const ingestion = useMemo(() => new IngestionApiClient(loadConfig(), client), [client]);
  const mounted = useRef(true);
  const [projection, setProjection] = useState<AsyncState<ReportingLineProjection>>({
    status: "loading",
  });
  const [capabilities, setCapabilities] = useState<IngestionCapabilities | null>(null);
  const [overview, setOverview] = useState<Awaited<ReturnType<typeof client.iamOverview>> | null>(
    null,
  );
  const [overviewFailed, setOverviewFailed] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [draft, setDraft] = useState<ReportLineDraftResult | null>(null);
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let cancelled = false;
    void client.reportingLines().then(
      (value) => {
        if (!cancelled) setProjection({ status: "ready", data: value });
      },
      (reason: unknown) => {
        if (!cancelled) {
          setProjection(
            isOptionalOperatorApiUnavailable(reason)
              ? { status: "unavailable", message: text("loadUnavailable") }
              : {
                  status: "error",
                  message: reason instanceof Error ? reason.message : String(reason),
                },
          );
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [client, refresh]);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([ingestion.capabilities(), client.iamOverview()]).then(
      ([nextCapabilities, nextOverview]) => {
        if (!cancelled) {
          setCapabilities(nextCapabilities);
          setOverview(nextOverview);
        }
      },
      () => {
        if (!cancelled) setOverviewFailed(true);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [client, ingestion]);

  useEffect(() => () => {
    mounted.current = false;
  }, []);

  const authority = resolveHandoverAuthority(auth, overview, overviewFailed);

  const extract = async (event: SubmitEvent) => {
    event.preventDefault();
    if (file === null || capabilities === null || working) {
      if (file === null) setError(text("fileRequired"));
      return;
    }
    setWorking(true);
    setError(null);
    setDraft(null);
    try {
      if (file.size > capabilities.max_file_size) {
        throw new Error(text("fileTooLarge"));
      }
      const storageMode = capabilities.storage_modes.includes("managed_copy")
        ? "managed_copy"
        : capabilities.storage_modes[0];
      if (storageMode === undefined) throw new Error(text("storageUnavailable"));
      const created = await ingestion.createUpload({
        source_name: file.name,
        collection_id: "human-report-lines",
        media_type_hint: file.type || "application/octet-stream",
        expected_size: file.size,
        expected_sha256: await sha256(file),
        storage_mode: storageMode,
        purposes: ["report_line_bootstrap"],
        access_descriptor_ref: "collection:human-report-lines",
        retention_policy_version: capabilities.policy_versions[0] ?? "default",
      });
      await ingestion.uploadContent(created.upload.target, file);
      await ingestion.completeUpload(created.session.upload_id);
      const terminal = await waitForTerminal(
        ingestion,
        created.session.upload_id,
        () => mounted.current,
      );
      if (terminal.state !== "ready" && terminal.state !== "ready_with_warnings") {
        throw new Error(text("processingFailed", { state: terminal.state }));
      }
      const result = await ingestion.reportLineDraft(created.session.upload_id);
      if (mounted.current) {
        setDraft(result);
        setSelected(new Set(result.candidates.map((candidate) => candidate.candidate_id)));
      }
    } catch (reason) {
      if (mounted.current) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      if (mounted.current) setWorking(false);
    }
  };

  const submitSelected = async () => {
    if (draft === null || selected.size === 0 || working) return;
    setWorking(true);
    setError(null);
    try {
      for (const candidate of draft.candidates) {
        if (!selected.has(candidate.candidate_id)) continue;
        await client.createReportingLineCase(
          {
            idempotency_key: `report-line:${draft.upload_id}:${candidate.candidate_id}`,
            upload_id: draft.upload_id,
            candidate_id: candidate.candidate_id,
            effective_from: null,
            effective_until: null,
            supersedes_case_id: null,
          },
          `report-line:${draft.upload_id}:${candidate.candidate_id}`,
        );
      }
      setDraft(null);
      setSelected(new Set());
      setRefresh((value) => value + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setWorking(false);
    }
  };

  const decide = async (
    item: ReportingLineCase,
    operation: "confirm" | "review",
    decision: "confirm" | "approve" | "reject",
  ) => {
    if (item.edgeDigest === null || working) return;
    setWorking(true);
    setError(null);
    try {
      await client.decideReportingLineCase(
        item.operatorCaseId,
        operation,
        {
          expected_revision: item.revision,
          decision,
          edge_digest: item.edgeDigest,
        },
        `report-line:${operation}:${item.operatorCaseId}:${item.revision}:${decision}`,
      );
      setRefresh((value) => value + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setWorking(false);
    }
  };

  return (
    <div class="stack report-lines-workspace">
      <section class="settings-iam-panel" aria-labelledby="report-line-import-title">
        <header class="settings-iam-panel-head">
          <div>
            <h3 id="report-line-import-title">{text("importTitle")}</h3>
            <p>{text("importBody")}</p>
          </div>
        </header>
        {authority === "granted" ? (
          <form class="stack report-line-import-form" onSubmit={(event) => void extract(event)}>
            <label>
              <span>{text("selectFile")}</span>
              <input
                type="file"
                disabled={working}
                accept=".csv,.txt,.pdf,.docx,.pptx,.xlsx,image/png,image/jpeg,image/tiff"
                onChange={(event) => setFile(event.currentTarget.files?.[0] ?? null)}
              />
            </label>
            <div>
              <button class="btn btn-primary" type="submit" disabled={working || file === null}>
                {working ? text("uploading") : text("upload")}
              </button>
            </div>
          </form>
        ) : (
          <p>{text("permissionRequired")}</p>
        )}
        {error !== null ? <div class="state-block state-error" role="alert">{error}</div> : null}
      </section>

      {draft !== null ? (
        <section class="settings-iam-panel" aria-labelledby="report-line-draft-title">
          <header class="settings-iam-panel-head">
            <div>
              <h3 id="report-line-draft-title">{text("draftTitle")}</h3>
              <p><code>{draft.document_id}</code></p>
            </div>
          </header>
          {draft.warnings.length > 0 ? (
            <div class="state-block state-warning" role="status">
              <strong>{text("warningTitle")}</strong>
              <ul>{draft.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
            </div>
          ) : null}
          {draft.candidates.length === 0 ? (
            <p>{text("draftEmpty")}</p>
          ) : (
            <div class="stack">
              {draft.candidates.map((candidate) => (
                <article class="approval-card" key={candidate.candidate_id}>
                  <div class="approval-card-body">
                  <label>
                    <input
                      type="checkbox"
                      checked={selected.has(candidate.candidate_id)}
                      disabled={working}
                      aria-label={text("selectRelationship", {
                        subject: candidate.subject.display_name,
                        manager: candidate.manager.display_name,
                      })}
                      onChange={(event) => {
                        const next = new Set(selected);
                        if (event.currentTarget.checked) next.add(candidate.candidate_id);
                        else next.delete(candidate.candidate_id);
                        setSelected(next);
                      }}
                    />
                    <strong>{text("relationship", {
                      subject: candidate.subject.display_name,
                      manager: candidate.manager.display_name,
                    })}</strong>
                  </label>
                  <StatusPill
                    kind={candidate.directory_comparison === "matched" ? "success" : "neutral"}
                    label={directoryLabel(candidate.directory_comparison)}
                  />
                  <p>{text("confidence")}: {Math.round(candidate.confidence * 100)}%</p>
                  <details>
                    <summary>{text("source")}</summary>
                    {candidate.citations.map((citation) => (
                      <p key={`${citation.unit_id}:${citation.locator}`}>
                        <code>{citation.locator}</code> {citation.quote}
                      </p>
                    ))}
                  </details>
                  </div>
                </article>
              ))}
              <div>
                <button
                  type="button"
                  class="btn btn-primary"
                  disabled={working || selected.size === 0}
                  onClick={() => void submitSelected()}
                >
                  {working ? text("submittingSelected") : text("submitSelected")}
                </button>
              </div>
            </div>
          )}
        </section>
      ) : null}

      <section class="settings-iam-panel" aria-labelledby="report-line-current-title">
        <header class="settings-iam-panel-head">
          <div>
            <h3 id="report-line-current-title">{text("currentTitle")}</h3>
            <p>{text("currentBody")}</p>
          </div>
          <button type="button" class="btn" onClick={() => setRefresh((value) => value + 1)}>
            {text("refresh")}
          </button>
        </header>
        <AsyncBoundary state={projection} resourceLabel={text("title")}>
          {(value) => value.items.length === 0 ? (
            <EmptyState title={text("noCases")} body={text("currentBody")} />
          ) : (
            <div class="stack">
              <div class="approvals-summary">
                <StatusPill kind="success" label={`${text("active")}: ${value.summary.active}`} />
                <StatusPill kind="hil" label={`${text("pendingConfirmation")}: ${value.summary.pendingConfirmation}`} />
                <StatusPill kind="neutral" label={`${text("pendingOwnerReview")}: ${value.summary.pendingOwnerReview}`} />
                <StatusPill kind="danger" label={`${text("conflict")}: ${value.summary.conflict}`} />
              </div>
              <div class="approval-card-list">
                {value.items.map((item) => (
                  <ReportingLineRecord
                    key={item.operatorCaseId}
                    item={item}
                    working={working}
                    onDecide={decide}
                  />
                ))}
              </div>
            </div>
          )}
        </AsyncBoundary>
      </section>
    </div>
  );
}

function ReportingLineRecord({
  item,
  working,
  onDecide,
}: {
  readonly item: ReportingLineCase;
  readonly working: boolean;
  readonly onDecide: (
    item: ReportingLineCase,
    operation: "confirm" | "review",
    decision: "confirm" | "approve" | "reject",
  ) => Promise<void>;
}) {
  return (
    <article class="approval-card">
      <div class="approval-card-body">
      <header>
        <h4>{item.subjectRef !== null && item.managerRef !== null
          ? text("relationship", { subject: item.subjectRef, manager: item.managerRef })
          : item.candidateId}</h4>
        <StatusPill kind={statusKind(item.state)} label={statusLabel(item.state)} />
      </header>
      <dl class="approval-facts">
        <div><dt>{text("subject")}</dt><dd><code>{item.subjectRef ?? "-"}</code></dd></div>
        <div><dt>{text("manager")}</dt><dd><code>{item.managerRef ?? "-"}</code></dd></div>
        <div><dt>{text("effectiveWindow")}</dt><dd>
          {item.effectiveFrom !== null ? formatConsoleTimestamp(item.effectiveFrom) : "-"}
          {" - "}
          {item.effectiveUntil !== null ? formatConsoleTimestamp(item.effectiveUntil) : "-"}
        </dd></div>
      </dl>
      {item.canConfirm ? (
        <div class="approval-decision-actions">
          <button
            type="button"
            class="btn btn-primary"
            disabled={working}
            onClick={() => void onDecide(item, "confirm", "confirm")}
          >
            {text("confirm")}
          </button>
          <button
            type="button"
            class="btn"
            disabled={working}
            onClick={() => void onDecide(item, "confirm", "reject")}
          >
            {text("denyRelationship")}
          </button>
        </div>
      ) : null}
      {item.canReview ? (
        <div class="approval-decision-actions">
          <button
            type="button"
            class="btn btn-primary"
            disabled={working}
            onClick={() => void onDecide(item, "review", "approve")}
          >
            {text("approveEdge")}
          </button>
          <button
            type="button"
            class="btn"
            disabled={working}
            onClick={() => void onDecide(item, "review", "reject")}
          >
            {text("rejectEdge")}
          </button>
        </div>
      ) : null}
      <details>
        <summary>{text("technicalDetails")}</summary>
        <p><code>{item.operatorCaseId}</code></p>
        {item.edgeDigest !== null ? <p><code>{item.edgeDigest}</code></p> : null}
      </details>
      </div>
    </article>
  );
}

function directoryLabel(value: string): string {
  if (value === "matched") return text("directoryMatched");
  if (value === "conflict") return text("directoryConflict");
  return text("directoryUnavailable");
}

function statusLabel(value: ReportingLineState): string {
  const labels: Record<ReportingLineState, ReturnType<typeof text>> = {
    active: text("active"),
    pending_confirmation: text("pendingConfirmation"),
    pending_owner_review: text("pendingOwnerReview"),
    activation_pending: text("activationPending"),
    conflict: text("conflict"),
    awaiting_core: text("awaitingCore"),
    rejected: text("rejected"),
    superseded: text("superseded"),
  };
  return labels[value];
}

function statusKind(value: ReportingLineState): "success" | "hil" | "danger" | "neutral" {
  if (value === "active") return "success";
  if (value === "conflict" || value === "rejected") return "danger";
  if (
    value === "pending_confirmation"
    || value === "pending_owner_review"
    || value === "activation_pending"
  ) return "hil";
  return "neutral";
}
