import { useEffect, useState } from "preact/hooks";
import type { AuthContext } from "../auth";
import { StatusPill } from "../components/ui";
import { SegmentedControl } from "./settings.controls";
import {
  requestModelBindingOperation,
  saveModelBindingPolicy,
  type ModelBindingProposalReceipt,
} from "./settings-models.command";
import { modelText } from "./settings-models.i18n";
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
  readonly reload: () => Promise<void>;
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

export function ModelBindingPolicyEditor({ auth, operatorApiBaseUrl, view, reload }: Props) {
  const capabilities = view.capabilities;
  const [selectedName, setSelectedName] = useState(capabilities[0]?.name ?? "");
  const [drafts, setDrafts] = useState(() => policyDrafts(view));
  const [busy, setBusy] = useState<"save" | "assess" | "plan" | null>(null);
  const [receipt, setReceipt] = useState<ModelBindingProposalReceipt | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDrafts(policyDrafts(view));
    setSelectedName((current) => capabilities.some((item) => item.name === current)
      ? current
      : capabilities[0]?.name ?? "");
  }, [view]);

  const selected = capabilities.find((item) => item.name === selectedName) ?? null;
  const selectedDraft = selected === null ? null : drafts[selected.name] ?? defaultDraft(selected);
  const pairError = modelBindingT2Conflict(capabilities, drafts);
  const persistedDigest = receipt?.policyDigest ?? view.bindingPolicy.policyDigest;
  const persistedRevision = receipt?.policyRevision ?? view.bindingPolicy.revision;
  const canRequest = persistedDigest !== null && persistedRevision > 0;

  const updateSelected = (change: Partial<CapabilityDraft>) => {
    if (selected === null || selectedDraft === null) return;
    setDrafts((current) => ({
      ...current,
      [selected.name]: { ...selectedDraft, ...change },
    }));
    setReceipt(null);
    setError(null);
  };

  const save = async () => {
    if (!view.bindingPolicy.canManage || pairError !== null || busy !== null) return;
    setBusy("save");
    setError(null);
    try {
      const nextRevision = view.bindingPolicy.revision + 1;
      const next = await saveModelBindingPolicy(auth, operatorApiBaseUrl, {
        policy: buildModelBindingPolicy(view, drafts, nextRevision),
        expectedRevision: view.bindingPolicy.revision,
        idempotencyKey: requestKey("draft"),
      });
      setReceipt(next);
      await reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(null);
    }
  };

  const requestOperation = async (operation: "assess" | "plan") => {
    if (!view.bindingPolicy.canManage || !canRequest || busy !== null) return;
    if (operation === "plan" && view.resolvedMetadata.digest === null) return;
    setBusy(operation);
    setError(null);
    try {
      const next = await requestModelBindingOperation(auth, operatorApiBaseUrl, operation, {
        environment: view.bindingPolicy.environment,
        policyRevision: persistedRevision,
        policyDigest: persistedDigest,
        idempotencyKey: requestKey(operation),
      });
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
          kind={view.bindingPolicy.state === "draft" ? "warning" : "neutral"}
          label={view.bindingPolicy.state === "draft"
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
      <div class="settings-binding-actions">
        <span>
          {modelText("bindingRevision")}: {view.bindingPolicy.revision} | {modelText("bindingEnvironment")}: {view.bindingPolicy.environment}
        </span>
        <div>
          <button
            type="button"
            class="secondary"
            disabled={!view.bindingPolicy.canManage || busy !== null || pairError !== null}
            onClick={() => { void save(); }}
          >
            {busy === "save" ? modelText("bindingSaving") : modelText("bindingSave")}
          </button>
          <button
            type="button"
            class="secondary"
            disabled={!view.bindingPolicy.canManage || !canRequest || busy !== null}
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
            }
            onClick={() => { void requestOperation("plan"); }}
          >
            {busy === "plan" ? modelText("bindingPlanning") : modelText("bindingPlan")}
          </button>
        </div>
      </div>
      {receipt === null ? null : (
        <div class="settings-binding-receipt" role="status">
          <strong>{modelText("bindingRequestAccepted")}</strong>
          <span>{receipt.state} | revision {receipt.policyRevision}</span>
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

function requestKey(operation: string): string {
  return `model-binding-${operation}-${globalThis.crypto.randomUUID()}`;
}
