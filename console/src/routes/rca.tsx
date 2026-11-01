import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import {
  AsyncBoundary,
  PageHeader,
  type AsyncState,
} from "../components/ui";
import { usePublishViewContext, type ViewSnapshot } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { currentRoute, navigate, ROUTE_STATE_EVENT, routeHref } from "../router";
import type { RcaView } from "../types";
import { rcaText } from "./rca.i18n";
import { RcaBody } from "./rca.presentation";
import "./rca.css";

export { hasRecordedRca } from "./rca.presentation";

/**
 * Read-only RCA route for one incident correlation. The route owns loading
 * and deep-link state; the result module owns evidence presentation.
 */

interface Props {
  readonly client: OperatorApiClient;
}

export const MAX_RCA_CORRELATION_ID_LENGTH = 256;

export function normalizeRcaCorrelationId(value: string | null | undefined): string {
  const trimmed = value?.trim() ?? "";
  if (!trimmed || trimmed.length > MAX_RCA_CORRELATION_ID_LENGTH || /[\r\n\0]/.test(trimmed)) {
    return "";
  }
  return trimmed;
}

/** Read the ``?correlation=`` value used by incident and evidence deep links. */
function correlationFromLocation(): string {
  return normalizeRcaCorrelationId(currentRoute().search.get("correlation"));
}

export function rcaCorrelationHref(
  correlationId: string,
  search?: URLSearchParams,
): string {
  const normalized = normalizeRcaCorrelationId(correlationId);
  return routeHref("rca", {
    params: {
      correlation: normalized || null,
      data: search?.get("data") === "sample" ? "sample" : null,
    },
  });
}

export function RcaRoute({ client }: Props) {
  const [selectedCorrelationId, setSelectedCorrelationId] = useState(
    () => correlationFromLocation(),
  );
  const [draftCorrelationId, setDraftCorrelationId] = useState(
    () => correlationFromLocation(),
  );
  const [lookupOpen, setLookupOpen] = useState(() => !correlationFromLocation());
  const [lookupFocusRequest, setLookupFocusRequest] = useState(0);
  const [state, setState] = useState<AsyncState<RcaView>>({ status: "idle" });
  const requestGeneration = useRef(0);
  const lookupInput = useRef<HTMLInputElement>(null);
  const lookupToggle = useRef<HTMLButtonElement>(null);

  async function fetchRca(id: string): Promise<void> {
    if (!id) return;
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    setState({ status: "loading" });
    try {
      const data = await client.rca(id);
      if (requestGeneration.current === generation) setState({ status: "ready", data });
    } catch (err) {
      if (requestGeneration.current === generation) {
        setState({
          status: "error",
          message: err instanceof Error ? err.message : String(err),
        });
      }
    }
  }

  useEffect(() => {
    const sync = () => {
      const next = correlationFromLocation();
      setSelectedCorrelationId(next);
      setDraftCorrelationId(next);
      setLookupOpen(!next);
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    window.addEventListener(ROUTE_STATE_EVENT, sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
      window.removeEventListener(ROUTE_STATE_EVENT, sync);
    };
  }, []);

  useEffect(() => {
    if (consumeLookupFocusState()) {
      setLookupFocusRequest((current) => current + 1);
    }
    if (selectedCorrelationId) void fetchRca(selectedCorrelationId);
    else setState({ status: "idle" });
    return () => {
      requestGeneration.current += 1;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, selectedCorrelationId]);

  useEffect(() => {
    if (lookupFocusRequest > 0) lookupToggle.current?.focus();
  }, [lookupFocusRequest]);

  const loadedCorrelation = state.status === "ready"
    ? state.data.correlation_id
    : selectedCorrelationId;
  const hasCorrelation = Boolean(loadedCorrelation.trim());

  function toggleLookup(): void {
    if (lookupOpen) {
      setDraftCorrelationId(loadedCorrelation);
      setLookupOpen(false);
      return;
    }
    setDraftCorrelationId(loadedCorrelation);
    setLookupOpen(true);
    window.requestAnimationFrame(() => lookupInput.current?.focus());
  }

  return (
    <div class="stack rca-page">
      <PageHeader title={t("route.rca")} subtitle={rcaText("subtitle")} />
      <aside class="rca-authority-note" role="note">
        <strong>{rcaText("readOnlyTitle")}</strong>
        <span>{rcaText("readOnlyBody")}</span>
      </aside>
      <section class="rca-query-panel" aria-label={rcaText("lookup")}>
        {hasCorrelation ? (
          <div class="rca-lookup-summary">
            <div>
              <strong class="mono">{loadedCorrelation}</strong>
              <small role="status" aria-live="polite" aria-atomic="true">
                {lookupStatusLabel(state)}
              </small>
            </div>
            <button
              ref={lookupToggle}
              type="button"
              class="btn"
              aria-controls="rca-lookup-form"
              aria-expanded={lookupOpen}
              onClick={toggleLookup}
            >
              {lookupOpen ? rcaText("cancelChange") : rcaText("changeCorrelation")}
            </button>
          </div>
        ) : null}
        <form
          id="rca-lookup-form"
          class="rca-lookup-form"
          hidden={hasCorrelation && !lookupOpen}
          onSubmit={(event) => {
            event.preventDefault();
            const normalized = draftCorrelationId.trim();
            if (normalized) {
              if (normalized === selectedCorrelationId) {
                setDraftCorrelationId(selectedCorrelationId);
                setLookupOpen(false);
                setLookupFocusRequest((current) => current + 1);
                void fetchRca(selectedCorrelationId);
              } else {
                navigate(
                  rcaCorrelationHref(normalized, currentRoute().search),
                  false,
                  { fdaiRcaLookupFocus: true },
                );
              }
            }
          }}
        >
          <label class="rca-lookup-field">
            <span>{rcaText("correlationLabel")}</span>
            <input
              ref={lookupInput}
              type="text"
              maxLength={MAX_RCA_CORRELATION_ID_LENGTH}
              value={draftCorrelationId}
              aria-describedby="rca-lookup-help"
              onInput={(event) => setDraftCorrelationId(
                (event.target as HTMLInputElement).value,
              )}
              required
            />
          </label>
          <button
            type="submit"
            class="btn primary"
            disabled={
              !normalizeRcaCorrelationId(draftCorrelationId)
              || (
                state.status === "loading"
                && normalizeRcaCorrelationId(draftCorrelationId) === loadedCorrelation.trim()
              )
            }
          >
            {rcaText("fetch")}
          </button>
          <small id="rca-lookup-help">{rcaText("lookupHelp")}</small>
        </form>
      </section>
      {state.status === "ready" ? null : (
        <RcaPendingContext
          correlationId={selectedCorrelationId}
          status={state.status}
        />
      )}
      <AsyncBoundary
        state={state}
        resourceLabel={t("route.rca")}
        loading={<RcaLoadingState />}
        idle={<p class="rca-idle-state">{rcaText("idle")}</p>}
      >
        {(data) => <RcaBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

type RcaPendingStatus = Exclude<AsyncState<RcaView>["status"], "ready">;

function RcaPendingContext({
  correlationId,
  status,
}: {
  readonly correlationId: string;
  readonly status: RcaPendingStatus;
}) {
  usePublishViewContext(
    () => buildRcaPendingViewSnapshot(correlationId, status),
    [correlationId, status],
  );
  return null;
}

export function buildRcaPendingViewSnapshot(
  correlationId: string,
  status: RcaPendingStatus,
): ViewSnapshot {
  const headline = status === "loading"
    ? rcaText("lookupStatusLoading")
    : status === "idle"
      ? rcaText("idle")
      : rcaText("lookupStatusError");
  return {
    routeId: "rca",
    routeLabel: t("route.rca"),
    purpose: rcaText("viewPurpose"),
    headline,
    glossary: composeGlossary([
      TERMS.correlationId,
      TERMS.tier,
      TERMS.gateDecision,
      TERMS.mode,
      TERMS.outcome,
    ]),
    facts: [
      { key: "correlation_id", value: correlationId || null, group: "rca" },
      { key: "load_status", value: status, group: "rca" },
    ],
    records: { hypotheses: [], response: [] },
    capturedAt: new Date().toISOString(),
  };
}

function consumeLookupFocusState(): boolean {
  const state: unknown = window.history.state;
  if (
    state === null
    || typeof state !== "object"
    || !("fdaiRcaLookupFocus" in state)
    || state.fdaiRcaLookupFocus !== true
  ) {
    return false;
  }
  const nextState = { ...state };
  delete nextState.fdaiRcaLookupFocus;
  const route = currentRoute();
  const query = route.search.toString();
  window.history.replaceState(
    nextState,
    "",
    `${route.canonicalPathname}${query ? `?${query}` : ""}${window.location.hash}`,
  );
  return true;
}

function lookupStatusLabel(state: AsyncState<RcaView>): string {
  if (state.status === "loading") return rcaText("lookupStatusLoading");
  if (state.status === "ready") return rcaText("lookupStatusReady");
  if (state.status === "error") return rcaText("lookupStatusError");
  return rcaText("lookupStatusSelected");
}

function RcaLoadingState() {
  return (
    <div class="rca-skeleton" role="status" aria-live="polite" aria-busy="true">
      <span class="sr-only">{t("shared.loadingResource", { resource: t("route.rca") })}</span>
      <div class="rca-skeleton-hero" aria-hidden="true">
        <span class="skeleton-shimmer" />
        <span class="skeleton-shimmer" />
        <span class="skeleton-shimmer" />
      </div>
      <div class="rca-skeleton-panels" aria-hidden="true">
        <span class="skeleton-shimmer" />
        <span class="skeleton-shimmer" />
      </div>
    </div>
  );
}
