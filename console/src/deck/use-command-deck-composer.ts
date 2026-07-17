import { useCallback, useEffect, useMemo } from "preact/hooks";
import { DEFAULT_NARRATOR, type Turn } from "./command-deck-presenters";
import {
  DECK_SLASH_COMMANDS,
  matchSlashCommand,
  slashHelpText,
  type DeckSlashCommand,
} from "./command-deck-slash";
import {
  recallNewer,
  recallOlder,
  type DraftHistory,
} from "./draft-history";

type StateSetter<T> = (value: T | ((current: T) => T)) => void;
interface MutableValueRef<T> {
  current: T;
}

interface UseCommandDeckComposerOptions {
  readonly draft: string;
  readonly turns: readonly Turn[];
  readonly slashActiveIndex: number;
  readonly historyRef: MutableValueRef<DraftHistory>;
  readonly turnsRef: MutableValueRef<readonly Turn[]>;
  readonly setDraft: StateSetter<string>;
  readonly setTurns: StateSetter<readonly Turn[]>;
  readonly setSlashActiveIndex: StateSetter<number>;
  readonly setSrStatus: StateSetter<string>;
  readonly submit: (text: string) => void;
  readonly startNewConversation: () => void;
  readonly clearTurns: () => void;
  readonly closeDeck: () => void;
  readonly cancelActiveRequest: () => "stream" | "action" | null;
}

function shortTime(): string {
  const date = new Date();
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}:${String(date.getSeconds()).padStart(2, "0")}`;
}

function newId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function useCommandDeckComposer({
  draft,
  turns,
  slashActiveIndex,
  historyRef,
  turnsRef,
  setDraft,
  setTurns,
  setSlashActiveIndex,
  setSrStatus,
  submit,
  startNewConversation,
  clearTurns,
  closeDeck,
  cancelActiveRequest,
}: UseCommandDeckComposerOptions) {
  const appendDeckNotice = useCallback((text: string) => {
    const turn: Turn = {
      id: newId(),
      role: "deck",
      text,
      agent: DEFAULT_NARRATOR,
      terminal: true,
      at: shortTime(),
    };
    setTurns((current) => [...current, turn]);
    turnsRef.current = [...turnsRef.current, turn];
  }, [setTurns, turnsRef]);

  const runSlashCommand = useCallback(
    (input: string): boolean => {
      const match = matchSlashCommand(input);
      if (match === null) return false;
      setDraft("");
      switch (match.canonical) {
        case "new":
          startNewConversation();
          break;
        case "clear":
          clearTurns();
          break;
        case "close":
          closeDeck();
          break;
        case "help":
          appendDeckNotice(slashHelpText());
          break;
        default:
          appendDeckNotice(`Unknown command "/${match.token}".\n\n${slashHelpText()}`);
      }
      return true;
    },
    [appendDeckNotice, clearTurns, closeDeck, setDraft, startNewConversation],
  );

  const stopStream = useCallback(() => {
    const kind = cancelActiveRequest();
    setSrStatus(kind === "action"
      ? "Response dismissed; submission outcome may be unknown."
      : "Stopped.");
  }, [cancelActiveRequest, setSrStatus]);

  const regenerateAt = useCallback(
    (deckIndex: number) => {
      for (let index = deckIndex - 1; index >= 0; index--) {
        const previous = turns[index];
        if (previous && previous.role === "operator") {
          void submit(previous.text);
          return;
        }
      }
    },
    [submit, turns],
  );

  const slashSuggestions = useMemo(() => {
    const trimmed = draft.trim();
    if (!/^\/\S*$/.test(trimmed)) return [] as DeckSlashCommand[];
    const token = trimmed.slice(1).toLowerCase();
    return DECK_SLASH_COMMANDS.filter(
      (command) =>
        command.name.startsWith(token) ||
        command.aliases.some((alias) => alias.startsWith(token)),
    );
  }, [draft]);

  useEffect(() => {
    setSlashActiveIndex((index) =>
      slashSuggestions.length === 0
        ? 0
        : Math.min(index, slashSuggestions.length - 1),
    );
  }, [setSlashActiveIndex, slashSuggestions.length]);

  const onInputKeyDown = useCallback(
    (event: KeyboardEvent) => {
      const input = event.target as HTMLTextAreaElement;
      if (slashSuggestions.length > 0) {
        if (event.key === "ArrowDown") {
          event.preventDefault();
          setSlashActiveIndex((index) => (index + 1) % slashSuggestions.length);
          return;
        }
        if (event.key === "ArrowUp") {
          event.preventDefault();
          setSlashActiveIndex(
            (index) => (index - 1 + slashSuggestions.length) % slashSuggestions.length,
          );
          return;
        }
        if (event.key === "Enter" && !event.shiftKey) {
          event.preventDefault();
          const picked = slashSuggestions[
            Math.min(slashActiveIndex, slashSuggestions.length - 1)
          ];
          if (picked) runSlashCommand(`/${picked.name}`);
          return;
        }
        if (event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          setDraft("");
          return;
        }
      }
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        if (runSlashCommand(input.value)) return;
        submit(input.value);
        return;
      }
      if (event.key === "ArrowUp") {
        const caretOnFirstLine = !input.value
          .slice(0, input.selectionStart ?? 0)
          .includes("\n");
        if (!caretOnFirstLine) return;
        const result = recallOlder(historyRef.current, input.value);
        historyRef.current = result.history;
        if (result.draft !== null) {
          event.preventDefault();
          setDraft(result.draft);
        }
        return;
      }
      if (event.key === "ArrowDown") {
        const caretOnLastLine = !input.value
          .slice(input.selectionStart ?? 0)
          .includes("\n");
        if (!caretOnLastLine) return;
        const result = recallNewer(historyRef.current);
        historyRef.current = result.history;
        if (result.draft !== null) {
          event.preventDefault();
          setDraft(result.draft);
        }
      }
    },
    [
      historyRef,
      runSlashCommand,
      setDraft,
      setSlashActiveIndex,
      slashActiveIndex,
      slashSuggestions,
      submit,
    ],
  );

  return {
    onInputKeyDown,
    regenerateAt,
    runSlashCommand,
    slashSuggestions,
    stopStream,
  };
}
