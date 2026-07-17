import { useCallback } from "preact/hooks";
import type { Turn } from "./command-deck-presenters";

const CONTEXT_TYPE_MS = 14;

type StateSetter<T> = (value: T | ((current: T) => T)) => void;
interface MutableValueRef<T> {
  current: T;
}

interface UseContextTurnStreamOptions {
  readonly turnsRef: MutableValueRef<readonly Turn[]>;
  readonly contextTimersRef: MutableValueRef<Set<number>>;
  readonly setTurns: StateSetter<readonly Turn[]>;
}

function shortTime(): string {
  const date = new Date();
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}:${String(date.getSeconds()).padStart(2, "0")}`;
}

function newId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function contextChunks(text: string): string[] {
  const chunks: string[] = [];
  const pattern = /\s*\S{1,4}|\s+$/g;
  for (const match of text.matchAll(pattern)) chunks.push(match[0]);
  return chunks.length > 0 ? chunks : [text];
}

export function useContextTurnStream({
  turnsRef,
  contextTimersRef,
  setTurns,
}: UseContextTurnStreamOptions) {
  return useCallback((
    agent: string | null,
    fullText: string,
    source = "context",
  ) => {
    const turnId = newId();
    const shouldAnimate =
      document.visibilityState !== "hidden" &&
      (typeof document.hasFocus !== "function" || document.hasFocus());
    const seed: Turn = {
      id: turnId,
      role: "deck",
      text: shouldAnimate ? "" : fullText,
      source,
      streaming: shouldAnimate,
      at: shortTime(),
      ...(agent ? { agent } : {}),
    };
    setTurns((current) => [...current, seed]);
    turnsRef.current = [...turnsRef.current, seed];
    if (!shouldAnimate) return;
    const chunks = contextChunks(fullText);
    let index = 0;
    const scheduleStep = (): void => {
      const timer = window.setTimeout(() => {
        contextTimersRef.current.delete(timer);
        step();
      }, CONTEXT_TYPE_MS);
      contextTimersRef.current.add(timer);
    };
    const step = (): void => {
      if (index >= chunks.length) {
        setTurns((current) =>
          current.map((turn) =>
            turn.id === turnId ? { ...turn, streaming: false } : turn,
          ),
        );
        return;
      }
      const piece = chunks[index]!;
      index += 1;
      setTurns((current) =>
        current.map((turn) =>
          turn.id === turnId ? { ...turn, text: turn.text + piece } : turn,
        ),
      );
      scheduleStep();
    };
    scheduleStep();
  }, [contextTimersRef, setTurns, turnsRef]);
}
