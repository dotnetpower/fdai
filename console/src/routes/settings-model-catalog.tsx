import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { ErrorState, LoadingState, StatusPill } from "../components/ui";
import { formatConsoleTimestamp } from "../time-format";
import { modelText } from "./settings-models.i18n";
import {
  decodeModelSettings,
  type GptModelCatalogEntryView,
  type GptModelCatalogView,
} from "./settings-models.model";
import { filterCatalogModels, formatTpm } from "./settings-models.presentation";

const PAGE_SIZE = 12;

interface Props {
  readonly client: OperatorApiClient;
  readonly active: boolean;
  readonly catalog: GptModelCatalogView;
  readonly onLoaded: (catalog: GptModelCatalogView) => void;
  readonly selectionForModel: (model: GptModelCatalogEntryView) => (() => void) | null;
}

export function ModelCatalogPanel({ client, active, catalog, onLoaded, selectionForModel }: Props) {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const attempted = useRef(false);
  const inFlight = useRef(false);
  const publish = useRef(onLoaded);
  publish.current = onLoaded;

  const load = async (refreshCatalog = false) => {
    if (inFlight.current) return;
    inFlight.current = true;
    attempted.current = true;
    const request = ++generation.current;
    setPending(true);
    setError(null);
    try {
      const next = decodeModelSettings(await client.modelSettings({ refreshCatalog }));
      if (request === generation.current) publish.current(next.modelCatalog);
    } catch (reason) {
      if (request === generation.current) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    } finally {
      if (request === generation.current) {
        inFlight.current = false;
        setPending(false);
      }
    }
  };

  useEffect(() => {
    attempted.current = false;
    inFlight.current = false;
    return () => { generation.current += 1; };
  }, [client]);

  useEffect(() => {
    if (active && catalog.loadState === "deferred" && !attempted.current) void load();
  }, [active, catalog.loadState, client]);

  const filtered = filterCatalogModels(catalog.models, query);
  const lastPage = Math.max(0, Math.ceil(filtered.length / PAGE_SIZE) - 1);
  const currentPage = Math.min(page, lastPage);
  const start = currentPage * PAGE_SIZE;
  const visible = filtered.slice(start, start + PAGE_SIZE);
  const deferred = catalog.loadState === "deferred";

  return (
    <section
      class="settings-iam-panel"
      aria-labelledby="model-catalog-heading"
      aria-busy={pending}
      hidden={!active}
    >
      <header class="settings-iam-panel-head">
        <div>
          <h3 id="model-catalog-heading" tabIndex={-1}>{modelText("catalogTitle")}</h3>
          <p>{modelText("catalogHint")}</p>
        </div>
        <div class="settings-model-catalog-head-actions">
          <StatusPill
            kind={deferred ? "neutral" : catalog.available ? "success" : "warning"}
            label={deferred
              ? modelText("catalogDeferred")
              : catalog.available ? modelText("catalogLive") : modelText("catalogUnavailable")}
          />
          <button
            id="model-catalog-refresh"
            type="button"
            class="secondary"
            disabled={pending}
            onClick={() => { void load(true); }}
          >
            {pending ? modelText("refreshing") : modelText("refreshCatalog")}
          </button>
        </div>
      </header>
      {error ? (
        <ErrorState
          message={error}
          onRetry={() => { void load(true); }}
          retryLabel={modelText("retryCatalog")}
        />
      ) : null}
      {pending && !deferred ? <p role="status">{modelText("catalogRefreshingHint")}</p> : null}
      {deferred ? (
        error ? null : <LoadingState label={modelText("catalogLoading")} />
      ) : (
        <>
          <p class="muted">
            {modelText("catalogObservedAt").replace(
              "{time}",
              catalog.asOf === null ? modelText("catalogTimeUnavailable") : formatConsoleTimestamp(catalog.asOf),
            )}
          </p>
          {catalog.available ? <div class="settings-model-catalog-controls">
            <label for="model-catalog-search">{modelText("searchCatalog")}</label>
            <input
              id="model-catalog-search"
              type="search"
              value={query}
              placeholder={modelText("searchCatalogPlaceholder")}
              disabled={catalog.models.length === 0}
              onInput={(event) => {
                setQuery(event.currentTarget.value);
                setPage(0);
              }}
            />
            {query ? (
              <button type="button" class="secondary" onClick={() => {
                setQuery("");
                setPage(0);
                document.getElementById("model-catalog-search")?.focus();
              }}>{modelText("clearCatalogSearch")}</button>
            ) : null}
            <span role="status">
              {modelText("catalogSummary")
                .replace("{visible}", String(filtered.length))
                .replace("{total}", String(catalog.models.length))}
            </span>
          </div> : null}
          {!catalog.available ? (
            <div class="settings-model-catalog-empty settings-model-empty-guidance">
              <p class="muted">{modelText("catalogUnavailableHint")}</p>
              {catalog.unavailableReason ? (
                <details>
                  <summary>{modelText("catalogTechnicalReason")}</summary>
                  <code>{catalog.unavailableReason}</code>
                </details>
              ) : null}
              <a href="/settings/environment-and-deployment">{modelText("reviewEnvironment")}</a>
            </div>
          ) : filtered.length === 0 ? (
            <p class="settings-model-catalog-empty muted">{modelText("catalogNoMatches")}</p>
          ) : (
            <>
              <div class="settings-model-catalog-grid">
                {visible.map((model) => (
                  <CatalogModelCard
                    key={`${model.publisher}:${model.family}:${model.version}`}
                    model={model}
                    onSelect={selectionForModel(model)}
                  />
                ))}
              </div>
              <nav class="settings-list-pager" aria-label={modelText("catalogPagination")}>
                <button type="button" class="secondary" disabled={currentPage === 0}
                  onClick={() => setPage(currentPage - 1)}>{modelText("previousPage")}</button>
                <span role="status">{modelText("catalogPageRange")
                  .replace("{start}", String(start + 1))
                  .replace("{end}", String(start + visible.length))
                  .replace("{total}", String(filtered.length))}</span>
                <button type="button" class="secondary" disabled={currentPage === lastPage}
                  onClick={() => setPage(currentPage + 1)}>{modelText("nextPage")}</button>
              </nav>
            </>
          )}
        </>
      )}
      <p class="settings-iam-panel-foot">{modelText("autoProvisionBoundary")}</p>
      <p class="settings-iam-panel-foot">{modelText("secondaryRegistryBoundary")}</p>
    </section>
  );
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
            : model.provisionable ? modelText("autoProvisionReady") : modelText("quotaUnavailable")}
        />
      </header>
      <dl>
        <div><dt>{modelText("availableQuota")}</dt><dd>{formatTpm(model.availableTpm)}</dd></div>
        <div><dt>{modelText("lifecycle")}</dt><dd>{model.lifecycle}</dd></div>
        <div><dt>{modelText("supportedSkus")}</dt><dd>{model.skus.map((sku) => sku.name).join(", ") || "-"}</dd></div>
        <div><dt>{modelText("deployments")}</dt><dd>{model.deployments.join(", ") || modelText("notDeployed")}</dd></div>
      </dl>
      <a class="settings-model-detail-link" href="/settings/environment-and-deployment">
        {modelText("reviewDeploymentReadiness")}
      </a>
      <button type="button" class="secondary" disabled={!actionable} onClick={onSelect ?? undefined}>
        {actionable ? modelText("useInT2Draft") : modelText("unavailableForT2Draft")}
      </button>
    </article>
  );
}
