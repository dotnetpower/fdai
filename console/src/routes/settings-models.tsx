import { useEffect, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import type { AuthContext } from "../auth";
import { DataTable, PageHeader, StatusPill } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import {
  ModelSettingsCommandError,
  saveNarratorPreference,
  saveWebSearchSettings,
} from "./settings-models.command";
import { modelText } from "./settings-models.i18n";
import {
  DEFAULT_WEB_SEARCH_DOMAINS,
  decodeModelSettings,
  draftRevisionIsCurrent,
  modelChoiceKey,
  normalizeAndValidateDomains,
  projectionGenerationIsCurrent,
  renderT2GovernanceDraft,
  t2PairIsValid,
  type GptModelCatalogEntryView,
  type ModelCapabilityView,
  type ModelEndpointInventoryView,
  type ModelRoutingCandidateView,
  type ModelSettingsView,
  type NarratorCandidateView,
  type T2ModelChoiceView,
  webSearchControlsDisabled,
} from "./settings-models.model";

interface Props {
  readonly client: ReadApiClient;
  readonly auth: AuthContext;
}

export function SettingsModelsRoute({ client, auth }: Props) {
  const narratorDraftRevision = useRef(0);
  const webSearchDraftRevision = useRef(0);
  const [view, setView] = useState<ModelSettingsView | null>(null);
  const [selection, setSelection] = useState("auto");
  const [loading, setLoading] = useState(true);
  const [refreshingCatalog, setRefreshingCatalog] = useState(false);
  const [catalogQuery, setCatalogQuery] = useState("");
  const [saving, setSaving] = useState(false);
  const [webSearchEnabled, setWebSearchEnabled] = useState(true);
  const [allowedDomainsText, setAllowedDomainsText] = useState(
    DEFAULT_WEB_SEARCH_DOMAINS.join("\n"),
  );
  const [savingWebSearch, setSavingWebSearch] = useState(false);
  const [webSearchError, setWebSearchError] = useState<string | null>(null);
  const [t2PrimaryKey, setT2PrimaryKey] = useState("");
  const [t2SecondaryKey, setT2SecondaryKey] = useState("");
  const [t2CopyState, setT2CopyState] = useState<"idle" | "copied" | "failed">("idle");
  const [error, setError] = useState<string | null>(null);
  const loadGeneration = useRef(0);
  const mounted = useRef(true);

  const applyProjection = (
    next: ModelSettingsView,
    submittedRevisions?: { readonly narrator: number; readonly webSearch: number },
  ) => {
    setView(next);
    if (
      submittedRevisions === undefined
      || draftRevisionIsCurrent(narratorDraftRevision.current, submittedRevisions.narrator)
    ) {
      setSelection(next.narrator.requested);
    }
    if (
      submittedRevisions === undefined
      || draftRevisionIsCurrent(webSearchDraftRevision.current, submittedRevisions.webSearch)
    ) {
      setWebSearchEnabled(next.webSearch.enabled);
      setAllowedDomainsText(next.webSearch.allowedDomains.join("\n"));
    }
  };

  const load = async (background = false, refreshCatalog = false) => {
    const generation = ++loadGeneration.current;
    if (background) setRefreshingCatalog(true);
    else setLoading(true);
    setError(null);
    try {
      const path = refreshCatalog ? "/models/settings?refresh_catalog=1" : "/models/settings";
      const next = decodeModelSettings(await client.panel<unknown>(path));
      if (!projectionGenerationIsCurrent(loadGeneration.current, generation)) return;
      applyProjection(next);
      setWebSearchError(null);
    } catch (reason) {
      if (!projectionGenerationIsCurrent(loadGeneration.current, generation)) return;
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      if (projectionGenerationIsCurrent(loadGeneration.current, generation)) {
        setLoading(false);
        setRefreshingCatalog(false);
      }
    }
  };

  useEffect(() => {
    void load(false);
    return () => {
      mounted.current = false;
      loadGeneration.current += 1;
    };
  }, [client]);

  useEffect(() => {
    if (view === null) return;
    setT2PrimaryKey((current) => validChoiceKey(
      current,
      view.t2ModelPolicy.primaryCandidates,
      view.t2ModelPolicy.activePrimary,
    ));
    setT2SecondaryKey((current) => validChoiceKey(
      current,
      view.t2ModelPolicy.secondaryCandidates,
      view.t2ModelPolicy.activeSecondary,
    ));
  }, [view]);

  const t2Primary = choiceByKey(view?.t2ModelPolicy.primaryCandidates ?? [], t2PrimaryKey);
  const t2Secondary = choiceByKey(
    view?.t2ModelPolicy.secondaryCandidates ?? [],
    t2SecondaryKey,
  );
  const t2PairValid = t2PairIsValid(t2Primary, t2Secondary);
  const t2Draft = t2PairValid && t2Primary !== null && t2Secondary !== null
    ? renderT2GovernanceDraft(t2Primary, t2Secondary)
    : "";
  const visibleCatalogModels = view === null
    ? []
    : filterCatalogModels(view.modelCatalog.models, catalogQuery);

  const copyT2Draft = async () => {
    if (!t2PairValid || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(t2Draft);
      setT2CopyState("copied");
    } catch {
      setT2CopyState("failed");
    }
  };

  const save = async () => {
    const submittedRevisions = {
      narrator: narratorDraftRevision.current,
      webSearch: webSearchDraftRevision.current,
    };
    const generation = ++loadGeneration.current;
    setSaving(true);
    setError(null);
    try {
      const next = await saveNarratorPreference(
        auth,
        client.readApiBaseUrl,
        selection,
        view?.narrator.revision ?? 0,
      );
      if (projectionGenerationIsCurrent(loadGeneration.current, generation)) {
        applyProjection(next, submittedRevisions);
      }
    } catch (reason) {
      if (projectionGenerationIsCurrent(loadGeneration.current, generation)) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      if (mounted.current) setSaving(false);
    }
  };

  const saveWebSearch = async () => {
    if (view === null || savingWebSearch || !view.webSearch.canManage) return;
    const validation = normalizeAndValidateDomains(allowedDomainsText, webSearchEnabled);
    setAllowedDomainsText(validation.domains.join("\n"));
    if (validation.error !== null) {
      setWebSearchError(domainValidationMessage(validation.error, validation.invalidDomains));
      return;
    }
    setSavingWebSearch(true);
    const submittedRevisions = {
      narrator: narratorDraftRevision.current,
      webSearch: webSearchDraftRevision.current,
    };
    const generation = ++loadGeneration.current;
    setWebSearchError(null);
    try {
      const next = await saveWebSearchSettings(auth, client.readApiBaseUrl, {
        enabled: webSearchEnabled,
        allowedDomains: validation.domains,
        expectedRevision: view.webSearch.revision,
      });
      if (projectionGenerationIsCurrent(loadGeneration.current, generation)) {
        applyProjection(next, submittedRevisions);
      }
    } catch (reason) {
      if (reason instanceof ModelSettingsCommandError && reason.status === 409) {
        try {
          const latest = decodeModelSettings(await client.panel<unknown>("/models/settings"));
          if (projectionGenerationIsCurrent(loadGeneration.current, generation)) {
            applyProjection(latest, {
              narrator: submittedRevisions.narrator,
              webSearch: webSearchDraftRevision.current,
            });
            setWebSearchError(t("settings.models.webSearchConflict"));
          }
        } catch {
          if (projectionGenerationIsCurrent(loadGeneration.current, generation)) {
            setWebSearchError(t("settings.models.webSearchConflictReloadFailed"));
          }
        }
      } else {
        if (projectionGenerationIsCurrent(loadGeneration.current, generation)) {
          setWebSearchError(reason instanceof Error ? reason.message : String(reason));
        }
      }
    } finally {
      if (mounted.current) setSavingWebSearch(false);
    }
  };

  usePublishViewContext(
    () => ({
      routeId: "settings-models",
      routeLabel: t("route.settingsModels"),
      purpose: "Resolved T1 and T2 model inventory, latency evidence, and user narrator preference.",
      glossary: composeGlossary([TERMS.tier]),
      headline: view
        ? `${view.narrator.effective} narrator preference in ${view.region ?? "unknown region"}`
        : "Model settings loading",
      capturedAt: new Date().toISOString(),
      facts: view ? [
        { key: "narrator_preference", value: view.narrator.effective, group: "models" },
        { key: "provisioning_status", value: view.provisioning.status, group: "models" },
        { key: "capability_count", value: view.capabilities.length, group: "models" },
        { key: "web_search_enabled", value: view.webSearch.enabled, group: "web_search" },
        { key: "web_search_available", value: view.webSearch.available, group: "web_search" },
        {
          key: "web_search_allowed_domain_count",
          value: view.webSearch.allowedDomains.length,
          group: "web_search",
        },
        { key: "web_search_provider", value: view.webSearch.provider, group: "web_search" },
        { key: "resolved_metadata_source", value: view.resolvedMetadata.source, group: "models" },
        { key: "resolved_metadata_as_of", value: view.resolvedMetadata.asOf, group: "models" },
        { key: "model_catalog_available", value: view.modelCatalog.available, group: "models" },
        { key: "model_catalog_count", value: view.modelCatalog.models.length, group: "models" },
        {
          key: "web_search_current_model",
          value: view.webSearch.currentAutoPick ?? "unavailable",
          group: "web_search",
        },
      ] : [],
      records: view ? {
        narrator_candidates: view.narrator.candidates.map((candidate) => ({ ...candidate })),
        model_capabilities: view.capabilities.map((capability) => ({
          ...capability,
          reasons: capability.reasons.join(", ") || "-",
        })),
        model_endpoints: view.endpointInventory.map((endpoint) => ({ ...endpoint })),
      } : {},
    }),
    [view],
  );

  return (
    <div class="stack settings-route settings-models-route">
      <PageHeader title={t("route.settingsModels")} subtitle={t("settings.models.subtitle")} />
      {loading ? <p class="muted" role="status">{t("settings.models.loading")}</p> : null}
      {error ? <div class="error" role="alert">{error}</div> : null}
      {!loading && view ? (
        <>
          <section class="settings-iam-panel" aria-labelledby="model-automation-heading">
            <header class="settings-iam-panel-head">
              <div>
                <h3 id="model-automation-heading">{t("settings.models.automation")}</h3>
                <p>{t("settings.models.automationHint")}</p>
              </div>
            </header>
            <div class="filter-summary" aria-label={t("settings.models.resolvedMetadata")}>
              <span>{t("settings.models.source")}: <strong>{view.resolvedMetadata.source}</strong></span>
              <span>{t("settings.models.kind")}: <strong>{view.resolvedMetadata.kind}</strong></span>
              <span>{t("settings.models.asOf")}: <strong>
                {new Date(view.resolvedMetadata.asOf).toLocaleString()}
              </strong></span>
            </div>
            <div class="settings-access-strip settings-model-summary">
              <SummaryDatum
                label={t("settings.models.discovery")}
                value={view.discovery.automatic ? t("settings.models.automatic") : t("settings.models.manual")}
                status={view.discovery.status}
              />
              <SummaryDatum
                label={t("settings.models.provisioning")}
                value={view.provisioning.automatic ? t("settings.models.automatic") : t("settings.models.manual")}
                status={view.provisioning.status}
              />
              <SummaryDatum
                label={t("settings.models.capabilityCoverage")}
                value={t("settings.models.resolvedCount", { count: view.provisioning.resolvedCount })}
                status={t("settings.models.hilOnlyCount", { count: view.provisioning.hilOnlyCount })}
              />
              <SummaryDatum
                label={t("settings.models.region")}
                value={view.region ?? t("settings.models.unavailable")}
                status={view.mixedModelMode ?? t("settings.models.unavailable")}
              />
            </div>
          </section>

          <section class="settings-iam-panel" aria-labelledby="model-catalog-heading">
            <header class="settings-iam-panel-head">
              <div>
                <h3 id="model-catalog-heading">{modelText("catalogTitle")}</h3>
                <p>{modelText("catalogHint")}</p>
              </div>
              <div class="settings-model-catalog-head-actions">
                <StatusPill
                  kind={view.modelCatalog.available ? "success" : "warning"}
                  label={view.modelCatalog.available
                    ? modelText("catalogLive")
                    : modelText("catalogUnavailable")}
                />
                <button
                  type="button"
                  class="secondary"
                  disabled={refreshingCatalog}
                  onClick={() => { void load(true, true); }}
                >
                  {refreshingCatalog ? modelText("refreshing") : modelText("refreshCatalog")}
                </button>
              </div>
            </header>
            <div class="settings-model-catalog-controls">
              <label for="model-catalog-search">{modelText("searchCatalog")}</label>
              <input
                id="model-catalog-search"
                type="search"
                value={catalogQuery}
                placeholder={modelText("searchCatalogPlaceholder")}
                onInput={(event) => setCatalogQuery(event.currentTarget.value)}
              />
              <span>
                {modelText("catalogSummary")
                  .replace("{visible}", String(visibleCatalogModels.length))
                  .replace("{total}", String(view.modelCatalog.models.length))}
              </span>
            </div>
            {!view.modelCatalog.available ? (
              <p class="settings-model-catalog-empty muted">{modelText("catalogUnavailableHint")}</p>
            ) : visibleCatalogModels.length === 0 ? (
              <p class="settings-model-catalog-empty muted">{modelText("catalogNoMatches")}</p>
            ) : (
              <div class="settings-model-catalog-grid">
                {visibleCatalogModels.map((model) => (
                  <CatalogModelCard
                    key={`${model.family}:${model.version}`}
                    model={model}
                    onSelect={() => {
                      const candidate = view.t2ModelPolicy.primaryCandidates.find(
                        (item) => item.family === model.family,
                      );
                      if (candidate === undefined) return;
                      setT2PrimaryKey(modelChoiceKey(candidate));
                      setT2CopyState("idle");
                      document.getElementById("t2-primary-model")?.focus();
                    }}
                  />
                ))}
              </div>
            )}
            <p class="settings-iam-panel-foot">{modelText("autoProvisionBoundary")}</p>
          </section>

          <section class="settings-iam-panel" aria-labelledby="t2-model-policy-heading">
            <header class="settings-iam-panel-head">
              <div>
                <h3 id="t2-model-policy-heading">{modelText("t2Policy")}</h3>
                <p>{modelText("t2PolicyHint")}</p>
              </div>
              <StatusPill
                kind={view.t2ModelPolicy.quorumReady ? "success" : "warning"}
                label={view.t2ModelPolicy.quorumReady
                  ? modelText("quorumReady")
                  : modelText("approvalRequired")}
              />
            </header>
            <div class="settings-t2-boundary" role="note">
              <strong>{modelText("prArtifactOnly")}</strong>
              <span>{modelText("prArtifactOnlyHint")}</span>
            </div>
            <dl class="settings-t2-current">
              <div>
                <dt>{modelText("activePrimary")}</dt>
                <dd>{modelChoiceLabel(view.t2ModelPolicy.activePrimary)}</dd>
              </div>
              <div>
                <dt>{modelText("activeSecondary")}</dt>
                <dd>{modelChoiceLabel(view.t2ModelPolicy.activeSecondary)}</dd>
              </div>
              <div>
                <dt>{modelText("mixedModelInvariant")}</dt>
                <dd>{modelText("distinctPublisher")}</dd>
              </div>
            </dl>
            <div class="settings-t2-picker">
              <label for="t2-primary-model">
                <span>{modelText("primaryReasoner")}</span>
                <select
                  id="t2-primary-model"
                  value={t2PrimaryKey}
                  disabled={view.t2ModelPolicy.primaryCandidates.length === 0}
                  onChange={(event) => {
                    setT2PrimaryKey(event.currentTarget.value);
                    setT2CopyState("idle");
                  }}
                >
                  {view.t2ModelPolicy.primaryCandidates.length === 0 ? (
                    <option value="">{t("settings.models.unavailable")}</option>
                  ) : null}
                  {view.t2ModelPolicy.primaryCandidates.map((candidate) => (
                    <option key={modelChoiceKey(candidate)} value={modelChoiceKey(candidate)}>
                      {modelChoiceOptionLabel(candidate)}
                    </option>
                  ))}
                </select>
              </label>
              <label for="t2-secondary-model">
                <span>{modelText("secondaryReasoner")}</span>
                <select
                  id="t2-secondary-model"
                  value={t2SecondaryKey}
                  disabled={view.t2ModelPolicy.secondaryCandidates.length === 0}
                  onChange={(event) => {
                    setT2SecondaryKey(event.currentTarget.value);
                    setT2CopyState("idle");
                  }}
                >
                  {view.t2ModelPolicy.secondaryCandidates.length === 0 ? (
                    <option value="">{t("settings.models.unavailable")}</option>
                  ) : null}
                  {view.t2ModelPolicy.secondaryCandidates.map((candidate) => (
                    <option key={modelChoiceKey(candidate)} value={modelChoiceKey(candidate)}>
                      {modelChoiceLabel(candidate)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div class={`settings-t2-invariant ${t2PairValid ? "is-valid" : "is-invalid"}`} role="status">
              <strong>
                {t2PairValid
                  ? modelText("pairValid")
                  : modelText("pairInvalid")}
              </strong>
              <span>{modelText("pairValidationHint")}</span>
            </div>
            <div class="settings-t2-artifact">
              <div>
                <strong>{modelText("draftPreview")}</strong>
                <span>{modelText("draftTarget")}</span>
              </div>
              <pre tabIndex={0} aria-label={modelText("draftPreview")}>
                {t2Draft || modelText("noValidPair")}
              </pre>
              <div class="settings-t2-actions">
                <button
                  type="button"
                  class="secondary"
                  disabled={!t2PairValid}
                  onClick={() => { void copyT2Draft(); }}
                >
                  {t2CopyState === "copied"
                    ? modelText("draftCopied")
                    : modelText("copyDraft")}
                </button>
                {t2CopyState === "failed" ? (
                  <span class="error" role="alert">{modelText("copyDraftFailed")}</span>
                ) : null}
              </div>
            </div>
          </section>

          <section class="settings-iam-panel" aria-labelledby="narrator-preference-heading">
            <header class="settings-iam-panel-head">
              <div>
                <h3 id="narrator-preference-heading">{t("settings.models.narratorPreference")}</h3>
                <p>{t("settings.models.narratorPreferenceHint")}</p>
              </div>
              <StatusPill kind="neutral" label={t("settings.models.perUser")} />
            </header>
            <div class="settings-model-preference-control">
              <label for="preferred-narrator-model">{t("settings.models.preferredModel")}</label>
              <select
                id="preferred-narrator-model"
                value={selection}
                onChange={(event) => {
                  narratorDraftRevision.current += 1;
                  setSelection(event.currentTarget.value);
                }}
              >
                <option value="auto">{t("settings.models.autoFastest")}</option>
                {view.narrator.candidates.map((candidate) => (
                  <option key={candidate.deployment} value={candidate.deployment}>
                    {candidate.deployment}
                  </option>
                ))}
              </select>
              <button type="button" class="secondary" disabled={saving} onClick={() => { void save(); }}>
                {saving ? t("settings.models.saving") : t("settings.models.save")}
              </button>
              <small>
                {t("settings.models.effectiveModel", {
                  model: view.narrator.effective === "auto"
                    ? view.narrator.currentAutoPick ?? "Auto"
                    : view.narrator.effective,
                })}
              </small>
            </div>
            {view.narrator.fallbackReason ? (
              <div class="settings-model-fallback" role="status">{view.narrator.fallbackReason}</div>
            ) : null}
            <DataTable
              columns={candidateColumns()}
              rows={view.narrator.candidates}
              keyOf={(candidate) => candidate.deployment}
              empty={t("settings.models.noCandidates")}
            />
          </section>

          <section class="settings-iam-panel" aria-labelledby="model-routing-heading">
            <header class="settings-iam-panel-head">
              <div>
                <h3 id="model-routing-heading">{t("settings.models.routing")}</h3>
                <p>{t("settings.models.routingHint")}</p>
              </div>
              <StatusPill kind="neutral" label={t("settings.models.systemGoverned")} />
            </header>
            {view.modelRouting.length === 0 ? (
              <p class="muted">{t("settings.models.noRoutingState")}</p>
            ) : view.modelRouting.map((routing) => (
              <div class="settings-model-routing" key={routing.role}>
                <div class="settings-model-routing-summary">
                  <strong>{routing.role}</strong>
                  <span>
                    {t("settings.models.selectedDeployment", {
                      model: routing.selectedDeployment ?? t("settings.models.unavailable"),
                    })}
                  </span>
                  <small>{routing.selectionReason ?? t("settings.models.noFallback")}</small>
                </div>
                <DataTable
                  columns={routingCandidateColumns()}
                  rows={routing.candidates}
                  keyOf={(candidate) => candidate.deployment}
                  empty={t("settings.models.noHealthTransitions")}
                />
              </div>
            ))}
          </section>

          <section class="settings-iam-panel" aria-labelledby="model-endpoints-heading">
            <header class="settings-iam-panel-head">
              <div>
                <h3 id="model-endpoints-heading">{t("settings.models.endpointInventory")}</h3>
                <p>{t("settings.models.endpointInventoryHint")}</p>
              </div>
              <StatusPill kind="neutral" label={t("settings.models.readOnlyInventory")} />
            </header>
            <DataTable
              columns={endpointColumns()}
              rows={view.endpointInventory}
              keyOf={(endpoint) => endpoint.bindingId}
              empty={t("settings.models.noEndpoints")}
            />
          </section>

          <section class="settings-iam-panel" aria-labelledby="web-search-settings-heading">
            <header class="settings-iam-panel-head">
              <div>
                <h3 id="web-search-settings-heading">{t("settings.models.webSearch")}</h3>
                <p>{t("settings.models.webSearchHint")}</p>
              </div>
              <StatusPill
                kind="neutral"
                label={!view.webSearch.available
                  ? t("settings.models.unavailable")
                  : view.webSearch.canManage
                    ? t("settings.models.deploymentWide")
                    : t("settings.models.ownerManaged")}
              />
            </header>
            <div class="settings-web-search-body">
              <div class="settings-web-search-toggle-row">
                <div>
                  <strong>{t("settings.models.webSearchEnabled")}</strong>
                  <small>{t("settings.models.webSearchEnabledHint")}</small>
                </div>
                <label class="settings-toggle-control">
                  <input
                    type="checkbox"
                    checked={webSearchEnabled}
                    disabled={webSearchControlsDisabled(
                      view.webSearch.canManage,
                      savingWebSearch,
                    )}
                    onChange={(event) => {
                      webSearchDraftRevision.current += 1;
                      setWebSearchEnabled(event.currentTarget.checked);
                    }}
                  />
                  <span aria-hidden="true" />
                  <strong>
                    {webSearchEnabled ? t("settings.enabled") : t("settings.disabled")}
                  </strong>
                </label>
              </div>

              <label class="settings-domain-editor" for="web-search-allowed-domains">
                <strong>{t("settings.models.allowedDomains")}</strong>
                <small>{t("settings.models.allowedDomainsHint")}</small>
                <textarea
                  id="web-search-allowed-domains"
                  rows={8}
                  value={allowedDomainsText}
                  disabled={webSearchControlsDisabled(
                    view.webSearch.canManage,
                    savingWebSearch,
                  )}
                  onInput={(event) => {
                    webSearchDraftRevision.current += 1;
                    setAllowedDomainsText(event.currentTarget.value);
                  }}
                  onBlur={() => {
                    webSearchDraftRevision.current += 1;
                    setAllowedDomainsText(
                      normalizeAndValidateDomains(
                        allowedDomainsText,
                        webSearchEnabled,
                      ).domains.join("\n"),
                    );
                  }}
                />
              </label>

              <div class="settings-web-search-warning" role="note">
                {t("settings.models.webSearchBoundaryWarning")}
              </div>
              <dl class="settings-web-search-runtime">
                <div>
                  <dt>{t("settings.models.provider")}</dt>
                  <dd>{view.webSearch.provider}</dd>
                </div>
                <div>
                  <dt>{t("settings.models.currentSearchModel")}</dt>
                  <dd>{view.webSearch.currentAutoPick ?? t("settings.models.unavailable")}</dd>
                </div>
              </dl>
              {webSearchError ? (
                <div class="error settings-web-search-error" role="alert">
                  {webSearchError}
                </div>
              ) : null}
              <div class="settings-web-search-actions">
                <button
                  type="button"
                  disabled={webSearchControlsDisabled(
                    view.webSearch.canManage,
                    savingWebSearch,
                  )}
                  onClick={() => { void saveWebSearch(); }}
                >
                  {savingWebSearch
                    ? t("settings.models.savingWebSearch")
                    : t("settings.models.saveWebSearch")}
                </button>
              </div>
            </div>
          </section>

          <section class="settings-iam-panel" aria-labelledby="model-capabilities-heading">
            <header class="settings-iam-panel-head">
              <div>
                <h3 id="model-capabilities-heading">{t("settings.models.capabilities")}</h3>
                <p>{t("settings.models.capabilitiesHint")}</p>
              </div>
              <StatusPill kind="neutral" label={t("settings.models.t2Governed")} />
            </header>
            <DataTable
              columns={capabilityColumns()}
              rows={view.capabilities}
              keyOf={(capability) => capability.name}
              empty={t("settings.models.noCapabilities")}
            />
          </section>
        </>
      ) : null}
    </div>
  );
}

function domainValidationMessage(
  error: "required" | "too-many" | "invalid",
  invalidDomains: readonly string[],
): string {
  if (error === "required") return t("settings.models.domainRequired");
  if (error === "too-many") return t("settings.models.domainLimit");
  return t("settings.models.domainInvalid", { domains: invalidDomains.join(", ") });
}

function choiceByKey(
  candidates: readonly T2ModelChoiceView[],
  key: string,
): T2ModelChoiceView | null {
  return candidates.find((candidate) => modelChoiceKey(candidate) === key) ?? null;
}

function validChoiceKey(
  current: string,
  candidates: readonly T2ModelChoiceView[],
  active: T2ModelChoiceView | null,
): string {
  if (choiceByKey(candidates, current) !== null) return current;
  if (active !== null && choiceByKey(candidates, modelChoiceKey(active)) !== null) {
    return modelChoiceKey(active);
  }
  return candidates[0] ? modelChoiceKey(candidates[0]) : "";
}

function modelChoiceLabel(choice: T2ModelChoiceView | null): string {
  return choice === null
    ? t("settings.models.unavailable")
    : `${choice.family} · ${choice.publisher}`;
}

function modelChoiceOptionLabel(choice: T2ModelChoiceView): string {
  const status = choice.catalogStatus === "deployed"
    ? modelText("deployed")
    : choice.catalogStatus === "provisionable"
      ? modelText("autoProvisionReady")
      : choice.catalogStatus === "quota-unavailable"
        ? modelText("quotaUnavailable")
        : modelText("registryCandidate");
  return `${modelChoiceLabel(choice)} · ${status}`;
}

function filterCatalogModels(
  models: readonly GptModelCatalogEntryView[],
  query: string,
): readonly GptModelCatalogEntryView[] {
  const normalized = query.trim().toLocaleLowerCase();
  return models.filter((model) => {
    if (!model.selectable && !model.deployed) return false;
    return normalized === ""
      || `${model.family} ${model.version} ${model.status}`.toLowerCase().includes(normalized);
  });
}

function CatalogModelCard({ model, onSelect }: {
  readonly model: GptModelCatalogEntryView;
  readonly onSelect: () => void;
}) {
  const actionable = model.selectable && (model.deployed || model.provisionable);
  return (
    <article class="settings-model-catalog-card">
      <header>
        <div>
          <strong>{model.family}</strong>
          <small>{model.version}</small>
        </div>
        <StatusPill
          kind={model.deployed ? "success" : model.provisionable ? "info" : "warning"}
          label={model.deployed
            ? modelText("deployed")
            : model.provisionable
              ? modelText("autoProvisionReady")
              : modelText("quotaUnavailable")}
        />
      </header>
      <dl>
        <div>
          <dt>{modelText("availableQuota")}</dt>
          <dd>{formatTpm(model.availableTpm)}</dd>
        </div>
        <div>
          <dt>{modelText("supportedSkus")}</dt>
          <dd>{model.skus.map((sku) => sku.name).join(", ") || "-"}</dd>
        </div>
        <div>
          <dt>{modelText("deployments")}</dt>
          <dd>{model.deployments.join(", ") || modelText("notDeployed")}</dd>
        </div>
      </dl>
      <button type="button" class="secondary" disabled={!actionable} onClick={onSelect}>
        {model.deployed ? modelText("selectT2Primary") : modelText("planAutoProvision")}
      </button>
    </article>
  );
}

function formatTpm(value: number): string {
  if (value <= 0) return "0 TPM";
  return `${new Intl.NumberFormat().format(Math.round(value / 1000))}K TPM`;
}

function SummaryDatum({ label, value, status }: {
  readonly label: string;
  readonly value: string;
  readonly status: string;
}) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{status}</small>
    </div>
  );
}

function candidateColumns() {
  return [
    {
      key: "model",
      header: t("settings.models.model"),
      mobileLabel: t("settings.models.model"),
      render: (item: NarratorCandidateView) => (
        <span class="settings-model-name"><strong>{item.deployment}</strong><small>{item.family ?? "-"}</small></span>
      ),
    },
    {
      key: "ttft",
      header: t("settings.models.ttft"),
      mobileLabel: t("settings.models.ttft"),
      render: (item: NarratorCandidateView) => latency(item.ttftP50Ms, item.ttftP95Ms, item.ttftSamples),
    },
    {
      key: "total",
      header: t("settings.models.totalLatency"),
      mobileLabel: t("settings.models.totalLatency"),
      render: (item: NarratorCandidateView) => latency(item.totalP50Ms, item.totalP95Ms, item.totalSamples),
    },
    {
      key: "status",
      header: t("settings.models.status"),
      mobileLabel: t("settings.models.status"),
      render: (item: NarratorCandidateView) => <StatusPill kind="success" label={item.status} />,
    },
  ];
}

function routingCandidateColumns() {
  return [
    {
      key: "deployment",
      header: t("settings.models.model"),
      mobileLabel: t("settings.models.model"),
      render: (item: ModelRoutingCandidateView) => item.deployment,
    },
    {
      key: "status",
      header: t("settings.models.status"),
      mobileLabel: t("settings.models.status"),
      render: (item: ModelRoutingCandidateView) => (
        <StatusPill
          kind={item.status === "recovered" ? "success" : "warning"}
          label={item.status}
        />
      ),
    },
    {
      key: "failure",
      header: t("settings.models.fallbackReason"),
      mobileLabel: t("settings.models.fallbackReason"),
      render: (item: ModelRoutingCandidateView) => item.failureKind ?? t("settings.models.none"),
    },
    {
      key: "cooldown",
      header: t("settings.models.cooldown"),
      mobileLabel: t("settings.models.cooldown"),
      render: (item: ModelRoutingCandidateView) => `${item.cooldownSeconds}s`,
    },
  ];
}

function capabilityColumns() {
  return [
    {
      key: "capability",
      header: t("settings.models.capability"),
      mobileLabel: t("settings.models.capability"),
      render: (item: ModelCapabilityView) => (
        <span class="settings-model-name"><strong>{item.name}</strong><small>{item.invocation}</small></span>
      ),
    },
    { key: "tier", header: t("settings.models.tier"), mobileLabel: t("settings.models.tier"), render: (item: ModelCapabilityView) => item.tier },
    {
      key: "model",
      header: t("settings.models.model"),
      mobileLabel: t("settings.models.model"),
      render: (item: ModelCapabilityView) => item.family ?? t("settings.models.unavailable"),
    },
    {
      key: "status",
      header: t("settings.models.status"),
      mobileLabel: t("settings.models.status"),
      render: (item: ModelCapabilityView) => (
        <StatusPill kind={item.status === "resolved" ? "success" : "warning"} label={item.status} />
      ),
    },
    {
      key: "capacity",
      header: t("settings.models.capacity"),
      mobileLabel: t("settings.models.capacity"),
      render: (item: ModelCapabilityView) => (
        `${item.capacityValue} ${item.capacityUnit.toUpperCase()}`
      ),
    },
    {
      key: "reason",
      header: t("settings.models.resolutionReason"),
      mobileLabel: t("settings.models.resolutionReason"),
      render: (item: ModelCapabilityView) => item.reasons.length > 0 ? (
        <details>
          <summary class="details-summary">
            {t("settings.models.reasonCount", { count: item.reasons.length })}
          </summary>
          <ul>{item.reasons.map((reason) => <li key={reason}><code>{reason}</code></li>)}</ul>
        </details>
      ) : <span class="muted">-</span>,
    },
  ];
}

function endpointColumns() {
  return [
    {
      key: "binding",
      header: t("settings.models.capability"),
      mobileLabel: t("settings.models.capability"),
      render: (item: ModelEndpointInventoryView) => (
        <span class="settings-model-name">
          <strong>{item.capability}</strong>
          <small>{item.bindingId}</small>
        </span>
      ),
    },
    {
      key: "route",
      header: t("settings.models.route"),
      mobileLabel: t("settings.models.route"),
      render: (item: ModelEndpointInventoryView) => (
        <span class="settings-model-name">
          <strong>{item.routeKind}</strong>
          <small>{item.providerKind}</small>
        </span>
      ),
    },
    {
      key: "model",
      header: t("settings.models.model"),
      mobileLabel: t("settings.models.model"),
      render: (item: ModelEndpointInventoryView) => (
        <span class="settings-model-name">
          <strong>{item.deployment}</strong>
          <small>{item.publisher} / {item.family}</small>
        </span>
      ),
    },
    {
      key: "protocol",
      header: t("settings.models.protocol"),
      mobileLabel: t("settings.models.protocol"),
      render: (item: ModelEndpointInventoryView) => `${item.apiStyle} / ${item.authKind}`,
    },
    {
      key: "capacity",
      header: t("settings.models.capacity"),
      mobileLabel: t("settings.models.capacity"),
      render: (item: ModelEndpointInventoryView) => (
        `${item.capacityValue} ${item.capacityUnit.toUpperCase()}`
      ),
    },
    {
      key: "discovery",
      header: t("settings.models.discovery"),
      mobileLabel: t("settings.models.discovery"),
      render: (item: ModelEndpointInventoryView) => (
        <span class="settings-model-name">
          <strong>{item.discoverySource}</strong>
          <small>{new Date(item.verifiedAt).toLocaleString()}</small>
        </span>
      ),
    },
  ];
}

function latency(p50: number | null, p95: number | null, samples: number) {
  if (p50 === null || p95 === null || samples === 0) {
    return <span class="muted">{t("settings.models.unavailable")}</span>;
  }
  return (
    <span class="settings-model-latency">
      <strong>{Math.round(p50)} ms</strong>
      <small>p95 {Math.round(p95)} ms · n={samples}</small>
    </span>
  );
}
