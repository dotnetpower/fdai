/** Offline cloud-knowledge package preparation and governed intake presentation. */
import type { RefObject } from "preact";
import { StatusPill } from "../components/ui";
import { cloudKnowledgeText as text, type CloudKnowledgeMessageKey } from "./cloud-knowledge.i18n";
import {
  canImportCloudKnowledgePackage,
  type cloudKnowledgePermissions,
  formatCloudKnowledgePackageSize,
  isCloudKnowledgePackageFile,
  type CloudKnowledgeIntakeReadiness,
  type CloudKnowledgeRequestKind,
  type InspectedCloudKnowledgePackage,
} from "./cloud-knowledge.model";
import { ActionButton, ReleaseDetails } from "./cloud-knowledge.views";

type Permissions = ReturnType<typeof cloudKnowledgePermissions>;

const INTAKE_READINESS_KEYS: Readonly<Record<
  CloudKnowledgeIntakeReadiness,
  CloudKnowledgeMessageKey
>> = {
  ready: "packageReady",
  "setup-required": "packageSetupRequired",
  "access-required": "packageAccessRequired",
  "reload-required": "packageReloadRequired",
  busy: "packageBusy",
};

const INTAKE_PILL_KEYS: Readonly<Record<
  CloudKnowledgeIntakeReadiness,
  CloudKnowledgeMessageKey
>> = {
  ready: "configured",
  "setup-required": "setupRequired",
  "access-required": "accessRequired",
  "reload-required": "reloadRequired",
  busy: "requestInProgress",
};

/** Render local selection, exact-byte inspection, and review-only submission as separate steps. */
export function PackageIntake({
  input,
  file,
  inspection,
  confirmed,
  permissions,
  readiness,
  busy,
  setupReason,
  onFile,
  onConfirm,
  onInspect,
  onImport,
}: {
  readonly input: RefObject<HTMLInputElement>;
  readonly file: File | null;
  readonly inspection: InspectedCloudKnowledgePackage | null;
  readonly confirmed: boolean;
  readonly permissions: Permissions;
  readonly readiness: CloudKnowledgeIntakeReadiness;
  readonly busy: CloudKnowledgeRequestKind | null;
  readonly setupReason: string | undefined;
  readonly onFile: (file: File | null) => void;
  readonly onConfirm: (confirmed: boolean) => void;
  readonly onInspect: () => void;
  readonly onImport: () => void;
}) {
  const invalidFile = file !== null && !isCloudKnowledgePackageFile(file);
  const inspected = file !== null && inspection?.file === file;
  const selectionLocked = readiness === "busy" || readiness === "reload-required";
  const clearFile = () => {
    if (input.current) input.current.value = "";
    onFile(null);
  };
  return (
    <section class="cloud-knowledge-intake" aria-labelledby="cloud-knowledge-package">
      <header class="cloud-knowledge-intake-header">
        <div>
          <h4 id="cloud-knowledge-package">{text("packageTitle")}</h4>
          <p id="cloud-knowledge-package-help">{text("packageHint")}</p>
        </div>
        <StatusPill
          kind={readiness === "ready" ? "success" : readiness === "busy" ? "info" : "neutral"}
          label={text(INTAKE_PILL_KEYS[readiness])}
        />
      </header>
      <p id="cloud-knowledge-intake-readiness" class="cloud-knowledge-intake-readiness">
        {text(INTAKE_READINESS_KEYS[readiness])}
      </p>
      {readiness === "setup-required" && setupReason ? (
        <details class="cloud-knowledge-intake-technical">
          <summary>{text("technicalDetails")}</summary>
          <code>{setupReason}</code>
        </details>
      ) : null}
      <ol class="cloud-knowledge-intake-steps">
        <li data-state={file !== null && !invalidFile ? "complete" : "current"}>
          <span class="cloud-knowledge-step-number" aria-hidden="true">1</span>
          <div class="cloud-knowledge-step-body">
            <h5>{text("selectStepTitle")}</h5>
            <p>{text("selectStepBody")}</p>
            <label class="cs-control-field">
              <span class="cs-control-label">{text("file")}</span>
              <input
                ref={input}
                class="cs-control-input"
                type="file"
                accept="application/json,.json"
                disabled={selectionLocked}
                aria-invalid={invalidFile}
                aria-describedby={`cloud-knowledge-package-help cloud-knowledge-intake-readiness${invalidFile ? " cloud-knowledge-file-error" : ""}`}
                onChange={(event) => onFile(event.currentTarget.files?.[0] ?? null)}
              />
            </label>
            {file ? (
              <div class="cloud-knowledge-selected-file">
                <span>{text("selectedFile", {
                  name: file.name,
                  size: formatCloudKnowledgePackageSize(file.size),
                })}</span>
                <ActionButton disabled={selectionLocked} onClick={clearFile}>
                  {text("clearFile")}
                </ActionButton>
              </div>
            ) : null}
            {invalidFile ? (
              <p id="cloud-knowledge-file-error" class="cs-control-error" role="alert">
                {text("invalidFile")}
              </p>
            ) : null}
          </div>
        </li>
        <li data-state={inspected ? "complete" : file !== null && !invalidFile ? "current" : "pending"}>
          <span class="cloud-knowledge-step-number" aria-hidden="true">2</span>
          <div class="cloud-knowledge-step-body">
            <h5>{text("inspectStepTitle")}</h5>
            <p>{text("inspectStepBody")}</p>
            <ActionButton
              disabled={!permissions.inspect || file === null || invalidFile}
              busy={busy === "inspect"}
              onClick={onInspect}
            >
              {text("inspect")}
            </ActionButton>
            {inspected && inspection ? (
              <section class="cloud-knowledge-inspection" aria-labelledby="cloud-knowledge-inspection-title">
                <div>
                  <h5 id="cloud-knowledge-inspection-title">{text("inspectionDetails")}</h5>
                  <StatusPill kind="success" label={text("verifiedCandidate")} />
                </div>
                <p>{text("documentCount", { count: inspection.result.document_count })}</p>
                <ReleaseDetails release={inspection.result.release} imported={false} />
              </section>
            ) : null}
          </div>
        </li>
        <li data-state={confirmed ? "complete" : inspected ? "current" : "pending"}>
          <span class="cloud-knowledge-step-number" aria-hidden="true">3</span>
          <div class="cloud-knowledge-step-body">
            <h5>{text("submitStepTitle")}</h5>
            <p>{text("submitStepBody")}</p>
            <label class="cloud-knowledge-confirm">
              <input
                type="checkbox"
                checked={confirmed}
                disabled={!permissions.import || !inspected}
                onChange={(event) => onConfirm(event.currentTarget.checked)}
              />
              <span>{text("confirmImport")}</span>
            </label>
            <ActionButton
              disabled={!canImportCloudKnowledgePackage(
                file,
                inspection,
                confirmed,
                permissions.import,
              )}
              busy={busy === "import"}
              onClick={onImport}
            >
              {text("import")}
            </ActionButton>
          </div>
        </li>
      </ol>
    </section>
  );
}
