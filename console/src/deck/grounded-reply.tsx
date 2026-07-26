/**
 * GroundedReply - renders a deck (assistant) turn the way the source-streaming
 * mock does: the answer text types in token by token, then a "Grounded on N
 * sources" pill summarises the reply, and expanding it rolls the cited sources
 * through a slot-machine window (reusing the retrieval-trace slot styles).
 *
 * Honest-data only: every source card is a real ``Citation`` the backend
 * returned (a fact the answer is grounded in). The pill's summary line is the
 * real reply ``source`` descriptor (``llm:<model> · <ms> · <tokens>`` or
 * ``deterministic``). Nothing here is fabricated - it re-presents what the
 * reply already carries.
 *
 * Single responsibility: present one grounded deck reply. No I/O, no
 * privileged calls, only self-cancelling timers.
 */

import { useState } from "preact/hooks";
import { Tooltip } from "../components/tooltip";
import { useTransientFlag } from "../hooks/use-transient-flag";
import { t } from "../i18n";
import type {
  AnswerPlanMetadata,
  AnswerPlanningMetadata,
  AnswerVerification,
  DelegationMetadata,
  GroundedCodeArtifact,
  VerificationProgress,
} from "./backend";
import { RichContent } from "./rich-content";
import { relevantCitations, type Citation } from "./citations";
import {
  buildSources,
  citationMarks,
  groundingAgents,
  groundingStages,
  handoffReasonKey,
  parseReplySource,
  pillStats,
  type GroundedSource,
  type TraceStage,
} from "./grounded-sources";

export function GroundedReply({
  turnId,
  text,
  citations,
  source,
  streaming,
  verification,
  verificationProgress,
  answerPlan,
  answerPlanning,
  delegation,
  codeArtifacts,
  onRegenerate,
}: {
  readonly turnId: string;
  readonly text: string;
  readonly citations: readonly Citation[] | undefined;
  readonly source: string | undefined;
  /** True while the answer is still streaming tokens in from the backend. */
  readonly streaming: boolean;
  readonly verification: AnswerVerification | undefined;
  readonly verificationProgress: VerificationProgress | undefined;
  readonly answerPlan: AnswerPlanMetadata | undefined;
  readonly answerPlanning: AnswerPlanningMetadata | undefined;
  readonly delegation: DelegationMetadata | undefined;
  readonly codeArtifacts: readonly GroundedCodeArtifact[] | undefined;
  /** Re-run the operator question that produced this reply, if known. */
  readonly onRegenerate?: () => void;
}) {
  void turnId;
  const parsedSource = parseReplySource(source);
  const [open, setOpen] = useState(false);
  const [copied, showCopied] = useTransientFlag(1500);
  const cites = relevantCitations(citations ?? [], text);
  const evidenceReferences = cites.every((citation) =>
    citation.label.startsWith("evidence."));
  const sources = buildSources(verification, cites);
  const groundingIncomplete = verification?.evidence_manifest?.complete === false;
  const marks = citationMarks(sources);
  const replyModel = parsedSource?.kind === "llm"
    ? parsedSource.timing
      ? `${parsedSource.model} \u00b7 ${parsedSource.timing}`
      : parsedSource.model
    : null;
  const stages = groundingStages({
    sources,
    source,
    verification,
    agents: groundingAgents(delegation, answerPlanning),
    ...(delegation?.handoff_from
      ? {
          handoff: {
            from: delegation.handoff_from,
            to: delegation.primary_agent,
            ...(delegation.handoff_reason ? { reason: delegation.handoff_reason } : {}),
          },
        }
      : {}),
  });
  const boundedCorrection = verification?.status === "corrected" && (
    verification.reason_code === "screen_unsupported_sentences_removed" ||
    verification.reason_code === "concept_scope_claims_removed"
  );
  const verifiedAmbiguity = verification?.status === "verified" &&
    verification.reason_code === "ambiguous_incident";
  const recordedFailure = verification?.status === "verified" &&
    verification.reason_code === "recorded_failure_reason";
  const showProcessingDisclosure = !streaming && (
    parsedSource?.kind === "llm" || parsedSource?.kind === "deterministic"
  );
  const successfulPlanningAgents = answerPlanning?.contributions.map((item) => item.agent) ?? [];

  const copy = () => {
    void navigator.clipboard?.writeText(text).then(
      () => {
        showCopied();
      },
      () => {
        /* clipboard denied - leave the label unchanged */
      },
    );
  };

  return (
    <div class="deck-gr">
      {answerPlan ? (
        <Tooltip content={t(`deck.answerPlan.format.${answerPlan.format}`)}>
          <div class="deck-answer-plan">
            <span>{delegation?.primary_agent ?? "Bragi"}</span>
            <span aria-hidden="true">·</span>
            <span>{t(`deck.answerPlan.intent.${answerPlan.intent}`)}</span>
            <span aria-hidden="true">·</span>
            <span>{t(`deck.answerPlan.detail.${answerPlan.detail_level}`)}</span>
            {answerPlan.preference_applied ? (
              <>
                <span aria-hidden="true">·</span>
                <span>{t("deck.answerPlan.preferenceApplied")}</span>
              </>
            ) : null}
          </div>
        </Tooltip>
      ) : null}
      {answerPlanning && successfulPlanningAgents.length > 0 ? (
        <div class="deck-answer-plan">
          <span>
            {t("deck.answerPlanning.consulted")}: {successfulPlanningAgents.join(", ")}
          </span>
          <span aria-hidden="true">·</span>
          <span>
            {t("deck.answerPlanning.uniqueSources", {
              count: answerPlanning.unique_evidence_count,
            })}
          </span>
          {answerPlanning.conflicting_evidence_refs.length > 0 ? (
            <>
              <span aria-hidden="true">·</span>
              <span>
                {t("deck.answerPlanning.unresolvedConflicts", {
                  count: answerPlanning.conflicting_evidence_refs.length,
                })}
              </span>
            </>
          ) : null}
        </div>
      ) : null}
      <div class="deck-turn-body">
        <RichContent
          text={text}
          streaming={streaming}
          suppressCode={!streaming && (codeArtifacts?.length ?? 0) > 0}
          citeMarks={marks}
        />
      </div>

      {!streaming && codeArtifacts && codeArtifacts.length > 0 ? (
        <CodeEvidence artifacts={codeArtifacts} />
      ) : null}

      {verificationProgress && !verification ? (
        <div class="deck-verification is-active" role="status" aria-live="polite">
          <span class="deck-verification-spinner" aria-hidden="true" />
          <span>{verificationProgress.label}</span>
          {verificationProgress.total !== null && verificationProgress.completed !== null ? (
            <span class="muted">
              {verificationProgress.completed}/{verificationProgress.total}
            </span>
          ) : null}
        </div>
      ) : null}

      {showProcessingDisclosure ? (
        <section
          class="deck-llm-escalation"
          aria-label={t(
            parsedSource.kind === "llm"
              ? "deck.grounded.llmEscalation"
              : "deck.grounded.deterministicPath",
          )}
        >
          <header class="deck-llm-escalation-head">
            <span class="deck-llm-escalation-label">
              {t(
                parsedSource.kind === "llm"
                  ? "deck.grounded.llmEscalation"
                  : "deck.grounded.deterministicPath",
              )}
            </span>
            <strong class="deck-llm-escalation-model">
              {parsedSource.kind === "llm"
                ? parsedSource.model
                : t("deck.grounded.deterministicAnswerer")}
            </strong>
            {parsedSource.kind === "llm" && parsedSource.timing ? (
              <span class="deck-llm-escalation-timing">
                {t("deck.grounded.processingTime", { timing: parsedSource.timing })}
              </span>
            ) : null}
          </header>
          <p class="deck-llm-escalation-summary">
            {parsedSource.kind === "llm"
              ? t(
                  sources.length > 0
                    ? "deck.grounded.llmGroundedSummary"
                    : "deck.grounded.llmContextSummary",
                  { model: parsedSource.model },
                )
              : t(
                  parsedSource.reason
                    ? "deck.grounded.deterministicReasonSummary"
                    : "deck.grounded.deterministicSummary",
                  { reason: parsedSource.reason ?? "" },
                )}
          </p>
          <GroundingTrace stages={stages} />
        </section>
      ) : null}

      {!streaming && (verification || text.trim().length > 0 || cites.length > 0) ? (
        <div class="deck-gr-actions">
          {verification ? (
            <Tooltip content={verificationLabel(verification)}>
              <div
                class={`deck-verification is-${verifiedAmbiguity || recordedFailure ? "consistent" : boundedCorrection ? "verified" : verification.status}`}
                role="status"
                aria-label={verificationLabel(verification)}
              >
                <span class="deck-verification-mark" aria-hidden="true">
                  {!verifiedAmbiguity && !recordedFailure && (verification.status === "verified" ||
                  verification.status === "consistent" ||
                  boundedCorrection)
                    ? "\u2713"
                    : verifiedAmbiguity || recordedFailure
                      ? "!"
                      : verification.status === "corrected"
                      ? "\u21bb"
                      : "!"}
                </span>
                <span class="deck-verification-short">
                  {shortVerificationStatus(verification, boundedCorrection)}
                </span>
              </div>
            </Tooltip>
          ) : null}

          {text.trim().length > 0 ? (
            <>
              <Tooltip content={copied ? t("deck.tooltip.copied") : t("deck.tooltip.copyReply")}>
                <button
                  type="button"
                  class="deck-gr-tool deck-gr-icon"
                  onClick={copy}
                  aria-label={t("deck.tooltip.copyReply")}
                >
                  {copied ? <IconCheck /> : <IconCopy />}
                </button>
              </Tooltip>
              {onRegenerate ? (
                <Tooltip content={t("deck.tooltip.regenerateHint")}>
                  <button
                    type="button"
                    class="deck-gr-tool deck-gr-icon"
                    onClick={onRegenerate}
                    aria-label={t("deck.tooltip.regenerate")}
                  >
                    <IconRegenerate />
                  </button>
                </Tooltip>
              ) : null}
            </>
          ) : null}

          {sources.length > 0 ? (
            <Tooltip
              content={
                evidenceReferences
                  ? t("deck.tooltip.evidenceReferences", { count: sources.length })
                  : t("deck.tooltip.groundedSources", { count: sources.length })
              }
            >
              <button
                type="button"
                class="deck-gr-pill"
                onClick={() => setOpen((v) => !v)}
                aria-expanded={open}
              >
                <span class="deck-gr-check" aria-hidden="true">
                  {groundingIncomplete ? "!" : "\u2713"}
                </span>
                {pillStats({
                  sourceCount: sources.length,
                  checksCompleted: verification?.checks_completed ?? 0,
                  checksTotal: verification?.checks_total ?? 0,
                  agentCount: answerPlanning?.consulted_agents.length ?? 0,
                }).map((stat, i) => (
                  <span key={`${stat.label}-${i}`} class="deck-gr-stat">
                    <strong>{stat.value}</strong> {stat.label}
                  </span>
                ))}
                {replyModel ? <span class="deck-gr-stat is-model">{replyModel}</span> : null}
                {groundingIncomplete ? (
                  <span class="deck-gr-stat">{t("deck.grounded.partialEvidence")}</span>
                ) : null}
                <span class="deck-gr-more">
                  {open ? t("deck.grounded.hideSources") : t("deck.grounded.showSources")}
                </span>
              </button>
            </Tooltip>
          ) : null}
        </div>
      ) : null}

      {!streaming && open && sources.length > 0 ? (
        <div class="deck-gr-panel">
          <SourceDetail sources={sources} />
        </div>
      ) : null}
    </div>
  );
}

/** Short one-word status for the compact verification chip; the full sentence
 *  stays available on hover (title). */
function shortVerificationStatus(
  verification: AnswerVerification,
  boundedCorrection: boolean,
): string {
  if (verification.reason_code === "ambiguous_incident") {
    return t("deck.grounded.verificationStatus.needsSelection");
  }
  if (verification.reason_code === "recorded_failure_reason") {
    return t("deck.grounded.verificationStatus.recordedFailure");
  }
  if (boundedCorrection) return t("deck.grounded.verificationStatus.verified");
  switch (verification.status) {
    case "verified":
      return t("deck.grounded.verificationStatus.verified");
    case "consistent":
      return t("deck.grounded.verificationStatus.consistent");
    case "corrected":
      return t("deck.grounded.verificationStatus.corrected");
    case "unverified":
      return t("deck.grounded.verificationStatus.unverified");
  }
}

/** The reconstructed retrieval trace: how this reply was grounded, shown when
 *  the operator expands the grounded pill. Mirrors the source-streaming mock's
 *  "show trace" affordance (mocks/ui/deck-sources.html). */
function GroundingTrace({ stages }: { readonly stages: readonly TraceStage[] }) {
  if (stages.length === 0) return null;
  return (
    <ol class="deck-gr-trace" aria-label={t("deck.grounded.traceLabel")}>
      {stages.map((stage, i) => (
        <li key={`${stage.label}-${i}`} class={`deck-gr-trace-row is-${stage.status}`}>
          <span class="deck-gr-trace-mark" aria-hidden="true">
            {stage.status === "attention" ? "!" : "\u2713"}
          </span>
          <span class="deck-gr-trace-copy">
            <span class="deck-gr-trace-label">
              {t(`deck.grounded.stage.${stage.action}`, {
                model: stage.model ?? "",
                from: stage.from ?? "",
                to: stage.to ?? "",
              })}
            </span>
            <span class="deck-gr-trace-detail">
              {stage.reasonCode
                ? t(handoffReasonKey(stage.reasonCode))
                : stage.detailKey
                  ? t(stage.detailKey, stage.detailParams)
                  : stage.detail}
            </span>
          </span>
          <span class={`deck-gr-trace-side is-${stage.side}`}>
            {t(`deck.grounded.side.${stage.side}`)}
          </span>
        </li>
      ))}
    </ol>
  );
}

/** Expanded "show sources" cards. Each grounding source renders as a typed card
 *  with a coloured category badge, a bold title, and its cited value - the
 *  clean presentation from the source-streaming mock. Every card is a real
 *  evidence entry or citation the backend returned; nothing is fabricated. */
function SourceDetail({ sources }: { readonly sources: readonly GroundedSource[] }) {
  return (
    <ul class="deck-gr-list">
      {sources.map((source) => (
        <li key={`${source.n}-${source.title}`} class="deck-src-row">
          <span class={`deck-src-badge is-${source.tone}`} aria-hidden="true">
            {source.badge}
          </span>
          <span class="deck-src-num" aria-hidden="true">{source.n}</span>
          <span class="deck-src-text">
            <span class="deck-src-title">{source.title}</span>
            {source.meta ? <span class="deck-src-meta">{source.meta}</span> : null}
            {source.path ? <span class="deck-src-path muted">{source.path}</span> : null}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Inline monochrome icons (currentColor) for the reply tool row. */
function IconCopy() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
      <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" />
      <path d="M10.5 5.5V4A1.5 1.5 0 0 0 9 2.5H4A1.5 1.5 0 0 0 2.5 4v5A1.5 1.5 0 0 0 4 10.5h1.5" />
    </svg>
  );
}

function IconCheck() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
      <path d="M3 8.5 6.5 12 13 4.5" />
    </svg>
  );
}

function IconRegenerate() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
      <path d="M13 8a5 5 0 1 1-1.46-3.54" />
      <path d="M13 2.5V5h-2.5" />
    </svg>
  );
}

function CodeEvidence({ artifacts }: { readonly artifacts: readonly GroundedCodeArtifact[] }) {
  return (
    <details class="deck-code-evidence">
      <summary>
        <span>{t("deck.codeEvidence.label")}</span>
        <span class="muted">{t("deck.codeEvidence.count", { count: artifacts.length })}</span>
      </summary>
      <div class="deck-code-evidence-list">
        {artifacts.map((artifact, index) => (
          <section key={artifact.artifact_ref} class="deck-code-evidence-item">
            <header class="deck-code-evidence-head">
              <span class="deck-code-lang">{artifact.language}</span>
              <span class={`deck-code-validation is-${artifact.validation_status}`}>
                {t(`deck.codeEvidence.status.${artifact.validation_status}`)}
              </span>
              <span class="muted">#{index + 1}</span>
            </header>
            <RichContent
              text={`\`\`\`${artifact.language}\n${artifact.content}\`\`\``}
            />
            <footer class="deck-code-evidence-foot">
              <code>{artifact.artifact_ref}</code>
              {artifact.validation_detail ? <span>{artifact.validation_detail}</span> : null}
            </footer>
          </section>
        ))}
      </div>
    </details>
  );
}

export function verificationLabel(verification: AnswerVerification): string {
  const claims = verification.claims ?? [];
  const supportedClaims = claims.filter((claim) => claim.status === "supported").length;
  const claimSummary = claims.length > 0
    ? t("deck.grounded.verificationLabel.claimSummary", {
        supported: supportedClaims,
        total: claims.length,
      })
    : "";
  const supportedSummary = supportedClaims > 0
    ? t("deck.grounded.verificationLabel.supportedSummary", { supported: supportedClaims })
    : "";
  if (verification.reason_code === "ambiguous_incident") {
    return t("deck.grounded.verificationLabel.ambiguousIncident");
  }
  if (verification.reason_code === "recorded_failure_reason") {
    return t("deck.grounded.verificationLabel.recordedFailure");
  }
  switch (verification.status) {
    case "verified":
      return t("deck.grounded.verificationLabel.verified", {
        references: verification.evidence_refs.length,
        claims: claimSummary,
      });
    case "corrected":
      if (
        verification.reason_code === "screen_unsupported_sentences_removed" ||
        verification.reason_code === "concept_scope_claims_removed"
      ) {
        return t("deck.grounded.verificationLabel.correctedBounded", {
          claims: supportedSummary,
        });
      }
      return t("deck.grounded.verificationLabel.corrected", { claims: claimSummary });
    case "consistent":
      const evidenceScope = verification.authority === "client_snapshot"
        ? t("deck.grounded.verificationLabel.scope.currentScreen")
        : verification.authority === "server_read_model"
          ? t("deck.grounded.verificationLabel.scope.serverEvidence")
          : t("deck.grounded.verificationLabel.scope.groundedEvidence");
      return claims.length > 0
        ? t("deck.grounded.verificationLabel.consistent", {
            scope: evidenceScope,
            claims: claimSummary,
          })
        : t("deck.grounded.verificationLabel.consistentNoClaims", { scope: evidenceScope });
    case "unverified":
      return t("deck.grounded.verificationLabel.unverified", { claims: claimSummary });
  }
}
