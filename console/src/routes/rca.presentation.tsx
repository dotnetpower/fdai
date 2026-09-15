import type { ComponentChildren } from "preact";
import {
  StatusPill,
  kpiEvidenceLabel,
  type PillKind,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { routeHref } from "../router";
import { formatConsoleCompactTimestamp } from "../time-format";
import type {
  RcaCitation,
  RcaHypothesis,
  RcaResponsePlan,
  RcaView,
} from "../types";
import { CausalChainSection } from "./rca-causal-chain";
import { rcaCauseDomainText, rcaText, rcaTierText } from "./rca.i18n";

export function RcaBody({ data }: { readonly data: RcaView }) {
  const recorded = hasRecordedRca(data);
  const primaryHypothesis = data.hypotheses[0] ?? null;
  const linkedResponse = linkedRcaResponse(data);
  usePublishViewContext(
    () => ({
      routeId: "rca",
      routeLabel: t("route.rca"),
      purpose: rcaText("viewPurpose"),
      glossary: composeGlossary([
        TERMS.correlationId,
        TERMS.tier,
        TERMS.gateDecision,
        TERMS.mode,
        TERMS.outcome,
      ]),
      headline: rcaText("viewHeadline", {
        count: data.hypotheses.length,
        correlation: data.correlation_id,
      }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "correlation_id", value: data.correlation_id, group: "rca" },
        { key: "hypothesis_count", value: data.hypotheses.length, group: "rca" },
        { key: "verdict", value: linkedResponse?.verdict ?? null, group: "rca" },
      ],
      records: {
        hypotheses: data.hypotheses.map((hypothesis) => ({ ...hypothesis })),
        response: linkedResponse ? [{ ...linkedResponse }] : [],
      },
    }),
    [data, linkedResponse],
  );

  return (
    <div class="rca-results">
      <div class="rca-context">
        <div class="rca-context-status">
          {primaryHypothesis ? (
            <>
              <StatusPill kind="info" label={rcaTierText(primaryHypothesis.tier)} />
              <StatusPill
                kind={primaryHypothesis.grounded ? "success" : "hil"}
                label={primaryHypothesis.grounded
                  ? rcaText("grounded")
                  : rcaText("abstained")}
              />
              <StatusPill kind={primaryHypothesis.mode} label={primaryHypothesis.mode} />
              <time dateTime={primaryHypothesis.recorded_at}>
                <span>{rcaText("recordedAt")}</span>
                {formatConsoleCompactTimestamp(primaryHypothesis.recorded_at)}
              </time>
            </>
          ) : null}
        </div>
        <nav class="rca-related-links" aria-label={rcaText("relatedViews")}>
          {recorded ? (
            <a href={routeHref("reports", {
              segments: ["incident-rca-dossier"],
              params: { correlation_id: data.correlation_id },
            })}>
              {rcaText("report")}
            </a>
          ) : null}
          <a href={routeHref("incidents", {
            params: { status: "all", correlation: data.correlation_id },
          })}>
            {rcaText("incident")}
          </a>
          <a href={routeHref("trace", { params: { correlation: data.correlation_id } })}>
            {rcaText("technicalActivity")}
          </a>
          <a href={routeHref("audit", { params: { correlation: data.correlation_id } })}>
            {rcaText("auditRecords")}
          </a>
        </nav>
      </div>
      {recorded ? (
        <section class="rca-result-section" aria-labelledby="rca-hypotheses-title">
          <header class="rca-section-heading">
            <h3 id="rca-hypotheses-title">{rcaText("hypotheses")}</h3>
            <span>{rcaText("hypothesisCount", { count: data.hypotheses.length })}</span>
          </header>
          <div class="rca-hypothesis-list">
            {data.hypotheses.map((hypothesis, index) => (
              <HypothesisCard
                key={hypothesis.seq}
                hypothesis={hypothesis}
                correlationId={data.correlation_id}
                response={linkedResponse}
                primary={index === 0}
              />
            ))}
          </div>
        </section>
      ) : (
        <section class="rca-unavailable-state" aria-labelledby="rca-unavailable-title">
          <h3 id="rca-unavailable-title">{rcaText("notRecordedTitle")}</h3>
          <p>{rcaText("notRecordedBody")}</p>
        </section>
      )}
    </div>
  );
}

export function hasRecordedRca(data: RcaView): boolean {
  return data.hypotheses.length > 0;
}

export function linkedRcaResponse(data: RcaView): RcaResponsePlan | null {
  const primaryHypothesis = data.hypotheses[0];
  const response = data.response;
  if (!primaryHypothesis?.grounded || response === null) return null;
  if (
    response.hypothesis_seq !== primaryHypothesis.seq
    || response.source_seq <= primaryHypothesis.seq
    || response.action_kind === "incident.members"
  ) {
    return null;
  }
  return response;
}

function HypothesisCard({
  hypothesis,
  correlationId,
  response,
  primary,
}: {
  readonly hypothesis: RcaHypothesis;
  readonly correlationId: string;
  readonly response: RcaResponsePlan | null;
  readonly primary: boolean;
}) {
  const titleId = `rca-hypothesis-${hypothesis.seq}`;
  const cause = hypothesis.cause
    ?? (hypothesis.grounded ? rcaText("none") : rcaText("abstainedCauseTitle"));
  return (
    <article class="rca-hypothesis-workspace" aria-labelledby={titleId}>
      <div class="rca-hypothesis-tier">
        <strong>
          {primary
            ? rcaText("primaryHypothesis")
            : rcaText("hypothesisLabel", { position: hypothesis.seq })}
        </strong>
        <StatusPill kind="info" label={rcaTierText(hypothesis.tier)} />
        <StatusPill kind="neutral" label={rcaCauseDomainText(hypothesis.cause_domain)} />
        <StatusPill
          kind={hypothesis.grounded ? "success" : "hil"}
          label={hypothesis.grounded ? rcaText("grounded") : rcaText("abstained")}
        />
      </div>
      <section class={`rca-hypothesis-hero ${hypothesis.grounded ? "is-grounded" : "is-abstained"}`}>
        <div class="rca-hypothesis-copy">
          <div class="rca-hypothesis-tags">
            <StatusPill kind="info" label={rcaTierText(hypothesis.tier)} />
            <StatusPill kind={hypothesis.mode} label={hypothesis.mode} />
          </div>
          <h4 id={titleId}>{cause}</h4>
          <p>{hypothesis.reason ?? rcaText("reasonUnavailable")}</p>
        </div>
        <ConfidenceIndicator hypothesis={hypothesis} />
      </section>
      <aside class={`rca-caveat${hypothesis.grounded ? "" : " is-abstained"}`} role="note">
        <strong>
          {hypothesis.grounded
            ? rcaText("hypothesisCaveatTitle")
            : rcaText("abstainedCauseTitle")}
        </strong>
        <span>
          {hypothesis.grounded
            ? rcaText("hypothesisCaveatBody")
            : rcaText("abstainedNotice")}
        </span>
      </aside>
      <CausalChainSection hypothesis={hypothesis} />
      <section class="rca-detail-section" aria-labelledby={`rca-evidence-${hypothesis.seq}`}>
        <header class="rca-section-heading">
          <h4 id={`rca-evidence-${hypothesis.seq}`}>{rcaText("evidenceAndResponse")}</h4>
          <span>{rcaText("citationCount", { count: hypothesis.citations.length })}</span>
        </header>
        <div class={`rca-evidence-grid${primary ? "" : " is-citations-only"}`}>
          <CitationsPanel hypothesis={hypothesis} correlationId={correlationId} />
          {primary ? <ResponsePlan response={response} correlationId={correlationId} /> : null}
        </div>
      </section>
    </article>
  );
}

function ConfidenceIndicator({ hypothesis }: { readonly hypothesis: RcaHypothesis }) {
  const confidence = hypothesis.confidence;
  const confidenceValue = confidence === null ? null : confidence.toFixed(2);
  const confidencePercent = confidence === null
    ? 0
    : Math.min(100, Math.max(0, confidence * 100));
  const accessibleLabel = confidenceValue === null
    ? rcaText("confidenceUnavailable")
    : rcaText("confidenceLabel", { value: confidenceValue });
  return (
    <div class={`rca-confidence${confidence === null ? " is-unavailable" : ""}`}>
      <div
        class="rca-confidence-ring"
        role="img"
        aria-label={accessibleLabel}
        style={`--rca-confidence: ${confidencePercent}%`}
      >
        <strong aria-hidden="true">
          {confidenceValue ?? kpiEvidenceLabel("not-measured")}
        </strong>
      </div>
      <span>{rcaText("confidence")}</span>
    </div>
  );
}

function CitationsPanel({
  hypothesis,
  correlationId,
}: {
  readonly hypothesis: RcaHypothesis;
  readonly correlationId: string;
}) {
  return (
    <section class="rca-panel" aria-label={rcaText("citations")}>
      <header>
        <h5>{rcaText("citations")}</h5>
        <span>
          {hypothesis.citations.length > 0
            ? rcaText("referencesResolved")
            : rcaText("citationCount", { count: 0 })}
        </span>
      </header>
      {hypothesis.citations.length > 0 ? (
        <ul class="rca-citation-list">
          {hypothesis.citations.map((citation, index) => {
            const destination = citationDestination(citation, correlationId);
            return (
              <li key={`${citation.kind}:${citation.ref}:${index}`}>
                <a href={destination.href}>
                  <span class="rca-citation-kind">{citation.kind}</span>
                  <strong class="mono">{citation.ref}</strong>
                  <span>{destination.label}</span>
                </a>
              </li>
            );
          })}
        </ul>
      ) : (
        <p class="rca-panel-empty">{rcaText("noCitations")}</p>
      )}
    </section>
  );
}

function ResponsePlan({
  response,
  correlationId,
}: {
  readonly response: RcaResponsePlan | null;
  readonly correlationId: string;
}) {
  const auditHref = routeHref("audit", { params: { correlation: correlationId } });
  const traceHref = routeHref("trace", { params: { correlation: correlationId } });
  return (
    <section class="rca-panel" aria-label={rcaText("response")}>
      <header>
        <h5>{rcaText("response")}</h5>
        <span>
          {response === null ? rcaText("responseUnavailable") : rcaText("responseRecorded")}
        </span>
      </header>
      {response === null ? (
        <p class="rca-panel-empty">{rcaText("noResponse")}</p>
      ) : (
        <div class="rca-response-facts">
          <ResponseFact href={traceHref} label={rcaText("verdict")}>
            <StatusPill kind={verdictPill(response.verdict)} label={response.verdict} />
          </ResponseFact>
          <ResponseFact
            href={traceHref}
            label={rcaText("decision")}
            evidenceState={response.decision === null ? "not-applicable" : "measured"}
          >
            {response.decision ?? kpiEvidenceLabel("not-applicable")}
          </ResponseFact>
          <ResponseFact
            href={auditHref}
            label={rcaText("action")}
            evidenceState={response.action_kind === null ? "not-applicable" : "measured"}
          >
            <span class="mono">{response.action_kind ?? kpiEvidenceLabel("not-applicable")}</span>
          </ResponseFact>
          <ResponseFact
            href={response.mode === null
              ? auditHref
              : routeHref("audit", { params: { correlation: correlationId, mode: response.mode } })}
            label={rcaText("modeColumn")}
            evidenceState={response.mode === null ? "not-applicable" : "measured"}
          >
            {response.mode === null
              ? kpiEvidenceLabel("not-applicable")
              : <StatusPill kind={response.mode} label={response.mode} />}
          </ResponseFact>
          <ResponseFact
            href={auditHref}
            label={rcaText("rollback")}
            evidenceState={response.rollback_reference === null ? "not-applicable" : "measured"}
          >
            <span class="mono">
              {response.rollback_reference ?? kpiEvidenceLabel("not-applicable")}
            </span>
          </ResponseFact>
        </div>
      )}
    </section>
  );
}

function ResponseFact({
  href,
  label,
  evidenceState = "measured",
  children,
}: {
  readonly href: string;
  readonly label: string;
  readonly evidenceState?: "measured" | "not-applicable";
  readonly children: ComponentChildren;
}) {
  return (
    <a class="rca-response-fact" data-evidence-state={evidenceState} href={href}>
      <span>{label}</span>
      <strong>{children}</strong>
    </a>
  );
}

function citationDestination(
  citation: RcaCitation,
  correlationId: string,
): { readonly href: string; readonly label: string } {
  const kind = citation.kind.toLowerCase();
  if (kind === "rule") {
    return {
      href: routeHref("rules", { params: { rule: citation.ref } }),
      label: rcaText("citationDestinationRule"),
    };
  }
  if (kind === "incident") {
    return {
      href: routeHref("incidents", { params: { status: "all", q: citation.ref } }),
      label: rcaText("citationDestinationIncident"),
    };
  }
  if (kind === "telemetry" || kind === "metric" || kind === "trace") {
    return {
      href: routeHref("trace", { params: { correlation: correlationId } }),
      label: rcaText("citationDestinationTrace"),
    };
  }
  return {
    href: routeHref("audit", { params: { correlation: correlationId } }),
    label: rcaText("citationDestinationAudit"),
  };
}

function verdictPill(verdict: string): PillKind {
  const value = verdict.toLowerCase();
  if (value === "auto") return "auto";
  if (value === "hil") return "hil";
  if (value === "deny") return "danger";
  if (value === "abstain") return "neutral";
  return "info";
}
