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
import { takeComposerAttachments } from "./composer-attachment-store";
import { DEFAULT_NARRATOR, type Turn } from "./command-deck-presenters";
import { upsertEvidenceBranch, upsertInvestigationActivity } from "./investigation-timeline";
import {
  investigationTurnsAreSettled,
  settleInvestigationTurn,
  settleInvestigationTurns,
} from "./investigation-turn-state";
import { provisionalReplyAgent, replyAgent, sessionIdFor } from "./command-deck-session";
import {
  conversationLabelForPrompt,
  conversationPath,
  type ConversationSummary,
} from "./conversation-sessions";
import type { ViewSnapshot } from "./context";
import { record as recordHistory, type DraftHistory } from "./draft-history";
import {
  drainStreamPaint,
  shouldFlushStreamPaintSynchronously,
  terminalRevealChunks,
} from "./stream-paint";
import { backendHistoryForTurns } from "./turn-history";

const MIN_PREPARING_VISIBLE_MS = 420;

export interface ActiveRequest {
  readonly id: string;
  readonly sessionKey: string;
  readonly controller: AbortController;
  readonly kind: "stream";
}

type StateSetter<T> = (value: T | ((current: T) => T)) => void;
interface MutableValueRef<T> {
  current: T;
}

interface UseCommandDeckSubmitOptions {
  readonly snapshot: ViewSnapshot | null;
  readonly pending: boolean;
  readonly turns: readonly Turn[];
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
  readonly revealCompletedWork: (turnId: string) => void;
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
  turns,
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
}: UseCommandDeckSubmitOptions) {
  return useCallback(async (raw: string) => {
    const text = raw.trim();
    if (text.length === 0 || pending || inFlightRef.current) return;
    // Drain staged image attachments only once we know this turn will send, so
    // a no-op empty/busy submit (e.g. Enter on an empty composer) never
    // silently discards the operator's pending images. Draining here also means
    // exactly this turn owns them, so a concurrent composer clear cannot race
    // the payload away.
    const attachments = takeComposerAttachments();
    const originSessionKey = sessionKeyRef.current;
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
    const operatorTurn: Turn = {
      id: newId(),
      role: "operator",
      text,
      at: shortTime(),
      recordedAt: activityAt,
    };
    const activeSummary = conversations.find((item) => item.key === originSessionKey);
    const sessionSummary = activeSummary ?? sessionMetadataRef.current.get(originSessionKey);
    const hasOperatorTurn = turnsRef.current.some((turn) => turn.role === "operator");
    updateConversationIndex({
      key: originSessionKey,
      label:
        sessionSummary
          ? conversationLabelForPrompt(sessionSummary, text, hasOperatorTurn)
          : t("deck.general"),
      kind: sessionSummary?.kind ?? "screen-default",
      ...(sessionSummary?.agent ? { agent: sessionSummary.agent } : {}),
      originPath: sessionSummary?.originPath ?? conversationPath(currentPathname()),
      originLabel: sessionSummary?.originLabel ?? snapshot?.routeLabel ?? currentPathname(),
      createdAt: sessionSummary?.createdAt ?? activityAt,
      updatedAt: activityAt,
      lastReadAt: activityAt,
    });
    setTurns((current) => [...current, operatorTurn]);
    turnsRef.current = [...turnsRef.current, operatorTurn];
    setDraft("");
    historyRef.current = recordHistory(historyRef.current, text);
    setPending(true);
    setRetrievalProgress(null);
    setSrStatus(t("deck.announcement.retrieving"));
    setInFlight(true);

    const history = backendHistoryForTurns(turns);
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
      let visibleAcc = "";
      let pendingRevision = 0;
      const preparingStartedAt = Date.now();
      let revealTimer: number | null = null;
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
        if (started || revealTimer !== null || !isCurrent() || !observedWorkSettled()) return;
        const remaining = MIN_PREPARING_VISIBLE_MS - (Date.now() - preparingStartedAt);
        if (remaining <= 0) {
          ensureTurn();
          return;
        }
        revealTimer = window.setTimeout(() => {
          revealTimer = null;
          ensureTurn();
        }, remaining);
      };
      let reply: Awaited<ReturnType<typeof askBackendStream>>;
      try {
        reply = await askBackendStream(text, snapshot, history, {
          sessionId: sessionIdFor(sessionIdsRef.current, originSessionKey),
          ...(sessionSummary?.agent ? { targetAgent: sessionSummary.agent } : {}),
          ...(attachments.length > 0 ? { attachments } : {}),
          ...(sessionSummary?.binding
            ? { conversationBinding: sessionSummary.binding }
            : {}),
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
              const next = current.map((turn) =>
                turn.id === deckId && revision > (turn.revision ?? 0)
                  ? { ...turn, text: answer, revision }
                  : turn,
              );
              turnsRef.current = next;
              return next;
            });
          },
          onConfirmed: (segment: ConfirmedAnswerSegment) => {
            if (!isCurrent()) return;
            pendingRevision = Math.max(pendingRevision, segment.revision);
            revealWhenReady();
            if (!started) return;
            if (!receivedToken) {
              setTurns((current) => {
                const next = current.map((turn) => turn.id === deckId
                  ? { ...turn, revision: segment.revision, confirmed: segment }
                  : turn);
                turnsRef.current = next;
                return next;
              });
              return;
            }
            visibleAcc = segment.text;
            paintQueue.length = 0;
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
        if (revealTimer !== null) window.clearTimeout(revealTimer);
        if (paintFrame !== null) cancelAnimationFrame(paintFrame);
        throw error;
      }
      const terminalRecordedAt = reply.turnTiming?.completed_at ?? new Date().toISOString();
      terminalReplyReady = true;
      if (!started && isCurrent()) {
        const remaining = MIN_PREPARING_VISIBLE_MS - (Date.now() - preparingStartedAt);
        if (remaining > 0) {
          await new Promise<void>((resolve) => window.setTimeout(resolve, remaining));
        }
      }
      if (revealTimer !== null) {
        window.clearTimeout(revealTimer);
        revealTimer = null;
      }
      if (paintFrame !== null) {
        cancelAnimationFrame(paintFrame);
        paintFrame = null;
      }
      paintQueue.length = 0;
      ensureTurn();
      if (!receivedToken && reply.text.length > 0 && isCurrent()) {
        const terminalQueue = terminalRevealChunks(reply.text);
        if (shouldFlushStreamPaintSynchronously(
          document.visibilityState,
          document.hasFocus(),
        )) {
          visibleAcc = reply.text;
        } else {
          visibleAcc = "";
          while (terminalQueue.length > 0 && isCurrent()) {
            await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
            visibleAcc += drainStreamPaint(terminalQueue);
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
        setTurns((current) => {
          const next = current.map((turn) => {
            if (activityTurnIds.has(turn.id)) {
              return { ...turn, streaming: false, terminal: true };
            }
            return turn.id === deckId
              ? {
                  ...turn,
                  text: reply.text,
                  recordedAt: terminalRecordedAt,
                  streaming: false,
                  terminal: reply.source !== "stopped" && !reply.source.startsWith("partial"),
                  citations: reply.citations,
                  followUps: reply.followUps,
                  source: reply.source,
                  agent: replyAgent(reply),
                  ...(reply.verification ? { verification: reply.verification } : {}),
                  ...(reply.confirmed ? { confirmed: reply.confirmed } : {}),
                  ...(reply.router ? { router: reply.router } : {}),
                  ...(reply.answerPlan ? { answerPlan: reply.answerPlan } : {}),
                  ...(reply.answerPlanning ? { answerPlanning: reply.answerPlanning } : {}),
                  ...(reply.delegation ? { delegation: reply.delegation } : {}),
                  ...(reply.codeArtifacts ? { codeArtifacts: reply.codeArtifacts } : {}),
                  ...(reply.actionDraft ? { actionDraft: reply.actionDraft } : {}),
                  ...(reply.modelTrace ? { modelTrace: reply.modelTrace } : {}),
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
                }
              : turn;
          });
          turnsRef.current = next;
          return next;
        });
        const firstActivityTurnId = activityTurnIds.values().next().value;
        revealCompletedWork(firstActivityTurnId ?? deckId);
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
    turns,
    conversations,
    updateConversationIndex,
    pinTranscriptToLatest,
    revealCompletedWork,
  ]);
}
