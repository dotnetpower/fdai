/** Server-backed Resource selection for the read-only Impact scope query. */

import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import {
  SearchableSelect,
  type SearchableSelectOption,
} from "../components/searchable-select";
import { CopyButton } from "../components/ui";
import { routeHref } from "../router";
import {
  decodeOntologyInstanceDirectory,
  isMatchableOntologyInstanceQuery,
  isOntologyInstanceDirectoryResource,
  type OntologyInstanceDirectory,
  type OntologyInstanceResource,
} from "./ontology-instances.model";
import { t } from "./i18n/ontology";

const RESOURCE_SEARCH_DEBOUNCE_MS = 250;
const RESOURCE_SEARCH_LIMIT = 20;
const RESOURCE_SEARCH_MAX_CHARS = 256;
const RESOURCE_ID_MAX_CHARS = 1024;

type DirectoryState =
  | { readonly status: "idle" }
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly data: OntologyInstanceDirectory }
  | { readonly status: "unavailable"; readonly message: string }
  | { readonly status: "error"; readonly message: string };

interface Props {
  readonly client: OperatorApiClient;
  readonly selectedId: string;
  readonly onSelect: (resourceId: string) => void;
}

export function ImpactResourcePicker({ client, selectedId, onSelect }: Props) {
  const [query, setQuery] = useState<string | null>(null);
  const [queryRevision, setQueryRevision] = useState(0);
  const [directDraft, setDirectDraft] = useState(selectedId);
  const [directory, setDirectory] = useState<DirectoryState>({ status: "idle" });
  const [selectedLookup, setSelectedLookup] =
    useState<DirectoryState>({ status: "idle" });
  const [focusSearch, setFocusSearch] = useState(false);
  const [directOpen, setDirectOpen] = useState(false);
  const directInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setDirectDraft(selectedId);
    if (!selectedId) {
      setSelectedLookup({ status: "idle" });
      return;
    }
    let cancelled = false;
    setSelectedLookup({ status: "loading" });
    void loadDirectory(client, selectedResourceSearch(selectedId)).then(
      (data) => {
        if (!cancelled) setSelectedLookup({ status: "ready", data });
      },
      (error: unknown) => {
        if (!cancelled) setSelectedLookup(directoryFailure(error));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [client, selectedId]);

  useEffect(() => {
    if (query === null || !isMatchableOntologyInstanceQuery(query)) return;
    let cancelled = false;
    setDirectory({ status: "loading" });
    const timer = window.setTimeout(() => {
      void loadDirectory(client, query.trim()).then(
        (data) => {
          if (!cancelled) setDirectory({ status: "ready", data });
        },
        (error: unknown) => {
          if (!cancelled) setDirectory(directoryFailure(error));
        },
      );
    }, RESOURCE_SEARCH_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [client, query, queryRevision]);

  const selectedResource = selectedLookup.status === "ready"
    ? selectedLookup.data.resources.find((resource) => resource.id === selectedId) ?? null
    : null;
  const resources = useMemo(
    () => directory.status === "ready"
      ? directory.data.resources
        .filter(isOntologyInstanceDirectoryResource)
        .sort((first, second) =>
          (first.name ?? first.resource_type).localeCompare(
            second.name ?? second.resource_type,
          )
          || first.resource_type.localeCompare(second.resource_type))
      : [],
    [directory],
  );
  const resourceById = useMemo(
    () => new Map(resources.map((resource) => [resource.id, resource])),
    [resources],
  );
  const options = useMemo<readonly SearchableSelectOption[]>(
    () => resources.map((resource) => ({
      value: resource.id,
      label: resource.name ?? t("ontology.instances.unnamedResource"),
      description: resourceDescription(resource),
      detail: resource.id,
      keywords: [
        resource.resource_type,
        resource.resource_group ?? "",
        resource.location ?? "",
      ],
    })),
    [resources],
  );
  const queryUnmatchable = query !== null && !isMatchableOntologyInstanceQuery(query);
  const searchMessage = resourceSearchMessage(directory, queryUnmatchable);
  const loading = directory.status === "loading";

  const clearSelection = (): void => {
    setQuery(null);
    setDirectory({ status: "idle" });
    setDirectDraft("");
    setDirectOpen(false);
    setFocusSearch(true);
    onSelect("");
  };

  const applyDirectId = (): void => {
    const resourceId = directDraft.trim();
    if (!resourceId) return;
    setQuery(null);
    onSelect(resourceId);
  };

  const showDirectEntry = (): void => {
    setDirectOpen(true);
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    window.requestAnimationFrame(() => directInput.current?.focus());
  };

  if (selectedId) {
    return (
      <div class="impact-resource-picker">
        <span class="impact-resource-picker-label">
          {t("ontology.blast.targetResource")}
        </span>
        <section class="impact-resource-selection" aria-label={t("ontology.blast.selectedResource")}>
          <div class="impact-resource-selection-copy">
            <strong>{selectedResource?.name ?? shortResourceId(selectedId)}</strong>
            <span>
              {selectedResource
                ? resourceDescription(selectedResource)
                : selectedLookup.status === "loading" || selectedLookup.status === "idle"
                  ? t("ontology.blast.resourceDetailsLoading")
                  : t("ontology.blast.resourceDetailsUnavailable")}
            </span>
            <code>{selectedId}</code>
          </div>
          <div class="impact-resource-selection-actions">
            <CopyButton text={selectedId} label={t("ontology.blast.copyResourceId")} />
            <button
              type="button"
              class="btn"
              onClick={clearSelection}
            >
              {t("ontology.blast.changeResource")}
            </button>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div class="impact-resource-picker">
      <SearchableSelect
        label={t("ontology.blast.targetResource")}
        value=""
        options={options}
        onChange={(resourceId) => {
          const resource = resourceById.get(resourceId);
          if (resource !== undefined) {
            setDirectOpen(false);
            onSelect(resource.id);
          }
        }}
        onQueryChange={(nextQuery) => {
          setFocusSearch(false);
          setQuery(nextQuery);
          setQueryRevision((current) => current + 1);
          setDirectory(isMatchableOntologyInstanceQuery(nextQuery)
            ? { status: "loading" }
            : { status: "idle" });
        }}
        loading={loading}
        autoFocus={focusSearch}
        maxLength={RESOURCE_SEARCH_MAX_CHARS}
        placeholder={t("ontology.blast.resourceSearchPlaceholder")}
        emptyLabel={searchMessage}
        emptyAction={(
          <button type="button" class="btn" onClick={showDirectEntry}>
            {t("ontology.blast.enterExactResourceId")}
          </button>
        )}
        helpText={directory.status === "ready" && !directory.data.complete
          ? t("ontology.blast.resourceResultsBounded", {
              count: directory.data.resources.length,
            })
          : directory.status === "unavailable" || directory.status === "error"
            ? t("ontology.blast.resourceDirectoryUnavailable")
          : t("ontology.blast.resourceSearchHint")}
        resultsLabel={(shown, total) => loading
          ? t("ontology.blast.resourceSearchLoading")
          : t("ontology.blast.resourceSearchResults", { shown, total })}
      />
      <a class="impact-resource-browse-link" href={routeHref("ontology", {
        params: { view: "instances" },
      })}>
        {t("ontology.blast.browseResources")}
      </a>
      <details
        class="impact-resource-direct"
        open={directOpen}
        onToggle={(event) => setDirectOpen(event.currentTarget.open)}
      >
        <summary>{t("ontology.blast.enterExactResourceId")}</summary>
        <div class="impact-resource-direct-fields">
          <label>
            <span>{t("ontology.blast.exactResourceId")}</span>
            <input
              ref={directInput}
              class="impact-query-input"
              maxLength={RESOURCE_ID_MAX_CHARS}
              value={directDraft}
              onInput={(event) => setDirectDraft(event.currentTarget.value)}
              onKeyDown={(event) => {
                if (event.key !== "Enter") return;
                event.preventDefault();
                applyDirectId();
              }}
            />
          </label>
          <button
            type="button"
            class="btn"
            disabled={directDraft.trim().length === 0}
            onClick={applyDirectId}
          >
            {t("ontology.blast.useExactResourceId")}
          </button>
        </div>
        <p>{t("ontology.blast.exactResourceIdHint")}</p>
      </details>
    </div>
  );
}

async function loadDirectory(
  client: OperatorApiClient,
  search: string,
): Promise<OntologyInstanceDirectory> {
  const params = search
    ? { limit: String(RESOURCE_SEARCH_LIMIT), search }
    : { limit: String(RESOURCE_SEARCH_LIMIT) };
  return decodeOntologyInstanceDirectory(
    await client.panel<unknown>("/ontology/instances", params),
  );
}

function directoryFailure(error: unknown): DirectoryState {
  return isOptionalOperatorApiUnavailable(error)
    ? {
        status: "unavailable",
        message: t("ontology.blast.resourceDirectoryUnavailable"),
      }
    : {
        status: "error",
        message: error instanceof Error ? error.message : String(error),
      };
}

function resourceSearchMessage(
  state: DirectoryState,
  queryUnmatchable: boolean,
): string {
  if (queryUnmatchable) return t("ontology.instances.searchNotMatchable");
  if (state.status === "unavailable") return state.message;
  if (state.status === "error") {
    return t("ontology.blast.resourceSearchError", { message: state.message });
  }
  return t("ontology.blast.noResourceMatches");
}

function resourceDescription(resource: OntologyInstanceResource): string {
  return [
    resource.resource_type,
    resource.resource_group,
    resource.location,
  ].filter((value): value is string => Boolean(value)).join(" - ");
}

function shortResourceId(value: string): string {
  return value.split("/").filter(Boolean).at(-1) ?? value;
}

function selectedResourceSearch(value: string): string {
  return value.slice(-RESOURCE_SEARCH_MAX_CHARS);
}
