import { useEffect, useState } from "preact/hooks";
import { currentRoute, replaceRouteState, routeHref } from "../router";
import { t } from "./i18n/ontology";
import {
  compactRecord,
  formatUnknown,
  recordValue,
  type OntologyActionTypeRecord,
  type UnknownRecord,
} from "./ontology.types";

const ALL = "all";

export interface OntologyActionFilters {
  readonly query: string;
  readonly category: string;
  readonly trigger: string;
  readonly execution: string;
}

export function ontologyActionFiltersFromSearch(search: URLSearchParams): OntologyActionFilters {
  return {
    query: search.get("q") ?? "",
    category: search.get("category") ?? ALL,
    trigger: search.get("trigger") ?? ALL,
    execution: search.get("execution") ?? ALL,
  };
}

export function requestedOntologyAction(search: URLSearchParams): string | null {
  return search.get("action");
}

export function ontologyActionHref(
  filters: OntologyActionFilters,
  selectedName: string | null,
): string {
  return routeHref("ontology", {
    params: {
      view: "actions",
      action: selectedName,
      q: filters.query || null,
      category: filters.category === ALL ? null : filters.category,
      trigger: filters.trigger === ALL ? null : filters.trigger,
      execution: filters.execution === ALL ? null : filters.execution,
    },
  });
}

export function resolveOntologyActionSelection(
  actions: readonly OntologyActionTypeRecord[],
  filtered: readonly OntologyActionTypeRecord[],
  selectedName: string | null,
): OntologyActionTypeRecord | null {
  if (selectedName === null) return filtered[0] ?? null;
  const requested = actions.find((action) => action.name === selectedName) ?? null;
  return requested !== null && filtered.includes(requested) ? requested : null;
}

export function OntologyActionsView({
  actions,
  selectedName,
}: {
  readonly actions: readonly OntologyActionTypeRecord[];
  readonly selectedName: string | null;
}) {
  const [filters, setFilters] = useState<OntologyActionFilters>(
    () => ontologyActionFiltersFromSearch(currentRoute().search),
  );
  useEffect(() => {
    const sync = () => setFilters(ontologyActionFiltersFromSearch(currentRoute().search));
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, []);
  const updateFilters = (next: OntologyActionFilters): void => {
    setFilters(next);
    replaceRouteState(ontologyActionHref(next, selectedName));
  };
  const { query, category, trigger, execution } = filters;
  const normalizedQuery = query.trim().toLowerCase();
  const categories = uniqueValues(actions.map((action) => action.category));
  const triggers = uniqueValues(actions.map((action) => recordValue(action.trigger_kind, "kind")));
  const executions = uniqueValues(actions.map((action) => action.execution_path));
  const filtered = actions.filter((action) => {
    const matchesQuery = normalizedQuery === ""
      || action.name.toLowerCase().includes(normalizedQuery)
      || (action.description ?? "").toLowerCase().includes(normalizedQuery)
      || action.operation.toLowerCase().includes(normalizedQuery);
    return matchesQuery
      && (category === ALL || action.category === category)
      && (trigger === ALL || recordValue(action.trigger_kind, "kind") === trigger)
      && (execution === ALL || action.execution_path === execution);
  });
  const requested = actions.find((action) => action.name === selectedName) ?? null;
  const selected = resolveOntologyActionSelection(actions, filtered, selectedName);
  const invalidSelection = selectedName !== null && requested === null;
  const hiddenSelection = requested !== null && !filtered.includes(requested);

  if (actions.length === 0) {
    return <div class="empty-state">{t("ontology.actions.unavailable")}</div>;
  }

  return (
    <section class="ontology-actions-view">
      <div class="ontology-action-toolbar">
        <label class="ontology-action-search">
          <span>{t("ontology.actions.search")}</span>
          <input
            type="search"
            value={query}
            placeholder={t("ontology.actions.searchPlaceholder")}
            onInput={(event) => updateFilters({
              ...filters,
              query: (event.target as HTMLInputElement).value,
            })}
          />
        </label>
        <ActionFilter
          label={t("ontology.actions.category")}
          value={category}
          values={categories}
          onChange={(value) => updateFilters({ ...filters, category: value })}
        />
        <ActionFilter
          label={t("ontology.actions.trigger")}
          value={trigger}
          values={triggers}
          onChange={(value) => updateFilters({ ...filters, trigger: value })}
        />
        <ActionFilter
          label={t("ontology.actions.execution")}
          value={execution}
          values={executions}
          onChange={(value) => updateFilters({ ...filters, execution: value })}
        />
        <span class="ontology-action-result-count">{t("ontology.actions.resultCount", { filtered: filtered.length, total: actions.length })}</span>
      </div>

      <div class="ontology-action-workspace">
        <div class="ontology-action-table-wrap">
          <table class="ontology-action-table">
            <thead>
              <tr>
                <th>{t("ontology.actions.actionType")}</th>
                <th>{t("ontology.actions.category")}</th>
                <th>{t("ontology.actions.trigger")}</th>
                <th>{t("ontology.actions.execution")}</th>
                <th>{t("ontology.actions.rollback")}</th>
                <th>{t("ontology.actions.default")}</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((action) => (
                <tr key={action.name} class={action.name === selected?.name ? "is-selected" : undefined}>
                  <td>
                    <a
                      href={ontologyActionHref(filters, action.name)}
                      aria-current={action.name === selected?.name ? "page" : undefined}
                    >
                      <code>{action.name}</code>
                      <small>{action.description ?? action.operation}</small>
                    </a>
                  </td>
                  <td><span class={`ontology-action-category is-${action.category ?? "other"}`}>{action.category ?? "-"}</span></td>
                  <td>{recordValue(action.trigger_kind, "kind") ?? "-"}</td>
                  <td><code>{action.execution_path ?? "-"}</code></td>
                  <td><code>{action.rollback_contract}</code></td>
                  <td><span class={`ontology-action-mode is-${action.default_mode}`}>{action.default_mode}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 ? <div class="empty-state">{t("ontology.actions.noMatches")}</div> : null}
        </div>

        {selected ? <ActionInspector action={selected} /> : invalidSelection ? (
          <div class="state-block state-unavailable" role="alert">
            {t("ontology.actions.invalid", { name: selectedName ?? "" })}
          </div>
        ) : hiddenSelection ? (
          <div class="state-block state-unavailable" role="status">
            {t("ontology.actions.hidden")}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function ActionFilter({
  label,
  value,
  values,
  onChange,
}: {
  readonly label: string;
  readonly value: string;
  readonly values: readonly string[];
  readonly onChange: (value: string) => void;
}) {
  return (
    <label class="ontology-action-filter">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange((event.target as HTMLSelectElement).value)}>
        <option value={ALL}>{t("ontology.common.all")}</option>
        {values.map((item) => <option value={item} key={item}>{item}</option>)}
      </select>
    </label>
  );
}

function ActionInspector({ action }: { readonly action: OntologyActionTypeRecord }) {
  return (
    <aside class="ontology-action-inspector" aria-label={t("ontology.actions.safetyContractLabel")}>
      <header>
        <span class="eyebrow">{t("ontology.actions.actionType")}</span>
        <h3><code>{action.name}</code></h3>
        <p>{action.description ?? t("ontology.common.noDescription")}</p>
      </header>

      <section>
        <h4>{t("ontology.actions.identityRouting")}</h4>
        <dl class="ontology-action-facts">
          <dt>{t("ontology.actions.version")}</dt><dd>{action.version}</dd>
          <dt>{t("ontology.actions.operation")}</dt><dd><code>{action.operation}</code></dd>
          <dt>{t("ontology.actions.category")}</dt><dd>{action.category ?? "-"}</dd>
          <dt>{t("ontology.actions.trigger")}</dt><dd>{recordValue(action.trigger_kind, "kind") ?? "-"}</dd>
          <dt>{t("ontology.actions.execution")}</dt><dd><code>{action.execution_path ?? "-"}</code></dd>
          <dt>{t("ontology.actions.environment")}</dt><dd>{action.env_scope}</dd>
          <dt>{t("ontology.actions.interfaces")}</dt><dd>{action.interfaces.join(", ") || "-"}</dd>
        </dl>
      </section>

      <section>
        <h4>{t("ontology.actions.safetyContract")}</h4>
        <dl class="ontology-action-facts">
          <dt>{t("ontology.actions.rollback")}</dt><dd><code>{action.rollback_contract}</code></dd>
          <dt>{t("ontology.actions.irreversible")}</dt><dd>{t(action.irreversible ? "ontology.common.yes" : "ontology.common.no")}</dd>
          <dt>{t("ontology.actions.defaultMode")}</dt><dd>{action.default_mode}</dd>
          <dt>{t("ontology.actions.impactScope")}</dt><dd>{action.blast_radius ? compactRecord(action.blast_radius) : "-"}</dd>
          <dt>{t("ontology.actions.liveProbe")}</dt><dd>{action.live_probe_ref ?? "-"}</dd>
        </dl>
      </section>

      <RecordList title={t("ontology.actions.preconditions")} records={action.preconditions} />
      <RecordList title={t("ontology.actions.stopConditions")} records={action.stop_conditions} />
      <RecordFacts title={t("ontology.actions.promotionGate")} record={action.promotion_gate} />
      {action.ceiling_by_tier ? <TierCeilings record={action.ceiling_by_tier} /> : null}
      {action.prod_downgrade ? <RecordFacts title={t("ontology.actions.productionDowngrade")} record={action.prod_downgrade} /> : null}
    </aside>
  );
}

function RecordList({ title, records }: { readonly title: string; readonly records: readonly UnknownRecord[] }) {
  return (
    <section>
      <h4>{title} <span>{records.length}</span></h4>
      {records.length === 0 ? <p class="muted">{t("ontology.common.noneDeclared")}</p> : (
        <ul class="ontology-action-records">
          {records.map((record, index) => <li key={index}>{compactRecord(record)}</li>)}
        </ul>
      )}
    </section>
  );
}

function RecordFacts({ title, record }: { readonly title: string; readonly record: UnknownRecord }) {
  return (
    <section>
      <h4>{title}</h4>
      <dl class="ontology-action-facts">
        {Object.entries(record).map(([key, value]) => (
          <><dt key={`${key}-term`}>{key.replaceAll("_", " ")}</dt><dd key={`${key}-value`}>{formatUnknown(value)}</dd></>
        ))}
      </dl>
    </section>
  );
}

function TierCeilings({ record }: { readonly record: UnknownRecord }) {
  return (
    <section>
      <h4>{t("ontology.actions.tierCeilings")}</h4>
      <div class="ontology-tier-grid">
        {Object.entries(record).map(([tier, value]) => (
          <div key={tier}>
            <strong>{tier.toUpperCase()}</strong>
            <span>{formatUnknown(value)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function uniqueValues(values: readonly (string | null | undefined)[]): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))].sort();
}
