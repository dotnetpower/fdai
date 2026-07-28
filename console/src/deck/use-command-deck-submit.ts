import { useCallback } from "preact/hooks";
import { t } from "../i18n";
import {
  askBackendStream,
  type BackendTurn,
  type ConfirmedAnswerSegment,
  type EvidenceBranch,
  type InvestigationActivity,
  type InvestigationMilestone,
  type VerificationProgress,
} from "./backend";
import { takeComposerAttachments } from "./composer-attachment-store";
import { DEFAULT_NARRATOR, type Turn } from "./command-deck-presenters";
import { upsertEvidenceBranch, upsertInvestigationActivity } from "./investigation-timeline";
import { replyAgent, sessionIdFor } from "./command-deck-session";
import {
  conversationLabelForPrompt,
  conversationPath,
  type ConversationSummary,
} from "./conversation-sessions";
import type { ViewSnapshot } from "./context";
import { record as recordHistory, type DraftHistory } from "./draft-history";
import {
  drainStreamPaint,
  flushStreamPaint,
  shouldFlushStreamPaintSynchronously,
} from "./stream-paint";

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
    const operatorTurn: Turn = { id: newId(), role: "operator", text, at: shortTime() };
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
      createdAt: sessionSummary?.createdAt ?? new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    });
    setTurns((current) => [...current, operatorTurn]);
    turnsRef.current = [...turnsRef.current, operatorTurn];
    setDraft("");
    historyRef.current = recordHistory(historyRef.current, text);
    setPending(true);
    setRetrievalProgress(null);
    setSrStatus("Retrieving answer...");
    setInFlight(true);

    const history: BackendTurn[] = turns
      .filter((turn) => turn.kind !== "activity")
      .map((turn) => ({
        role: turn.role === "operator" ? "user" : "assistant",
        content: turn.text,
      }));
    const deckId = newId();
    const activityTurnId = newId();
    const milestoneIds = new Set<string>();
    let hasActivityTurn = false;
    try {
      let started = false;
      let visibleAcc = "";
      let pendingRevision = 0;
      const preparingStartedAt = Date.now();
      let revealTimer: number | null = null;
      let paintFrame: number | null = null;
      const paintQueue: string[] = [];
      let paintDrainResolve: (() => void) | null = null;
      const resolvePaintDrain = (): void => {
        const resolve = paintDrainResolve;
        paintDrainResolve = null;
        if (resolve !== null) resolve();
      };
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
          else resolvePaintDrain();
        });
      };
      const ensureTurn = () => {
        if (started || !isCurrent()) return;
        started = true;
        setPending(false);
        setRetrievalProgress(null);
        setSrStatus("Assistant is answering...");
        setTurns((current) => {
          const next: readonly Turn[] = [
            ...current,
            {
              id: deckId,
              role: "deck",
              text: visibleAcc,
              streaming: true,
              terminal: false,
              revision: pendingRevision,
              agent: DEFAULT_NARRATOR,
              at: shortTime(),
            },
          ];
          turnsRef.current = next;
          return next;
        });
        scheduleStreamPaint();
        pinTranscriptToLatest();
      };
      const revealWhenReady = () => {
        if (started || revealTimer !== null || !isCurrent()) return;
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
      const waitForPaintDrain = async () => {
        if (paintQueue.length === 0 && paintFrame === null) return;
        if (shouldFlushStreamPaintSynchronously(document.visibilityState, document.hasFocus())) {
          if (paintFrame !== null) {
            cancelAnimationFrame(paintFrame);
            paintFrame = null;
          }
          visibleAcc += flushStreamPaint(paintQueue);
          resolvePaintDrain();
          return;
        }
        await new Promise<void>((resolve) => {
          paintDrainResolve = resolve;
          scheduleStreamPaint();
        });
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
            setPending(false);
            setRetrievalProgress(null);
            setSrStatus(activity.label);
            setTurns((current) => {
              const existing = current.find((turn) => turn.id === activityTurnId);
              const activities = upsertInvestigationActivity(
                existing?.activities ?? [],
                activity,
              );
              const text = [
                ...(existing?.branches ?? []).map((branch) => branch.summary),
                ...activities.map((item) => item.label),
              ].join("\n");
              const next = existing
                ? current.map((turn) => turn.id === activityTurnId
                  ? { ...turn, text, activities }
                  : turn)
                : [
                    ...current,
                    {
                      id: activityTurnId,
                      role: "deck" as const,
                      kind: "activity" as const,
                      text,
                      activities,
                      source: "investigation",
                      streaming: true,
                      terminal: false,
                      at: shortTime(),
                    },
                  ];
              turnsRef.current = next;
              return next;
            });
            pinTranscriptToLatest();
          },
          onBranch: (branch: EvidenceBranch) => {
            if (!isCurrent()) return;
            hasActivityTurn = true;
            setPending(false);
            setRetrievalProgress(null);
            setSrStatus(branch.summary);
            setTurns((current) => {
              const existing = current.find((turn) => turn.id === activityTurnId);
              const branches = upsertEvidenceBranch(existing?.branches ?? [], branch);
              const text = [
                ...branches.map((item) => item.summary),
                ...(existing?.activities ?? []).map((item) => item.label),
              ].join("\n");
              const next = existing
                ? current.map((turn) => turn.id === activityTurnId
                  ? { ...turn, text, branches }
                  : turn)
                : [
                    ...current,
                    {
                      id: activityTurnId,
                      role: "deck" as const,
                      kind: "activity" as const,
                      text,
                      branches,
                      source: "investigation",
                      streaming: true,
                      terminal: false,
                      at: shortTime(),
                    },
                  ];
              turnsRef.current = next;
              return next;
            });
            pinTranscriptToLatest();
          },
          onMilestone: (milestone: InvestigationMilestone) => {
            if (!isCurrent() || milestoneIds.has(milestone.messageId)) return;
            milestoneIds.add(milestone.messageId);
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
                ? "Answer corrected."
                : status === "unverified"
                  ? "Answer could not be verified."
                  : "Answer verified.",
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
            visibleAcc = segment.text;
            paintQueue.length = 0;
            pendingRevision = Math.max(pendingRevision, segment.revision);
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
        if (revealTimer !== null) window.clearTimeout(revealTimer);
        if (paintFrame !== null) cancelAnimationFrame(paintFrame);
        resolvePaintDrain();
        throw error;
      }
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
      ensureTurn();
      await waitForPaintDrain();
      if (isCurrent()) {
        setTurns((current) => {
          const next = current.map((turn) => {
            if (turn.id === activityTurnId) {
              return { ...turn, streaming: false, terminal: true };
            }
            return turn.id === deckId
              ? {
                  ...turn,
                  text: reply.text,
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
                }
              : turn;
          });
          turnsRef.current = next;
          return next;
        });
        pinTranscriptToLatest();
      }
    } finally {
      if (isCurrent()) {
        if (hasActivityTurn) {
          setTurns((current) => {
            const next = current.map((turn) => turn.id === activityTurnId
              ? { ...turn, streaming: false, terminal: true }
              : turn);
            turnsRef.current = next;
            return next;
          });
        }
        activeRequestRef.current = null;
        abortRef.current = null;
        inFlightRef.current = false;
        setPending(false);
        setRetrievalProgress(null);
        setSrStatus(controller.signal.aborted ? "Stopped." : "Answer ready.");
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
  ]);
}
