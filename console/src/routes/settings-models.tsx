import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import { DataTable, ErrorState, LoadingState, PageHeader, StatusPill } from "../components/ui";
import { useSettingsDirtyState } from "../components/settings-dirty-state";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import {
  ModelSettingsCommandError,
  saveNarratorPreference,
  saveWebSearchSettings,
} from "./settings-models.command";
import { ModelBindingPolicyEditor } from "./settings-model-binding-policy";
import { modelText } from "./settings-models.i18n";
import {
  filterCatalogModels,
  formatDisplayTimestamp,
  formatTpm,
  independentSecondaryCandidates,
  matchesModelQuery,
  modelReadinessState,
  nextModelWorkspaceView,
  presentModelStatus,
  type ModelWorkspaceView,
} from "./settings-models.presentation";
import {
  appendAllowedDomain,
  DEFAULT_WEB_SEARCH_DOMAINS,
  decodeModelSettings,
  draftRevisionIsCurrent,
  modelChoiceKey,
  normalizeAndValidateDomains,
  projectionGenerationIsCurrent,
  removeAllowedDomain,
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
  webSearchSettingsAreDirty,
  webSearchUnavailableMessageKey,
} from "./settings-models.model";

interface Props {
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
}

const MODELS_WORKSPACE_VIEWS: readonly ModelWorkspaceView[] = [
  "overview",
  "catalog",
  "routing",
  "web-search",
];

export function SettingsModelsRoute({ client, auth }: Props) {
  const narratorDraftRevision = useRef(0);
  const webSearchDraftRevision = useRef(0);
  const [view, setView] = useState<ModelSettingsView | null>(null);
  const [selection, setSelection] = useState("auto");
  const [loading, setLoading] = useState(true);
  const [refreshingCatalog, setRefreshingCatalog] = useState(false);
  const [catalogQuery, setCatalogQuery] = useState("");
  const [routingQuery, setRoutingQuery] = useState("");
  const [activeWorkspaceView, setActiveWorkspaceView] = useState<ModelWorkspaceView>("overview");
  const [saving, setSaving] = useState(false);
  const [narratorError, setNarratorError] = useState<string | null>(null);
  const [bindingDirty, setBindingDirty] = useState(false);
  const [webSearchEnabled, setWebSearchEnabled] = useState(true);
  const [allowedDomainsText, setAllowedDomainsText] = useState(
    DEFAULT_WEB_SEARCH_DOMAINS.join("\n"),
  );
  const [domainDraft, setDomainDraft] = useState("");
  const [savingWebSearch, setSavingWebSearch] = useState(false);
  const [webSearchError, setWebSearchError] = useState<string | null>(null);
  const [t2PrimaryKey, setT2PrimaryKey] = useState("");
  const [t2SecondaryKey, setT2SecondaryKey] = useState("");
  const [t2CopyState, setT2CopyState] = useState<"idle" | "copied" | "failed">("idle");
  const [error, setError] = useState<string | null>(null);
  const [backgroundError, setBackgroundError] = useState<string | null>(null);
  const loadGeneration = useRef(0);
  const [failedLoad, setFailedLoad] = useState<
    readonly [background: boolean, refreshCatalog: boolean] | null
  >(null);
  const mounted = useRef(true);

  const applyProjection = (
    next: ModelSettingsView,
    submittedRevisions?: {
      readonly narrator: number;
      readonly webSearch: number;
      readonly preserveNarrator?: boolean;
      readonly preserveWebSearch?: boolean;
    },
  ) => {
    setView(next);
    if (
      submittedRevisions === undefined
      || (!submittedRevisions.preserveNarrator
        && draftRevisionIsCurrent(narratorDraftRevision.current, submittedRevisions.narrator))
    ) {
      setSelection(next.narrator.requested);
    }
    if (
      submittedRevisions === undefined
      || (!submittedRevisions.preserveWebSearch
        && draftRevisionIsCurrent(webSearchDraftRevision.current, submittedRevisions.webSearch))
    ) {
      setWebSearchEnabled(next.webSearch.enabled);
      setAllowedDomainsText(next.webSearch.allowedDomains.join("\n"));
    }
  };

  const load = async (background = false, refreshCatalog = false, force = false) => {
    const generation = ++loadGeneration.current;
    const submittedRevisions = {
      narrator: narratorDraftRevision.current,
      webSearch: webSearchDraftRevision.current,
      preserveNarrator: view !== null && selection !== view.narrator.requested,
      preserveWebSearch: view !== null && webSearchSettingsAreDirty({
        enabled: webSearchEnabled,
        domains: normalizeAndValidateDomains(allowedDomainsText, false).domains,
        savedEnabled: view.webSearch.enabled,
        savedDomains: view.webSearch.allowedDomains,
      }),
    };
    setFailedLoad(null);
    if (background) {
      setRefreshingCatalog(true);
      setBackgroundError(null);
    } else {
      setLoading(true);
      setError(null);
    }
    try {
      const next = decodeModelSettings(await client.modelSettings({ refreshCatalog, force }));
      if (!projectionGenerationIsCurrent(loadGeneration.current, generation)) return false;
      applyProjection(next, submittedRevisions);
      setWebSearchError(null);
      setBackgroundError(null);
      return true;
    } catch (reason) {
      if (!projectionGenerationIsCurrent(loadGeneration.current, generation)) return false;
      setFailedLoad([background, refreshCatalog]);
      const message = reason instanceof Error ? reason.message : String(reason);
      if (background) setBackgroundError(message);
      else setError(message);
      return false;
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

  useEffect(() => {
    if (view === null) return;
    const primary = choiceByKey(view.t2ModelPolicy.primaryCandidates, t2PrimaryKey);
    const candidates = independentSecondaryCandidates(
      primary,
      view.t2ModelPolicy.secondaryCandidates,
    );
    setT2SecondaryKey((current) => validChoiceKey(
      current,
      candidates,
      view.t2ModelPolicy.activeSecondary,
    ));
  }, [t2PrimaryKey, view]);

  const t2Primary = choiceByKey(view?.t2ModelPolicy.primaryCandidates ?? [], t2PrimaryKey);
  const t2SecondaryCandidates = independentSecondaryCandidates(
    t2Primary,
    view?.t2ModelPolicy.secondaryCandidates ?? [],
  );
  const t2Secondary = choiceByKey(
    t2SecondaryCandidates,
    t2SecondaryKey,
  );
  const t2PairValid = t2PairIsValid(t2Primary, t2Secondary);
  const t2Draft = t2PairValid && t2Primary !== null && t2Secondary !== null
    ? renderT2GovernanceDraft(t2Primary, t2Secondary)
    : "";
  const visibleCatalogModels = view === null
    ? []
    : filterCatalogModels(view.modelCatalog.models, catalogQuery);
  const visibleModelRouting = view?.modelRouting.filter((routing) => matchesModelQuery(
    routingQuery,
    [
      routing.role,
      routing.selectedDeployment,
      routing.selectionReason,
      ...routing.candidates.flatMap((candidate) => [
        candidate.deployment,
        candidate.status,
        candidate.failureKind,
      ]),
    ],
  )) ?? [];
  const visibleEndpointInventory = view?.endpointInventory.filter((endpoint) => matchesModelQuery(
    routingQuery,
    [
      endpoint.bindingId,
      endpoint.capability,
      endpoint.providerKind,
      endpoint.routeKind,
      endpoint.apiStyle,
      endpoint.deployment,
      endpoint.publisher,
      endpoint.family,
      endpoint.version,
      endpoint.discoverySource,
    ],
  )) ?? [];
  const visibleCapabilities = view?.capabilities.filter((capability) => matchesModelQuery(
    routingQuery,
    [
      capability.name,
      capability.tier,
      capability.publisher,
      capability.family,
      capability.version,
      capability.sku,
      capability.selectionMode,
      capability.status,
      ...capability.reasons,
    ],
  )) ?? [];
  const allowedDomains = normalizeAndValidateDomains(allowedDomainsText, false).domains;
  const webSearchDirty = view !== null && webSearchSettingsAreDirty({
    enabled: webSearchEnabled,
    domains: allowedDomains,
    savedEnabled: view.webSearch.enabled,
    savedDomains: view.webSearch.allowedDomains,
  });
  const narratorDirty = view !== null && selection !== view.narrator.requested;
  const defaultT2PrimaryKey = view === null ? "" : validChoiceKey(
    "",
    view.t2ModelPolicy.primaryCandidates,
    view.t2ModelPolicy.activePrimary,
  );
  const defaultT2Primary = choiceByKey(
    view?.t2ModelPolicy.primaryCandidates ?? [],
    defaultT2PrimaryKey,
  );
  const defaultT2SecondaryCandidates = independentSecondaryCandidates(
    defaultT2Primary,
    view?.t2ModelPolicy.secondaryCandidates ?? [],
  );
  const defaultT2SecondaryKey = view === null ? "" : validChoiceKey(
    "",
    defaultT2SecondaryCandidates,
    view.t2ModelPolicy.activeSecondary,
  );
  const t2PolicyDirty = view !== null && (
    t2PrimaryKey !== defaultT2PrimaryKey || t2SecondaryKey !== defaultT2SecondaryKey
  );
  const readinessState = view === null
    ? "review-required"
    : modelReadinessState(
        view.t2ModelPolicy.quorumReady,
        view.t2ModelPolicy.activeSecondary !== null,
      );
  useSettingsDirtyState(
    "settings-models",
    bindingDirty || narratorDirty || webSearchDirty || t2PolicyDirty,
  );

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
    setFailedLoad(null);
    setNarratorError(null);
    try {
      const next = await saveNarratorPreference(
        auth,
        client.operatorApiBaseUrl,
        selection,
        view?.narrator.revision ?? 0,
      );
      if (projectionGenerationIsCurrent(loadGeneration.current, generation)) {
        client.invalidateModelSettings();
        applyProjection(next, submittedRevisions);
        setNarratorError(null);
      }
    } catch (reason) {
      if (projectionGenerationIsCurrent(loadGeneration.current, generation)) {
        if (reason instanceof ModelSettingsCommandError && reason.status === 409) {
          try {
            const latest = decodeModelSettings(await client.modelSettings({ force: true }));
            if (projectionGenerationIsCurrent(loadGeneration.current, generation)) {
              applyProjection(latest, {
                narrator: narratorDraftRevision.current,
                webSearch: webSearchDraftRevision.current,
                preserveNarrator: true,
                preserveWebSearch: webSearchDirty,
              });
              setNarratorError(modelText("narratorConflict"));
            }
          } catch {
            if (projectionGenerationIsCurrent(loadGeneration.current, generation)) {
              setNarratorError(modelText("narratorConflictReloadFailed"));
            }
          }
        } else {
          setNarratorError(reason instanceof Error ? reason.message : String(reason));
        }
      }
    } finally {
      if (mounted.current) setSaving(false);
    }
  };

  const addDomain = () => {
    if (!domainDraft.trim()) return;
    const validation = appendAllowedDomain(
      allowedDomainsText,
      domainDraft,
      webSearchEnabled,
    );
    if (validation.error !== null) {
      setWebSearchError(domainValidationMessage(
        validation.error,
        validation.invalidDomains,
      ));
      return;
    }
    webSearchDraftRevision.current += 1;
    setAllowedDomainsText(validation.domains.join("\n"));
    setDomainDraft("");
    setWebSearchError(null);
  };

  const removeDomain = (domain: string) => {
    webSearchDraftRevision.current += 1;
    setAllowedDomainsText(removeAllowedDomain(allowedDomainsText, domain));
    setWebSearchError(null);
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
      const next = await saveWebSearchSettings(auth, client.operatorApiBaseUrl, {
        enabled: webSearchEnabled,
        allowedDomains: validation.domains,
        expectedRevision: view.webSearch.revision,
      });
      if (projectionGenerationIsCurrent(loadGeneration.current, generation)) {
        client.invalidateModelSettings();
        applyProjection(next, submittedRevisions);
      }
    } catch (reason) {
      if (reason instanceof ModelSettingsCommandError && reason.status === 409) {
        try {
          const latest = decodeModelSettings(await client.modelSettings({ force: true }));
          if (projectionGenerationIsCurrent(loadGeneration.current, generation)) {
            applyProjection(latest, {
              narrator: submittedRevisions.narrator,
              webSearch: webSearchDraftRevision.current,
              preserveWebSearch: true,
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
          key: "web_search_unavailable_reason",
          value: view.webSearch.unavailableReason,
          group: "web_search",
        },
        {
          key: "web_search_allowed_domain_count",
          value: view.webSearch.allowedDomains.length,
          group: "web_search",
        },
        { key: "web_search_provider", value: view.webSearch.provider, group: "web_search" },
        {
          key: "web_search_agent",
          value: view.webSearch.agentName,
          group: "web_search",
        },
        {
          key: "web_search_model_deployment",
          value: view.webSearch.modelDeployment,
          group: "web_search",
        },
        {
          key: "web_search_provisioning_status",
          value: view.webSearch.provisioningStatus,
          group: "web_search",
        },
        {
          key: "web_search_readiness_status",
          value: view.webSearch.readinessStatus,
          group: "web_search",
        },
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
      <nav
        class="settings-model-workspace-nav"
        aria-label={modelText("workspaceNavigation")}
        onKeyDown={(event) => {
          const next = nextModelWorkspaceView(activeWorkspaceView, event.key);
          if (next === activeWorkspaceView) return;
          event.preventDefault();
          setActiveWorkspaceView(next);
          globalThis.requestAnimationFrame(() => {
            document.getElementById(`settings-model-view-${next}`)?.focus();
          });
        }}
      >
        {MODELS_WORKSPACE_VIEWS.map((workspaceView) => (
          <button
            key={workspaceView}
            id={`settings-model-view-${workspaceView}`}
            type="button"
            aria-pressed={activeWorkspaceView === workspaceView}
            tabIndex={activeWorkspaceView === workspaceView ? 0 : -1}
            onClick={() => setActiveWorkspaceView(workspaceView)}
          >
            {modelText(workspaceViewLabelKey(workspaceView))}
          </button>
        ))}
      </nav>
      {loading ? <LoadingState label={t("settings.models.loading")} /> : null}
      {error ? (
        <ErrorState
          message={error}
          {...(failedLoad ? {
            onRetry: () => { void load(...failedLoad); },
            retryLabel: t("settings.retry"),
          } : {})}
        />
      ) : null}
      {backgroundError && view ? (
        <div class="settings-model-stale-warning" role="alert">
          <div>
            <strong>{modelText("refreshFailed")}</strong>
            <span>{modelText("retainedValuesHint")}</span>
            <code>{backgroundError}</code>
          </div>
          {failedLoad ? (
            <button type="button" class="secondary" onClick={() => { void load(...failedLoad); }}>
              {t("settings.retry")}
            </button>
          ) : null}
        </div>
      ) : null}
      {!loading && view ? (
        <>
          <section
            class="settings-iam-panel settings-model-readiness"
            aria-labelledby="model-readiness-heading"
            hidden={activeWorkspaceView !== "overview"}
          >
            <header class="settings-iam-panel-head">
              <div>
                <h3 id="model-readiness-heading">{modelText("readinessTitle")}</h3>
                <p>{modelText("readinessHint")}</p>
              </div>
              <StatusPill
                kind={readinessState === "ready" ? "success" : "warning"}
                label={modelText(readinessState === "ready"
                  ? "t2PairReady"
                  : "t2PairIncomplete")}
              />
            </header>
            <dl class="settings-model-readiness-facts">
              <div>
                <dt>{modelText("currentNarrator")}</dt>
                <dd>{view.narrator.effective === "auto"
                  ? view.narrator.currentAutoPick ?? t("settings.models.unavailable")
                  : view.narrator.effective}</dd>
              </div>
              <div>
                <dt>{modelText("activePrimary")}</dt>
                <dd>{modelChoiceLabel(view.t2ModelPolicy.activePrimary)}</dd>
              </div>
              <div>
                <dt>{modelText("activeSecondary")}</dt>
                <dd>{modelChoiceLabel(view.t2ModelPolicy.activeSecondary)}</dd>
              </div>
              <div>
                <dt>{modelText("bindingEnvironment")}</dt>
                <dd>{view.bindingPolicy.environment}</dd>
              </div>
            </dl>
            <div
              class={`settings-model-readiness-note settings-model-readiness-note--${readinessState}`}
              role="status"
            >
              <strong>{modelText(readinessState === "ready"
                ? "t2ReadyTitle"
                : readinessState === "secondary-missing"
                  ? "t2SecondaryMissingTitle"
                  : "t2ReviewRequiredTitle")}</strong>
              <span>{modelText(readinessState === "ready"
                ? "t2ReadyHint"
                : readinessState === "secondary-missing"
                  ? "t2SecondaryMissingHint"
                  : "t2ReviewRequiredHint")}</span>
            </div>
            <div class="settings-model-readiness-actions">
              <button
                type="button"
                class="secondary"
                onClick={() => {
                  setActiveWorkspaceView("catalog");
                  globalThis.requestAnimationFrame(() => {
                    document.getElementById("t2-model-policy-heading")?.focus();
                  });
                }}
              >
                {modelText("reviewT2Policy")}
              </button>
              <button
                type="button"
                class="secondary"
                onClick={() => {
                  setActiveWorkspaceView("catalog");
                  globalThis.requestAnimationFrame(() => {
                    const search = document.getElementById("model-catalog-search") as HTMLInputElement | null;
                    if (search?.disabled) document.getElementById("model-catalog-refresh")?.focus();
                    else search?.focus();
                  });
                }}
              >
                {modelText("openCatalog")}
              </button>
            </div>
          </section>

          <div hidden={activeWorkspaceView !== "catalog"}>
            <ModelBindingPolicyEditor
              auth={auth}
              operatorApiBaseUrl={client.operatorApiBaseUrl}
              view={view}
              reload={() => load(true, false, true)}
              onDirtyChange={setBindingDirty}
            />
          </div>

          <section
            class="settings-iam-panel"
            aria-labelledby="model-catalog-heading"
            hidden={activeWorkspaceView !== "catalog"}
          >
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
                  id="model-catalog-refresh"
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
                disabled={view.modelCatalog.models.length === 0}
                onInput={(event) => setCatalogQuery(event.currentTarget.value)}
              />
              <span>
                {modelText("catalogSummary")
                  .replace("{visible}", String(visibleCatalogModels.length))
                  .replace("{total}", String(view.modelCatalog.models.length))}
              </span>
            </div>
            {!view.modelCatalog.available ? (
              <div class="settings-model-catalog-empty settings-model-empty-guidance">
                <p class="muted">{modelText("catalogUnavailableHint")}</p>
                <a href="/settings/environment-and-deployment">{modelText("reviewEnvironment")}</a>
              </div>
            ) : visibleCatalogModels.length === 0 ? (
              <p class="settings-model-catalog-empty muted">{modelText("catalogNoMatches")}</p>
            ) : (
              <div class="settings-model-catalog-grid">
                {visibleCatalogModels.map((model) => (
                  <CatalogModelCard
                    key={`${model.family}:${model.version}`}
                    model={model}
                    onSelect={(() => {
                      const candidate = view.t2ModelPolicy.primaryCandidates.find((item) => (
                        item.publisher === model.publisher && item.family === model.family
                      ));
                      if (candidate === undefined) return null;
                      return () => {
                      setT2PrimaryKey(modelChoiceKey(candidate));
                      setT2CopyState("idle");
                      document.getElementById("t2-primary-model")?.focus();
                      };
                    })()}
                  />
                ))}
              </div>
            )}
            <p class="settings-iam-panel-foot">{modelText("autoProvisionBoundary")}</p>
            <p class="settings-iam-panel-foot">{modelText("secondaryRegistryBoundary")}</p>
          </section>

          <section
            class="settings-model-routing-filter"
            aria-labelledby="model-routing-filter-heading"
            hidden={activeWorkspaceView !== "routing"}
          >
            <div>
              <h3 id="model-routing-filter-heading">{modelText("inventorySearchTitle")}</h3>
              <p>{modelText("inventorySearchHint")}</p>
            </div>
            <label for="model-routing-search">{modelText("inventorySearchLabel")}</label>
            <input
              id="model-routing-search"
              type="search"
              value={routingQuery}
              placeholder={modelText("inventorySearchPlaceholder")}
              onInput={(event) => setRoutingQuery(event.currentTarget.value)}
            />
            <span>{modelText("inventorySearchSummary")
              .replace("{capabilities}", String(visibleCapabilities.length))
              .replace("{endpoints}", String(visibleEndpointInventory.length))
              .replace("{roles}", String(visibleModelRouting.length))}</span>
          </section>

          <section
            class="settings-iam-panel"
            aria-labelledby="t2-model-policy-heading"
            hidden={activeWorkspaceView !== "catalog"}
          >
            <header class="settings-iam-panel-head">
              <div>
                <h3 id="t2-model-policy-heading" tabIndex={-1}>{modelText("t2Policy")}</h3>
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
                  disabled={t2SecondaryCandidates.length === 0}
                  onChange={(event) => {
                    setT2SecondaryKey(event.currentTarget.value);
                    setT2CopyState("idle");
                  }}
                >
                  {t2SecondaryCandidates.length === 0 ? (
                    <option value="">{modelText("noIndependentSecondary")}</option>
                  ) : null}
                  {t2SecondaryCandidates.map((candidate) => (
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

          <section
            class="settings-iam-panel settings-model-narrator"
            aria-labelledby="narrator-preference-heading"
            hidden={activeWorkspaceView !== "overview"}
          >
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
              <button type="button" class="secondary" disabled={saving || !narratorDirty} onClick={() => { void save(); }}>
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
            <div class="settings-model-preference-actions">
              <span aria-live="polite">
                {narratorDirty ? modelText("narratorUnsaved") : modelText("narratorCurrent")}
              </span>
              <button
                type="button"
                class="secondary"
                disabled={!narratorDirty || saving}
                onClick={() => {
                  narratorDraftRevision.current += 1;
                  setSelection(view.narrator.requested);
                  setNarratorError(null);
                }}
              >
                {modelText("discardChanges")}
              </button>
            </div>
            {narratorError ? <div class="error" role="alert">{narratorError}</div> : null}
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

          <section
            class="settings-iam-panel settings-model-lifecycle"
            aria-labelledby="model-automation-heading"
            hidden={activeWorkspaceView !== "overview"}
          >
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
                {formatDisplayTimestamp(view.resolvedMetadata.asOf)}
              </strong></span>
            </div>
            <div class="settings-access-strip settings-model-summary">
              <SummaryDatum
                label={t("settings.models.discovery")}
                value={view.discovery.automatic ? t("settings.models.automatic") : t("settings.models.manual")}
                status={modelText(presentModelStatus(view.discovery.status).label)}
              />
              <SummaryDatum
                label={t("settings.models.provisioning")}
                value={view.provisioning.automatic ? t("settings.models.automatic") : t("settings.models.manual")}
                status={modelText(presentModelStatus(view.provisioning.status).label)}
              />
              <SummaryDatum
                label={t("settings.models.capabilityCoverage")}
                value={t("settings.models.resolvedCount", { count: view.provisioning.resolvedCount })}
                status={t("settings.models.hilOnlyCount", { count: view.provisioning.hilOnlyCount })}
              />
              <SummaryDatum
                label={t("settings.models.region")}
                value={view.region ?? t("settings.models.unavailable")}
                status={view.mixedModelMode === null
                  ? t("settings.models.unavailable")
                  : modelText(presentModelStatus(view.mixedModelMode).label)}
              />
            </div>
          </section>

          <section
            class="settings-iam-panel"
            aria-labelledby="model-routing-heading"
            hidden={activeWorkspaceView !== "routing"}
          >
            <header class="settings-iam-panel-head">
              <div>
                <h3 id="model-routing-heading">{t("settings.models.routing")}</h3>
                <p>{t("settings.models.routingHint")}</p>
              </div>
              <StatusPill kind="neutral" label={t("settings.models.systemGoverned")} />
            </header>
            {visibleModelRouting.length === 0 ? (
              <div class="settings-model-empty-guidance">
                <p class="muted">{view.modelRouting.length === 0
                  ? t("settings.models.noRoutingState")
                  : modelText("noInventoryMatches")}</p>
                {view.modelRouting.length === 0 ? (
                  <a href="/settings/environment-and-deployment">{modelText("reviewEnvironment")}</a>
                ) : null}
              </div>
            ) : visibleModelRouting.map((routing) => (
              <div class="settings-model-routing" key={routing.role}>
                <div class="settings-model-routing-summary">
                  <strong>{routing.role}</strong>
                  <span>
                    {t("settings.models.selectedDeployment", {
                      model: routing.selectedDeployment ?? t("settings.models.unavailable"),
                    })}
                  </span>
                  <small>{routing.selectionReason ?? t("settings.models.noFallback")}</small>
                  <small>{routing.selectedAt === null
                    ? modelText("selectionTimeUnavailable")
                    : formatDisplayTimestamp(routing.selectedAt)}</small>
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

          <section
            class="settings-iam-panel"
            aria-labelledby="model-endpoints-heading"
            hidden={activeWorkspaceView !== "routing"}
          >
            <header class="settings-iam-panel-head">
              <div>
                <h3 id="model-endpoints-heading">{t("settings.models.endpointInventory")}</h3>
                <p>{t("settings.models.endpointInventoryHint")}</p>
              </div>
              <StatusPill kind="neutral" label={t("settings.models.readOnlyInventory")} />
            </header>
            <DataTable
              columns={endpointColumns()}
              rows={visibleEndpointInventory}
              keyOf={(endpoint) => endpoint.bindingId}
              empty={view.endpointInventory.length === 0
                ? t("settings.models.noEndpoints")
                : modelText("noInventoryMatches")}
            />
            {view.endpointInventory.length === 0 ? (
              <div class="settings-model-empty-guidance settings-model-empty-followup">
                <a href="/settings/environment-and-deployment">{modelText("reviewEnvironment")}</a>
              </div>
            ) : null}
          </section>

          <section
            class="settings-iam-panel"
            aria-labelledby="web-search-settings-heading"
            hidden={activeWorkspaceView !== "web-search"}
          >
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
            {!view.webSearch.available ? (
              <div class="settings-model-availability-note" role="status">
                <div>
                  <strong>{modelText("webSearchUnavailableTitle")}</strong>
                  <span>{modelText("webSearchUnavailableHint")}</span>
                  {view.webSearch.unavailableReason ? (
                    <span>{t(webSearchUnavailableMessageKey(view.webSearch.unavailableReason))}</span>
                  ) : null}
                </div>
                <a href="/settings/environment-and-deployment">
                  {modelText("reviewEnvironment")}
                </a>
              </div>
            ) : null}
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

              <fieldset
                class="settings-domain-editor"
                disabled={webSearchControlsDisabled(
                  view.webSearch.canManage,
                  savingWebSearch,
                )}
              >
                <legend>{t("settings.models.allowedDomains")}</legend>
                <p>{t("settings.models.allowedDomainsHint")}</p>
                <div class="settings-domain-list cs-control-policy-list" role="list">
                  {allowedDomains.length > 0 ? allowedDomains.map((domain) => (
                    <div class="settings-domain-row cs-control-policy-row" role="listitem" key={domain}>
                      <code>{domain}</code>
                      <span class="cs-control-policy-state">{modelText("approvedHost")}</span>
                      <button
                        type="button"
                        aria-label={modelText("removeDomain").replace("{domain}", domain)}
                        onClick={() => removeDomain(domain)}
                      >
                        {modelText("remove")}
                      </button>
                    </div>
                  )) : (
                    <span class="settings-domain-empty">{modelText("noDomains")}</span>
                  )}
                </div>
                <form
                  class="settings-domain-add"
                  onSubmit={(event) => {
                    event.preventDefault();
                    addDomain();
                  }}
                >
                  <label for="web-search-domain-draft">
                    {modelText("addDomain")}
                  </label>
                  <div>
                    <input
                      id="web-search-domain-draft"
                      value={domainDraft}
                      placeholder={modelText("domainPlaceholder")}
                      onInput={(event) => setDomainDraft(event.currentTarget.value)}
                    />
                    <button
                      type="submit"
                      class="secondary"
                      disabled={!domainDraft.trim()}
                    >
                      {modelText("add")}
                    </button>
                  </div>
                  <small>{modelText("domainCount")
                    .replace("{count}", String(allowedDomains.length))
                    .replace("{max}", "100")}</small>
                </form>
              </fieldset>

              <div class="settings-web-search-warning" role="note">
                {t("settings.models.webSearchBoundaryWarning")}
              </div>
              <dl class="settings-web-search-runtime">
                <div>
                  <dt>{t("settings.models.provider")}</dt>
                  <dd>{view.webSearch.provider}</dd>
                </div>
                <div>
                  <dt>{t("settings.models.foundryProject")}</dt>
                  <dd>{view.webSearch.projectConfigured
                    ? t("settings.models.configured")
                    : t("settings.models.notConfigured")}</dd>
                </div>
                <div>
                  <dt>{t("settings.models.searchAgent")}</dt>
                  <dd>{view.webSearch.agentName ?? t("settings.models.unavailable")}</dd>
                </div>
                <div>
                  <dt>{t("settings.models.searchModelDeployment")}</dt>
                  <dd>{view.webSearch.modelDeployment ?? t("settings.models.unavailable")}</dd>
                </div>
                <div>
                  <dt>{t("settings.models.agentProvisioning")}</dt>
                  <dd>{view.webSearch.provisioningStatus === "configured"
                    ? t("settings.models.configured")
                    : t("settings.models.notConfigured")}</dd>
                </div>
                <div>
                  <dt>{t("settings.models.agentReadiness")}</dt>
                  <dd>{view.webSearch.readinessStatus === "ready"
                    ? t("settings.models.ready")
                    : t("settings.models.unavailable")}</dd>
                </div>
                <div>
                  <dt>{t("settings.models.currentSearchModel")}</dt>
                  <dd>{view.webSearch.currentAutoPick ?? t("settings.models.unavailable")}</dd>
                </div>
                {view.webSearch.unavailableReason ? (
                  <div>
                    <dt>{t("settings.models.unavailableReason")}</dt>
                    <dd>{t(webSearchUnavailableMessageKey(view.webSearch.unavailableReason))}</dd>
                  </div>
                ) : null}
              </dl>
              {webSearchError ? (
                <div class="error settings-web-search-error" role="alert">
                  {webSearchError}
                </div>
              ) : null}
              <div class="settings-web-search-actions">
                <span aria-live="polite">
                  <strong>{webSearchDirty
                    ? modelText("unsavedChanges")
                    : modelText("settingsCurrent")}</strong>
                  <small>{modelText("saveBoundary")}</small>
                </span>
                <button
                  type="button"
                  disabled={webSearchControlsDisabled(
                    view.webSearch.canManage,
                    savingWebSearch,
                  ) || !webSearchDirty}
                  onClick={() => { void saveWebSearch(); }}
                >
                  {savingWebSearch
                    ? t("settings.models.savingWebSearch")
                    : t("settings.models.saveWebSearch")}
                </button>
              </div>
            </div>
          </section>

          <section
            class="settings-iam-panel"
            aria-labelledby="model-capabilities-heading"
            hidden={activeWorkspaceView !== "routing"}
          >
            <header class="settings-iam-panel-head">
              <div>
                <h3 id="model-capabilities-heading">{t("settings.models.capabilities")}</h3>
                <p>{t("settings.models.capabilitiesHint")}</p>
              </div>
              <StatusPill kind="neutral" label={t("settings.models.t2Governed")} />
            </header>
            <DataTable
              columns={capabilityColumns()}
              rows={visibleCapabilities}
              keyOf={(capability) => capability.name}
              empty={view.capabilities.length === 0
                ? t("settings.models.noCapabilities")
                : modelText("noInventoryMatches")}
            />
          </section>
        </>
      ) : null}
    </div>
  );
}

function workspaceViewLabelKey(
  workspaceView: ModelWorkspaceView,
): "workspaceOverview" | "workspaceCatalog" | "workspaceRouting" | "workspaceWebSearch" {
  if (workspaceView === "catalog") return "workspaceCatalog";
  if (workspaceView === "routing") return "workspaceRouting";
  if (workspaceView === "web-search") return "workspaceWebSearch";
  return "workspaceOverview";
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

function CatalogModelCard({ model, onSelect }: {
  readonly model: GptModelCatalogEntryView;
  readonly onSelect: (() => void) | null;
}) {
  const actionable = onSelect !== null && model.selectable && (model.deployed || model.provisionable);
  return (
    <article class="settings-model-catalog-entry">
      <header>
        <div>
          <strong>{model.family}</strong>
          <small>{model.publisher} / {model.version}</small>
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
          <dt>{modelText("lifecycle")}</dt>
          <dd>{model.lifecycle}</dd>
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
      <a class="settings-model-detail-link" href="/settings/environment-and-deployment">
        {modelText("reviewDeploymentReadiness")}
      </a>
      <button
        type="button"
        class="secondary"
        disabled={!actionable}
        onClick={onSelect ?? undefined}
      >
        {actionable ? modelText("useInT2Draft") : modelText("unavailableForT2Draft")}
      </button>
    </article>
  );
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
      render: (item: NarratorCandidateView) => <LocalizedModelStatus status={item.status} />,
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
      render: (item: ModelRoutingCandidateView) => <LocalizedModelStatus status={item.status} />,
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
      render: (item: ModelRoutingCandidateView) => (
        <span class="settings-model-name">
          <strong>{item.cooldownSeconds}s</strong>
          <small>{formatDisplayTimestamp(item.updatedAt)}</small>
        </span>
      ),
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
        <span class="settings-model-name">
          <strong>{item.name}</strong>
          <small>{item.invocation} / {selectionModeLabel(item.selectionMode)}</small>
        </span>
      ),
    },
    { key: "tier", header: t("settings.models.tier"), mobileLabel: t("settings.models.tier"), render: (item: ModelCapabilityView) => item.tier },
    {
      key: "model",
      header: t("settings.models.model"),
      mobileLabel: t("settings.models.model"),
      render: (item: ModelCapabilityView) => (
        <span class="settings-model-name">
          <strong>{item.family ?? t("settings.models.unavailable")}</strong>
          <small>{[item.publisher, item.version, item.sku].filter(Boolean).join(" / ") || "-"}</small>
        </span>
      ),
    },
    {
      key: "status",
      header: t("settings.models.status"),
      mobileLabel: t("settings.models.status"),
      render: (item: ModelCapabilityView) => <LocalizedModelStatus status={item.status} />,
    },
    {
      key: "capacity",
      header: t("settings.models.capacity"),
      mobileLabel: t("settings.models.capacity"),
      render: (item: ModelCapabilityView) => (
        `${new Intl.NumberFormat().format(item.capacityValue)} ${item.capacityUnit.toUpperCase()}`
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
          <small>{item.providerKind} / {item.managedBy}</small>
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
          <small>{[item.publisher, item.family, item.version].filter(Boolean).join(" / ")}</small>
        </span>
      ),
    },
    {
      key: "protocol",
      header: t("settings.models.protocol"),
      mobileLabel: t("settings.models.protocol"),
      render: (item: ModelEndpointInventoryView) => (
        <span class="settings-model-name">
          <strong>{item.apiStyle} / {item.authKind}</strong>
          <small>{item.apiVersion ?? modelText("apiVersionUnavailable")}</small>
          <small>{endpointFeatureLabels(item).join(", ") || modelText("noEndpointFeatures")}</small>
        </span>
      ),
    },
    {
      key: "capacity",
      header: t("settings.models.capacity"),
      mobileLabel: t("settings.models.capacity"),
      render: (item: ModelEndpointInventoryView) => (
        `${new Intl.NumberFormat().format(item.capacityValue)} ${item.capacityUnit.toUpperCase()}`
      ),
    },
    {
      key: "discovery",
      header: t("settings.models.discovery"),
      mobileLabel: t("settings.models.discovery"),
      render: (item: ModelEndpointInventoryView) => (
        <span class="settings-model-name">
          <strong>{item.discoverySource}</strong>
          <small>{formatDisplayTimestamp(item.verifiedAt)}</small>
        </span>
      ),
    },
  ];
}

function latency(p50: number | null, p95: number | null, samples: number) {
  if (samples === 0) {
    return <span class="muted">{modelText("notMeasured")}</span>;
  }
  if (p50 === null || p95 === null) {
    return <span class="muted">{modelText("incompleteMeasurement")}</span>;
  }
  return (
    <span class="settings-model-latency">
      <strong>{Math.round(p50)} ms</strong>
      <small>p95 {Math.round(p95)} ms · n={samples}</small>
    </span>
  );
}

function LocalizedModelStatus({ status }: { readonly status: string }) {
  const presentation = presentModelStatus(status);
  return (
    <span class="settings-model-status">
      <StatusPill kind={presentation.tone} label={modelText(presentation.label)} />
      <code>{status}</code>
    </span>
  );
}

function selectionModeLabel(mode: ModelCapabilityView["selectionMode"]): string {
  if (mode === "pinned") return modelText("bindingPinned");
  if (mode === "hil-only") return modelText("bindingHilOnly");
  return modelText("bindingAuto");
}

function endpointFeatureLabels(item: ModelEndpointInventoryView): string[] {
  return [
    item.features.streaming ? modelText("streaming") : null,
    item.features.embeddings ? modelText("embeddings") : null,
    item.features.structuredOutput ? modelText("structuredOutput") : null,
    item.features.toolCalling ? modelText("toolCalling") : null,
  ].filter((value): value is string => value !== null);
}
