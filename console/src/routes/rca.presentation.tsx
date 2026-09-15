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
import { rcaText } from "./rca.i18n";

export function RcaBody({ data }: { readonly data: RcaView }) {
  const recorded = hasRecordedRca(data);
  const primaryHypothesis = data.hypotheses[0] ?? null;
  const linkedResponse = linkedRcaResponse(data);
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
              <StatusPill kind="info" label={t(`rca.tierName.${primaryHypothesis.tier}`)} />
              <StatusPill
                kind={primaryHypothesis.grounded ? "success" : "hil"}
                label={primaryHypothesis.grounded ? t("rca.grounded") : t("rca.abstained")}
              />
              <StatusPill kind={primaryHypothesis.mode} label={primaryHypothesis.mode} />
              <time dateTime={primaryHypothesis.recorded_at}>
                <span>{t("rca.recordedAt")}</span>
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
              {t("rca.report")}
            </a>
          ) : null}
          <a href={routeHref("incidents", {
            params: { status: "all", correlation: data.correlation_id },
          })}>
            {t("rca.incident")}
          </a>
          <a href={routeHref("trace", { params: { correlation: data.correlation_id } })}>
            {t("rca.technicalActivity")}
          </a>
          <a href={routeHref("audit", { params: { correlation: data.correlation_id } })}>
            {t("rca.auditRecords")}
          </a>
        </nav>
      </div>
      {recorded ? (
        <section class="rca-result-section" aria-labelledby="rca-hypotheses-title">
          <header class="rca-section-heading">
            <h3 id="rca-hypotheses-title">{t("rca.hypotheses")}</h3>
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
          <h3 id="rca-unavailable-title">{t("rca.notRecordedTitle")}</h3>
          <p>{t("rca.notRecordedBody")}</p>
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
  if (!primaryHypothesis?.grounded) return null;
  if (data.response?.action_kind === "incident.members") return null;
  return data.response;
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
    ?? (hypothesis.grounded ? t("rca.none") : rcaText("abstainedCauseTitle"));
  return (
    <article class="rca-hypothesis-workspace" aria-labelledby={titleId}>
      <div class="rca-hypothesis-tier">
        <strong>
          {primary
            ? rcaText("primaryHypothesis")
            : rcaText("hypothesisLabel", { position: hypothesis.seq })}
        </strong>
        <StatusPill kind="info" label={t(`rca.tierName.${hypothesis.tier}`)} />
        <StatusPill kind="neutral" label={t(`rca.causeDomain.${hypothesis.cause_domain}`)} />
        <StatusPill
          kind={hypothesis.grounded ? "success" : "hil"}
          label={hypothesis.grounded ? t("rca.grounded") : t("rca.abstained")}
        />
      </div>
      <section class={`rca-hypothesis-hero ${hypothesis.grounded ? "is-grounded" : "is-abstained"}`}>
        <div class="rca-hypothesis-copy">
          <div class="rca-hypothesis-tags">
            <StatusPill kind="info" label={t(`rca.tierName.${hypothesis.tier}`)} />
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
          {hypothesis.grounded ? rcaText("hypothesisCaveatBody") : t("rca.abstainedNotice")}
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
      <span>{t("rca.confidence")}</span>
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
    <section class="rca-panel" aria-label={t("rca.citations")}>
      <header>
        <h5>{t("rca.citations")}</h5>
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
        <p class="rca-panel-empty">{t("rca.noCitations")}</p>
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
    <section class="rca-panel" aria-label={t("rca.response")}>
      <header>
        <h5>{t("rca.response")}</h5>
        <span>
          {response === null ? rcaText("responseUnavailable") : rcaText("responseRecorded")}
        </span>
      </header>
      {response === null ? (
        <p class="rca-panel-empty">{t("rca.noResponse")}</p>
      ) : (
        <div class="rca-response-facts">
          <ResponseFact href={traceHref} label={t("rca.verdict")}>
            <StatusPill kind={verdictPill(response.verdict)} label={response.verdict} />
          </ResponseFact>
          <ResponseFact
            href={traceHref}
            label={t("rca.decision")}
            evidenceState={response.decision === null ? "not-applicable" : "measured"}
          >
            {response.decision ?? kpiEvidenceLabel("not-applicable")}
          </ResponseFact>
          <ResponseFact
            href={auditHref}
            label={t("rca.action")}
            evidenceState={response.action_kind === null ? "not-applicable" : "measured"}
          >
            <span class="mono">{response.action_kind ?? kpiEvidenceLabel("not-applicable")}</span>
          </ResponseFact>
          <ResponseFact
            href={response.mode === null
              ? auditHref
              : routeHref("audit", { params: { correlation: correlationId, mode: response.mode } })}
            label={t("rca.modeColumn")}
            evidenceState={response.mode === null ? "not-applicable" : "measured"}
          >
            {response.mode === null
              ? kpiEvidenceLabel("not-applicable")
              : <StatusPill kind={response.mode} label={response.mode} />}
          </ResponseFact>
          <ResponseFact
            href={auditHref}
            label={t("rca.rollback")}
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
