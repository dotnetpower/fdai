import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import {
  AsyncBoundary,
  DataTable,
  EmptyState,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
} from "../components/ui";
import type { ConsoleDataMode } from "../console-data-mode";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary, TERMS } from "../deck/glossary";
import { currentRoute, navigate, routeHref, ROUTE_STATE_EVENT } from "../router";
import "./background-tasks.css";
import { backgroundTasksText } from "./background-tasks.i18n";
import {
  BACKGROUND_TASK_INTENTS,
  appendBackgroundTaskPage,
  backgroundTaskTone,
  canCancelBackgroundTask,
  decodeBackgroundTaskDetail,
  decodeBackgroundTaskPage,
  decodeBackgroundTaskProgress,
  formatBackgroundTaskTimestamp,
  normalizeBackgroundTaskCreateInput,
  type BackgroundTaskCreateInput,
  type BackgroundTaskCursor,
  type BackgroundTaskItem,
  type BackgroundTaskPage,
  type BackgroundTaskProgressPage,
  type BackgroundTaskStatus,
} from "./background-tasks.model";
import {
  buildTaskWorkersViewModel,
  decodeTaskWorkerDetailProjection,
  decodeTaskWorkerEventsProjection,
  decodeTaskWorkerListProjection,
  type TaskWorkersViewModel,
} from "./task-workers.model";

export {
  buildTaskWorkersViewModel,
  decodeTaskWorkerDetailProjection,
  decodeTaskWorkerEventsProjection,
  decodeTaskWorkerListProjection,
  type TaskWorkersViewModel,
};

const PAGE_SIZE = 50;
const EMPTY_CREATE_INPUT: BackgroundTaskCreateInput = {
  prompt: "",
  intent: "resource_state",
  resourceName: "",
  resourceType: "",
  resourceGroup: "",
  explicitDeep: false,
};

interface TaskDetail {
  readonly task: BackgroundTaskItem;
  readonly progress: BackgroundTaskProgressPage;
}

export function backgroundTasksHref(
  taskId: string | null,
  sampleMode: boolean,
): string {
  return routeHref("background-tasks", {
    ...(taskId !== null ? { segments: [taskId] } : {}),
    params: { data: sampleMode ? "sample" : null },
  });
}

export function BackgroundTasksRoute({
  client,
  dataMode,
}: {
  readonly client: OperatorApiClient;
  readonly dataMode?: ConsoleDataMode;
}) {
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(
    () => currentRoute().segments[0] ?? null,
  );
  const [pageState, setPageState] = useState<AsyncState<BackgroundTaskPage>>({ status: "loading" });
  const [detailState, setDetailState] = useState<AsyncState<TaskDetail>>(
    selectedTaskId === null ? { status: "idle" } : { status: "loading" },
  );
  const [loadingMore, setLoadingMore] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [createInput, setCreateInput] = useState<BackgroundTaskCreateInput>(EMPTY_CREATE_INPUT);
  const [creating, setCreating] = useState(false);
  const [cancellingTaskId, setCancellingTaskId] = useState<string | null>(null);
  const [mutationNotice, setMutationNotice] = useState<string | null>(null);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const generation = useRef(0);
  const detailGeneration = useRef(0);
  const createIdempotencyKey = useRef<string | null>(null);
  const cancelIdempotency = useRef<{ readonly taskId: string; readonly key: string } | null>(null);
  const sampleMode = dataMode === "sample" || currentRoute().search.get("data") === "sample";

  useEffect(() => {
    const sync = () => setSelectedTaskId(currentRoute().segments[0] ?? null);
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    window.addEventListener(ROUTE_STATE_EVENT, sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
      window.removeEventListener(ROUTE_STATE_EVENT, sync);
    };
  }, []);

  const loadPage = async (cursor: BackgroundTaskCursor | null): Promise<void> => {
    const request = cursor === null ? ++generation.current : generation.current;
    setPageError(null);
    if (cursor === null) setPageState({ status: "loading" });
    else setLoadingMore(true);
    try {
      const payload = await client.panel<unknown>("/background-tasks", {
        limit: String(PAGE_SIZE),
        ...(cursor ?? {}),
      });
      const page = decodeBackgroundTaskPage(payload);
      if (request !== generation.current) return;
      setPageState((current) => cursor !== null && current.status === "ready"
        ? { status: "ready", data: appendBackgroundTaskPage(current.data, cursor, page) }
        : { status: "ready", data: page });
    } catch (error) {
      if (request !== generation.current) return;
      const message = error instanceof Error ? error.message : String(error);
      if (cursor === null) setPageState({ status: "error", message });
      else setPageError(message);
    } finally {
      if (request === generation.current) setLoadingMore(false);
    }
  };

  const loadDetail = async (taskId: string, refresh = false): Promise<void> => {
    const request = ++detailGeneration.current;
    if (refresh) setRefreshing(true);
    else setDetailState({ status: "loading" });
    try {
      const encoded = encodeURIComponent(taskId);
      const detailPayload = await client.panel<unknown>(`/background-tasks/${encoded}`);
      let task = decodeBackgroundTaskDetail(detailPayload);
      const progressPayload = await client.panel<unknown>(
        `/background-tasks/${encoded}/progress`,
        { limit: "256" },
      );
      const progress = decodeBackgroundTaskProgress(progressPayload);
      if (task.task_id !== taskId || progress.task_id !== taskId) {
        throw new Error("background task response identity does not match the selected task");
      }
      if (task.status !== progress.status) {
        task = decodeBackgroundTaskDetail(
          await client.panel<unknown>(`/background-tasks/${encoded}`),
        );
        if (task.task_id !== taskId || task.status !== progress.status) {
          throw new Error("background task detail and progress snapshots do not converge");
        }
      }
      if (request !== detailGeneration.current) return;
      setDetailState({ status: "ready", data: { task, progress } });
    } catch (error) {
      if (request !== detailGeneration.current) return;
      setDetailState({
        status: "error",
        message: error instanceof Error ? error.message : String(error),
      });
    } finally {
      if (request === detailGeneration.current) setRefreshing(false);
    }
  };

  useEffect(() => {
    setLoadingMore(false);
    setMutationNotice(null);
    setMutationError(null);
    void loadPage(null);
    return () => { generation.current += 1; };
  }, [client]);

  useEffect(() => {
    if (selectedTaskId === null) {
      detailGeneration.current += 1;
      setDetailState({ status: "idle" });
    }
    else void loadDetail(selectedTaskId);
    return () => { detailGeneration.current += 1; };
  }, [client, selectedTaskId]);

  const createTask = async (): Promise<void> => {
    const request = normalizeBackgroundTaskCreateInput(createInput);
    if (request === null || creating) return;
    setCreating(true);
    setMutationNotice(null);
    setMutationError(null);
    createIdempotencyKey.current ??= `background-create-${crypto.randomUUID()}`;
    try {
      const receipt = await client.createBackgroundTask(request, createIdempotencyKey.current);
      createIdempotencyKey.current = null;
      setCreateInput(EMPTY_CREATE_INPUT);
      setMutationNotice(backgroundTasksText("createQueued", { taskId: receipt.task_id }));
      await loadPage(null);
    } catch (error) {
      setMutationError(error instanceof Error ? error.message : String(error));
    } finally {
      setCreating(false);
    }
  };

  const cancelTask = async (taskId: string): Promise<void> => {
    if (cancellingTaskId !== null) return;
    setCancellingTaskId(taskId);
    setMutationNotice(null);
    setMutationError(null);
    if (cancelIdempotency.current?.taskId !== taskId) {
      cancelIdempotency.current = {
        taskId,
        key: `background-cancel-${crypto.randomUUID()}`,
      };
    }
    try {
      await client.cancelBackgroundTask(taskId, cancelIdempotency.current.key);
      cancelIdempotency.current = null;
      setMutationNotice(backgroundTasksText("cancelQueued", { taskId }));
      await Promise.all([loadPage(null), loadDetail(taskId, true)]);
    } catch (error) {
      setMutationError(error instanceof Error ? error.message : String(error));
    } finally {
      setCancellingTaskId(null);
    }
  };

  return (
    <div class="stack background-tasks-route">
      <PageHeader title={backgroundTasksText("title")} subtitle={backgroundTasksText("subtitle")} />
      <p class="background-task-boundary">
        <strong>{backgroundTasksText("boundaryTitle")}</strong>
        <span>{backgroundTasksText(sampleMode ? "sampleBoundary" : "boundary")}</span>
      </p>
      {sampleMode ? null : (
        <BackgroundTaskCreateForm
          value={createInput}
          submitting={creating}
          onChange={setCreateInput}
          onSubmit={() => void createTask()}
        />
      )}
      {mutationNotice ? <p class="notice" role="status">{mutationNotice}</p> : null}
      {mutationError ? <p class="error" role="alert">{mutationError}</p> : null}
      <AsyncBoundary state={pageState} resourceLabel={backgroundTasksText("resourceLabel")}>
        {(page) => (
          <TaskTable
            page={page}
            selectedTaskId={selectedTaskId}
            loadingMore={loadingMore}
            pageError={pageError}
            onSelect={(task) => navigate(backgroundTasksHref(task.task_id, sampleMode))}
            onLoadMore={() => {
              if (page.next_cursor !== null) void loadPage(page.next_cursor);
            }}
          />
        )}
      </AsyncBoundary>
      {selectedTaskId === null ? null : (
        // A stable container keeps the row's aria-controls target present while the detail loads or fails.
        <div id="background-task-detail">
          <AsyncBoundary state={detailState} resourceLabel={backgroundTasksText("detailLabel", { taskId: selectedTaskId })}>
            {(detail) => (
              <TaskDetailView
                detail={detail}
                refreshing={refreshing}
                cancellationAvailable={!sampleMode && canCancelBackgroundTask(detail.task.status)}
                cancelling={cancellingTaskId === selectedTaskId}
                onRefresh={() => void loadDetail(selectedTaskId, true)}
                onCancel={() => void cancelTask(selectedTaskId)}
                onClose={() => navigate(backgroundTasksHref(null, sampleMode))}
              />
            )}
          </AsyncBoundary>
        </div>
      )}
    </div>
  );
}

function BackgroundTaskCreateForm({ value, submitting, onChange, onSubmit }: {
  readonly value: BackgroundTaskCreateInput;
  readonly submitting: boolean;
  readonly onChange: (value: BackgroundTaskCreateInput) => void;
  readonly onSubmit: () => void;
}) {
  const request = normalizeBackgroundTaskCreateInput(value);
  return (
    <form
      class="background-task-create"
      aria-labelledby="background-task-create-title"
      onSubmit={(event) => { event.preventDefault(); onSubmit(); }}
    >
      <div class="background-task-create-heading">
        <h2 id="background-task-create-title">{backgroundTasksText("createTitle")}</h2>
        <p>{backgroundTasksText("createDescription")}</p>
      </div>
      <div class="background-task-create-grid">
        <label class="background-task-create-prompt">
          <span>{backgroundTasksText("prompt")}</span>
          <textarea
            required
            maxLength={4_000}
            rows={3}
            value={value.prompt}
            onInput={(event) => onChange({ ...value, prompt: event.currentTarget.value })}
          />
        </label>
        <label>
          <span>{backgroundTasksText("intent")}</span>
          <select
            value={value.intent}
            onChange={(event) => onChange({
              ...value,
              intent: event.currentTarget.value as BackgroundTaskCreateInput["intent"],
            })}
          >
            {BACKGROUND_TASK_INTENTS.map((intent) => (
              <option key={intent} value={intent}>{backgroundTasksText(`intent_${intent}`)}</option>
            ))}
          </select>
        </label>
        <label>
          <span>{backgroundTasksText("resourceName")}</span>
          <input
            required
            maxLength={512}
            value={value.resourceName}
            onInput={(event) => onChange({ ...value, resourceName: event.currentTarget.value })}
          />
        </label>
        <label class="background-task-create-secondary">
          <span>{backgroundTasksText("resourceType")}</span>
          <input
            maxLength={256}
            value={value.resourceType}
            onInput={(event) => onChange({ ...value, resourceType: event.currentTarget.value })}
          />
        </label>
        <label class="background-task-create-secondary">
          <span>{backgroundTasksText("resourceGroup")}</span>
          <input
            maxLength={512}
            value={value.resourceGroup}
            onInput={(event) => onChange({ ...value, resourceGroup: event.currentTarget.value })}
          />
        </label>
      </div>
      <div class="background-task-create-actions">
        <label class="background-task-deep-option">
          <input
            type="checkbox"
            checked={value.explicitDeep}
            onChange={(event) => onChange({ ...value, explicitDeep: event.currentTarget.checked })}
          />
          <span>{backgroundTasksText("explicitDeep")}</span>
        </label>
        <button type="submit" class="btn primary" disabled={submitting || request === null}>
          {backgroundTasksText(submitting ? "creating" : "create")}
        </button>
      </div>
    </form>
  );
}

function TaskTable({ page, selectedTaskId, loadingMore, pageError, onSelect, onLoadMore }: {
  readonly page: BackgroundTaskPage;
  readonly selectedTaskId: string | null;
  readonly loadingMore: boolean;
  readonly pageError: string | null;
  readonly onSelect: (task: BackgroundTaskItem) => void;
  readonly onLoadMore: () => void;
}) {
  usePublishViewContext(
    () => ({
      routeId: "background-tasks",
      routeLabel: backgroundTasksText("title"),
      purpose: backgroundTasksText("subtitle"),
      glossary: composeGlossary([TERMS.backgroundTask]),
      headline: backgroundTasksText("viewHeadline", { count: page.tasks.length }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "loaded_tasks", value: page.tasks.length, group: "background-tasks" },
        { key: "has_more", value: page.has_more, group: "background-tasks" },
      ],
      records: { tasks: page.tasks.map((task) => ({ ...task })) },
    }),
    [page],
  );
  const columns: readonly Column<BackgroundTaskItem>[] = [
    {
      key: "work",
      header: backgroundTasksText("requestedWork"),
      render: (task) => (
        <span class="background-task-work-cell">
          <strong>{task.request_summary ?? backgroundTasksText("requestUnavailable")}</strong>
          <span class="mono">{task.task_id}</span>
        </span>
      ),
    },
    {
      key: "agent",
      header: backgroundTasksText("accountableAgent"),
      render: (task) => (
        <span class={`background-task-agent${task.accountable_agent === null ? " is-unattributed" : ""}`}>
          {task.accountable_agent ?? backgroundTasksText("agentUnattributed")}
        </span>
      ),
    },
    {
      key: "status",
      header: backgroundTasksText("status"),
      render: (task) => <StatusPill kind={backgroundTaskTone(task.status)} label={statusLabel(task.status)} />,
    },
    {
      key: "outcome",
      header: backgroundTasksText("outcome"),
      render: (task) => <span class="background-task-outcome-preview">{outcomeText(task)}</span>,
    },
    { key: "updated", header: backgroundTasksText("updatedAt"), render: (task) => formatBackgroundTaskTimestamp(task.updated_at) },
  ];
  return (
    <section class="stack-section" aria-label={backgroundTasksText("resourceLabel")}>
      <DataTable
        columns={columns}
        rows={page.tasks}
        keyOf={(task) => task.task_id}
        empty={<EmptyState title={backgroundTasksText("empty")} />}
        onRowClick={onSelect}
        isRowActive={(task) => task.task_id === selectedTaskId}
        rowActionLabel={(task) => backgroundTasksText("selectTask", { taskId: task.task_id })}
        rowActionControls="background-task-detail"
      />
      {page.next_cursor !== null ? (
        <button type="button" class="btn" disabled={loadingMore} onClick={onLoadMore}>
          {backgroundTasksText(loadingMore ? "loadingMore" : "loadMore")}
        </button>
      ) : null}
      {pageError ? <div class="error" role="alert">{backgroundTasksText("loadMoreError", { message: pageError })}</div> : null}
    </section>
  );
}

function TaskDetailView({ detail, refreshing, cancellationAvailable, cancelling, onRefresh, onCancel, onClose }: {
  readonly detail: TaskDetail;
  readonly refreshing: boolean;
  readonly cancellationAvailable: boolean;
  readonly cancelling: boolean;
  readonly onRefresh: () => void;
  readonly onCancel: () => void;
  readonly onClose: () => void;
}) {
  const { task, progress } = detail;
  return (
    <section class="stack-section" aria-label={backgroundTasksText("detailLabel", { taskId: task.task_id })}>
      <header class="background-task-detail-header">
        <div class="background-task-detail-heading">
          <p class="background-task-eyebrow mono">{task.task_id}</p>
          <h2>{task.request_summary ?? backgroundTasksText("investigationFallback")}</h2>
          <div class="background-task-heading-meta">
            <StatusPill kind={backgroundTaskTone(task.status)} label={statusLabel(task.status)} />
            <span class={`background-task-agent${task.accountable_agent === null ? " is-unattributed" : ""}`}>
              {backgroundTasksText("agentPrefix")}: {task.accountable_agent ?? backgroundTasksText("agentUnattributed")}
            </span>
          </div>
        </div>
        <div class="background-task-actions">
          <button type="button" class="btn" disabled={refreshing} onClick={onRefresh}>{backgroundTasksText(refreshing ? "refreshing" : "refresh")}</button>
          {cancellationAvailable ? (
            <button type="button" class="btn danger" disabled={cancelling} onClick={onCancel}>
              {backgroundTasksText(cancelling ? "cancelling" : "cancel")}
            </button>
          ) : null}
          <button type="button" class="btn" onClick={onClose}>{backgroundTasksText("closeDetail")}</button>
        </div>
      </header>
      <section class="background-task-section" aria-labelledby="background-task-request-title">
        <h3 id="background-task-request-title">{backgroundTasksText("requestedWork")}</h3>
        <p class={`background-task-narrative${task.request_summary === null ? " is-unavailable" : ""}`}>
          {task.request_summary ?? backgroundTasksText("requestUnavailableDetail")}
        </p>
        {task.request_truncated ? <p class="muted small">{backgroundTasksText("requestTruncated")}</p> : null}
      </section>
      <section class="background-task-section" aria-labelledby="background-task-outcome-title">
        <h3 id="background-task-outcome-title">{backgroundTasksText("outcomeAndEvidence")}</h3>
        <p class={`background-task-narrative${task.result_summary === null ? " is-unavailable" : ""}`}>
          {outcomeText(task, true)}
        </p>
        {task.result_truncated ? <p class="muted small">{backgroundTasksText("resultTruncated")}</p> : null}
        <div class="background-task-evidence">
          <strong>{backgroundTasksText("evidence")}</strong>
          {task.evidence_refs.length === 0 ? (
            <span class="muted">{backgroundTasksText("evidenceNone")}</span>
          ) : (
            <ul>
              {task.evidence_refs.map((reference) => <li key={reference}><code>{reference}</code></li>)}
            </ul>
          )}
          {task.evidence_truncated ? <span class="muted small">{backgroundTasksText("evidenceTruncated")}</span> : null}
        </div>
      </section>
      <section class="background-task-section" aria-labelledby="background-task-attribution-title">
        <h3 id="background-task-attribution-title">{backgroundTasksText("executionAttribution")}</h3>
        <dl class="detail-grid background-task-attribution-grid">
          <Fact label={backgroundTasksText("accountableAgent")} value={task.accountable_agent ?? backgroundTasksText("agentUnattributed")} />
          <Fact label={backgroundTasksText("executionWorker")} value={workerLabel(task.execution_worker)} />
          <Fact label={backgroundTasksText("kind")} value={kindLabel(task.kind)} />
          <Fact label={backgroundTasksText("updatedAt")} value={formatBackgroundTaskTimestamp(task.updated_at)} />
        </dl>
      </section>
      <section class="background-task-section" aria-labelledby="background-task-progress-title">
        <h3 id="background-task-progress-title">{backgroundTasksText("activityTimeline")}</h3>
        {progress.events.length === 0 ? <EmptyState title={backgroundTasksText("noProgress")} /> : (
          <ol class="background-task-timeline">
            {progress.events.map((event) => (
              <li key={event.sequence}>
                <span class="background-task-sequence" aria-hidden="true">{event.sequence + 1}</span>
                <div>
                  <strong>{eventKindLabel(event.kind)}</strong>
                  <p>{event.message}</p>
                </div>
                <time dateTime={event.at}>{formatBackgroundTaskTimestamp(event.at)}</time>
              </li>
            ))}
          </ol>
        )}
      </section>
      <details class="background-task-technical">
        <summary>{backgroundTasksText("technicalDetails")}</summary>
        <dl class="detail-grid">
          <Fact label={backgroundTasksText("createdAt")} value={formatBackgroundTaskTimestamp(task.created_at)} />
          <Fact label={backgroundTasksText("leaseExpiresAt")} value={formatBackgroundTaskTimestamp(task.lease_expires_at)} />
          <Fact label={backgroundTasksText("retentionUntil")} value={formatBackgroundTaskTimestamp(task.retention_until)} />
          <Fact label={backgroundTasksText("terminalReason")} value={task.terminal_reason ?? "-"} />
          <Fact label={backgroundTasksText("completionState")} value={task.completion_state ?? "-"} />
          <Fact label={backgroundTasksText("duration")} value={task.duration_seconds === null ? "-" : `${task.duration_seconds.toFixed(1)} s`} />
          <Fact label={backgroundTasksText("tokens")} value={displayNumber(task.usage["tokens"])} />
          <Fact label={backgroundTasksText("toolCalls")} value={displayNumber(task.usage["tool_calls"])} />
          <Fact label={backgroundTasksText("cost")} value={displayNumber(task.usage["cost_microusd"])} />
        </dl>
      </details>
    </section>
  );
}

function Fact({ label, value }: { readonly label: string; readonly value: string }) {
  return <><dt class="muted">{label}</dt><dd>{value}</dd></>;
}

function displayNumber(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value.toLocaleString()
    : "-";
}

function outcomeText(task: BackgroundTaskItem, detailed = false): string {
  if (task.result_summary !== null) return task.result_summary;
  if (task.status === "queued" || task.status === "claimed" || task.status === "running") {
    return backgroundTasksText(detailed ? "resultPendingDetail" : "resultPending");
  }
  return backgroundTasksText(detailed ? "resultUnavailableDetail" : "resultUnavailable");
}

function workerLabel(worker: string): string {
  return worker === "background-task-coordinator"
    ? backgroundTasksText("backgroundTaskCoordinator")
    : worker;
}

function kindLabel(kind: string): string {
  return kind === "read_only_investigation" ? backgroundTasksText("readOnlyInvestigation") : kind;
}

function eventKindLabel(kind: string): string {
  const labels: Readonly<Record<string, string>> = {
    "investigation.planned": backgroundTasksText("phasePlanned"),
    "investigation.started": backgroundTasksText("phaseStarted"),
    "investigation.progress": backgroundTasksText("phaseProgress"),
    "investigation.completed": backgroundTasksText("phaseCompleted"),
  };
  return labels[kind] ?? kind;
}

function statusLabel(status: BackgroundTaskStatus): string {
  const keys = {
    queued: "statusQueued",
    claimed: "statusClaimed",
    running: "statusRunning",
    succeeded: "statusSucceeded",
    failed: "statusFailed",
    cancelled: "statusCancelled",
    timed_out: "statusTimedOut",
    unknown: "statusUnknown",
  } as const;
  return backgroundTasksText(keys[status]);
}
