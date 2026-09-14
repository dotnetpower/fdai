import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { triggerBlobDownload } from "../blob-download";
import {
  AsyncBoundary, ErrorState, type AsyncState,
} from "../components/ui";
import { loadConfig } from "../config";
import {
  IngestionApiClient, IngestionApiError,
  type CloudKnowledgeIntakeResult, type CloudKnowledgeOverview,
} from "../ingestion-api";
import type { PanelProps } from "../panels";
import { routeHref } from "../router";
import { cloudKnowledgeText as text, type CloudKnowledgeMessageKey } from "./cloud-knowledge.i18n";
import {
  canImportCloudKnowledgePackage, cloudKnowledgeOutcomeText, cloudKnowledgePermissions,
  formatCloudKnowledgeDate, isCloudKnowledgePackageFile, requireCloudKnowledgeOverview,
  requireCloudKnowledgeRelease,
  type InspectedCloudKnowledgePackage,
} from "./cloud-knowledge.model";
import {
  ActionButton, CollectionList, CONTROL_STYLE, Metadata, PackageIntake, SourceList,
} from "./cloud-knowledge.views";

type RequestKind = "load" | "refresh" | "export" | "stage" | "inspect" | "import";
const BUSY_KEYS: Readonly<Record<RequestKind, CloudKnowledgeMessageKey>> = {
  load: "loading", refresh: "checking", export: "exporting", stage: "staging",
  inspect: "inspecting", import: "importing",
};

/** A bounded tool inside Knowledge overview; all authority and lifecycle transitions remain server-owned. */
export function CloudKnowledgePanel({ client, dataMode }: PanelProps) {
  const { api, readTimeout } = useMemo(() => {
    const config = loadConfig();
    return { api: new IngestionApiClient(config, client), readTimeout: config.operatorApiRequestTimeoutMs };
  }, [client]);
  const [view, setView] = useState<{ api: IngestionApiClient; state: AsyncState<CloudKnowledgeOverview> }>({
    api, state: { status: "loading" },
  });
  const [busy, setBusy] = useState<RequestKind | null>("load");
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [requiresReload, setRequiresReload] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [inspection, setInspection] = useState<InspectedCloudKnowledgePackage | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const request = useRef<AbortController | null>(null);
  const selectedFile = useRef<File | null>(null);
  const confirmedFile = useRef<File | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const state: AsyncState<CloudKnowledgeOverview> = view.api === api ? view.state : { status: "loading" };
  const overview = state.status === "ready" && dataMode === "live" ? state.data : null;
  const permissions = cloudKnowledgePermissions(overview, busy !== null || requiresReload);

  const clearInspection = () => {
    confirmedFile.current = null;
    setInspection(null);
    setConfirmed(false);
  };
  const confirmPackage = (next: boolean) => {
    const allowed = next && permissions.import && request.current === null && file !== null
      && selectedFile.current === file && inspection?.file === file;
    confirmedFile.current = allowed ? file : null;
    setConfirmed(allowed);
  };
  const chooseFile = (next: File | null) => {
    if (request.current !== null) return;
    selectedFile.current = next;
    setFile(next);
    clearInspection();
    setNotice(null);
    setError(null);
  };

  // The ref closes the same-frame duplicate-submit window. No POST is retried or polled.
  const run = async (
    kind: RequestKind,
    operation?: (signal: AbortSignal) => Promise<string>,
  ) => {
    if (request.current !== null || dataMode !== "live") return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(kind);
    setError(null);
    setNotice(null);
    let reading = kind === "load";
    let timedOut = false;
    const timeout = kind === "refresh" ? 16 * 60_000 : kind === "load" ? readTimeout : 120_000;
    const timer = globalThis.setTimeout(() => { timedOut = true; controller.abort(); }, timeout);
    try {
      if (operation) {
        const message = await operation(controller.signal);
        controller.signal.throwIfAborted();
        setNotice(message);
      }
      if (["load", "refresh", "stage", "import"].includes(kind)) {
        reading = true;
        clearInspection();
        setBusy("load");
        setView({ api, state: { status: "loading" } });
        const data = requireCloudKnowledgeOverview(await api.cloudKnowledge(controller.signal));
        controller.signal.throwIfAborted();
        setView({ api, state: data.available ? { status: "ready", data } : {
          status: "unavailable",
          message: `${text("unavailable")}${typeof data.reason === "string"
            ? ` ${text("reason")}: ${data.reason}` : ""}`,
        } });
        setRequiresReload(false);
      }
    } catch (failure) {
      if (request.current !== controller || (controller.signal.aborted && !timedOut)) return;
      const message = timedOut ? text("timeout")
        : failure instanceof Error ? failure.message : text("unknown");
      if (reading) {
        const unavailable = failure instanceof IngestionApiError
          && (failure.status === 404 || failure.status === 501);
        setView({ api, state: unavailable
          ? { status: "unavailable", message: text("unavailable") }
          : { status: "error", message } });
      } else {
        setError(text("actionFailed", { message }));
        setRequiresReload(true);
      }
      clearInspection();
    } finally {
      globalThis.clearTimeout(timer);
      if (request.current === controller) { request.current = null; setBusy(null); }
    }
  };

  useEffect(() => {
    selectedFile.current = null;
    setFile(null);
    clearInspection();
    setNotice(null);
    setError(null);
    setRequiresReload(false);
    if (input.current) input.current.value = "";
    if (dataMode === "live") void run("load");
    else {
      setBusy(null);
      setView({ api, state: { status: "unavailable", message: text("liveOnly") } });
    }
    return () => {
      const pending = request.current;
      request.current = null;
      pending?.abort();
    };
  }, [api, dataMode]);

  const intakeMessage = (result: CloudKnowledgeIntakeResult): string => {
    if (result?.status !== "ingestion_requested" || result.approval_required !== true
      || typeof result.session?.version_id !== "string") {
      throw new IngestionApiError(502, "The cloud knowledge intake acknowledgement is malformed.");
    }
    requireCloudKnowledgeRelease(result.release);
    return text("submitted", { version: result.session.version_id });
  };
  const refresh = () => {
    if (!permissions.refresh) return;
    void run("refresh", async (signal) => {
      const result = await api.refreshCloudKnowledge(signal);
      signal.throwIfAborted();
      if (!result || !Number.isSafeInteger(result.checked) || result.checked < 0
        || !Number.isSafeInteger(result.failed) || result.failed < 0 || result.failed > result.checked
        || typeof result.status !== "string") {
        throw new IngestionApiError(502, "The cloud knowledge check result is malformed.");
      }
      return text("checkedResult", { ...result, status: cloudKnowledgeOutcomeText(result.status) });
    });
  };
  const exportCollection = (collection: string) => {
    if (!permissions.export) return;
    void run("export", async (signal) => {
      const blob = await api.exportCloudKnowledge(collection, signal);
      signal.throwIfAborted();
      triggerBlobDownload(blob, "cloud-knowledge-review.json");
      return text("exported");
    });
  };
  const stageCollection = (collection: string) => {
    if (!permissions.stage) return;
    void run("stage", async (signal) => intakeMessage(await api.stageCloudKnowledge(collection, signal)));
  };
  const rollbackRevision = (collection: string, version: string) => {
    if (!permissions.refresh) return;
    void run("stage", async (signal) => intakeMessage(await api.rollbackCloudKnowledge(collection, version, signal)));
  };
  const inspectPackage = () => {
    if (!permissions.inspect || !file || selectedFile.current !== file || !isCloudKnowledgePackageFile(file)) return;
    clearInspection();
    void run("inspect", async (signal) => {
      const bytes = await file.arrayBuffer();
      signal.throwIfAborted();
      const content = new Blob([bytes], { type: "application/json" });
      const result = await api.inspectCloudKnowledgePackage(content, signal);
      signal.throwIfAborted();
      if (result?.status !== "verified_candidate" || result.approval_required !== true
        || !Number.isSafeInteger(result.document_count) || result.document_count < 1) {
        throw new IngestionApiError(502, "The cloud knowledge inspection result is malformed.");
      }
      requireCloudKnowledgeRelease(result.release);
      if (result.document_count !== result.release.sources.length) {
        throw new IngestionApiError(502, "The cloud knowledge inspection source count is inconsistent.");
      }
      if (selectedFile.current === file) setInspection({ file, content, result });
      return text("inspected", { count: result.document_count });
    });
  };
  const importPackage = () => {
    if (selectedFile.current !== file || confirmedFile.current !== file || !file || !inspection
      || !canImportCloudKnowledgePackage(file, inspection, confirmed, permissions.import)) return;
    const content = inspection.content;
    // Consume the local confirmation even if the server response is lost or rejected.
    clearInspection();
    void run("import", async (signal) => {
      const result = await api.importCloudKnowledgePackage(content, signal);
      signal.throwIfAborted();
      const message = intakeMessage(result);
      selectedFile.current = null;
      setFile(null);
      if (input.current) input.current.value = "";
      return message;
    });
  };

  return (
    <section class="stack" aria-labelledby="cloud-knowledge-title" style={{ minWidth: 0, overflowWrap: "anywhere" }}>
      <div class="knowledge-section-heading">
        <div>
          <h3 id="cloud-knowledge-title" class="cs-type-section-title">{text("title")}</h3>
          <p>{text("subtitle")}</p>
        </div>
        <a class="cs-control-button" style={CONTROL_STYLE} href={routeHref("hil-queue")}>{text("approvals")}</a>
      </div>
      <p class="muted" style={{ margin: 0 }}>{text("boundary")}</p>
      <div class="knowledge-connector-actions">
        <ActionButton disabled={busy !== null || dataMode !== "live"} onClick={() => void run("load")}>{text("reload")}</ActionButton>
        <ActionButton disabled={!permissions.refresh} busy={busy === "refresh"} onClick={refresh}>{text("checkDue")}</ActionButton>
      </div>
      <p class="muted" style={{ margin: 0 }}>{text("checkHint")}</p>
      <p class="muted" style={{ margin: 0 }}>{text("permissions")}</p>
      {busy && busy !== "load" ? (
        <div class="stack-section" role="status" aria-live="polite" aria-busy="true">
          <span>{text(BUSY_KEYS[busy])}</span>
          <span class="skeleton-shimmer loading-skeleton-line" aria-hidden="true" />
        </div>
      ) : null}
      {notice ? <p role="status" aria-live="polite">{notice}</p> : null}
      {error ? <ErrorState message={error} /> : null}
      {requiresReload ? <p class="muted">{text("reloadBeforeRetry")}</p> : null}
      <AsyncBoundary state={state} resourceLabel={text("title")}>
        {(data) => (
          <div class="stack" style={{ minWidth: 0 }}>
            <Metadata items={[
              ["registry", data.registry_revision ?? text("unknown")],
              ["registryValidUntil", formatCloudKnowledgeDate(data.registry_valid_until)],
            ]} />
            <SourceList sources={data.sources} />
            <CollectionList collections={data.collections} permissions={permissions}
              onExport={exportCollection} onStage={stageCollection} onRollback={rollbackRevision} />
          </div>
        )}
      </AsyncBoundary>
      <PackageIntake input={input} file={file} inspection={overview ? inspection : null}
        confirmed={confirmed} permissions={permissions} onFile={chooseFile}
        onConfirm={confirmPackage} onInspect={inspectPackage} onImport={importPackage} />
    </section>
  );
}
