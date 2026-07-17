import { useCallback, useEffect, useRef } from "preact/hooks";
import type { VerificationProgress } from "./backend";
import { clearScheduledTimeouts } from "./command-deck-session";
import type { Turn } from "./command-deck-presenters";
import type { ActiveRequest } from "./use-command-deck-submit";

type StateSetter<T> = (value: T | ((current: T) => T)) => void;

interface LifecycleOptions {
  readonly setOpen: StateSetter<boolean>;
  readonly setTurns: StateSetter<readonly Turn[]>;
  readonly setPending: StateSetter<boolean>;
  readonly setRetrievalProgress: StateSetter<VerificationProgress | null>;
  readonly setInFlight: StateSetter<boolean>;
  readonly turnsRef: { current: readonly Turn[] };
  readonly activeRequestRef: { current: ActiveRequest | null };
  readonly abortRef: { current: AbortController | null };
  readonly inFlightRef: { current: boolean };
  readonly contextTimersRef: { current: Set<number> };
  readonly inputRef: { current: HTMLTextAreaElement | null };
}

export function useCommandDeckLifecycle({
  setOpen,
  setTurns,
  setPending,
  setRetrievalProgress,
  setInFlight,
  turnsRef,
  activeRequestRef,
  abortRef,
  inFlightRef,
  contextTimersRef,
  inputRef,
}: LifecycleOptions) {
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  const focusInput = useCallback(() => {
    requestAnimationFrame(() => inputRef.current?.focus());
  }, [inputRef]);

  const openDeck = useCallback(() => {
    restoreFocusRef.current = (document.activeElement as HTMLElement | null) ?? null;
    setOpen(true);
    focusInput();
  }, [focusInput, setOpen]);

  const cancelActiveRequest = useCallback((): ActiveRequest["kind"] | null => {
    clearScheduledTimeouts(contextTimersRef.current);
    const active = activeRequestRef.current;
    activeRequestRef.current = null;
    abortRef.current = null;
    active?.controller.abort();
    inFlightRef.current = false;
    const completed = turnsRef.current.map((turn) =>
      turn.streaming
        ? {
            ...turn,
            streaming: false,
            terminal: false,
            verificationProgress: {
              phase: "unverified",
              label: "Verification stopped",
              completed: null,
              total: null,
            },
          }
        : turn,
    );
    turnsRef.current = completed;
    setTurns(completed);
    setPending(false);
    setRetrievalProgress(null);
    setInFlight(false);
    return active?.kind ?? null;
  }, [
    abortRef,
    activeRequestRef,
    contextTimersRef,
    inFlightRef,
    setInFlight,
    setPending,
    setRetrievalProgress,
    setTurns,
    turnsRef,
  ]);

  const closeDeck = useCallback(() => {
    cancelActiveRequest();
    setOpen(false);
    const target = restoreFocusRef.current;
    if (target && typeof target.focus === "function") {
      requestAnimationFrame(() => target.focus());
    }
  }, [cancelActiveRequest, setOpen]);

  useEffect(() => () => cancelActiveRequest(), [cancelActiveRequest]);

  return { cancelActiveRequest, closeDeck, focusInput, openDeck };
}
