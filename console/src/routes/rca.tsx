import { useEffect, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { architectureHref } from "../components/architecture-map.model";
import type { RcaHypothesis, RcaView } from "../types";
import {
  AsyncBoundary,
  DataTable,
  KpiCard,
  KpiGrid,
  StatusPill,
  PageHeader,
  type AsyncState,
  type Column,
  type PillKind,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { navigate, routeHref } from "../router";

/**
 * RCA (root-cause analysis) view. Given an incident correlation id, calls
 * ``GET /rca?correlation=...`` and renders the tiered, grounded
 * root-cause hypotheses (T0 / T1 / T2), their citations, and the linked
 * response plan. Read-only projection over the audit log; an RCA
 * hypothesis answers "why", never "execute" - execution eligibility stays
 * with the risk gate + verifier. An ungrounded hypothesis is shown
 * explicitly as "insufficient grounding -> HIL", never a confident cause.
 */

interface Props {
  readonly client: ReadApiClient;
}

/** Read a ``?correlation=`` deep-link value from the hash query string.
 * The Incidents roster links here (``#/rca?correlation=...``). */
function correlationFromHash(): string {
  const params = new URLSearchParams(window.location.search);
  return params.get("correlation")?.trim() ?? "";
}

export function rcaCorrelationHref(correlationId: string): string {
  return routeHref("rca", { params: { correlation: correlationId.trim() } });
}

export function RcaRoute({ client }: Props) {
  const [correlationId, setCorrelationId] = useState(() => correlationFromHash());
  const [state, setState] = useState<AsyncState<RcaView>>({ status: "idle" });
  const requestGeneration = useRef(0);

  async function fetchRca(id: string = correlationId): Promise<void> {
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

  // Auto-fetch when arriving via a deep link (or when the deep-link
  // correlation changes while this panel stays mounted).
  useEffect(() => {
    const sync = () => {
      const deepLinked = correlationFromHash();
      if (!deepLinked) {
        requestGeneration.current += 1;
        setCorrelationId("");
        setState({ status: "idle" });
        return;
      }
      setCorrelationId(deepLinked);
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

  return (
    <div class="stack">
      <PageHeader title={t("route.rca")} subtitle={t("rca.subtitle")} />
      <section class="stack-section">
        <h3 class="section-title">{t("rca.lookup")}</h3>
        <form
          class="form-grid inline"
          onSubmit={(e) => {
            e.preventDefault();
            navigate(rcaCorrelationHref(correlationId));
          }}
        >
          <label>
            {t("rca.correlationLabel")}
            <input
              type="text"
              value={correlationId}
              onInput={(e) => {
                requestGeneration.current += 1;
                setCorrelationId((e.target as HTMLInputElement).value);
                setState({ status: "idle" });
              }}
              required
            />
          </label>
          <button
            type="submit"
            class="btn primary"
            disabled={state.status === "loading" || !correlationId}
          >
            {t("rca.fetch")}
          </button>
        </form>
      </section>
      <AsyncBoundary
        state={state}
        resourceLabel={t("route.rca")}
        idle={<p class="muted footnote">{t("rca.idle")}</p>}
      >
        {(data) => <RcaBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

function RcaBody({ data }: { readonly data: RcaView }) {
  usePublishViewContext(
    () => ({
      routeId: "rca",
      routeLabel: t("route.rca"),
      purpose: t("rca.viewPurpose"),
      glossary: composeGlossary([
        TERMS.correlationId,
        TERMS.tier,
        TERMS.gateDecision,
        TERMS.mode,
        TERMS.outcome,
      ]),
      headline: t("rca.viewHeadline", {
        count: data.hypotheses.length,
        correlation: data.correlation_id,
      }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "correlation_id", value: data.correlation_id, group: "rca" },
        { key: "hypothesis_count", value: data.hypotheses.length, group: "rca" },
        { key: "verdict", value: data.response?.verdict ?? null, group: "rca" },
      ],
      records: {
        hypotheses: data.hypotheses.map((h) => ({ ...h })),
        response: data.response ? [{ ...data.response }] : [],
      },
    }),
    [data],
  );

  return (
    <div class="stack">
      <p>
        <a href={routeHref("reports", {
          segments: ["incident-rca-dossier"],
          params: { correlation_id: data.correlation_id },
        })}>
          {t("rca.report")}
        </a>
        {" | "}
        <a href={routeHref("audit", { params: { correlation: data.correlation_id } })}>
          {t("rca.audit")}
        </a>
        {" | "}
        <a href={routeHref("trace", { params: { correlation: data.correlation_id } })}>
          {t("rca.trace")}
        </a>
      </p>
      <ResponsePlan data={data} />
      <section class="stack-section">
        <h3 class="section-title">{t("rca.hypotheses")}</h3>
        {data.hypotheses.length === 0 ? (
          <p class="muted">{t("rca.empty")}</p>
        ) : (
          <div class="stack">
            {data.hypotheses.map((hypothesis) => (
              <HypothesisCard key={hypothesis.seq} hypothesis={hypothesis} correlationId={data.correlation_id} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function ResponsePlan({ data }: { readonly data: RcaView }) {
  const response = data.response;
  const auditHref = routeHref("audit", { params: { correlation: data.correlation_id } });
  const traceHref = routeHref("trace", { params: { correlation: data.correlation_id } });
  return (
    <section class="stack-section">
      <h3 class="section-title">{t("rca.response")}</h3>
      {response === null ? (
        <p class="muted">{t("rca.noResponse")}</p>
      ) : (
        <KpiGrid>
          <KpiCard
            href={traceHref}
            label={t("rca.verdict")}
            value={<StatusPill kind={verdictPill(response.verdict)} label={response.verdict} />}
          />
          <KpiCard href={traceHref} label={t("rca.decision")} value={response.decision ?? t("rca.none")} />
          <KpiCard
            href={auditHref}
            label={t("rca.action")}
            value={<span class="mono small">{response.action_kind ?? t("rca.none")}</span>}
          />
          <KpiCard
            href={response.mode === null
              ? auditHref
              : routeHref("audit", { params: { correlation: data.correlation_id, mode: response.mode } })}
            label={t("rca.modeColumn")}
            value={
              response.mode === null ? (
                t("rca.none")
              ) : (
                <StatusPill kind={response.mode} label={response.mode} />
              )
            }
          />
          <KpiCard
            href={auditHref}
            label={t("rca.rollback")}
            value={<span class="mono small">{response.rollback_reference ?? t("rca.none")}</span>}
          />
        </KpiGrid>
      )}
    </section>
  );
}

function HypothesisCard({ hypothesis, correlationId }: { readonly hypothesis: RcaHypothesis; readonly correlationId: string }) {
  const auditEntryHref = routeHref("audit", {
    params: { correlation: correlationId, entry: hypothesis.seq },
  });
  return (
    <section class="stack-section">
      <div class="cluster">
        <StatusPill kind="info" label={t(`rca.tierName.${hypothesis.tier}`)} />
        <StatusPill
          kind={hypothesis.grounded ? "success" : "hil"}
          label={hypothesis.grounded ? t("rca.grounded") : t("rca.abstained")}
        />
        <StatusPill kind={hypothesis.mode} label={hypothesis.mode} />
      </div>
      <KpiGrid>
        <KpiCard
          href={auditEntryHref}
          label={t("rca.confidence")}
          value={hypothesis.confidence === null ? t("rca.none") : hypothesis.confidence.toFixed(2)}
        />
        <KpiCard
          href={auditEntryHref}
          label={t("rca.recordedAt")}
          value={<span class="mono small">{hypothesis.recorded_at}</span>}
        />
        <KpiCard
          href={auditEntryHref}
          label={t("rca.remediation")}
          value={<span class="mono small">{hypothesis.remediation_ref ?? t("rca.none")}</span>}
        />
      </KpiGrid>
      {!hypothesis.grounded ? (
        <p class="state-error-text" role="note">
          {t("rca.abstainedNotice")}
        </p>
      ) : null}
      <p>
        <strong>{t("rca.cause")}:</strong> {hypothesis.cause ?? t("rca.none")}
      </p>
      {hypothesis.reason ? (
        <p class="muted footnote">
          <strong>{t("rca.reason")}:</strong> {hypothesis.reason}
        </p>
      ) : null}
      <CausalChainSection hypothesis={hypothesis} />
      <CitationsTable hypothesis={hypothesis} />
    </section>
  );
}

function CausalChainSection({ hypothesis }: { readonly hypothesis: RcaHypothesis }) {
  const chain = hypothesis.causal_chain;
  if (chain === null) return null;
  return (
    <section class="rca-chain" aria-labelledby={`rca-chain-${hypothesis.seq}`}>
      <div class="section-header">
        <h4 id={`rca-chain-${hypothesis.seq}`} class="section-title">{t("rca.causalChain")}</h4>
        <span class="footnote">
          {t("rca.causalSummary", {
            hops: chain.hops.length,
            ambiguity: chain.ambiguity,
          })}
        </span>
      </div>
      <ol class="rca-chain-list">
        {chain.hops.map((hop, index) => (
          <li key={`${hop.cause_event_id}:${hop.effect_event_id}:${index}`}>
            <div class="rca-chain-edge">
              <span class="status-pill status-pill-info">{hop.relationship}</span>
              <span class="footnote">
                {t("rca.causalLead", { seconds: hop.lead_seconds.toFixed(1) })}
              </span>
              <span class="footnote">
                {t("rca.causalConfidence", { value: hop.confidence.toFixed(2) })}
              </span>
            </div>
            <div class="rca-chain-nodes">
              <span>
                <a href={architectureHref(hop.cause_resource_ref)}><strong>{hop.cause_resource_ref}</strong></a>
                <code>{hop.cause_event_id}</code>
              </span>
              <span aria-hidden="true">-&gt;</span>
              <span>
                <a href={architectureHref(hop.effect_resource_ref)}><strong>{hop.effect_resource_ref}</strong></a>
                <code>{hop.effect_event_id}</code>
              </span>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function CitationsTable({ hypothesis }: { readonly hypothesis: RcaHypothesis }) {
  const columns: readonly Column<RcaHypothesis["citations"][number]>[] = [
    {
      key: "kind",
      header: t("rca.citationKind"),
      render: (item) => <StatusPill kind="neutral" label={item.kind} />,
    },
    {
      key: "ref",
      header: t("rca.citationRef"),
      render: (item) => item.kind === "rule" ? (
        <a class="mono small" href={routeHref("rules", { params: { rule: item.ref } })}>
          {item.ref}
        </a>
      ) : <span class="mono small">{item.ref}</span>,
      cellClass: "mono",
    },
  ];
  return (
    <div class="stack">
      <h4 class="section-title">{t("rca.citations")}</h4>
      <DataTable
        columns={columns}
        rows={hypothesis.citations}
        keyOf={(item, index) => `${item.kind}:${item.ref}:${index}`}
        empty={t("rca.noCitations")}
      />
    </div>
  );
}

function verdictPill(verdict: string): PillKind {
  const value = verdict.toLowerCase();
  if (value === "auto") return "auto";
  if (value === "hil") return "hil";
  if (value === "deny") return "danger";
  if (value === "abstain") return "neutral";
  return "info";
}
