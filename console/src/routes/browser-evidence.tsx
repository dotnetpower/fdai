import type { ComponentChildren } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable } from "../api";
import type { OperatorApiClient } from "../api";
import {
  AsyncBoundary,
  PageHeader,
  type AsyncState,
} from "../components/ui";
import { usePublishViewContext, type ViewSnapshot } from "../deck/context";
import { composeGlossary } from "../deck/glossary";
import { currentRoute } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { t } from "./i18n/browser-evidence";
import {
  appendBrowserEvidencePage,
  browserEvidenceRequest,
  decodeBrowserEvidenceWorkspace,
  type BrowserEvidenceData,
  type BrowserEvidenceRequest,
  type BrowserEvidenceWorkspaceResponse,
} from "./browser-evidence.model";
import {
  BrowserEvidenceWorkspace,
} from "./browser-evidence.workspace";
import { BrowserEvidenceFilters } from "./browser-evidence.filters";
import "./browser-evidence.css";

export { decodeBrowserEvidenceWorkspace } from "./browser-evidence.model";

export function buildBrowserEvidenceViewSnapshot(
  data: BrowserEvidenceData,
  selectedId: string | null = null,
): ViewSnapshot {
  const page = data.page;
  const selected = data.items.find((item) => item.artifact_id === selectedId) ?? null;
  return {
    routeId: "browser-evidence",
    routeLabel: t("route.browserEvidence"),
    purpose: t("browserEvidence.readOnlyBody"),
    glossary: composeGlossary([], [
      {
        term: t("route.browserEvidence"),
        plain: t("browserEvidence.subtitle"),
        tech: "BrowserEvidenceArtifact",
      },
    ]),
    headline: t("browserEvidence.viewHeadline", {
      loaded: data.items.length,
      matching: page.matching_admitted_count,
      findings: page.summary.security_finding_count,
      withheld: page.snapshot_withheld_count,
    }),
    capturedAt: page.observed_at,
    facts: [
      {
        key: "loaded_count",
        label: t("browserEvidence.metrics.loaded"),
        value: data.items.length,
      },
      {
        key: "matching_admitted_count",
        label: t("browserEvidence.metrics.matching"),
        value: page.matching_admitted_count,
      },
      {
        key: "snapshot_admitted_count",
        label: t("browserEvidence.metrics.admitted"),
        value: page.snapshot_admitted_count,
      },
      {
        key: "snapshot_withheld_count",
        label: t("browserEvidence.metrics.withheld"),
        value: page.snapshot_withheld_count,
      },
      {
        key: "security_finding_count",
        label: t("browserEvidence.metrics.findings"),
        value: page.summary.security_finding_count,
      },
      {
        key: "consistency",
        label: t("browserEvidence.consistency"),
        value: page.consistency,
      },
      {
        key: "source_observed_at",
        label: t("browserEvidence.sourceObserved"),
        value: page.source_observed_at,
      },
    ],
    records: {
      artifacts: data.items.map((item) => ({
        artifact: shortArtifactId(item.artifact_id),
        source_host: item.source_host,
        policy: `${item.policy_id}@${item.policy_version}`,
        captured_at: item.captured_at,
        retention_state: item.retention_state,
        prompt_injection_findings: item.prompt_injection_finding_count,
      })),
      selected_artifact: selected === null ? [] : [{
        artifact_id: selected.artifact_id,
        source_host: selected.source_host,
        final_host: selected.final_host,
        policy: `${selected.policy_id}@${selected.policy_version}`,
        captured_at: selected.captured_at,
        expires_at: selected.expires_at,
        retention_state: selected.retention_state,
        selectors: selected.selector_count,
        redactions: selected.redaction_count,
        prompt_injection_findings: selected.prompt_injection_finding_count,
        digest_presence: selected.digest_presence,
        browser_version: selected.browser_version,
        custody_audit_ref: selected.custody_audit_ref,
        audit: selected.audit,
        isolation_verified: true,
        untrusted: true,
        can_authorize_action: false,
      }],
    },
  };
}

export function BrowserEvidenceRoute({ client }: { readonly client: OperatorApiClient }) {
  const [request, setRequest] = useState<BrowserEvidenceRequest>(
    () => browserEvidenceRequest(currentRoute().search),
  );
  const [searchKey, setSearchKey] = useState(() => currentRoute().search.toString());
  const [state, setState] = useState<AsyncState<BrowserEvidenceData>>({
    status: "loading",
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const generation = useRef(0);
  const mounted = useRef(true);

  useEffect(() => () => {
    mounted.current = false;
    generation.current += 1;
  }, []);

  useEffect(() => {
    const sync = () => {
      const search = currentRoute().search;
      setRequest(browserEvidenceRequest(search));
      setSearchKey(search.toString());
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, []);

  useEffect(() => {
    const currentGeneration = generation.current + 1;
    generation.current = currentGeneration;
    setLoadingMore(false);
    setPageError(null);
    setSelectedId(null);
    if (request.invalid.length > 0) {
      setState({
        status: "error",
        message: t("browserEvidence.filters.invalid", {
          fields: request.invalid.join(", "),
        }),
      });
      return;
    }
    setState({ status: "loading" });
    void loadBrowserEvidenceState(client, request).then((next) => {
      if (!mounted.current || generation.current !== currentGeneration) return;
      setState(next);
      if (next.status === "ready") {
        const requested = request.params["artifact"];
        setSelectedId(
          requested && next.data.items.some((item) => item.artifact_id === requested)
            ? requested
            : next.data.items[0]?.artifact_id ?? null,
        );
      }
    });
  }, [client, request]);

  const loadMore = async (cursor: string): Promise<void> => {
    if (
      state.status !== "ready"
      || loadingMore
      || state.data.page.next_cursor !== cursor
    ) return;
    const currentGeneration = generation.current;
    setLoadingMore(true);
    setPageError(null);
    try {
      const page = await loadBrowserEvidencePage(client, request, cursor);
      if (!mounted.current || generation.current !== currentGeneration) return;
      setState((current) => current.status === "ready"
        ? {
            status: "ready",
            data: appendBrowserEvidencePage(current.data, cursor, page),
          }
        : current);
    } catch (error) {
      if (!mounted.current || generation.current !== currentGeneration) return;
      setPageError(error instanceof Error ? error.message : String(error));
    } finally {
      if (mounted.current && generation.current === currentGeneration) {
        setLoadingMore(false);
      }
    }
  };

  return (
    <div class="browser-evidence-page">
      <PageHeader
        title={t("route.browserEvidence")}
        subtitle={t("browserEvidence.subtitle")}
        actions={<BrowserEvidenceHeaderMeta state={state} />}
      />
      <aside class="browser-evidence-boundary" role="note">
        <strong>{t("browserEvidence.readOnlyTitle")}</strong>
        <span>{t("browserEvidence.readOnlyBody")}</span>
      </aside>
      <BrowserEvidenceFilters
        key={searchKey}
        search={new URLSearchParams(searchKey)}
      />
      <AsyncBoundary
        state={state}
        resourceLabel={t("browserEvidence.resourceLabel")}
        loading={<BrowserEvidenceLoading />}
      >
        {(data) => (
          <BrowserEvidenceContext data={data} selectedId={selectedId}>
            <BrowserEvidenceWorkspace
              data={data}
              selectedId={selectedId}
              loadingMore={loadingMore}
              pageError={pageError}
              onSelect={setSelectedId}
              onLoadMore={loadMore}
            />
          </BrowserEvidenceContext>
        )}
      </AsyncBoundary>
    </div>
  );
}

export async function loadBrowserEvidenceState(
  client: Pick<OperatorApiClient, "panel">,
  request: BrowserEvidenceRequest,
): Promise<AsyncState<BrowserEvidenceData>> {
  try {
    const page = await loadBrowserEvidencePage(client, request);
    return { status: "ready", data: { page, items: page.items } };
  } catch (error) {
    if (isOptionalOperatorApiUnavailable(error)) {
      return { status: "unavailable", message: t("browserEvidence.unavailable") };
    }
    return {
      status: "error",
      message: error instanceof Error ? error.message : String(error),
    };
  }
}

async function loadBrowserEvidencePage(
  client: Pick<OperatorApiClient, "panel">,
  request: BrowserEvidenceRequest,
  cursor?: string,
): Promise<BrowserEvidenceWorkspaceResponse> {
  const value = await client.panel<unknown>(
    "/browser-evidence/snapshot",
    cursor ? { ...request.params, cursor } : { ...request.params },
  );
  return decodeBrowserEvidenceWorkspace(value, request.sort);
}

function BrowserEvidenceContext({
  data,
  selectedId,
  children,
}: {
  readonly data: BrowserEvidenceData;
  readonly selectedId: string | null;
  readonly children: ComponentChildren;
}) {
  usePublishViewContext(
    () => buildBrowserEvidenceViewSnapshot(data, selectedId),
    [data, selectedId],
  );
  return <>{children}</>;
}

function BrowserEvidenceHeaderMeta({
  state,
}: {
  readonly state: AsyncState<BrowserEvidenceData>;
}) {
  if (state.status !== "ready") return null;
  return (
    <div class="browser-evidence-header-meta">
      <span>{t("browserEvidence.observed")}</span>
      <strong>{formatConsoleTimestamp(state.data.page.observed_at)}</strong>
      <span>{t("browserEvidence.sourceObserved")}</span>
      <strong>{formatConsoleTimestamp(
        state.data.page.source_observed_at,
        t("browserEvidence.notObserved"),
      )}</strong>
    </div>
  );
}

function BrowserEvidenceLoading() {
  return (
    <div
      class="browser-evidence-skeleton"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <span class="sr-only">{t("shared.loadingResource", {
        resource: t("browserEvidence.resourceLabel"),
      })}</span>
      <div aria-hidden="true">
        <span class="skeleton-shimmer" />
        <span class="skeleton-shimmer" />
        <div>
          <span class="skeleton-shimmer" />
          <span class="skeleton-shimmer" />
          <span class="skeleton-shimmer" />
          <span class="skeleton-shimmer" />
        </div>
        <span class="skeleton-shimmer" />
      </div>
    </div>
  );
}

function shortArtifactId(value: string): string {
  return `${value.slice(0, 15)}...${value.slice(-8)}`;
}
