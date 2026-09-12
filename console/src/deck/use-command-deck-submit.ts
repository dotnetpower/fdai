import { useCallback } from "preact/hooks";
import { t } from "../i18n";
import {
  askBackendStream,
  type ConfirmedAnswerSegment,
  type EvidenceBranch,
  type InvestigationActivity,
  type InvestigationMilestone,
  type VerificationProgress,
} from "./backend";
import {
  hasPendingComposerAttachments,
  takeComposerAttachments,
} from "./composer-attachment-store";
import { DEFAULT_NARRATOR, type Turn } from "./command-deck-presenters";
import { upsertEvidenceBranch, upsertInvestigationActivity } from "./investigation-timeline";
import {
  investigationTurnsAreSettled,
  settleInvestigationTurn,
  settleInvestigationTurns,
} from "./investigation-turn-state";
import {
  handoverGoalIdForSessionKey,
  provisionalReplyAgent,
  replyAgent,
  routePromptToAgent,
  sessionIdFor,
} from "./command-deck-session";
import {
  conversationLabelForPrompt,
  conversationPath,
  type ConversationSummary,
} from "./conversation-sessions";
import type { ViewSnapshot } from "./context";
import { withdrawExpiredCohortContext } from "./expiring-cohort-context";
import { record as recordHistory, type DraftHistory } from "./draft-history";
import {
  drainStreamPaint,
  drainTerminalReveal,
  flushStreamPaint,
  shouldFlushStreamPaintSynchronously,
  terminalRevealChunks,
} from "./stream-paint";
import { completedWorkRevealTarget } from "./scroll-stick";
import { backendHistoryForTurns } from "./turn-history";
import type { IncidentConversationBinding } from "./open-deck";
import type { ConversationModelTier } from "./conversation-model-selection";
import {
  isSemanticDirectResponseSource,
  queueNextRequestId,
} from "./backend-normalizers";

function waitForVisualRevealFrame(): Promise<void> {
  return new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      cancelAnimationFrame(frame);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      resolve();
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "hidden") finish();
    };
    const frame = requestAnimationFrame(finish);
    document.addEventListener("visibilitychange", onVisibilityChange);
    if (shouldFlushStreamPaintSynchronously(document.visibilityState, document.hasFocus())) {
      finish();
    }
  });
}

export interface ActiveRequest {
  readonly id: string;
  readonly sessionKey: string;
  readonly controller: AbortController;
  readonly kind: "stream";
}

export interface CommandDeckSubmitOptions {
  readonly historyTurns?: readonly Turn[];
  readonly conversationBinding?: IncidentConversationBinding;
  readonly requestId?: string;
  readonly snapshot?: ViewSnapshot | null;
}

type StateSetter<T> = (value: T | ((current: T) => T)) => void;
interface MutableValueRef<T> {
  current: T;
}

/** Capture request context without retaining mutable route snapshot references. */
export function requestSnapshotForSubmit(
  current: ViewSnapshot | null,
  supplied: ViewSnapshot | null | undefined,
): ViewSnapshot | null {
  const selected = supplied === undefined ? current : supplied;
  return selected === null ? null : withdrawExpiredCohortContext(structuredClone(selected), Date.now());
}

interface UseCommandDeckSubmitOptions {
  readonly snapshot: ViewSnapshot | null;
  readonly pending: boolean;
  readonly conversations: readonly ConversationSummary[];
  readonly sessionKeyRef: MutableValueRef<string>;
  readonly turnsRef: MutableValueRef<readonly Turn[]>;
  readonly activeRequestRef: MutableValueRef<ActiveRequest | null>;
  readonly abortRef: MutableValueRef<AbortController | null>;
  readonly inFlightRef: MutableValueRef<boolean>;
  readonly sessionIdsRef: MutableValueRef<Map<string, string>>;
  readonly sessionMetadataRef: MutableValueRef<Map<string, ConversationSummary>>;
  readonly historyRef: MutableValueRef<DraftHistory>;
  readonly setTurns: StateSetter<readonly Turn[]>;
  readonly setDraft: StateSetter<string>;
  readonly setPending: StateSetter<boolean>;
  readonly setRetrievalProgress: StateSetter<VerificationProgress | null>;
  readonly setSrStatus: StateSetter<string>;
  readonly setInFlight: StateSetter<boolean>;
  readonly updateConversationIndex: (summary: ConversationSummary) => void;
  readonly focusInput: () => void;
  readonly pinTranscriptToLatest: () => void;
  readonly revealCompletedWork: (turnId: string, childSelector?: string) => void;
  readonly conversationModelTier: ConversationModelTier;
}

export function resolveConversationSummary(
  conversations: readonly ConversationSummary[],
  metadata: ReadonlyMap<string, ConversationSummary>,
  key: string,
): ConversationSummary | undefined {
  return metadata.get(key) ?? conversations.find((item) => item.key === key);
}

export function synchronizeConversationSummary(
  metadata: { current: Map<string, ConversationSummary> },
  summary: ConversationSummary,
  updateConversationIndex: (summary: ConversationSummary) => void,
): ConversationSummary {
  metadata.current.set(summary.key, summary);
  updateConversationIndex(summary);
  return summary;
}

function shortTime(): string {
  const date = new Date();
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}:${String(date.getSeconds()).padStart(2, "0")}`;
}

function newId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function currentPathname(): string {
  return typeof window === "undefined" ? "/overview" : window.location.pathname;
}

export function useCommandDeckSubmit({
  snapshot,
  pending,
  conversations,
  sessionKeyRef,
  turnsRef,
  activeRequestRef,
  abortRef,
  inFlightRef,
  sessionIdsRef,
  sessionMetadataRef,
  historyRef,
  setTurns,
  setDraft,
  setPending,
  setRetrievalProgress,
  setSrStatus,
  setInFlight,
  updateConversationIndex,
  focusInput,
  pinTranscriptToLatest,
  revealCompletedWork,
  conversationModelTier,
}: UseCommandDeckSubmitOptions) {
  return useCallback(async (raw: string, options: CommandDeckSubmitOptions = {}) => {
    const text = raw.trim();
    if (text.length === 0 || pending || inFlightRef.current) return;
    if (hasPendingComposerAttachments()) {
      setSrStatus(t("deck.attach.scanning"));
      return;
    }
    // Drain staged image attachments only once we know this turn will send, so
    // a no-op empty/busy submit (e.g. Enter on an empty composer) never
    // silently discards the operator's pending images. Draining here also means
    // exactly this turn owns them, so a concurrent composer clear cannot race
    // the payload away.
    const attachments = takeComposerAttachments();
    const originSessionKey = sessionKeyRef.current;
    const conversationId = sessionIdFor(sessionIdsRef.current, originSessionKey);
    const controller = new AbortController();
    const request: ActiveRequest = {
      id: newId(),
      sessionKey: originSessionKey,
      controller,
      kind: "stream",
    };
    activeRequestRef.current = request;
    abortRef.current = controller;
    inFlightRef.current = true;
    const isCurrent = () =>
      activeRequestRef.current?.id === request.id &&
      sessionKeyRef.current === originSessionKey;
    const activityAt = new Date().toISOString();
    const requestSnapshot = requestSnapshotForSubmit(snapshot, options.snapshot);
    const operatorTurn: Turn = {
      id: newId(),
      role: "operator",
      text,
      ...(requestSnapshot ? { requestSnapshot } : {}),
      ...(attachments.length > 0
        ? {
            attachments: attachments.map((attachment) => ({
              id: attachment.id,
              name: attachment.name,
              mediaType: attachment.media_type,
              conversationId,
              src: attachment.data_url,
            })),
          }
        : {}),
      at: shortTime(),
      recordedAt: activityAt,
    };
    const sessionSummary = resolveConversationSummary(
      conversations,
      sessionMetadataRef.current,
      originSessionKey,
    );
    let currentSessionSummary = sessionSummary;
    const currentTurns = turnsRef.current;
    const historyTurns = options.historyTurns ?? currentTurns;
    const conversationBinding = options.conversationBinding ?? sessionSummary?.binding;
    const hasOperatorTurn = currentTurns.some((turn) => turn.role === "operator");
    currentSessionSummary = synchronizeConversationSummary(sessionMetadataRef, {
      key: originSessionKey,
      label:
        sessionSummary
          ? conversationLabelForPrompt(sessionSummary, text, hasOperatorTurn)
          : t("deck.general"),
      kind: sessionSummary?.kind ?? "screen-default",
      ...(sessionSummary?.agent ? { agent: sessionSummary.agent } : {}),
      ...(conversationBinding ? { binding: conversationBinding } : {}),
      originPath: sessionSummary?.originPath ?? conversationPath(currentPathname()),
      originLabel: sessionSummary?.originLabel ?? snapshot?.routeLabel ?? currentPathname(),
      createdAt: sessionSummary?.createdAt ?? activityAt,
      updatedAt: activityAt,
      lastReadAt: activityAt,
    }, updateConversationIndex);
    setTurns((current) => [...current, operatorTurn]);
    turnsRef.current = [...currentTurns, operatorTurn];
    setDraft("");
    historyRef.current = recordHistory(historyRef.current, text);
    setPending(true);
    setRetrievalProgress(null);
    setSrStatus(t("deck.announcement.retrieving"));
    setInFlight(true);

    const history = backendHistoryForTurns(historyTurns);
    const deckId = newId();
    let activityTurnId = newId();
    const activityTurnIds = new Set<string>();
    const milestoneIds = new Set<string>();
    let hasActivityTurn = false;
    const settleCurrentActivityTurn = () => {
      if (!activityTurnIds.has(activityTurnId)) return;
      const settledTurnId = activityTurnId;
      setTurns((current) => {
        const next = settleInvestigationTurn(current, settledTurnId);
        turnsRef.current = next;
        return next;
      });
      activityTurnId = newId();
    };
    try {
      let started = false;
      let receivedToken = false;
      let receivedTerminalContent = false;
      let visibleAcc = "";
      let pendingRevision = 0;
      let paintFrame: number | null = null;
      const paintQueue: string[] = [];
      let terminalReplyReady = false;
      const observedWorkSettled = () => terminalReplyReady ||
        investigationTurnsAreSettled(turnsRef.current, activityTurnIds);
      const scheduleStreamPaint = () => {
        if (!started || paintFrame !== null || paintQueue.length === 0 || !isCurrent()) return;
        paintFrame = requestAnimationFrame(() => {
          paintFrame = null;
          if (!isCurrent()) return;
          visibleAcc += drainStreamPaint(paintQueue);
          setTurns((current) => {
            const next = current.map((turn) =>
              turn.id === deckId ? { ...turn, text: visibleAcc } : turn,
            );
            turnsRef.current = next;
            return next;
          });
          if (paintQueue.length > 0) scheduleStreamPaint();
        });
      };
      const ensureTurn = () => {
        if (started || !isCurrent() || !observedWorkSettled()) return;
        started = true;
        setPending(false);
        setRetrievalProgress(null);
        setSrStatus(t("deck.announcement.answering"));
        setTurns((current) => {
          const settledCurrent = settleInvestigationTurns(current, activityTurnIds);
          const next: readonly Turn[] = [
            ...settledCurrent,
            {
              id: deckId,
              role: "deck",
              text: visibleAcc,
              streaming: true,
              terminal: false,
              revision: pendingRevision,
              agent: provisionalReplyAgent(sessionSummary?.agent),
              at: shortTime(),
              recordedAt: new Date().toISOString(),
            },
          ];
          turnsRef.current = next;
          return next;
        });
        scheduleStreamPaint();
        pinTranscriptToLatest();
      };
      const revealWhenReady = () => {
        if (started || !isCurrent() || !observedWorkSettled()) return;
        ensureTurn();
      };
      let reply: Awaited<ReturnType<typeof askBackendStream>>;
      try {
        if (options.requestId) queueNextRequestId(options.requestId);
        const handoverGoalId = handoverGoalIdForSessionKey(originSessionKey);
        const routedText = routePromptToAgent(
          text,
          handoverGoalId ? undefined : sessionSummary?.agent,
        );
        reply = await askBackendStream(routedText, requestSnapshot, history, {
          sessionId: conversationId,
          ...(handoverGoalId ? { handoverGoalId } : {}),
          ...(sessionSummary?.agent ? { targetAgent: sessionSummary.agent } : {}),
          ...(attachments.length > 0 ? { attachments } : {}),
          ...(conversationBinding
            ? { conversationBinding }
            : {}),
          ...(conversationModelTier === "auto"
            ? {}
            : { conversationModelTier }),
          onValidatedTerminal: () => {
            if (!isCurrent()) return;
            terminalReplyReady = true;
            revealWhenReady();
          },
          onToken: (delta) => {
            if (!isCurrent()) return;
            receivedToken = true;
            paintQueue.push(delta);
            revealWhenReady();
            if (!started) return;
            scheduleStreamPaint();
          },
          onProgress: (progress) => {
            if (!isCurrent()) return;
            setSrStatus(progress.label);
            if (!started) {
              setRetrievalProgress(progress);
              return;
            }
            setTurns((current) => {
              const next = current.map((turn) =>
                turn.id === deckId ? { ...turn, verificationProgress: progress } : turn,
              );
              turnsRef.current = next;
              return next;
            });
          },
          onActivity: (activity: InvestigationActivity) => {
            if (!isCurrent()) return;
            hasActivityTurn = true;
            const targetActivityTurnId = activityTurnId;
            activityTurnIds.add(targetActivityTurnId);
            setPending(false);
            setRetrievalProgress(null);
            setSrStatus(activity.label);
            setTurns((current) => {
              const existing = current.find((turn) => turn.id === targetActivityTurnId);
              const activities = upsertInvestigationActivity(
                existing?.activities ?? [],
                activity,
              );
              const text = [
                ...(existing?.branches ?? []).map((branch) => branch.summary),
                ...activities.map((item) => item.label),
              ].join("\n");
              const next = existing
                ? current.map((turn) => turn.id === targetActivityTurnId
                  ? { ...turn, text, activities }
                  : turn)
                : [
                    ...current,
                    {
                      id: targetActivityTurnId,
                      role: "deck" as const,
                      kind: "activity" as const,
                      text,
                      activities,
                      source: "investigation",
                      streaming: true,
                      terminal: false,
                      at: shortTime(),
                      recordedAt: activity.execution?.startedAt ??
                        activity.observedAt ?? new Date().toISOString(),
                    },
                  ];
              turnsRef.current = next;
              return next;
            });
            revealWhenReady();
            pinTranscriptToLatest();
          },
          onBranch: (branch: EvidenceBranch) => {
            if (!isCurrent()) return;
            hasActivityTurn = true;
            const targetActivityTurnId = activityTurnId;
            activityTurnIds.add(targetActivityTurnId);
            setPending(false);
            setRetrievalProgress(null);
            setSrStatus(branch.summary);
            setTurns((current) => {
              const existing = current.find((turn) => turn.id === targetActivityTurnId);
              const branches = upsertEvidenceBranch(existing?.branches ?? [], branch);
              const text = [
                ...branches.map((item) => item.summary),
                ...(existing?.activities ?? []).map((item) => item.label),
              ].join("\n");
              const next = existing
                ? current.map((turn) => turn.id === targetActivityTurnId
                  ? { ...turn, text, branches }
                  : turn)
                : [
                    ...current,
                    {
                      id: targetActivityTurnId,
                      role: "deck" as const,
                      kind: "activity" as const,
                      text,
                      branches,
                      source: "investigation",
                      streaming: true,
                      terminal: false,
                      at: shortTime(),
                      recordedAt: branch.startedAt,
                    },
                  ];
              turnsRef.current = next;
              return next;
            });
            revealWhenReady();
            pinTranscriptToLatest();
          },
          onMilestone: (milestone: InvestigationMilestone) => {
            if (!isCurrent() || milestoneIds.has(milestone.messageId)) return;
            milestoneIds.add(milestone.messageId);
            settleCurrentActivityTurn();
            setPending(false);
            setRetrievalProgress(null);
            setSrStatus(milestone.text);
            setTurns((current) => {
              const next = [
                ...current,
                {
                  id: `milestone-${milestone.messageId}`,
                  role: "deck" as const,
                  kind: "message" as const,
                  text: milestone.text,
                  agent: milestone.agent ?? DEFAULT_NARRATOR,
                  source: "investigation",
                  streaming: false,
                  terminal: true,
                  at: shortTime(),
                  recordedAt: milestone.recordedAt ?? new Date().toISOString(),
                },
              ];
              turnsRef.current = next;
              return next;
            });
            pinTranscriptToLatest();
          },
          onRevision: (answer, revision, status) => {
            if (!isCurrent()) return;
            receivedTerminalContent = true;
            visibleAcc = answer;
            paintQueue.length = 0;
            pendingRevision = revision;
            revealWhenReady();
            setSrStatus(
              status === "corrected"
                ? t("deck.announcement.corrected")
                : status === "unverified"
                  ? t("deck.announcement.unverified")
                  : t("deck.announcement.verified"),
            );
            if (!started) return;
            if (paintFrame !== null) {
              cancelAnimationFrame(paintFrame);
              paintFrame = null;
            }
            setTurns((current) => {
              const next = current.map((turn) => {
                if (turn.id !== deckId || revision <= (turn.revision ?? 0)) return turn;
                const revised = { ...turn, text: answer, revision };
                delete revised.confirmed;
                return revised;
              });
              turnsRef.current = next;
              return next;
            });
          },
          onConfirmed: (segment: ConfirmedAnswerSegment) => {
            if (!isCurrent()) return;
            receivedTerminalContent = true;
            pendingRevision = Math.max(pendingRevision, segment.revision);
            visibleAcc = segment.text;
            paintQueue.length = 0;
            revealWhenReady();
            if (!started) return;
            if (paintFrame !== null) {
              cancelAnimationFrame(paintFrame);
              paintFrame = null;
            }
            setTurns((current) => {
              const next = current.map((turn) => turn.id === deckId
                ? {
                    ...turn,
                    text: segment.text,
                    revision: segment.revision,
                    confirmed: segment,
                  }
                : turn);
              turnsRef.current = next;
              return next;
            });
          },
          signal: controller.signal,
        });
      } catch (error) {
        if (paintFrame !== null) cancelAnimationFrame(paintFrame);
        throw error;
      }
      const terminalRecordedAt = reply.turnTiming?.completed_at ?? new Date().toISOString();
      const directResponse = isSemanticDirectResponseSource(reply.source);
      terminalReplyReady = true;
      if (paintFrame !== null) {
        cancelAnimationFrame(paintFrame);
        paintFrame = null;
      }
      if (receivedToken && paintQueue.length > 0 && isCurrent()) {
        ensureTurn();
        while (paintQueue.length > 0 && isCurrent()) {
          await waitForVisualRevealFrame();
          visibleAcc += shouldFlushStreamPaintSynchronously(
            document.visibilityState,
            document.hasFocus(),
          )
            ? flushStreamPaint(paintQueue)
            : drainStreamPaint(paintQueue);
          setTurns((current) => {
            const next = current.map((turn) => turn.id === deckId
              ? { ...turn, text: visibleAcc }
              : turn);
            turnsRef.current = next;
            return next;
          });
        }
      }
      paintQueue.length = 0;
      ensureTurn();
      if (!receivedToken && !receivedTerminalContent && reply.text.length > 0 && isCurrent()) {
        const terminalQueue = terminalRevealChunks(reply.text);
        if (shouldFlushStreamPaintSynchronously(
          document.visibilityState,
          document.hasFocus(),
          reply.adaptiveAnswer !== undefined,
        )) {
          visibleAcc = reply.text;
        } else {
          visibleAcc = "";
          while (terminalQueue.length > 0 && isCurrent()) {
            await waitForVisualRevealFrame();
            visibleAcc += shouldFlushStreamPaintSynchronously(
              document.visibilityState,
              document.hasFocus(),
            )
              ? flushStreamPaint(terminalQueue)
              : drainTerminalReveal(terminalQueue);
            setTurns((current) => {
              const next = current.map((turn) => turn.id === deckId
                ? { ...turn, text: visibleAcc }
                : turn);
              turnsRef.current = next;
              return next;
            });
          }
        }
      }
      if (isCurrent()) {
        if (reply.conversationBinding) {
          currentSessionSummary = synchronizeConversationSummary(sessionMetadataRef, {
            key: originSessionKey,
            label: currentSessionSummary?.label ?? text,
            kind: currentSessionSummary?.kind ?? "screen-default",
            ...(currentSessionSummary?.agent ? { agent: currentSessionSummary.agent } : {}),
            binding: reply.conversationBinding,
            originPath: currentSessionSummary?.originPath ?? conversationPath(currentPathname()),
            originLabel: currentSessionSummary?.originLabel ?? snapshot?.routeLabel ?? currentPathname(),
            createdAt: currentSessionSummary?.createdAt ?? activityAt,
            updatedAt: terminalRecordedAt,
            lastReadAt: terminalRecordedAt,
          }, updateConversationIndex);
        }
        setTurns((current) => {
          const retained = directResponse
            ? current.filter((turn) => !activityTurnIds.has(turn.id))
            : current;
          const next = retained.map((turn) => {
            if (activityTurnIds.has(turn.id)) {
              return { ...turn, streaming: false, terminal: true };
            }
            if (turn.id !== deckId) return turn;
            const updated = {
              ...turn,
              text: reply.text,
              recordedAt: terminalRecordedAt,
              streaming: false,
              terminal: reply.source !== "stopped" && !reply.source.startsWith("partial"),
              citations: reply.citations,
              followUps: reply.followUps,
              source: reply.source,
              agent: replyAgent(reply),
              ...(reply.assessmentId ? { assessmentId: reply.assessmentId } : {}),
              ...(reply.verification ? { verification: reply.verification } : {}),
              ...(reply.confirmed ? { confirmed: reply.confirmed } : {}),
              ...(reply.router ? { router: reply.router } : {}),
              ...(reply.answerPlan ? { answerPlan: reply.answerPlan } : {}),
              ...(reply.answerPlanning ? { answerPlanning: reply.answerPlanning } : {}),
              ...(reply.delegation ? { delegation: reply.delegation } : {}),
              ...(reply.codeArtifacts ? { codeArtifacts: reply.codeArtifacts } : {}),
              ...(reply.incidentCandidates
                ? { incidentCandidates: reply.incidentCandidates }
                : {}),
              ...(reply.presentationArtifact
                ? { presentationArtifact: reply.presentationArtifact }
                : {}),
              ...(reply.documentArtifact
                ? { documentArtifact: reply.documentArtifact }
                : {}),
              ...(reply.actionDraft ? { actionDraft: reply.actionDraft } : {}),
              ...(reply.modelTrace ? { modelTrace: reply.modelTrace } : {}),
              ...(reply.modelLatencyMs !== undefined
                ? { modelLatencyMs: reply.modelLatencyMs }
                : {}),
              ...(reply.modelUsage ? { modelUsage: reply.modelUsage } : {}),
              ...(reply.turnTiming ? { turnTiming: reply.turnTiming } : {}),
              ...(reply.trajectoryDetail ? { trajectoryDetail: reply.trajectoryDetail } : {}),
              ...(reply.resourceContext ? { resourceContext: reply.resourceContext } : {}),
              ...(reply.evidenceFreshnessContext
                ? { evidenceFreshnessContext: reply.evidenceFreshnessContext }
                : {}),
              ...(reply.intentGraph ? { intentGraph: reply.intentGraph } : {}),
              ...(reply.intentGraphEvidence ? {
                intentGraphEvidence: reply.intentGraphEvidence,
              } : {}),
              ...(reply.evidenceMode ? { evidenceMode: reply.evidenceMode } : {}),
              ...(reply.semanticReceipt ? { semanticReceipt: reply.semanticReceipt } : {}),
              ...(reply.adaptiveAnswer ? { adaptiveAnswer: reply.adaptiveAnswer } : {}),
              ...(reply.conversationBinding
                ? { conversationBinding: reply.conversationBinding }
                : {}),
            };
            if (!reply.confirmed) delete updated.confirmed;
            return updated;
          });
          turnsRef.current = next;
          return next;
        });
        const firstActivityTurnId = directResponse
          ? undefined
          : activityTurnIds.values().next().value;
        const revealTarget = completedWorkRevealTarget(
          deckId,
          firstActivityTurnId,
          (reply.incidentCandidates?.length ?? 0) > 0,
        );
        revealCompletedWork(revealTarget.turnId, revealTarget.childSelector);
      }
    } finally {
      if (isCurrent()) {
        if (hasActivityTurn) {
          setTurns((current) => {
            const next = settleInvestigationTurns(current, activityTurnIds);
            turnsRef.current = next;
            return next;
          });
        }
        activeRequestRef.current = null;
        abortRef.current = null;
        inFlightRef.current = false;
        setPending(false);
        setRetrievalProgress(null);
        setSrStatus(controller.signal.aborted
          ? t("deck.announcement.stopped")
          : t("deck.announcement.ready"));
        setInFlight(false);
        focusInput();
      }
    }
  }, [
    snapshot,
    focusInput,
    pending,
    conversations,
    updateConversationIndex,
    pinTranscriptToLatest,
    revealCompletedWork,
    conversationModelTier,
  ]);
}
