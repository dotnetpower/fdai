/**
 * GroundedReply - renders a deck (assistant) turn on the shared conversation
 * layer (ui/calm-slate-deck-conversation.css): the answer text types in token
 * by token, then one action row carries the verification verdict, the sources
 * pill, and the reply tools, and the pill opens the cited sources in place.
 *
 * Honest-data only: every source row is a real ``Citation`` or evidence entry
 * the backend returned (a fact the answer is grounded in). The processing
 * disclosure names the real reply ``source`` descriptor
 * (``llm:<model> · <ms> · <tokens>`` or ``deterministic``). Nothing here is
 * fabricated - it re-presents what the reply already carries.
 *
 * Single responsibility: present one grounded deck reply. No I/O, no
 * privileged calls, only self-cancelling timers.
 */

import { Fragment } from "preact";
import { lazy, Suspense } from "preact/compat";
import { useEffect, useRef, useState } from "preact/hooks";
import { Tooltip } from "../components/tooltip";
import type { AdaptiveAnswer } from "./adaptive-answer";
import { AdaptiveAnswerSources } from "./adaptive-answer-sources";
import { answerEvidenceText } from "./answer-evidence-i18n";
import { useTransientFlag } from "../hooks/use-transient-flag";
import { getLocale, t, tForLocale } from "../i18n";
import { routeHref } from "../router";
import { getDeckUser } from "./deck-user";
import type {
  ActionDraft,
  AnswerPlanningMetadata,
  ConfirmedAnswerSegment,
  ConversationDocumentArtifact,
  AnswerVerification,
  DelegationMetadata,
  GroundedCodeArtifact,
  IncidentCandidate,
  PresentationArtifact,
  SemanticProjectionReceipt,
  VerificationProgress,
} from "./backend";
import {
  actionConfirmationCanRetry,
  confirmActionDraft,
  renderActionResult,
} from "./backend";
import { presentationArtifactSupersedesText } from "./presentation-artifact";
import { RichContent } from "./rich-content";
import { openDeckWithContext, type DeckOpenDetail } from "./open-deck";
import { relevantCitations, type Citation } from "./citations";
import type { ConversationTrajectory } from "./conversation-trajectory";
import {
  secondaryEvidencePostureIssueKind,
  verificationAttentionKind,
  verificationIssueDetailLabel,
  unverifiedDetailLabel,
  verificationIssueKind,
  verificationPrimaryLabel,
} from "./verification-presentation";
import {
  buildSources,
  citationMarks,
  groundingAttentionIssueKind,
  groundingAgents,
  groundingStages,
  handoffReasonKey,
  parseReplySource,
  type GroundedSource,
  type TraceStage,
} from "./grounded-sources";

const DocumentArtifactView = lazy(async () => ({
  default: (await import("./document-artifact-view")).DocumentArtifactView,
}));
const StructuredReply = lazy(async () => ({
  default: (await import("./structured-reply")).StructuredReply,
}));

export function GroundedReply({
  turnId,
  text,
  citations,
  source,
  streaming,
  verification,
  semanticReceipt,
  adaptiveAnswer,
  confirmed,
  verificationProgress,
  answerPlanning,
  delegation,
  codeArtifacts,
  incidentCandidates,
  actionDraft,
  presentationArtifact,
  documentArtifact,
  onRegenerate,
}: {
  readonly turnId: string;
  readonly text: string;
  readonly citations: readonly Citation[] | undefined;
  readonly source: string | undefined;
  /** True while the answer is still streaming tokens in from the backend. */
  readonly streaming: boolean;
  readonly verification: AnswerVerification | undefined;
  readonly semanticReceipt: SemanticProjectionReceipt | undefined;
  readonly adaptiveAnswer?: AdaptiveAnswer;
  readonly confirmed: ConfirmedAnswerSegment | undefined;
  readonly verificationProgress: VerificationProgress | undefined;
  readonly answerPlanning: AnswerPlanningMetadata | undefined;
  readonly delegation: DelegationMetadata | undefined;
  readonly codeArtifacts: readonly GroundedCodeArtifact[] | undefined;
  readonly incidentCandidates: readonly IncidentCandidate[] | undefined;
  readonly actionDraft: ActionDraft | undefined;
  readonly presentationArtifact: PresentationArtifact | undefined;
  readonly documentArtifact: ConversationDocumentArtifact | undefined;
  readonly trajectory: ConversationTrajectory | undefined;
  /** Re-run the operator question that produced this reply, if known. */
  readonly onRegenerate?: () => void;
}) {
  const parsedSource = parseReplySource(source);
  const deckUser = getDeckUser();
  const draftAccount = deckUser?.username ?? deckUser?.name ?? deckUser?.accountId ?? null;
  const [open, setOpen] = useState(false);
  const [selectedSource, setSelectedSource] = useState<{ number: number } | null>(null);
  const replyRef = useRef<HTMLDivElement>(null);
  const sourceReturn = useRef<{ trigger: HTMLElement; container: HTMLElement | null; top: number; wasOpen: boolean } | null>(null);
  const sourcePanelId = `${turnId}-sources`;
  const [copied, showCopied] = useTransientFlag(1500);
  const [draftState, setDraftState] = useState<"idle" | "submitting" | "done" | "cancelled">("idle");
  const [draftResult, setDraftResult] = useState<string | null>(null);
  const primaryText = primaryAnswerText(text, verification, semanticReceipt);
  const cites = relevantCitations(citations ?? [], primaryText);
  const renderedText = incidentCandidates && incidentCandidates.length > 0
    ? incidentCandidateAnswerLead(primaryText)
    : primaryText;
  const sources = buildSources(verification, cites);
  const evidenceReferences = hasEvidenceReferenceCitations(cites);
  const groundingIssue = groundingAttentionIssueKind(verification, semanticReceipt);
  const groundingIncomplete = groundingIssue === "partialEvidence";
  const groundingAttention = groundingIssue !== null || verification?.status === "unverified";
  const marks = citationMarks(sources);
  const verificationIssue = verification
    ? verificationAttentionKind(verification, semanticReceipt)
    : null;
  const renderedVerificationLabel = verification
    ? verificationLabel(verification, semanticReceipt)
    : null;
  const groundingStatusLabel = groundingIssue
    ? t(`deck.grounded.verificationStatus.${groundingIssue}`)
    : null;
  const secondaryGroundingIssue = secondaryEvidencePostureIssueKind(semanticReceipt);
  const stages = groundingStages({
    sources,
    source,
    verification,
    ...(semanticReceipt ? { semanticReceipt } : {}),
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
  const structuredPresentation = !streaming && !verificationIssue && presentationArtifact
    && presentationArtifactSupersedesText(presentationArtifact)
    ? presentationArtifact
    : null;
  const showProcessingDisclosure = !streaming && (
    parsedSource?.kind === "llm" || parsedSource?.kind === "deterministic"
  );
  const successfulPlanningAgents = answerPlanning?.contributions.map((item) => item.agent) ?? [];
  // A settled answer that needs no qualifier shows no state chip; its verdict sits in the action row.
  const answerState = source?.startsWith("partial")
    ? "partial"
    : streaming
    ? confirmed
      ? "confirmed"
      : "draft"
    : verification?.status === "corrected"
    ? "corrected"
    : "complete";
  const showAnswerState = answerState !== "complete";
  const sourceCountLabel = evidenceReferences
    ? t("deck.tooltip.evidenceReferences", { count: sources.length })
    : t("deck.tooltip.groundedSources", { count: sources.length });
  // The verification chip already states this status, so the sources pill omits it visibly.
  const verificationStatusText = verification
    ? shortVerificationStatus(verification, semanticReceipt, boundedCorrection)
    : null;
  const sourceButtonLabel = sourceButtonAccessibleLabel(sourceCountLabel, [
    groundingStatusLabel,
    secondaryGroundingIssue
      ? t(`deck.grounded.verificationStatus.${secondaryGroundingIssue}`)
      : null,
  ]);

  useEffect(() => {
    if (!open || selectedSource === null) return;
    const row = document.getElementById(`${sourcePanelId}-${selectedSource.number}`);
    const details = row?.querySelector("details");
    if (details) details.open = true;
    row?.querySelector("summary")?.focus({ preventScroll: true });
    row?.scrollIntoView({ block: "nearest" });
  }, [open, selectedSource, sourcePanelId]);

  const selectCitation = (number: number, trigger: HTMLElement) => {
    if (!sources.some((item) => item.n === number)) return;
    const container = replyRef.current?.closest<HTMLElement>(".deck-transcript") ?? null;
    sourceReturn.current = { trigger, container, top: container?.scrollTop ?? 0, wasOpen: open };
    setSelectedSource({ number });
    setOpen(true);
  };
  const returnToAnswer = () => {
    const origin = sourceReturn.current;
    setSelectedSource(null);
    if (!origin?.wasOpen) setOpen(false);
    requestAnimationFrame(() => {
      if (origin?.trigger.isConnected) {
        if (origin.container) origin.container.scrollTop = origin.top;
        origin.trigger.focus({ preventScroll: true });
      } else {
        replyRef.current?.querySelector<HTMLElement>(".deck-turn-body")?.focus();
      }
    });
    sourceReturn.current = null;
  };

  const copy = () => {
    void navigator.clipboard?.writeText(renderedText).then(
      () => {
        showCopied();
      },
      () => {
        /* clipboard denied - leave the label unchanged */
      },
    );
  };
  const confirmDraft = async () => {
    if (!actionDraft || draftState !== "idle") return;
    setDraftState("submitting");
    const result = await confirmActionDraft(actionDraft);
    setDraftResult(renderActionResult(result));
    setDraftState(actionConfirmationCanRetry(result) ? "idle" : "done");
  };

  return (
    <div class="deck-gr" ref={replyRef} data-sources-open={open ? "true" : "false"}>
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
      {!streaming && verification ? (
        <div class="deck-answer-posture" data-issue={verificationIssue ?? "none"} role="status">
          <strong>{verificationStatusText}</strong>
          {claimDetail(verification) ? <span>{claimDetail(verification)}</span> : null}
          <span class="deck-answer-posture-note">
            {verificationLabel(verification, semanticReceipt, { includeClaims: false })}
          </span>
        </div>
      ) : null}
      <div class="deck-turn-body cs-deck-answer" tabIndex={-1}>
        {showAnswerState ? (
          <span class={`cs-deck-answer-state is-${answerState}`} role="status">
            {t(`deck.answerState.${answerState}`)}
          </span>
        ) : null}
        {structuredPresentation ? (
          <>
            {renderedText.trim() ? (
              <div class="deck-presentation-lead">
                <RichContent
                  text={renderedText}
                  suppressCode={(codeArtifacts?.length ?? 0) > 0}
                  citeMarks={marks}
                  onCitationSelect={selectCitation}
                />
              </div>
            ) : null}
            <Suspense fallback={null}>
              <StructuredReply artifact={structuredPresentation} />
            </Suspense>
          </>
        ) : (
          <RichContent
            text={renderedText}
            streaming={streaming}
            suppressCode={!streaming && (codeArtifacts?.length ?? 0) > 0}
            citeMarks={marks}
            onCitationSelect={selectCitation}
          />
        )}
        {!streaming && renderedText.trim() ? (
          <OriginalMarkdown renderedText={renderedText} />
        ) : null}
      </div>

      {!streaming && adaptiveAnswer ? (
        <section aria-label={t("deck.adaptive.explanation")}>
          {adaptiveAnswer.answer !== text ? (
            <>
              <h4>{t("deck.adaptive.explanation")}</h4>
              <RichContent text={adaptiveAnswer.answer} />
            </>
          ) : null}
          <AdaptiveAnswerSources answer={adaptiveAnswer} />
        </section>
      ) : null}

      {!streaming && documentArtifact ? (
        <Suspense fallback={null}>
          <DocumentArtifactView artifact={documentArtifact} />
        </Suspense>
      ) : null}

      {actionDraft ? (
        <section class="deck-action-draft cs-deck-request is-proposal" aria-labelledby={`${turnId}-action-draft-title`}>
          <header class="cs-deck-request-head">
            <strong class="cs-deck-request-title" id={`${turnId}-action-draft-title`}>
              {t("deck.actionDraft.title")}
            </strong>
          </header>
          <dl class="cs-deck-request-fields">
            {draftAccount ? (
              <div>
                <dt>{t("deck.actionDraft.account")}</dt>
                <dd>{draftAccount}</dd>
              </div>
            ) : null}
            <div>
              <dt>{t("deck.actionDraft.action")}</dt>
              <dd>{actionDraft.actionType}</dd>
            </div>
            <div>
              <dt>{t("deck.actionDraft.arguments")}</dt>
              <dd><code>{JSON.stringify(actionDraft.arguments)}</code></dd>
            </div>
          </dl>
          <p class="cs-deck-request-note">{t("deck.actionDraft.authorityNote")}</p>
          {draftResult ? <p class="cs-deck-request-note" role="status">{draftResult}</p> : null}
          {draftState === "cancelled" ? (
            <p class="cs-deck-request-note" role="status">{t("deck.actionDraft.cancelled")}</p>
          ) : draftState === "idle" || draftState === "submitting" ? (
            <div class="deck-action-draft-actions cs-deck-request-actions">
              <button
                type="button"
                class="cs-deck-affordance"
                disabled={draftState === "submitting"}
                onClick={() => void confirmDraft()}
              >
                {draftState === "submitting"
                  ? t("deck.actionDraft.submitting")
                  : t("deck.actionDraft.confirm")}
              </button>
              <button
                type="button"
                class="cs-deck-affordance"
                disabled={draftState === "submitting"}
                onClick={() => setDraftState("cancelled")}
              >
                {t("deck.actionDraft.cancel")}
              </button>
            </div>
          ) : null}
        </section>
      ) : null}

      {!streaming && codeArtifacts && codeArtifacts.length > 0 ? (
        <CodeEvidence artifacts={codeArtifacts} />
      ) : null}

      {!streaming && incidentCandidates && incidentCandidates.length > 0 ? (
        <IncidentCandidatePicker candidates={incidentCandidates} />
      ) : null}

      {verificationProgress && !verification ? (
        <div class="cs-deck-action-row" role="status" aria-live="polite">
          <span class="cs-deck-verification is-pending">
            <span class="cs-grounding-spinner" aria-hidden="true" />
            <span>{verificationProgress.label}</span>
            {verificationProgress.total !== null && verificationProgress.completed !== null ? (
              <span class="cs-deck-verification-detail">
                {verificationProgress.completed}/{verificationProgress.total}
              </span>
            ) : null}
          </span>
        </div>
      ) : null}

      {showProcessingDisclosure ? (
        <details
          class="deck-llm-escalation cs-deck-disclosure"
          aria-label={t(
            parsedSource.kind === "llm"
              ? "deck.grounded.llmEscalation"
              : "deck.grounded.deterministicPath",
          )}
        >
          <summary class="cs-deck-disclosure-summary">
            <span class="cs-deck-disclosure-title">
              {t(
                parsedSource.kind === "llm"
                  ? "deck.grounded.llmEscalation"
                  : "deck.grounded.deterministicPath",
              )}
            </span>
            <span class="cs-deck-disclosure-meta">
              {parsedSource.kind === "llm"
                ? parsedSource.model
                : t("deck.grounded.deterministicAnswerer")}
            </span>
            {parsedSource.kind === "llm" && parsedSource.timing ? (
              <span class="cs-deck-disclosure-meta">
                {t("deck.grounded.processingTime", { timing: parsedSource.timing })}
              </span>
            ) : null}
            <span class="cs-run-chevron" aria-hidden="true" />
          </summary>
          <div class="cs-deck-disclosure-body">
            <p>
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
          </div>
        </details>
      ) : null}

      {!streaming && (verification || text.trim().length > 0 || cites.length > 0) ? (
        <div class="deck-gr-actions cs-deck-action-row">
          {verification ? (
            <Tooltip content={renderedVerificationLabel ?? ""}>
              <div
                class={`cs-deck-verification is-${verificationTone(verification, verificationIssue, {
                  boundedCorrection,
                  pendingSelection: verifiedAmbiguity || recordedFailure,
                })}`}
                role="status"
                aria-label={renderedVerificationLabel ?? ""}
              >
                <span class="cs-deck-verification-mark" aria-hidden="true">
                  {verificationIssue || verifiedAmbiguity || recordedFailure
                    ? "!"
                    : verification.status === "verified" ||
                        verification.status === "consistent" ||
                        boundedCorrection
                      ? "\u2713"
                      : verification.status === "corrected"
                        ? "\u21bb"
                        : "!"}
                </span>
                <span>{verificationStatusText}</span>
                {claimDetail(verification) ? (
                  <span class="cs-deck-verification-detail">{claimDetail(verification)}</span>
                ) : null}
              </div>
            </Tooltip>
          ) : null}

          {sources.length > 0 ? (
            <Tooltip placement="top-end" content={sourceButtonLabel}>
              <button
                type="button"
                class="deck-gr-pill cs-deck-pill"
                onClick={() => setOpen((v) => !v)}
                aria-expanded={open}
                aria-controls={sourcePanelId}
                aria-label={sourceButtonLabel}
              >
                {groundingAttention ? (
                  <span class="cs-deck-pill-mark" aria-hidden="true">!</span>
                ) : null}
                <span class="cs-deck-pill-stat">
                  <strong>{sources.length}</strong>{" "}
                  {sources.length === 1
                    ? t("deck.grounded.source")
                    : t("deck.grounded.sources")}
                </span>
                {pillIssues(groundingIncomplete, groundingStatusLabel, secondaryGroundingIssue)
                  .filter((issue) => issue !== verificationStatusText)
                  .map((issue) => (
                  <Fragment key={issue}>
                    <span aria-hidden="true">{"\u00b7"}</span>
                    <span class="cs-deck-pill-issue">{issue}</span>
                  </Fragment>
                ))}
                <span class="cs-deck-pill-more" aria-hidden="true"><IconChevron /></span>
              </button>
            </Tooltip>
          ) : null}

          {text.trim().length > 0 ? (
            <span class="cs-deck-tools">
              <Tooltip content={copied ? t("deck.tooltip.copied") : t("deck.tooltip.copyReply")}>
                <button
                  type="button"
                  class={`deck-gr-tool cs-deck-tool cs-deck-tool-icon${copied ? " is-done" : ""}`}
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
                    class="deck-gr-tool cs-deck-tool cs-deck-tool-icon"
                    onClick={onRegenerate}
                    aria-label={t("deck.tooltip.regenerate")}
                  >
                    <IconRegenerate />
                  </button>
                </Tooltip>
              ) : null}
              <Tooltip content={t("deck.reviewAnswer")}>
                <a
                  class="deck-gr-review cs-deck-tool cs-deck-tool-icon cs-deck-tool-link"
                  href={assuranceHref(turnId)}
                  aria-label={t("deck.reviewAnswer")}
                >
                  <IconReview />
                </a>
              </Tooltip>
            </span>
          ) : null}
        </div>
      ) : null}

      {!streaming && open && sources.length > 0 ? (
        <section
          class="deck-gr-panel cs-deck-sources"
          id={sourcePanelId}
          aria-label={answerEvidenceText("answerEvidence")}
        >
          <header class="deck-gr-panel-head">
            <h4>{answerEvidenceText("answerEvidence")}</h4>
            <button type="button" class="deck-gr-return cs-deck-affordance" onClick={returnToAnswer}>
              {answerEvidenceText("returnToAnswer")}
            </button>
          </header>
          <SourceDetail
            sources={sources}
            label={sourceCountLabel}
            panelId={sourcePanelId}
            selectedSource={selectedSource?.number ?? null}
          />
        </section>
      ) : null}
    </div>
  );
}

export function primaryAnswerText(
  text: string,
  verification: AnswerVerification | undefined,
  semanticReceipt?: SemanticProjectionReceipt,
): string {
  if (verification?.status === "unverified") {
    const clarification = text.trim();
    if (
      preservesTypedEvidenceHold(verification, semanticReceipt)
    ) {
      return clarification;
    }
    if (
      verification.reason_code === "semantic_clarification_required" &&
      clarification.endsWith("?")
    ) {
      return clarification;
    }
    return tForLocale(
      replyLocale(clarification),
      `deck.grounded.clarificationPrompt.${verificationIssueKind(verification.reason_code)}`,
    );
  }
  const reason = verification?.reason_code?.trim();
  if (!reason) return text;
  return stripReasonSuffix(text, reason);
}

/** Answer in the language the server used for this reply, not the Console chrome language. */
function replyLocale(serverText: string): "en" | "ko" {
  if (!serverText) return getLocale();
  for (const character of serverText) {
    if (character >= "가" && character <= "힣") return "ko";
  }
  return "en";
}

function stripReasonSuffix(text: string, reason: string | null): string {
  const trimmed = text.trimEnd();
  const suffix = reason?.trim() ? ` (${reason.trim()})` : "";
  return suffix && trimmed.endsWith(suffix)
    ? trimmed.slice(0, -suffix.length).trimEnd()
    : text;
}

export function hasEvidenceReferenceCitations(cites: readonly Citation[]): boolean {
  return cites.length > 0 && cites.every((citation) => citation.label.startsWith("evidence."));
}

function preservesTypedEvidenceHold(
  verification: AnswerVerification,
  semanticReceipt: SemanticProjectionReceipt | undefined,
): boolean {
  const observation = semanticReceipt?.assurance_observation;
  return (
    verification.authority.trim().length > 0 &&
    verification.authority !== "unavailable" &&
    verification.checks_completed > 0 &&
    verification.checks_completed <= verification.checks_total &&
    verification.evidence_refs.some((reference) => reference.trim().length > 0) &&
    (verification.reason_code === "semantic_evidence_held" ||
      verification.reason_code === "semantic_evidence_incomplete") &&
    semanticReceipt?.disposition === "held" &&
    semanticReceipt.unavailable_reason === "authoritative_evidence_unavailable" &&
    semanticReceipt.reason_code === verification.reason_code &&
    typeof semanticReceipt.plan_digest === "string" &&
    typeof semanticReceipt.execution_receipt_digest === "string" &&
    observation?.authority_posture === "read_only" &&
    observation.read_performed === true &&
    observation.evidence_posture !== "fresh" &&
    semanticReceipt.execution_authority === false
  );
}

export function assuranceHref(turnId: string): string {
  return routeHref("conversation-assurance", { params: { turn: turnId } });
}

export function sourceButtonAccessibleLabel(
  sourceCountLabel: string,
  statusLabels: readonly (string | null)[],
): string {
  return [sourceCountLabel, ...statusLabels.filter((item): item is string => Boolean(item))]
    .join(". ");
}

export function incidentCandidateDeckDetail(candidate: IncidentCandidate): DeckOpenDetail {
  return {
    sessionKey: `incident:${candidate.correlationId}`,
    sessionLabel: candidate.title,
    newConversation: true,
    prompt: tForLocale(candidate.locale, "deck.incidentCandidates.prompt"),
    submitPrompt: true,
    binding: {
      kind: "incident",
      incidentId: candidate.incidentId,
      correlationId: candidate.correlationId,
    },
  };
}

export function incidentCandidateAnswerLead(text: string): string {
  const lines = text.split("\n");
  const firstCandidate = lines.findIndex((line) => /^\s*-\s+/.test(line));
  return firstCandidate > 0 ? lines.slice(0, firstCandidate).join("\n").trimEnd() : text;
}

function IncidentCandidatePicker({ candidates }: {
  readonly candidates: readonly IncidentCandidate[];
}) {
  const locale = candidates[0]?.locale ?? "en";
  return (
    <section
      class="deck-incident-candidates"
      aria-label={tForLocale(locale, "deck.incidentCandidates.title")}
    >
      <strong>{tForLocale(locale, "deck.incidentCandidates.title")}</strong>
      <p>{tForLocale(locale, "deck.incidentCandidates.hint")}</p>
      <ul>
        {candidates.map((candidate) => (
          <li key={`${candidate.incidentId}:${candidate.correlationId}`}>
            <button
              type="button"
              onClick={() => openDeckWithContext(incidentCandidateDeckDetail(candidate))}
            >
              <span>{candidate.title}</span>
              <small>
                {candidate.severity} / {candidate.status} / {candidate.lastUpdatedAt}
              </small>
              <code>{candidate.incidentId}</code>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Short one-word status for the compact verification chip; the full sentence
 *  stays available on hover (title). */
function shortVerificationStatus(
  verification: AnswerVerification,
  semanticReceipt: SemanticProjectionReceipt | undefined,
  boundedCorrection: boolean,
): string {
  if (verification.reason_code === "ambiguous_incident") {
    return t("deck.grounded.verificationStatus.needsSelection");
  }
  if (verification.reason_code === "recorded_failure_reason") {
    return t("deck.grounded.verificationStatus.recordedFailure");
  }
  if (verification.status !== "unverified" && verificationAttentionKind(verification, semanticReceipt)) {
    return verificationPrimaryLabel(verification, semanticReceipt);
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
      return verificationPrimaryLabel(verification, semanticReceipt);
  }
}

/** The reconstructed retrieval trace: how this reply was grounded, shown when
 *  the operator expands the grounded pill. Mirrors the source-streaming mock's
 *  "show trace" affordance (mocks/ui/deck-sources.html). */
function GroundingTrace({ stages }: { readonly stages: readonly TraceStage[] }) {
  if (stages.length === 0) return null;
  return (
    <ol class="cs-grounding-stages" aria-label={t("deck.grounded.traceLabel")}>
      {stages.map((stage, i) => (
        <li
          key={`${stage.label}-${i}`}
          class={`cs-grounding-stage is-${stage.status === "attention" ? "attention" : "done"}`}
        >
          <span class="cs-grounding-mark" aria-hidden="true">
            {stage.status === "attention" ? "!" : "\u2713"}
          </span>
          <span class="cs-grounding-stage-copy">
            <span class="cs-grounding-stage-label">
              {t(`deck.grounded.stage.${stage.action}`, {
                model: stage.model ?? "",
                from: stage.from ?? "",
                to: stage.to ?? "",
              })}
            </span>
            <span class="cs-grounding-stage-detail">
              {stage.reasonCode
                ? t(handoffReasonKey(stage.reasonCode))
                : stage.detailKey
                  ? t(stage.detailKey, stage.detailParams)
                  : stage.detail}
            </span>
          </span>
          <span class="cs-grounding-phase">
            {t(`deck.grounded.side.${stage.side}`)}
          </span>
        </li>
      ))}
    </ol>
  );
}

/** The display-authorized answer as its original Markdown, on the layer's quiet disclosure. */
function OriginalMarkdown({ renderedText }: { readonly renderedText: string }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <details
      class="deck-answer-original cs-deck-disclosure"
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary class="cs-deck-disclosure-summary">
        <span class="cs-deck-disclosure-title">{answerEvidenceText("originalMarkdown")}</span>
        <span class="cs-run-chevron" aria-hidden="true" />
      </summary>
      {expanded ? (
        <div class="cs-deck-disclosure-body">
          <pre><code>{renderedText}</code></pre>
        </div>
      ) : null}
    </details>
  );
}

/** Answer evidence. Each grounding source is one numbered hairline row that opens its cited
 *  value and path in place, as in the Command deck mock. Every row is a real evidence entry or
 *  citation the backend returned; nothing is fabricated. A numbered citation opens its row. */
function SourceDetail({
  sources,
  label,
  panelId,
  selectedSource,
}: {
  readonly sources: readonly GroundedSource[];
  readonly label: string;
  readonly panelId: string;
  readonly selectedSource: number | null;
}) {
  return (
    <ol class="cs-deck-source-list" aria-label={label}>
      {sources.map((source) => (
        <li
          key={`${source.n}-${source.title}`}
          class="deck-src-row"
          id={`${panelId}-${source.n}`}
          data-selected={source.n === selectedSource ? "true" : "false"}
        >
          <details class="deck-src-detail">
            <summary class={`cs-deck-source${source.n === selectedSource ? " is-target" : ""}`}>
              <span class="cs-deck-source-num" aria-hidden="true">{source.n}</span>
              <span class="cs-deck-kind">{source.badge}</span>
              <span class="cs-deck-source-copy">
                <span class="cs-deck-source-title">{source.title}</span>
              </span>
            </summary>
            <div class="deck-src-text cs-deck-source-detail">
              {source.meta ? <span class="cs-deck-source-meta">{source.meta}</span> : null}
              {source.path ? <code class="deck-src-path cs-deck-source-path">{source.path}</code> : null}
            </div>
          </details>
        </li>
      ))}
    </ol>
  );
}

export type VerificationTone = "verified" | "consistent" | "attention" | "failure";

const HELD_FOR_INPUT_ISSUES: ReadonlySet<string> = new Set([
  "contextRequired",
  "sourceUnavailable",
  "visionUnverified",
]);

/** The verification tone keeps the established meaning of each status and evidence issue: a
 *  question held for more input or an unreachable source needs attention, while an unsupported or
 *  contradicted answer fails. A pending incident selection or a recorded failure reason is a
 *  consistent reading, and a bounded correction keeps only verified sentences. */
export function verificationTone(
  verification: AnswerVerification,
  issue: string | null,
  flags: { readonly boundedCorrection: boolean; readonly pendingSelection: boolean },
): VerificationTone {
  const status = flags.pendingSelection
    ? "consistent"
    : flags.boundedCorrection
      ? "verified"
      : verification.status;
  if (status === "unverified") {
    return issue && HELD_FOR_INPUT_ISSUES.has(issue) ? "attention" : "failure";
  }
  if (issue === "staleEvidence" || issue === "partialEvidence") return "attention";
  if (issue === "conflictingEvidence" || issue === "evidenceUnavailable") return "failure";
  if (status === "verified" || status === "consistent") return status;
  return "attention";
}

/** The visible claim count beside the status; the complete wording stays in the tooltip. */
export function claimDetail(verification: AnswerVerification): string | null {
  const claims = verification.claims ?? [];
  if (claims.length === 0) return null;
  const supported = claims.filter((claim) => claim.status === "supported").length;
  const summary = t("deck.grounded.verificationLabel.claimSummary", { supported, total: claims.length }).trim();
  return summary.replace(/^\((.*)\)$/s, "$1");
}

/** Evidence issues shown in the sources pill, each named once. */
export function pillIssues(
  incomplete: boolean,
  statusLabel: string | null,
  secondary: string | null,
): readonly string[] {
  const issues = [
    incomplete ? statusLabel ?? t("deck.grounded.partialEvidence") : statusLabel,
    secondary ? t(`deck.grounded.verificationStatus.${secondary}`) : null,
  ];
  return issues.filter((issue, index): issue is string => Boolean(issue) && issues.indexOf(issue) === index);
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

function IconReview() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
      <path d="M8 2.2l4.8 1.8v3.6c0 3-2 5.2-4.8 6.2-2.8-1-4.8-3.2-4.8-6.2V4z" />
      <path d="M5.8 8.1l1.6 1.6 2.9-3" />
    </svg>
  );
}

function IconChevron() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">
      <path d="M5 6.5l3 3 3-3" />
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

const CODE_VALIDATION_TONE = { valid: "verified", invalid: "failure", not_checked: "pending" } as const;
const CODE_VALIDATION_MARK = { valid: "\u2713", invalid: "!", not_checked: "?" } as const;

/** Generated code evidence: one quiet disclosure, then each artifact's static check, its code, and
 *  its artifact reference. Validation never means execution, and the status says so. */
function CodeEvidence({ artifacts }: { readonly artifacts: readonly GroundedCodeArtifact[] }) {
  return (
    <details class="deck-code-evidence cs-deck-disclosure">
      <summary class="cs-deck-disclosure-summary">
        <span class="cs-deck-disclosure-title">{t("deck.codeEvidence.label")}</span>
        <span class="cs-deck-disclosure-meta">
          {t("deck.codeEvidence.count", { count: artifacts.length })}
        </span>
        <span class="cs-run-chevron" aria-hidden="true" />
      </summary>
      <div class="cs-deck-disclosure-body">
        {artifacts.map((artifact, index) => (
          <section key={artifact.artifact_ref} class="cs-run-payload">
            <span class={`cs-deck-verification is-${CODE_VALIDATION_TONE[artifact.validation_status]}`}>
              <span class="cs-deck-verification-mark" aria-hidden="true">
                {CODE_VALIDATION_MARK[artifact.validation_status]}
              </span>
              <span>{t(`deck.codeEvidence.status.${artifact.validation_status}`)}</span>
              <span class="cs-deck-verification-detail">#{index + 1}</span>
            </span>
            <RichContent
              text={`\`\`\`${artifact.language}\n${artifact.content}\`\`\``}
            />
            <p class="cs-model-trace-hash">
              <code>{artifact.artifact_ref}</code>
              {artifact.validation_detail ? <span>{artifact.validation_detail}</span> : null}
            </p>
          </section>
        ))}
      </div>
    </details>
  );
}

export function verificationLabel(
  verification: AnswerVerification,
  semanticReceipt?: SemanticProjectionReceipt,
  options: { readonly includeClaims?: boolean } = {},
): string {
  const claims = options.includeClaims === false ? [] : verification.claims ?? [];
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
  if (semanticReceipt && verification.status !== "unverified") {
    const verificationIssue = verificationAttentionKind(verification, semanticReceipt);
    if (verificationIssue) {
      return verificationIssueDetailLabel(verificationIssue, claimSummary);
    }
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
      return (verification.claims ?? []).length > 0
        ? t("deck.grounded.verificationLabel.consistent", {
            scope: evidenceScope,
            claims: claimSummary,
          })
        : t("deck.grounded.verificationLabel.consistentNoClaims", { scope: evidenceScope });
    case "unverified":
      return unverifiedDetailLabel(verification, claimSummary);
  }
}
