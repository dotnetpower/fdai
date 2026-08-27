import { useEffect, useMemo, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import { AsyncBoundary, UnavailableState, type AsyncState } from "../components/ui";
import { usePublishViewContext, type ViewSnapshot } from "../deck/context";
import { composeGlossary, TERMS } from "../deck/glossary";
import { Tooltip } from "../components/tooltip";
import { currentRoute, replaceRouteState, routeHref } from "../router";
import { formatNumber, t } from "./i18n/ontology";
import {
  decodeOntologyInstanceDirectory,
  decodeOntologyInstanceExploration,
  groupOntologyInstanceRelationships,
  isOntologyInstanceDirectoryResource,
  isOntologyInstancePresentationRoot,
  isMatchableOntologyInstanceQuery,
  ontologyInstanceAksLanes,
  ontologyInstanceAutocompleteSuggestions,
  ontologyInstanceResourceAutocompleteOptions,
  ontologyInstancePresentationLinks,
  ontologyInstanceTrafficDirection,
  partitionOntologyInstanceLinks,
  resolveOntologyInstanceAutocomplete,
  type OntologyInstanceAutocompleteOption,
  type OntologyInstanceDirectory,
  type OntologyInstanceExploration,
  type OntologyInstanceLink,
  type OntologyInstanceResource,
} from "./ontology-instances.model";
import { OntologyInstanceGraph } from "./ontology-instance-graph";
import { OntologyInstanceInspector } from "./ontology-instances-inspector";
import "./ontology-instances.css";

interface Props {
  readonly client: OperatorApiClient;
}

const ONTOLOGY_INSTANCE_SEARCH_DEBOUNCE_MS = 250;

type DetailState = AsyncState<OntologyInstanceExploration> | { readonly status: "idle" };

export function OntologyInstancesView({ client }: Props) {
  const [directory, setDirectory] = useState<AsyncState<OntologyInstanceDirectory>>({ status: "loading" });
  const [searchDraft, setSearchDraft] = useState("");
  const [search, setSearch] = useState("");
  const [autocompleteOpen, setAutocompleteOpen] = useState(false);
  const [activeSuggestionIndex, setActiveSuggestionIndex] = useState<number | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(
    () => currentRoute().search.get("instance"),
  );
  const [detail, setDetail] = useState<DetailState>({ status: "idle" });

  useEffect(() => {
    let cancelled = false;
    // Unmounting the toolbar mid-search would blur the input and close its suggestions.
    setDirectory((current) => current.status === "ready" ? current : { status: "loading" });
    client.panel<unknown>("/ontology/instances", search
      ? { limit: "200", search }
      : { limit: "200" }).then(
      (payload) => {
        if (!cancelled) setDirectory({
          status: "ready",
          data: decodeOntologyInstanceDirectory(payload),
        });
      },
      (error: unknown) => {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : String(error);
        setDirectory(isOptionalOperatorApiUnavailable(error)
          ? { status: "unavailable", message: t("ontology.instances.inventoryUnavailable") }
          : { status: "error", message });
      },
    );
    return () => { cancelled = true; };
  }, [client, search]);

  useEffect(() => {
    const sync = () => setSelectedId(currentRoute().search.get("instance"));
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, []);

  // The directory is server-bounded, so an unsearched page hides most Resources.
  useEffect(() => {
    const draft = searchDraft.trim();
    if (draft === search || !isMatchableOntologyInstanceQuery(draft)) return;
    const timer = window.setTimeout(
      () => setSearch(draft),
      ONTOLOGY_INSTANCE_SEARCH_DEBOUNCE_MS,
    );
    return () => window.clearTimeout(timer);
  }, [searchDraft, search]);

  useEffect(() => {
    if (selectedId === null) {
      setDetail({ status: "idle" });
      return;
    }
    let cancelled = false;
    setDetail({ status: "loading" });
    client.panel<unknown>("/ontology/instances/explore", {
      root: selectedId,
      depth: "8",
      limit: "200",
      activity_limit: "30",
    }).then(
      (payload) => {
        if (cancelled) return;
        const data = decodeOntologyInstanceExploration(payload);
        if (!isOntologyInstancePresentationRoot(data)) {
          setSelectedId(null);
          setDetail({ status: "idle" });
          replaceRouteState(routeHref("ontology", { params: { view: "instances" } }));
          return;
        }
        setDetail({ status: "ready", data });
      },
      (error: unknown) => {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : String(error);
        setDetail(isOptionalOperatorApiUnavailable(error)
          ? { status: "unavailable", message: t("ontology.instances.detailUnavailable") }
          : { status: "error", message });
      },
    );
    return () => { cancelled = true; };
  }, [client, selectedId]);

  const selectResource = (resourceId: string | null): void => {
    setSelectedId(resourceId);
    replaceRouteState(routeHref("ontology", {
      params: { view: "instances", instance: resourceId },
    }));
  };

  useEffect(() => {
    if (directory.status !== "ready" || selectedId === null) return;
    const selectedResource = directory.data.resources.find((resource) =>
      resource.id === selectedId);
    if (selectedResource && !isOntologyInstanceDirectoryResource(selectedResource)) {
      selectResource(null);
    }
  }, [directory, selectedId]);

  const updateSearchDraft = (value: string): void => {
    setSearchDraft(value);
    setAutocompleteOpen(true);
    setActiveSuggestionIndex(null);
    const resourceId = resolveOntologyInstanceAutocomplete(autocompleteOptions, value);
    if (resourceId !== null && resourceId !== selectedId) selectResource(resourceId);
  };

  const chooseAutocompleteOption = (
    option: OntologyInstanceAutocompleteOption,
  ): void => {
    // The decorated option label is not a directory query, so keep the searchable name.
    setSearchDraft(option.primary);
    setAutocompleteOpen(false);
    selectResource(option.resourceId);
  };

  const options = useMemo(
    () => directory.status === "ready"
      ? directory.data.resources
        .filter(isOntologyInstanceDirectoryResource)
        .sort((first, second) =>
        (first.name ?? first.resource_type).localeCompare(second.name ?? second.resource_type)
        || first.resource_type.localeCompare(second.resource_type))
      : [],
    [directory],
  );
  const unnamedResourceLabel = t("ontology.instances.unnamedResource");
  const autocompleteOptions = useMemo(
    () => ontologyInstanceResourceAutocompleteOptions(options, unnamedResourceLabel),
    [options, unnamedResourceLabel],
  );
  const autocompleteSuggestions = useMemo(
    () => ontologyInstanceAutocompleteSuggestions(autocompleteOptions, searchDraft),
    [autocompleteOptions, searchDraft],
  );
  const searchUnmatchable = !isMatchableOntologyInstanceQuery(searchDraft);
  const autocompleteVisible = autocompleteOpen
    && !searchUnmatchable
    && autocompleteSuggestions.length > 0;

  return (
    <section class="ontology-instance-explorer" aria-label={t("ontology.instances.title")}>
      <AsyncBoundary state={directory} resourceLabel={t("ontology.instances.inventoryLoading")}>
        {() => (
          <>
            <form
              class="ontology-instance-toolbar"
              onSubmit={(event) => {
                event.preventDefault();
                if (searchUnmatchable) return;
                setSearch(searchDraft.trim());
              }}
            >
              <label class="ontology-instance-search">
                <span>{t("ontology.instances.search")}</span>
                <span class="ontology-instance-search-controls">
                  <span class="ontology-instance-combobox">
                    <input
                      role="combobox"
                      aria-autocomplete="list"
                      aria-controls="ontology-instance-search-options"
                      aria-expanded={autocompleteVisible}
                      aria-activedescendant={autocompleteVisible && activeSuggestionIndex !== null
                        ? `ontology-instance-search-option-${activeSuggestionIndex}`
                        : undefined}
                      type="search"
                      value={searchDraft}
                      placeholder={t("ontology.instances.searchPlaceholder")}
                      onFocus={() => setAutocompleteOpen(true)}
                      onBlur={() => setAutocompleteOpen(false)}
                      onInput={(event) => updateSearchDraft(event.currentTarget.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Escape") {
                          setAutocompleteOpen(false);
                          return;
                        }
                        if (!autocompleteVisible) return;
                        if (event.key === "ArrowDown") {
                          event.preventDefault();
                          setActiveSuggestionIndex((current) =>
                            Math.min((current ?? -1) + 1, autocompleteSuggestions.length - 1));
                        } else if (event.key === "ArrowUp") {
                          event.preventDefault();
                          setActiveSuggestionIndex((current) =>
                            current === null || current <= 0 ? null : current - 1);
                        } else if (event.key === "Enter" && activeSuggestionIndex !== null) {
                          // Enter without an actively highlighted option must still run the search.
                          event.preventDefault();
                          chooseAutocompleteOption(autocompleteSuggestions[activeSuggestionIndex]!);
                        }
                      }}
                    />
                    {autocompleteVisible ? (
                      <ul id="ontology-instance-search-options" role="listbox">
                        {autocompleteSuggestions.map((option, index) => (
                          <li key={option.resourceId}>
                            <button
                              id={`ontology-instance-search-option-${index}`}
                              type="button"
                              role="option"
                              aria-selected={index === activeSuggestionIndex}
                              onMouseDown={(event) => event.preventDefault()}
                              onMouseEnter={() => setActiveSuggestionIndex(index)}
                              onClick={() => chooseAutocompleteOption(option)}
                            >
                              <span class="ontology-instance-autocomplete-kind" aria-hidden="true">
                                {option.kind}
                              </span>
                              <span class="ontology-instance-autocomplete-copy">
                                <strong>{option.primary}</strong>
                                <small>{option.secondary}</small>
                              </span>
                              <span class="ontology-instance-autocomplete-type">Resource</span>
                            </button>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </span>
                  <button type="submit" class="btn">{t("ontology.instances.searchCommand")}</button>
                </span>
              </label>
              <div class="ontology-instance-toolbar-status">
                <strong>{t("ontology.instances.readOnly")}</strong>
                <span>{t("ontology.instances.resultBound", {
                  count: formatNumber(options.length),
                })}
                </span>
              </div>
            </form>
            {searchUnmatchable ? (
              <p class="ontology-instance-bound-notice" role="note">
                {t("ontology.instances.searchNotMatchable")}
              </p>
            ) : null}
            {!searchUnmatchable && directory.status === "ready" && !directory.data.complete ? (
              <p class="ontology-instance-bound-notice" role="note">
                {t("ontology.instances.resultBoundTruncated", {
                  count: formatNumber(options.length),
                })}
              </p>
            ) : null}
            {!searchUnmatchable && directory.status === "ready" && options.length === 0 ? (
              <UnavailableState message={t("ontology.instances.noSearchResults")} />
            ) : null}
            {selectedId === null ? (
              <div class="ontology-instance-empty">
                <strong>{t("ontology.instances.emptyTitle")}</strong>
                <p>{t("ontology.instances.emptyDescription")}</p>
              </div>
            ) : (
              <AsyncBoundary state={detail} resourceLabel={t("ontology.instances.detailLoading")}>
                {(data) => (
                  <OntologyInstanceWorkspace data={data} onSelect={selectResource} />
                )}
              </AsyncBoundary>
            )}
          </>
        )}
      </AsyncBoundary>
    </section>
  );
}

function OntologyInstanceWorkspace({
  data,
  onSelect,
}: {
  readonly data: OntologyInstanceExploration;
  readonly onSelect: (resourceId: string | null) => void;
}) {
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const root = data.resources.find((resource) => resource.id === data.root_id)!;
  const presentationLinks = ontologyInstancePresentationLinks(data);
  const relationships = partitionOntologyInstanceLinks(presentationLinks, data.root_id);
  const relationshipGroups = groupOntologyInstanceRelationships(presentationLinks, data.root_id);
  const aksLanes = ontologyInstanceAksLanes(data);
  const incompleteReasons = [
    ...data.truncation_reasons.map(truncationReasonLabel),
    ...(data.relationship_drop_reasons.length > 0
      ? [t("ontology.instances.relationshipCoverageIncomplete")]
      : []),
  ];
  usePublishViewContext(
    () => {
      const contextIdentity = contextIdentityForExploration(data);
      return {
        routeId: "ontology-instances",
      routeLabel: t("ontology.instances.title"),
      purpose: t("ontology.instances.contextPurpose"),
      glossary: composeGlossary([TERMS.resource]),
      headline: t("ontology.instances.contextHeadline", {
        name: root.name ?? root.resource_type,
        resources: formatNumber(data.resources.length),
        links: formatNumber(data.links.length),
        events: formatNumber(data.timeline.items.length),
      }),
      capturedAt: data.source_cutoff,
      facts: [
        { key: "source_generation", value: data.source_generation, group: "provenance" },
        { key: "ontology_release", value: data.ontology_release_digest, group: "provenance" },
        { key: "complete", value: data.complete, group: "provenance" },
        {
          key: "relationship_drop_reasons",
          value: data.relationship_drop_reasons.join(","),
          group: "provenance",
        },
        { key: "selected_resource", value: root.name ?? root.resource_type, group: "selection" },
      ],
      records: {
        selected_resource: [resourceContextRecord(root)],
        direct_relationships: relationships.direct
          .map((link) => relationshipContextRecord(link, data)),
        verified_ingress: relationshipGroups.verifiedIngress
          .map((link) => relationshipContextRecord(link, data)),
        verified_egress: relationshipGroups.verifiedEgress
          .map((link) => relationshipContextRecord(link, data)),
        access_context: relationshipGroups.accessContext
          .map((link) => relationshipContextRecord(link, data)),
        path_relationships: relationships.path
          .map((link) => relationshipContextRecord(link, data)),
        recent_activity: data.timeline.items.map((item) => ({
          action_kind: item.action_kind,
          actor: item.actor,
          recorded_at: item.recorded_at,
          ...item.facts,
          evidence_ref: item.evidence_ref,
        })),
      },
        ...(contextIdentity ? { contextIdentity } : {}),
      };
    },
    [data, root],
  );
  return (
    <div class={`ontology-instance-workbench${inspectorOpen ? "" : " is-inspector-collapsed"}`}>
      <div class="ontology-instance-map-pane">
        {aksLanes ? (
          <section
            class="ontology-instance-aks-lanes"
            aria-label={t("ontology.instances.aksCoverageTitle")}
          >
            <header>
              <strong>{t("ontology.instances.aksCoverageTitle")}</strong>
              <span>{t("ontology.instances.aksCoverageHint")}</span>
            </header>
            <div>
              {aksLanes.map((lane) => (
                <ol key={lane.id} aria-label={t(`ontology.instances.aksLane.${lane.id}`)}>
                  <li class="ontology-instance-aks-lane-title">
                    {t(`ontology.instances.aksLane.${lane.id}`)}
                  </li>
                  {lane.steps.map((step) => (
                    <li key={`${lane.id}-${step.id}`} class={`is-${step.status}`}>
                      <span>{t(`ontology.instances.aksStep.${step.id}`)}</span>
                      <small>{t(`ontology.instances.pathStatus.${step.status}`)}</small>
                    </li>
                  ))}
                </ol>
              ))}
            </div>
          </section>
        ) : null}
        <div class="ontology-instance-map-shell">
          {!inspectorOpen ? (
            <Tooltip content={t("ontology.instances.showInspector")}>
              <button
                type="button"
                class="ontology-instance-inspector-toggle is-restore"
                aria-label={t("ontology.instances.showInspector")}
                aria-expanded={false}
                aria-controls="ontology-instance-inspector"
                onClick={() => setInspectorOpen(true)}
              >
                <span class="ontology-instance-panel-icon" aria-hidden="true" />
              </button>
            </Tooltip>
          ) : null}
          <p id="ontology-instance-map-description" class="sr-only">
            {t("ontology.instances.mapDescription", {
              depth: formatNumber(data.depth),
              resources: formatNumber(data.resources.length),
              links: formatNumber(data.links.length),
            })}
          </p>
          <OntologyInstanceGraph data={data} onSelect={onSelect} />
        </div>
        {!data.complete ? (
          <UnavailableState message={t("ontology.instances.truncated", {
            reasons: incompleteReasons.join(", "),
          })} />
        ) : null}
      </div>
      <OntologyInstanceInspector
        data={data}
        root={root}
        onSelect={onSelect}
        hidden={!inspectorOpen}
        onToggle={() => setInspectorOpen(false)}
      />
    </div>
  );
}

function contextIdentityForExploration(
  data: OntologyInstanceExploration,
): ViewSnapshot["contextIdentity"] {
  if (
    !data.complete ||
    !data.principal_id ||
    !data.principal_scope_digest ||
    !data.selection_digest ||
    !data.selection_token
  ) {
    return undefined;
  }
  return {
    kind: "screen",
    screenId: "ontology-instances",
    resourceIds: data.resources.map((resource) => resource.id),
    selectionToken: data.selection_token,
    principalId: data.principal_id,
    principalScopeDigest: data.principal_scope_digest,
    ontologyReleaseDigest: data.ontology_release_digest,
    sourceGeneration: data.source_generation,
    selectionDigest: data.selection_digest,
    complete: true,
  };
}

function truncationReasonLabel(reason: OntologyInstanceExploration["truncation_reasons"][number]): string {
  return t(`ontology.instances.truncation.${reason}`);
}

function resourceContextRecord(resource: OntologyInstanceResource): Record<string, unknown> {
  return {
    name: resource.name,
    type: resource.resource_type,
    status: resource.status,
    location: resource.location,
    resource_group: resource.resource_group,
    last_seen: resource.last_seen,
  };
}

function relationshipContextRecord(
  link: OntologyInstanceLink,
  data: OntologyInstanceExploration,
): Record<string, unknown> {
  const outgoing = link.source === data.root_id;
  const incoming = link.target === data.root_id;
  const source = data.resources.find((resource) => resource.id === link.source);
  const target = data.resources.find((resource) => resource.id === link.target);
  return {
    direction: outgoing ? "outgoing" : incoming ? "incoming" : "path",
    link_type: link.link_type,
    source: source?.name ?? source?.resource_type ?? "unknown",
    target: target?.name ?? target?.resource_type ?? "unknown",
    evidence_status: link.evidence.status,
    evidence_kind: link.evidence.evidence_kind,
    evidence_source: link.evidence.source,
    evidence_cutoff: link.evidence.cutoff,
    evidence_complete: link.evidence.complete,
    mapping_id: link.evidence.mapping_id,
    source_property_path: link.evidence.source_property_path,
    traffic_direction: ontologyInstanceTrafficDirection(link, data.root_id),
    evidence_unavailable_reason: link.evidence.reason,
  };
}
