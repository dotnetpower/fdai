import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import {
  AsyncBoundary,
  PageHeader,
  type AsyncState,
} from "../components/ui";
import { t } from "../i18n";
import { navigate, routeHref } from "../router";
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

/** Read the ``?correlation=`` value used by incident and evidence deep links. */
function correlationFromLocation(): string {
  const params = new URLSearchParams(window.location.search);
  return params.get("correlation")?.trim() ?? "";
}

export function rcaCorrelationHref(correlationId: string): string {
  return routeHref("rca", { params: { correlation: correlationId.trim() } });
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
      const deepLinked = correlationFromLocation();
      if (!deepLinked) {
        requestGeneration.current += 1;
        setSelectedCorrelationId("");
        setDraftCorrelationId("");
        setLookupOpen(true);
        setState({ status: "idle" });
        return;
      }
      setSelectedCorrelationId(deepLinked);
      setDraftCorrelationId(deepLinked);
      setLookupOpen(false);
      if (deepLinked === selectedCorrelationId && consumeLookupFocusState()) {
        setLookupFocusRequest((current) => current + 1);
      }
      void fetchRca(deepLinked);
    };
    sync();
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      requestGeneration.current += 1;
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
      <PageHeader title={t("route.rca")} subtitle={t("rca.subtitle")} />
      <aside class="rca-authority-note" role="note">
        <strong>{rcaText("readOnlyTitle")}</strong>
        <span>{rcaText("readOnlyBody")}</span>
      </aside>
      <section class="rca-query-panel" aria-label={t("rca.lookup")}>
        {hasCorrelation ? (
          <div class="rca-lookup-summary">
            <div>
              <strong class="mono">{loadedCorrelation}</strong>
              <small>{lookupStatusLabel(state)}</small>
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
              navigate(rcaCorrelationHref(normalized), false, { fdaiRcaLookupFocus: true });
            }
          }}
        >
          <label class="rca-lookup-field">
            <span>{t("rca.correlationLabel")}</span>
            <input
              ref={lookupInput}
              type="text"
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
              !draftCorrelationId.trim()
              || (
                state.status === "loading"
                && draftCorrelationId.trim() === loadedCorrelation.trim()
              )
            }
          >
            {t("rca.fetch")}
          </button>
          <small id="rca-lookup-help">{rcaText("lookupHelp")}</small>
        </form>
      </section>
      <AsyncBoundary
        state={state}
        resourceLabel={t("route.rca")}
        loading={<RcaLoadingState />}
        idle={<p class="rca-idle-state">{t("rca.idle")}</p>}
      >
        {(data) => <RcaBody data={data} />}
      </AsyncBoundary>
    </div>
  );
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
  window.history.replaceState(
    nextState,
    "",
    `${window.location.pathname}${window.location.search}${window.location.hash}`,
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
