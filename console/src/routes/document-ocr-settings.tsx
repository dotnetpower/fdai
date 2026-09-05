import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import { StatusPill } from "../components/ui";
import {
  requestDocumentOcrPlan,
  saveDocumentOcrPolicy,
} from "./settings-models.command";
import {
  decodeModelSettings,
  type DocumentOcrSettingsView,
  type ModelSettingsView,
} from "./settings-models.model";
import { settingsIntegrationsText as text } from "./settings-integrations.i18n";

interface Props {
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
}

export function DocumentOcrSettingsPanel({ client, auth }: Props) {
  const [view, setView] = useState<ModelSettingsView | null>(null);
  const [provider, setProvider] = useState<DocumentOcrSettingsView["desiredProvider"]>(
    "local_python",
  );
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);

  const load = async () => {
    const current = ++generation.current;
    setError(null);
    try {
      const next = decodeModelSettings(await client.panel<unknown>("/models/settings"));
      if (generation.current !== current) return;
      setView(next);
      setProvider(next.documentOcr.desiredProvider);
    } catch (reason) {
      if (generation.current === current) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    }
  };

  useEffect(() => {
    void load();
    return () => {
      generation.current += 1;
    };
  }, [client]);

  const save = async (deprovisionRequested = false) => {
    if (view === null || !view.documentOcr.canManage || saving) return;
    const environment = view.bindingPolicy.environment;
    if (!isEnvironment(environment)) {
      setError(text("ocrEnvironmentUnavailable"));
      return;
    }
    setSaving(true);
    setNotice(null);
    setError(null);
    try {
      const policyUnchanged = !deprovisionRequested
        && provider === view.documentOcr.desiredProvider;
      const receipt = policyUnchanged
        ? {
            policyRevision: view.documentOcr.revision,
            policyDigest: requirePolicyDigest(view.documentOcr.policyDigest),
          }
        : await saveDocumentOcrPolicy(
            auth,
            client.operatorApiBaseUrl,
            {
              environment,
              expectedRevision: view.documentOcr.revision,
              provider: deprovisionRequested ? "local_python" : provider,
              azureResourceDesired: deprovisionRequested
                ? false
                : provider === "azure_document_intelligence"
                  || view.documentOcr.azureResourceDesired,
              deprovisionRequested,
              idempotencyKey: requestId("policy"),
            },
          );
      await requestDocumentOcrPlan(
        auth,
        client.operatorApiBaseUrl,
        {
          environment,
          policyRevision: receipt.policyRevision,
          policyDigest: receipt.policyDigest,
          idempotencyKey: requestId("plan"),
        },
      );
      setNotice(text("ocrPlanRequested"));
      await load();
    } catch (reason) {
      await load();
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section class="settings-section document-ocr-settings" aria-labelledby="document-ocr-title">
      <div class="settings-iam-panel-head">
        <div>
          <h3 id="document-ocr-title">{text("ocrTitle")}</h3>
          <p>{text("ocrSubtitle")}</p>
        </div>
        <StatusPill
          kind={view?.documentOcr.azureResourceState === "ready" ? "success" : "neutral"}
          label={view
            ? text("ocrResourceState", { state: view.documentOcr.azureResourceState })
            : text("ocrLoading")}
        />
      </div>
      {error ? <div class="error" role="alert">{error}</div> : null}
      {notice ? <div class="state-block state-success" role="status">{notice}</div> : null}
      {view ? (
        <>
          <div class="document-ocr-provider-grid">
            <label class={provider === "local_python" ? "selected" : ""}>
              <input
                type="radio"
                name="document-ocr-provider"
                value="local_python"
                checked={provider === "local_python"}
                disabled={!view.documentOcr.canManage || saving}
                onChange={() => setProvider("local_python")}
              />
              <strong>{text("ocrLocalTitle")}</strong>
              <span>{text("ocrLocalBody")}</span>
            </label>
            <label class={provider === "azure_document_intelligence" ? "selected" : ""}>
              <input
                type="radio"
                name="document-ocr-provider"
                value="azure_document_intelligence"
                checked={provider === "azure_document_intelligence"}
                disabled={!view.documentOcr.canManage || saving}
                onChange={() => setProvider("azure_document_intelligence")}
              />
              <strong>{text("ocrAzureTitle")}</strong>
              <span>{text("ocrAzureBody")}</span>
            </label>
          </div>
          <dl class="settings-web-search-runtime">
            <div>
              <dt>{text("ocrEffectiveProvider")}</dt>
              <dd>{view.documentOcr.effectiveProvider}</dd>
            </div>
            <div>
              <dt>{text("ocrKorean")}</dt>
              <dd>{view.documentOcr.koreanEnabled ? text("ocrReady") : text("ocrUnavailable")}</dd>
            </div>
            <div>
              <dt>{text("ocrRequestStateLabel")}</dt>
              <dd>{view.documentOcr.requestState}</dd>
            </div>
          </dl>
          <div class="settings-web-search-warning" role="note">{text("ocrApprovalBoundary")}</div>
          <div class="settings-actions">
            <button
              type="button"
              class="btn primary"
              disabled={
                !view.documentOcr.canManage
                || saving
                || (
                  provider === view.documentOcr.desiredProvider
                  && view.documentOcr.requestState !== "plan-required"
                )
              }
              onClick={() => { void save(false); }}
            >
              {saving
                ? text("ocrSaving")
                : provider === view.documentOcr.desiredProvider
                    ? text("ocrRequestPlan")
                    : text("ocrSaveAndPlan")}
            </button>
            <button
              type="button"
              class="secondary"
              disabled={
                !view.documentOcr.canManage
                || saving
                || view.documentOcr.azureResourceState === "absent"
              }
              onClick={() => { void save(true); }}
            >
              {text("ocrRequestRemoval")}
            </button>
          </div>
        </>
      ) : null}
    </section>
  );
}

function requestId(kind: string): string {
  return `document-ocr-${kind}-${crypto.randomUUID()}`;
}

function isEnvironment(value: string): value is "dev" | "staging" | "prod" {
  return value === "dev" || value === "staging" || value === "prod";
}

function requirePolicyDigest(value: string | null): string {
  if (value === null) throw new Error("document OCR policy digest is unavailable");
  return value;
}
