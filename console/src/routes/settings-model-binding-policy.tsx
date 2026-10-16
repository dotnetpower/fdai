import { useEffect, useRef, useState } from "preact/hooks";
import type { AuthContext } from "../auth";
import { StatusPill } from "../components/ui";
import { SegmentedControl } from "./settings.controls";
import {
  ModelSettingsCommandError,
  requestModelBindingOperation,
  saveModelBindingPolicy,
  type ModelBindingProposalReceipt,
} from "./settings-models.command";
import { modelText } from "./settings-models.i18n";
import { formatDisplayTimestamp } from "./settings-models.presentation";
import type {
  ModelBindingCapabilityPolicyView,
  ModelCapabilityView,
  ModelSettingsView,
} from "./settings-models.model";

type SelectionMode = ModelBindingCapabilityPolicyView["selectionMode"];

interface CapabilityDraft {
  readonly selectionMode: SelectionMode;
  readonly publisher: string;
  readonly family: string;
  readonly sku: string;
  readonly capacityValue: number;
}

interface Props {
  readonly auth: AuthContext;
  readonly operatorApiBaseUrl: string;
  readonly view: ModelSettingsView;
  readonly reload: () => Promise<boolean>;
  readonly onDirtyChange?: (dirty: boolean) => void;
}

const MODES = [
  { value: "auto", label: modelText("bindingAuto") },
  { value: "pinned", label: modelText("bindingPinned") },
  { value: "hil-only", label: modelText("bindingHilOnly") },
] as const;

const SKUS = [
  "Standard",
  "GlobalStandard",
  "ProvisionedManaged",
  "GlobalProvisionedManaged",
  "DataZoneProvisionedManaged",
] as const;

export function ModelBindingPolicyEditor({
  auth,
  operatorApiBaseUrl,
  view,
  reload,
  onDirtyChange,
}: Props) {
  const capabilities = view.capabilities;
  // Retain each key until a definitive response prevents duplicate proposals after timeouts.
  const [requestKeys] = useState(() => createModelBindingRequestKeyStore());
  const [selectedName, setSelectedName] = useState(capabilities[0]?.name ?? "");
  const [drafts, setDrafts] = useState(() => policyDrafts(view));
  const draftsRef = useRef(drafts);
  const baselineDraftsRef = useRef(policyDrafts(view));
  const baselineRevisionRef = useRef(view.bindingPolicy.revision);
  const [upstreamChanged, setUpstreamChanged] = useState(false);
  const [busy, setBusy] = useState<"save" | "assess" | "plan" | null>(null);
  const [receipt, setReceipt] = useState<ModelBindingProposalReceipt | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const nextBaseline = policyDrafts(view);
    const hasUnsavedChanges = modelBindingDraftsDiffer(
      capabilities,
      draftsRef.current,
      baselineDraftsRef.current,
    );
    const serverChanged = view.bindingPolicy.revision !== baselineRevisionRef.current
      || modelBindingDraftsDiffer(
        capabilities,
        nextBaseline,
        baselineDraftsRef.current,
      );
    if (!hasUnsavedChanges) setDrafts(nextBaseline);
    setUpstreamChanged(hasUnsavedChanges && serverChanged);
    baselineDraftsRef.current = nextBaseline;
    baselineRevisionRef.current = view.bindingPolicy.revision;
    requestKeys.clear("assess");
    requestKeys.clear("plan");
    setSelectedName((current) => capabilities.some((item) => item.name === current)
      ? current
      : capabilities[0]?.name ?? "");
  }, [requestKeys, view]);

  draftsRef.current = drafts;

  const selected = capabilities.find((item) => item.name === selectedName) ?? null;
  const selectedDraft = selected === null ? null : drafts[selected.name] ?? defaultDraft(selected);
  const pairError = modelBindingT2Conflict(capabilities, drafts);
  const dirty = modelBindingDraftsAreDirty(view, drafts);
  useEffect(() => onDirtyChange?.(dirty), [dirty, onDirtyChange]);
  const persistedDigest = receipt?.policyDigest ?? view.bindingPolicy.policyDigest;
  const persistedRevision = receipt?.policyRevision ?? view.bindingPolicy.revision;
  const canRequest = persistedDigest !== null && persistedRevision > 0;
  const requestGuidance = !view.bindingPolicy.canManage
    ? modelText("ownerPermissionRequired")
    : upstreamChanged
      ? modelText("bindingConflictHint")
      : dirty
        ? modelText("saveChangesFirst")
        : !canRequest
          ? modelText("saveDraftBeforeRequest")
          : view.resolvedMetadata.digest === null
            ? modelText("resolvedDigestRequired")
            : modelText("requestActionsReady");

  const updateSelected = (change: Partial<CapabilityDraft>) => {
    if (selected === null || selectedDraft === null) return;
    setDrafts((current) => ({
      ...current,
      [selected.name]: { ...selectedDraft, ...change },
    }));
    requestKeys.clear("draft");
    setReceipt(null);
    setError(null);
  };

  const save = async () => {
    if (
      !view.bindingPolicy.canManage
      || pairError !== null
      || busy !== null
      || !dirty
      || upstreamChanged
    ) return;
    setBusy("save");
    setError(null);
    try {
      const nextRevision = view.bindingPolicy.revision + 1;
      const next = await saveModelBindingPolicy(auth, operatorApiBaseUrl, {
        policy: buildModelBindingPolicy(view, drafts, nextRevision),
        expectedRevision: view.bindingPolicy.revision,
        idempotencyKey: requestKeys.get("draft"),
      });
      requestKeys.clear("draft");
      setReceipt(next);
      await reload();
    } catch (reason) {
      if (reason instanceof ModelSettingsCommandError && reason.status === 409) {
        const reloaded = await reload();
        setUpstreamChanged(reloaded);
        setError(reloaded ? null : modelText("bindingConflictReloadFailed"));
      } else {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      setBusy(null);
    }
  };

  const discard = () => {
    const saved = policyDrafts(view);
    draftsRef.current = saved;
    baselineDraftsRef.current = saved;
    baselineRevisionRef.current = view.bindingPolicy.revision;
    setDrafts(saved);
    setUpstreamChanged(false);
    setReceipt(null);
    setError(null);
  };

  const requestOperation = async (operation: "assess" | "plan") => {
    if (
      !view.bindingPolicy.canManage
      || !canRequest
      || busy !== null
      || dirty
      || upstreamChanged
    ) return;
    if (operation === "plan" && view.resolvedMetadata.digest === null) return;
    setBusy(operation);
    setError(null);
    try {
      const next = await requestModelBindingOperation(auth, operatorApiBaseUrl, operation, {
        environment: view.bindingPolicy.environment,
        policyRevision: persistedRevision,
        policyDigest: persistedDigest,
        idempotencyKey: requestKeys.get(operation),
      });
      requestKeys.clear(operation);
      setReceipt(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  };

  return (
    <section class="settings-iam-panel" aria-labelledby="model-binding-policy-heading">
      <header class="settings-iam-panel-head">
        <div>
          <h3 id="model-binding-policy-heading">{modelText("bindingTitle")}</h3>
          <p>{modelText("bindingHint")}</p>
        </div>
        <StatusPill
          kind={dirty ? "warning" : "neutral"}
          label={dirty
            ? modelText("bindingUnsaved")
            : view.bindingPolicy.state === "draft"
              ? modelText("bindingDraft")
              : modelText("bindingNotConfigured")}
        />
      </header>
      <div class="settings-t2-boundary" role="note">
        <strong>{modelText("bindingNoActivation")}</strong>
        <span>{modelText("bindingNoActivationHint")}</span>
      </div>
      <div class="settings-binding-editor">
        <label>
          <span>{modelText("bindingCapability")}</span>
          <select
            value={selectedName}
            onChange={(event) => setSelectedName(event.currentTarget.value)}
          >
            {capabilities.map((capability) => (
              <option key={capability.name} value={capability.name}>{capability.name}</option>
            ))}
          </select>
        </label>
        {selectedDraft === null ? null : (
          <>
            <SegmentedControl
              label={modelText("bindingMode")}
              value={selectedDraft.selectionMode}
              options={MODES}
              onChange={(value) => updateSelected({ selectionMode: value as SelectionMode })}
            />
            {selectedDraft.selectionMode === "pinned" ? (
              <div class="settings-binding-fields">
                <label>
                  <span>{modelText("bindingPublisher")}</span>
                  <input
                    value={selectedDraft.publisher}
                    onInput={(event) => updateSelected({ publisher: event.currentTarget.value })}
                  />
                </label>
                <label>
                  <span>{modelText("bindingFamily")}</span>
                  <input
                    value={selectedDraft.family}
                    onInput={(event) => updateSelected({ family: event.currentTarget.value })}
                  />
                </label>
                <label>
                  <span>{modelText("bindingSku")}</span>
                  <select
                    value={selectedDraft.sku}
                    onChange={(event) => updateSelected({ sku: event.currentTarget.value })}
                  >
                    {SKUS.map((sku) => <option key={sku} value={sku}>{sku}</option>)}
                  </select>
                </label>
                <label>
                  <span>{isProvisionedSku(selectedDraft.sku) ? "PTU" : "TPM"}</span>
                  <input
                    type="number"
                    min={isProvisionedSku(selectedDraft.sku) ? 1 : 1000}
                    max={10_000_000}
                    step={isProvisionedSku(selectedDraft.sku) ? 1 : 1000}
                    value={selectedDraft.capacityValue}
                    onInput={(event) => updateSelected({
                      capacityValue: Math.max(0, event.currentTarget.valueAsNumber || 0),
                    })}
                  />
                </label>
              </div>
            ) : null}
          </>
        )}
      </div>
      {pairError === null ? null : (
        <div class="settings-t2-invariant" role="alert">
          <strong>{modelText("pairInvalid")}</strong>
          <span>{pairError}</span>
        </div>
      )}
      {upstreamChanged ? (
        <div class="settings-t2-invariant" role="alert">
          <strong>{modelText("bindingConflict")}</strong>
          <span>{modelText("bindingConflictHint")}</span>
        </div>
      ) : null}
      <div class="settings-binding-actions">
        <div class="settings-binding-status-copy">
          <span>
            {dirty ? modelText("bindingUnsaved") : modelText("bindingCurrent")} | {modelText("bindingRevision")}: {view.bindingPolicy.revision} | {modelText("bindingEnvironment")}: {view.bindingPolicy.environment}
          </span>
          <small id="model-binding-request-guidance">{requestGuidance}</small>
        </div>
        <div>
          <button
            type="button"
            class="secondary"
            aria-describedby="model-binding-request-guidance"
            disabled={!dirty || busy !== null}
            onClick={discard}
          >
            {modelText("discardChanges")}
          </button>
          <button
            type="button"
            class="secondary"
            aria-describedby="model-binding-request-guidance"
            disabled={
              !view.bindingPolicy.canManage
              || busy !== null
              || pairError !== null
              || !dirty
              || upstreamChanged
            }
            onClick={() => { void save(); }}
          >
            {busy === "save" ? modelText("bindingSaving") : modelText("bindingSave")}
          </button>
          <button
            type="button"
            class="secondary"
            aria-describedby="model-binding-request-guidance"
            disabled={
              !view.bindingPolicy.canManage
              || !canRequest
              || busy !== null
              || dirty
              || upstreamChanged
            }
            onClick={() => { void requestOperation("assess"); }}
          >
            {busy === "assess" ? modelText("bindingAssessing") : modelText("bindingAssess")}
          </button>
          <button
            type="button"
            class="secondary"
            disabled={
              !view.bindingPolicy.canManage
              || !canRequest
              || view.resolvedMetadata.digest === null
              || busy !== null
              || dirty
              || upstreamChanged
            }
            onClick={() => { void requestOperation("plan"); }}
          >
            {busy === "plan" ? modelText("bindingPlanning") : modelText("bindingPlan")}
          </button>
        </div>
      </div>
      {receipt === null ? null : (
        <div class="settings-binding-receipt" role="status" aria-live="polite">
          <strong>{modelText("bindingRequestAccepted")}</strong>
          <dl>
            <div>
              <dt>{modelText("receiptState")}</dt>
              <dd>{bindingReceiptStateLabel(receipt.state)} <code>{receipt.state}</code></dd>
            </div>
            <div><dt>{modelText("bindingRevision")}</dt><dd>{receipt.policyRevision}</dd></div>
            <div><dt>{modelText("proposalId")}</dt><dd><code>{receipt.proposalId}</code></dd></div>
            <div><dt>{modelText("acceptedAt")}</dt><dd>{formatDisplayTimestamp(receipt.acceptedAt)}</dd></div>
            <div><dt>{modelText("duplicateRequest")}</dt><dd>{receipt.duplicate ? modelText("yes") : modelText("no")}</dd></div>
            <div><dt>{modelText("activationBoundary")}</dt><dd>{modelText("protectedPlanOnly")}</dd></div>
          </dl>
        </div>
      )}
      {error === null ? null : <div class="error" role="alert">{error}</div>}
    </section>
  );
}

function policyDrafts(view: ModelSettingsView): Record<string, CapabilityDraft> {
  return Object.fromEntries(view.capabilities.map((capability) => {
    const stored = view.bindingPolicy.capabilities[capability.name];
    return [capability.name, stored === undefined
      ? defaultDraft(capability)
      : {
          selectionMode: stored.selectionMode,
          publisher: stored.publisher ?? capability.publisher ?? "",
          family: stored.family ?? capability.family ?? "",
          sku: stored.sku ?? capability.sku ?? "Standard",
          capacityValue: stored.capacity?.value ?? capability.capacityValue,
        }];
  }));
}

function defaultDraft(capability: ModelCapabilityView): CapabilityDraft {
  return {
    selectionMode: "auto",
    publisher: capability.publisher ?? "",
    family: capability.family ?? "",
    sku: capability.sku ?? "Standard",
    capacityValue: capability.capacityValue || (capability.capacityUnit === "ptu" ? 1 : 1000),
  };
}

export function modelBindingDraftsAreDirty(
  view: ModelSettingsView,
  drafts: Readonly<Record<string, CapabilityDraft>>,
): boolean {
  const saved = policyDrafts(view);
  return modelBindingDraftsDiffer(view.capabilities, drafts, saved);
}

function modelBindingDraftsDiffer(
  capabilities: readonly ModelCapabilityView[],
  currentDrafts: Readonly<Record<string, CapabilityDraft>>,
  baselineDrafts: Readonly<Record<string, CapabilityDraft>>,
): boolean {
  return capabilities.some((capability) => {
    const current = currentDrafts[capability.name] ?? defaultDraft(capability);
    const baseline = baselineDrafts[capability.name] ?? defaultDraft(capability);
    return current.selectionMode !== baseline.selectionMode
      || current.publisher !== baseline.publisher
      || current.family !== baseline.family
      || current.sku !== baseline.sku
      || current.capacityValue !== baseline.capacityValue;
  });
}

function pinnedCapacity(value: number, sku: string): number {
  const minimum = isProvisionedSku(sku) ? 1 : 1000;
  if (!Number.isInteger(value) || value < minimum || value > 10_000_000) {
    throw new Error(`Pinned model capacity MUST be an integer from ${minimum} to 10000000`);
  }
  return value;
}

export function buildModelBindingPolicy(
  view: ModelSettingsView,
  drafts: Readonly<Record<string, CapabilityDraft>>,
  revision: number,
): Record<string, unknown> {
  return {
    schema_version: "1.0.0",
    environment: view.bindingPolicy.environment,
    revision,
    ...(view.resolvedMetadata.digest === null
      ? {}
      : { expected_active_digest: view.resolvedMetadata.digest }),
    capabilities: Object.fromEntries(view.capabilities.map((capability) => {
      const draft = drafts[capability.name] ?? defaultDraft(capability);
      if (draft.selectionMode !== "pinned") {
        return [capability.name, { selection_mode: draft.selectionMode }];
      }
      return [capability.name, {
        selection_mode: "pinned",
        publisher: draft.publisher.trim(),
        family: draft.family.trim(),
        version_policy: "latest-compatible",
        sku: draft.sku,
        capacity: {
          unit: isProvisionedSku(draft.sku) ? "ptu" : "tpm",
          value: pinnedCapacity(draft.capacityValue, draft.sku),
        },
      }];
    })),
  };
}

export function modelBindingT2Conflict(
  capabilities: readonly ModelCapabilityView[],
  drafts: Readonly<Record<string, CapabilityDraft>>,
): string | null {
  const publisher = (name: string): string | null => {
    const capability = capabilities.find((item) => item.name === name);
    if (capability === undefined) return null;
    const draft = drafts[name] ?? defaultDraft(capability);
    if (draft.selectionMode === "hil-only") return null;
    return (draft.selectionMode === "pinned" ? draft.publisher : capability.publisher)?.trim() || null;
  };
  const primary = publisher("t2.reasoner.primary");
  const secondary = publisher("t2.reasoner.secondary");
  return primary !== null && primary === secondary ? modelText("pairValidationHint") : null;
}

function isProvisionedSku(sku: string): boolean {
  return sku.endsWith("ProvisionedManaged");
}

function bindingReceiptStateLabel(state: ModelBindingProposalReceipt["state"]): string {
  if (state === "assessment-requested") return modelText("assessmentRequested");
  if (state === "plan-requested") return modelText("planRequested");
  if (state === "plan-required") return modelText("planRequired");
  return modelText("draftRecorded");
}

type ModelBindingRequestOperation = "draft" | "assess" | "plan";

export interface ModelBindingRequestKeyStore {
  readonly get: (operation: ModelBindingRequestOperation) => string;
  readonly clear: (operation: ModelBindingRequestOperation) => void;
}

export function createModelBindingRequestKeyStore(
  randomUUID: () => string = () => globalThis.crypto.randomUUID(),
): ModelBindingRequestKeyStore {
  const keys: Partial<Record<ModelBindingRequestOperation, string>> = {};
  return {
    get(operation) {
      return keys[operation] ??= `model-binding-${operation}-${randomUUID()}`;
    },
    clear(operation) {
      delete keys[operation];
    },
  };
}
