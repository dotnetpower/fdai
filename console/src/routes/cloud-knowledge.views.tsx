/** Cloud-knowledge presentation; API requests and authority remain with the panel and server. */
import type { ComponentChildren, RefObject } from "preact";
import { useState } from "preact/hooks";
import { DataTable, StatusPill } from "../components/ui";
import type {
  CloudKnowledgeCollection, CloudKnowledgeRelease,
  CloudKnowledgeSource, CloudKnowledgeSourceEvidence,
} from "../ingestion-api";
import { cloudKnowledgeText as text, type CloudKnowledgeMessageKey } from "./cloud-knowledge.i18n";
import {
  canImportCloudKnowledgePackage, cloudKnowledgeDateRange, cloudKnowledgeFreshness,
  cloudKnowledgeFreshnessText, cloudKnowledgeOutcomeText, type cloudKnowledgePermissions,
  formatCloudKnowledgeDate, isCloudKnowledgePackageFile, weakestCloudKnowledgeFreshness,
  type InspectedCloudKnowledgePackage,
} from "./cloud-knowledge.model";

type Permissions = ReturnType<typeof cloudKnowledgePermissions>;

/** Shared wrapping and touch-target dimensions for cloud-knowledge controls. */
export const CONTROL_STYLE = {
  height: "auto", minHeight: "var(--cs-control-height-touch)",
  maxWidth: "100%", whiteSpace: "normal",
} as const;

/** Render a consistently sized action control using the caller's disabled and busy state. */
export function ActionButton({ disabled, busy = false, onClick, children }: {
  readonly disabled: boolean;
  readonly busy?: boolean;
  readonly onClick: () => void;
  readonly children: ComponentChildren;
}) {
  return <button type="button" class="cs-control-button" style={CONTROL_STYLE}
    disabled={disabled} aria-busy={busy} onClick={onClick}>{children}</button>;
}

/** Pair localized metadata labels with their supplied values without changing evidence. */
export function Metadata({ items, compact = false }: {
  readonly items: readonly (readonly [CloudKnowledgeMessageKey, ComponentChildren])[];
  readonly compact?: boolean;
}) {
  return (
    <dl class={compact ? "stack-section" : "two-col"} style={{ margin: 0 }}>
      {items.map(([key, value]) => (
        <div key={key} style={{ minWidth: 0 }}>
          <dt class="muted cs-type-compact">{text(key)}</dt>
          <dd style={{ margin: 0 }}>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Show source dates, freshness, and check details from the supplied projection. */
export function SourceList({ sources }: { readonly sources: readonly CloudKnowledgeSource[] }) {
  return (
    <section class="stack-section" aria-labelledby="cloud-knowledge-sources">
      <h4 id="cloud-knowledge-sources" class="cs-type-panel-title">{text("sources")}</h4>
      <p class="muted" style={{ margin: 0 }}>{text("sourceHint")}</p>
      <p class="muted" style={{ margin: 0 }}>{text("collectedRange", { range: cloudKnowledgeDateRange(sources.map((source) => source.collected_at)) })}</p>
      <p class="muted" style={{ margin: 0 }}>{text("checkedRange", { range: cloudKnowledgeDateRange(sources.map((source) => source.checked_at)) })}</p>
      <p style={{ margin: 0 }}>{text("weakestFreshness", { state: cloudKnowledgeFreshnessText(weakestCloudKnowledgeFreshness(sources)) })}</p>
      <DataTable<CloudKnowledgeSource> rows={sources} keyOf={(source) => source.source_id}
        empty={text("noSources")} columns={[
          { key: "source", header: text("source"), render: (source) => (
            <div class="stack-section">
              <strong>{source.title}</strong><span class="muted">{source.collection_id}</span>
              <span>{text(source.mode)} - {text(source.enabled ? "enabled" : "disabled")}</span>
            </div>
          ) },
          { key: "freshness", header: text("freshness"), render: (source) => {
            const freshness = cloudKnowledgeFreshness(source);
            return <div class="stack-section">
              <StatusPill kind={freshness === "unknown" ? "neutral" : freshness === "fresh" ? "info" : "warning"}
                label={cloudKnowledgeFreshnessText(freshness)} />
              {source.update_pending ? <span>{text("pendingUpdate")}</span> : null}
            </div>;
          } },
          { key: "collected", header: text("collectedAt"), render: (source) => formatCloudKnowledgeDate(source.collected_at) },
          { key: "checked", header: text("checkedAt"), render: (source) => (
            <div class="stack-section">
              <span>{formatCloudKnowledgeDate(source.checked_at)}</span>
              <details>
                <summary style={{ minHeight: "44px", cursor: "pointer" }}>{text("sourceDetails")}</summary>
                <Metadata compact items={[
                  ["sourceId", source.source_id],
                  ["nextDueAt", formatCloudKnowledgeDate(source.next_due_at)],
                  ["checkInterval", text("seconds", { count: source.check_interval_seconds })],
                  ["maxUnverified", text("seconds", { count: source.max_unverified_seconds })],
                  ["lastAttempt", source.last_attempt ? formatCloudKnowledgeDate(source.last_attempt.checked_at) : text("noAttempt")],
                  ["attemptOutcome", source.last_attempt ? cloudKnowledgeOutcomeText(source.last_attempt.outcome) : text("noAttempt")],
                  ["reason", source.last_attempt?.reason ?? text("unknown")],
                  ["failures", source.consecutive_failures],
                ]} />
              </details>
            </div>
          ) },
        ]} />
    </section>
  );
}

/** Present collection history and forward governed requests without owning their API lifecycle. */
export function CollectionList({ collections, permissions, onExport, onStage, onRollback }: {
  readonly collections: readonly CloudKnowledgeCollection[];
  readonly permissions: Permissions;
  readonly onExport: (collection: string) => void;
  readonly onStage: (collection: string) => void;
  readonly onRollback: (collection: string, version: string) => void;
}) {
  return (
    <section class="stack-section" aria-labelledby="cloud-knowledge-collections">
      <h4 id="cloud-knowledge-collections" class="cs-type-panel-title">{text("collections")}</h4>
      <p class="muted" style={{ margin: 0 }}>{text("collectionsHint")}</p>
      {collections.length === 0 ? <p class="muted">{text("noCollections")}</p> : null}
      {collections.map((collection) => (
        <details key={collection.collection_id}>
          <summary class="cs-type-panel-title" style={{ minHeight: "44px", cursor: "pointer" }}>{collection.collection_id}</summary>
          <div class="stack" style={{ minWidth: 0 }}>
            <div class="knowledge-connector-actions">
              <ActionButton disabled={!permissions.stage} onClick={() => onStage(collection.collection_id)}>{text("stage")}</ActionButton>
              <ActionButton disabled={!permissions.export} onClick={() => onExport(collection.collection_id)}>{text("export")}</ActionButton>
            </div>
            <p class="muted" style={{ margin: 0 }}>{text("exportHint")}</p>
            {collection.versions.length === 0 ? <p class="muted">{text("noVersions")}</p> : null}
            {collection.versions.map((version) => (
              <details key={`${version.document_id}:${version.version_id}`}>
                <summary style={{ minHeight: "44px", cursor: "pointer" }}>
                  {version.release.release_id} - {text(version.active ? "active" : "inactive")} - {text(version.available ? "available" : "notAvailable")}
                </summary>
                <div class="stack" style={{ minWidth: 0 }}>
                  <Metadata items={[
                    ["documentId", version.document_id], ["versionId", version.version_id],
                    ["recordedState", version.state], ["updatedAt", formatCloudKnowledgeDate(version.updated_at)],
                  ]} />
                  <ReleaseDetails release={version.release} imported />
                  {!version.active && version.available ? <RollbackRequest
                    allowed={permissions.refresh} onRequest={() => onRollback(collection.collection_id, version.version_id)}
                  /> : null}
                </div>
              </details>
            ))}
          </div>
        </details>
      ))}
    </section>
  );
}

function RollbackRequest({ allowed, onRequest }: { readonly allowed: boolean; readonly onRequest: () => void }) {
  const [confirmed, setConfirmed] = useState(false);
  return <div class="stack-section">
    <label style={{ display: "flex", gap: "8px", minHeight: "44px" }}>
      <input type="checkbox" checked={confirmed} disabled={!allowed}
        onChange={(event) => setConfirmed(event.currentTarget.checked)} />
      <span>{text("confirmRollback")}</span>
    </label>
    <ActionButton disabled={!allowed || !confirmed} onClick={() => { setConfirmed(false); onRequest(); }}>
      {text("rollback")}
    </ActionButton>
  </div>;
}

function ReleaseDetails({ release, imported }: { readonly release: CloudKnowledgeRelease; readonly imported: boolean }) {
  return (
    <div class="stack-section" style={{ minWidth: 0 }}>
      <Metadata items={[
        ["releaseId", release.release_id], ["sequence", release.sequence], ["digest", release.manifest_digest],
        ["packageCreatedAt", formatCloudKnowledgeDate(release.package_created_at)],
        ["importedAt", imported ? formatCloudKnowledgeDate(release.imported_at) : text("noImportYet")],
        ["admissionExpiresAt", formatCloudKnowledgeDate(release.admission_expires_at)],
      ]} />
      <DataTable<CloudKnowledgeSourceEvidence> rows={release.sources} keyOf={(source) => source.source_id}
        caption={text("evidence")} empty={text("unknown")} columns={[
          { key: "source", header: text("sourceId"), render: (source) => (
            <div class="stack-section"><strong>{source.source_id}</strong><span class="muted">{source.source_url}</span></div>
          ) },
          { key: "collected", header: text("collectedAt"), render: (source) => formatCloudKnowledgeDate(source.collected_at) },
          { key: "checked", header: text("checkedAt"), render: (source) => formatCloudKnowledgeDate(source.check.checked_at) },
        ]} />
    </div>
  );
}

/** Render controlled package selection, inspection, and confirmation using panel-owned state. */
export function PackageIntake({ input, file, inspection, confirmed, permissions, onFile, onConfirm, onInspect, onImport }: {
  readonly input: RefObject<HTMLInputElement>;
  readonly file: File | null;
  readonly inspection: InspectedCloudKnowledgePackage | null;
  readonly confirmed: boolean;
  readonly permissions: Permissions;
  readonly onFile: (file: File | null) => void;
  readonly onConfirm: (confirmed: boolean) => void;
  readonly onInspect: () => void;
  readonly onImport: () => void;
}) {
  const invalidFile = file !== null && !isCloudKnowledgePackageFile(file);
  const inspected = file !== null && inspection?.file === file;
  return (
    <section class="stack-section" aria-labelledby="cloud-knowledge-package">
      <h4 id="cloud-knowledge-package" class="cs-type-panel-title">{text("packageTitle")}</h4>
      <p id="cloud-knowledge-package-help" class="muted" style={{ margin: 0 }}>{text("packageHint")}</p>
      <label class="cs-control-field">
        <span class="cs-control-label">{text("file")}</span>
        <input ref={input} class="cs-control-input" style={CONTROL_STYLE} type="file" accept="application/json,.json"
          disabled={!permissions.inspect} aria-invalid={invalidFile}
          aria-describedby={`cloud-knowledge-package-help${invalidFile ? " cloud-knowledge-file-error" : ""}`}
          onChange={(event) => onFile(event.currentTarget.files?.[0] ?? null)} />
      </label>
      {file ? <p class="muted" style={{ margin: 0 }}>{text("selectedFile", { name: file.name })}</p> : null}
      {invalidFile ? <p id="cloud-knowledge-file-error" class="cs-control-error" role="alert">{text("invalidFile")}</p> : null}
      <div class="knowledge-connector-actions">
        <ActionButton disabled={!permissions.inspect || file === null || invalidFile} onClick={onInspect}>{text("inspect")}</ActionButton>
      </div>
      {inspected && inspection ? (
        <details>
          <summary style={{ minHeight: "44px", cursor: "pointer" }}>{text("inspectionDetails")}</summary>
          <ReleaseDetails release={inspection.result.release} imported={false} />
        </details>
      ) : null}
      <label style={{ display: "flex", alignItems: "flex-start", gap: "8px", minHeight: "44px" }}>
        <input type="checkbox" checked={confirmed} disabled={!permissions.import || !inspected}
          onChange={(event) => onConfirm(event.currentTarget.checked)} />
        <span>{text("confirmImport")}</span>
      </label>
      <div class="knowledge-connector-actions">
        <ActionButton disabled={!canImportCloudKnowledgePackage(file, inspection, confirmed, permissions.import)} onClick={onImport}>{text("import")}</ActionButton>
      </div>
    </section>
  );
}
