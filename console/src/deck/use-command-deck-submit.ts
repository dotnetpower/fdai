import { useCallback } from "preact/hooks";
import { t } from "../i18n";
import {
  askBackendStream,
  renderActionResult,
  submitAction,
  type BackendTurn,
  type VerificationProgress,
} from "./backend";
import { detectActionIntent } from "./action-intent";
import { watchActionProgress } from "./action-progress";
import { DEFAULT_NARRATOR, type Turn } from "./command-deck-presenters";
import { replyAgent, sessionIdFor } from "./command-deck-session";
import {
  conversationLabelForPrompt,
  conversationPath,
  type ConversationSummary,
} from "./conversation-sessions";
import type { ViewSnapshot } from "./context";
import { record as recordHistory, type DraftHistory } from "./draft-history";
import { drainStreamPaint } from "./stream-paint";

const MIN_PREPARING_VISIBLE_MS = 420;

export interface ActiveRequest {
  readonly id: string;
  readonly sessionKey: string;
  readonly controller: AbortController;
  readonly kind: "stream" | "action";
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
    const originSessionKey = sessionKeyRef.current;
    const controller = new AbortController();
    const action = detectActionIntent(text);
    const request: ActiveRequest = {
      id: newId(),
      sessionKey: originSessionKey,
      controller,
      kind: action ? "action" : "stream",
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

    if (action) {
      try {
        const result = await submitAction(
          text,
          sessionIdFor(sessionIdsRef.current, originSessionKey),
          controller.signal,
        );
        if (isCurrent()) {
          setPending(false);
          const resultTurn: Turn = {
              id: newId(),
              role: "deck",
              text: renderActionResult(result),
              agent: DEFAULT_NARRATOR,
              terminal: true,
              at: shortTime(),
          };
          const progressId = newId();
          const progressTurn: Turn | null = result.submitted && result.correlationId
            ? {
                id: progressId,
                role: "deck",
                text: `Tracking ${result.correlationId}`,
                agent: DEFAULT_NARRATOR,
                source: "action-progress",
                streaming: true,
                terminal: false,
                at: shortTime(),
              }
            : null;
          setTurns((current) => {
            const next = [...current, resultTurn, ...(progressTurn ? [progressTurn] : [])];
            turnsRef.current = next;
            return next;
          });
          if (progressTurn && result.correlationId) {
            void watchActionProgress(result.correlationId, (snapshot) => {
              setTurns((current) => {
                const next = current.map((turn) =>
                  turn.id === progressId
                    ? {
                        ...turn,
                        text: snapshot.text,
                        streaming: !snapshot.terminal,
                        terminal: snapshot.terminal,
                      }
                    : turn,
                );
                turnsRef.current = next;
                return next;
              });
              pinTranscriptToLatest();
            }).catch(() => {
              setTurns((current) => current.map((turn) =>
                turn.id === progressId
                  ? {
                      ...turn,
                      text: `${turn.text}\n- Progress stream unavailable. Use the trace for this correlation.`,
                      streaming: false,
                      terminal: true,
                    }
                  : turn,
              ));
            });
          }
        }
      } finally {
        if (isCurrent()) {
          activeRequestRef.current = null;
          abortRef.current = null;
          inFlightRef.current = false;
          setPending(false);
          setSrStatus(controller.signal.aborted
            ? "Response dismissed; submission outcome may be unknown."
            : "Answer ready.");
          setInFlight(false);
          focusInput();
        }
      }
      return;
    }

    const history: BackendTurn[] = turns.map((turn) => ({
      role: turn.role === "operator" ? "user" : "assistant",
      content: turn.text,
    }));
    try {
      const deckId = newId();
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
        await new Promise<void>((resolve) => {
          paintDrainResolve = resolve;
          scheduleStreamPaint();
        });
      };
      let reply: Awaited<ReturnType<typeof askBackendStream>>;
      try {
        reply = await askBackendStream(text, snapshot, history, {
          sessionId: sessionIdFor(sessionIdsRef.current, originSessionKey),
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
          const next = current.map((turn) =>
            turn.id === deckId
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
                  ...(reply.router ? { router: reply.router } : {}),
                  ...(reply.answerPlan ? { answerPlan: reply.answerPlan } : {}),
                  ...(reply.answerPlanning ? { answerPlanning: reply.answerPlanning } : {}),
                  ...(reply.codeArtifacts ? { codeArtifacts: reply.codeArtifacts } : {}),
                }
              : turn,
          );
          turnsRef.current = next;
          return next;
        });
        pinTranscriptToLatest();
      }
    } finally {
      if (isCurrent()) {
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
