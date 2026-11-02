import { useEffect, useRef, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import { EvidenceRefresh } from "../components/evidence-refresh";
import { AsyncBoundary, type AsyncState } from "../components/ui";
import type { ConsoleDataMode } from "../console-data-mode";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary, TERMS } from "../deck/glossary";
import { t } from "../i18n";
import { formatConsoleTimestamp } from "../time-format";
import { decodeObserverProposals } from "./observer-proposals";
import { environmentUxText, observerReasonLabel } from "./environment-deployment.i18n";

type ObserverProposal = ReturnType<typeof decodeObserverProposals>[number];

export function effectiveObserverStatus(item: ObserverProposal, now: number): string {
  return item.status === "unavailable" ? "unavailable" : item.expiresAt <= now ? "expired" : item.status;
}

export function nextObserverExpiryDelay(items: readonly ObserverProposal[], now: number): number | null {
  const expiries = items.filter((item) => item.status !== "unavailable" && item.expiresAt > now).map((item) => item.expiresAt);
  return expiries.length === 0 ? null : Math.min(2_147_483_647, Math.max(1, Math.min(...expiries) - now + 20));
}

export function filterObserverProposals(items: readonly ObserverProposal[], search: string, status: string, now: number): readonly ObserverProposal[] {
  const query = search.trim().toLocaleLowerCase();
  return items.filter((item) => (!query || item.target.toLocaleLowerCase().includes(query))
    && (!status || effectiveObserverStatus(item, now) === status));
}

const statusLabel = (status: string) => status === "expired" || status === "unavailable"
  ? environmentUxText(status) : t(`observerProposals.${status}`);

export function EnvironmentDeploymentObservers({ client, dataMode }: {
  readonly client: OperatorApiClient; readonly dataMode: ConsoleDataMode;
}) {
  const [state, setState] = useState<AsyncState<readonly ObserverProposal[]>>({ status: "loading" });
  const [now, setNow] = useState(Date.now);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const generation = useRef(0);
  const load = async () => {
    const request = ++generation.current;
    if (dataMode !== "live") {
      setState({ status: "unavailable", message: t("observerProposals.unavailable") });
      return;
    }
    setState({ status: "loading" });
    try {
      const data = decodeObserverProposals(await client.panel<unknown>("/observer-deployment-proposals"));
      if (request === generation.current) {
        const received = Date.now();
        setNow(received);
        setCheckedAt(new Date(received).toISOString());
        setState({ status: "ready", data });
      }
    } catch (reason) {
      if (request === generation.current) setState(isOptionalOperatorApiUnavailable(reason)
        ? { status: "unavailable", message: t("observerProposals.unavailable") }
        : { status: "error", message: `${environmentUxText("sourceError")} ${reason instanceof Error ? reason.message : String(reason)}` });
    }
  };
  useEffect(() => {
    void load();
    return () => { generation.current += 1; };
  }, [client, dataMode]);
  useEffect(() => {
    const delay = state.status === "ready" ? nextObserverExpiryDelay(state.data, now) : null;
    if (delay === null) return undefined;
    const timer = window.setTimeout(() => setNow(Date.now()), delay);
    return () => window.clearTimeout(timer);
  }, [state, now]);
  usePublishViewContext(() => state.status !== "ready" ? null : ({
    routeId: "observer-proposals", routeLabel: t("observerProposals.title"),
    purpose: t("observerProposals.sourceDescription"),
    headline: environmentUxText("count", { shown: filterObserverProposals(state.data, search, status, now).length, total: state.data.length }),
    capturedAt: checkedAt ?? new Date().toISOString(), glossary: composeGlossary([TERMS.hil]),
    facts: [
      { key: "proposal_count", value: state.data.length, group: "proposals" },
      { key: "execution_authority", value: false, group: "proposals" },
    ],
    records: { proposals: filterObserverProposals(state.data, search, status, now).map((item) => ({
      target: item.target, status: effectiveObserverStatus(item, now),
      expires_at: new Date(item.expiresAt).toISOString(),
    })) },
  }), [state, now, checkedAt, search, status]);
  return <div class="stack observer-proposals">
    <header class="environment-deployment-section-header">
      <h2>{t("observerProposals.title")}</h2>
      <EvidenceRefresh loading={state.status === "loading"} onRefresh={() => void load()} />
    </header>
    <p class="muted">{checkedAt
      ? environmentUxText("lastFetched", { time: formatConsoleTimestamp(checkedAt) })
      : environmentUxText("notFetched")}</p>
    <AsyncBoundary state={state} resourceLabel={t("observerProposals.title")}>
      {(items) => items.length === 0 ? <section class="observer-proposals-empty" role="status">
        <h3>{t("observerProposals.emptyTitle")}</h3>
        <p>{t("observerProposals.emptyDescription")}</p>
        <p class="observer-proposals-empty-source">{t("observerProposals.sourceDescription")}</p>
      </section> : <>
        <div class="settings-filter-bar">
          <label><span>{environmentUxText("search")}</span><input type="search" class="form-input" value={search}
            onInput={(event) => setSearch(event.currentTarget.value)} /></label>
          <label><span>{environmentUxText("status")}</span><select class="form-input" value={status}
            onChange={(event) => setStatus(event.currentTarget.value)}>
            <option value="">{environmentUxText("all")}</option>
            {["ready_for_review", "needs_evidence", "blocked", "not_applicable", "expired", "unavailable"].map((value) =>
              <option key={value} value={value}>{statusLabel(value)}</option>)}
          </select></label>
          <button type="button" class="btn secondary" disabled={!search && !status}
            onClick={() => { setSearch(""); setStatus(""); }}>{environmentUxText("clear")}</button>
        </div>
        <p role="status">{environmentUxText("count", { shown: filterObserverProposals(items, search, status, now).length, total: items.length })}</p>
        {filterObserverProposals(items, search, status, now).length === 0 ? <p>{environmentUxText("noMatches")}</p> : null}
        {filterObserverProposals(items, search, status, now).map((item) => {
          const effectiveStatus = effectiveObserverStatus(item, now);
          const current = effectiveStatus !== "expired" && effectiveStatus !== "unavailable";
          return <details class="observer-proposal" key={item.target}>
            <summary><strong>{item.target}</strong><span>{statusLabel(effectiveStatus)}</span></summary>
            {current ? <div class="stack">
              {item.recommended ? <p>{t("observerProposals.recommendation")}: {t(`observerProposals.${item.recommended.method}`)} / {t(`observerProposals.${item.recommended.egress}`)}</p> : null}
              <dl>{item.candidates.map((candidate) => <div key={`${candidate.method}-${candidate.egress}`}>
                <dt>{t(`observerProposals.${candidate.method}`)} / {t(`observerProposals.${candidate.egress}`)}</dt>
                <dd><strong>{t(`observerProposals.${candidate.state}`)}</strong>
                  <p>{environmentUxText("blockers")}</p>
                  {candidate.blockers.length ? <ul>{candidate.blockers.map((reason, index) =>
                    <li key={`${reason}-${index}`}>{observerReasonLabel(reason)} <code>{reason}</code></li>)}</ul> : <p>{environmentUxText("noBlockers")}</p>}
                  <p>{environmentUxText("missing")}</p>
                  {candidate.missing.length ? <ul>{candidate.missing.map((reason, index) =>
                    <li key={`${reason}-${index}`}>{observerReasonLabel(reason)} <code>{reason}</code></li>)}</ul> : <p>{environmentUxText("noMissing")}</p>}
                </dd>
              </div>)}</dl>
            </div> : <p>{environmentUxText(effectiveStatus === "expired" ? "expiredHint" : "neverObserved")}</p>}
            <p>{effectiveStatus === "expired" ? environmentUxText("currentExpiry") : t("observerProposals.expires")}:{" "}
              <time dateTime={new Date(item.expiresAt).toISOString()}>{formatConsoleTimestamp(new Date(item.expiresAt).toISOString())}</time></p>
          </details>;
        })}
      </>}
    </AsyncBoundary>
  </div>;
}
