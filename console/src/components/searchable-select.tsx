import { autoUpdate, computePosition, flip, offset, shift, size } from "@floating-ui/dom";
import type { JSX } from "preact";
import { createPortal } from "preact/compat";
import { useCallback, useId, useLayoutEffect, useMemo, useRef, useState } from "preact/hooks";
import "./searchable-select.css";

/** A caller-owned choice; values must be unique and zero-count choices remain selectable. */
export interface SearchableSelectOption {
  readonly value: string;
  readonly label: string;
  readonly description?: string;
  readonly keywords?: readonly string[];
  readonly count?: number;
}

/** All presentation copy, including an optional all-values choice, belongs to the caller. */
export interface SearchableSelectProps {
  readonly label: string;
  readonly value: string;
  readonly options: readonly SearchableSelectOption[];
  readonly onChange: (value: string) => void;
  readonly placeholder: string;
  readonly emptyLabel: string;
  readonly helpText: string;
  readonly resultsLabel: (shown: number, total: number) => string;
  readonly disabled?: boolean;
}

function findSuggestions(options: readonly SearchableSelectOption[], query: string, value: string) {
  const tokens = query.normalize("NFC").toLocaleLowerCase().trim().split(/\s+/u).filter(Boolean);
  const matches = options.filter((option) => {
    const text = [option.label, option.description ?? "", ...(option.keywords ?? [])]
      .join(" ").normalize("NFC").toLocaleLowerCase();
    return tokens.every((token) => text.includes(token));
  });
  const selected = matches.find((option) => option.value === value);
  const ordered = selected
    ? [selected, ...matches.filter((option) => option.value !== value)]
    : matches;
  return { suggestions: ordered.slice(0, 12), total: matches.length };
}

function revealHighlight(list: HTMLUListElement | null): void {
  const option = list?.querySelector<HTMLElement>('[data-highlighted="true"]');
  if (!list || !option) return;
  const viewport = list.getBoundingClientRect();
  const item = option.getBoundingClientRect();
  if (item.top < viewport.top) list.scrollTop += item.top - viewport.top;
  else if (item.bottom > viewport.bottom) list.scrollTop += item.bottom - viewport.bottom;
}

/**
 * A controlled, manual-selection combobox that searches every option and displays at most 12 matches.
 * Only an option click or Enter on a keyboard-highlighted option calls onChange.
 * Dismissal discards the draft, and focus alone never opens the list.
 */
export function SearchableSelect({
  label, value, options, onChange, placeholder, emptyLabel, helpText, resultsLabel, disabled = false,
}: SearchableSelectProps) {
  const id = useId();
  const committedLabel = options.find((option) => option.value === value)?.label ?? "";
  const rootRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const popupRef = useRef<HTMLDivElement | null>(null);
  const listRef = useRef<HTMLUListElement | null>(null);
  const openRef = useRef(false);
  const draftRef = useRef(committedLabel);
  const composition = useRef<"idle" | "active" | "ended" | "cancelled">("idle");
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(committedLabel);
  const [query, setQuery] = useState("");
  const [highlighted, setHighlighted] = useState<string | null>(null);
  const { suggestions, total } = useMemo(
    () => findSuggestions(options, query, value), [options, query, value],
  );
  const highlightedIndex = suggestions.findIndex((option) => option.value === highlighted);
  const expanded = open && !disabled;

  const dismiss = useCallback(() => {
    if (composition.current !== "idle") composition.current = "cancelled";
    openRef.current = false;
    draftRef.current = committedLabel;
    setOpen(false);
    setDraft(committedLabel);
    setQuery("");
    setHighlighted(null);
    if (inputRef.current) inputRef.current.value = committedLabel;
  }, [committedLabel]);

  useLayoutEffect(dismiss, [dismiss, value, disabled]);

  useLayoutEffect(() => {
    const outside = (event: Event) => {
      const target = event.target;
      if (target instanceof Node
        && (rootRef.current?.contains(target) || popupRef.current?.contains(target))) return;
      dismiss();
    };
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("click", outside, true);
    window.addEventListener("blur", dismiss);
    return () => {
      document.removeEventListener("pointerdown", outside, true);
      document.removeEventListener("click", outside, true);
      window.removeEventListener("blur", dismiss);
    };
  }, [dismiss]);

  useLayoutEffect(() => {
    const input = inputRef.current;
    const popup = popupRef.current;
    if (!expanded || !input || !popup) return;
    let active = true;
    let revision = 0;
    const update = () => {
      const request = ++revision;
      void computePosition(input, popup, {
        strategy: "fixed",
        placement: "bottom-start",
        middleware: [
          offset(4),
          flip({ padding: 8 }),
          shift({ padding: 8 }),
          size({
            padding: 8,
            apply({ availableWidth, availableHeight, rects }) {
              if (!active || request !== revision) return;
              popup.style.width = `${Math.max(0, Math.min(Math.max(320, rects.reference.width), availableWidth))}px`;
              popup.style.maxHeight = `${Math.max(0, Math.min(360, availableHeight))}px`;
            },
          }),
        ],
      }).then((position) => {
        if (!active || request !== revision) return;
        popup.style.left = `${position.x}px`;
        popup.style.top = `${position.y}px`;
        popup.style.visibility = "visible";
        revealHighlight(listRef.current);
      });
    };
    const cleanup = autoUpdate(input, popup, update);
    return () => {
      active = false;
      cleanup();
    };
  }, [expanded]);

  useLayoutEffect(() => {
    if (expanded) revealHighlight(listRef.current);
  }, [expanded, highlighted, suggestions]);

  function restoreInput(): void {
    if (inputRef.current) {
      inputRef.current.value = openRef.current ? draftRef.current : committedLabel;
    }
  }

  function show(): void {
    if (disabled || openRef.current) return;
    openRef.current = true;
    draftRef.current = committedLabel;
    setDraft(committedLabel);
    setQuery("");
    setHighlighted(null);
    setOpen(true);
  }

  function edit(text: string): void {
    if (disabled || document.activeElement !== inputRef.current) {
      restoreInput();
      return;
    }
    draftRef.current = text;
    openRef.current = true;
    setDraft(text);
    setQuery(text);
    setHighlighted(null);
    setOpen(true);
  }

  function select(option: SearchableSelectOption): void {
    if (disabled || !openRef.current) return;
    dismiss();
    if (option.value !== value) onChange(option.value);
  }

  function onInput(event: JSX.TargetedInputEvent<HTMLInputElement>): void {
    // Some IMEs emit a final insertText after compositionend, including after dismissal.
    // Only a fresh edit gesture or compositionstart releases a cancelled composition.
    const compositionInput = event.isComposing || event.inputType?.toLowerCase().includes("composition");
    if (composition.current === "cancelled"
      || (compositionInput && composition.current !== "active" && composition.current !== "ended")) {
      composition.current = "cancelled";
      restoreInput();
      return;
    }
    edit(event.currentTarget.value);
  }

  function onKeyDown(event: JSX.TargetedKeyboardEvent<HTMLInputElement>): void {
    if (event.key === "Escape" || event.key === "Tab") {
      if (event.key === "Escape") event.preventDefault();
      dismiss();
      return;
    }
    if (event.isComposing || event.keyCode === 229 || composition.current === "active") return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const choices = openRef.current ? suggestions : findSuggestions(options, "", value).suggestions;
      const current = openRef.current ? highlightedIndex : -1;
      show();
      const index = current < 0
        ? event.key === "ArrowDown" ? 0 : choices.length - 1
        : (current + (event.key === "ArrowDown" ? 1 : -1) + choices.length) % choices.length;
      setHighlighted(choices[index]?.value ?? null);
    } else if (event.key === "Enter" && openRef.current) {
      event.preventDefault();
      const option = suggestions[highlightedIndex];
      if (option) select(option);
    } else if (event.key.length === 1 || event.key === "Backspace" || event.key === "Delete") {
      composition.current = "idle";
    }
  }

  return (
    <div ref={rootRef} class="searchable-select">
      <label class="searchable-select-label" id={`${id}-label`} for={`${id}-input`}>{label}</label>
      <div class="searchable-select-control">
        <input
          ref={inputRef}
          id={`${id}-input`}
          class="cs-control-input searchable-select-input"
          type="text"
          role="combobox"
          value={expanded ? draft : committedLabel}
          placeholder={placeholder}
          disabled={disabled}
          autoComplete="off"
          spellcheck={false}
          aria-autocomplete="list"
          aria-haspopup="listbox"
          aria-expanded={expanded}
          aria-controls={expanded ? `${id}-list` : undefined}
          aria-activedescendant={expanded && highlightedIndex >= 0 ? `${id}-option-${highlightedIndex}` : undefined}
          aria-describedby={`${id}-help`}
          onClick={(event) => {
            if (!openRef.current) {
              show();
              event.currentTarget.select();
            }
          }}
          onInput={onInput}
          onKeyDown={onKeyDown}
          onBlur={dismiss}
          onPaste={() => { composition.current = "idle"; }}
          onCut={() => { composition.current = "idle"; }}
          onCompositionStart={() => {
            composition.current = disabled || document.activeElement !== inputRef.current
              ? "cancelled" : "active";
          }}
          onCompositionEnd={(event) => {
            if (composition.current !== "active") {
              composition.current = "cancelled";
              restoreInput();
              return;
            }
            composition.current = "ended";
            edit(event.currentTarget.value);
          }}
        />
        <svg class="searchable-select-chevron" viewBox="0 0 16 16" aria-hidden="true">
          <path d="m4 6 4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.5" />
        </svg>
      </div>
      <p id={`${id}-help`} class="searchable-select-help">{helpText}</p>
      {expanded && typeof document !== "undefined" ? createPortal(
        <div
          ref={popupRef}
          class="searchable-select-popup"
          onMouseDown={(event) => event.preventDefault()}
        >
          <p class="searchable-select-results" role="status" aria-live="polite" aria-atomic="true">
            {resultsLabel(suggestions.length, total)}
          </p>
          <ul ref={listRef} id={`${id}-list`} class="searchable-select-list" role="listbox" aria-labelledby={`${id}-label`}>
            {suggestions.map((option, index) => (
              <li
                key={option.value}
                id={`${id}-option-${index}`}
                class="searchable-select-option"
                role="option"
                aria-selected={option.value === value}
                data-highlighted={option.value === highlighted ? "true" : undefined}
                onPointerDown={(event) => {
                  if (event.pointerType !== "touch") event.preventDefault();
                }}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => select(option)}
              >
                <svg class="searchable-select-check" viewBox="0 0 16 16" aria-hidden="true">
                  {option.value === value
                    ? <path d="m3 8 3 3 7-7" fill="none" stroke="currentColor" stroke-width="1.5" />
                    : null}
                </svg>
                <span class="searchable-select-option-copy">
                  <span class="searchable-select-option-label">{option.label}</span>
                  {option.description
                    ? <span class="searchable-select-description">{option.description}</span> : null}
                </span>
                {option.count !== undefined
                  ? <span class="searchable-select-count">{option.count}</span> : null}
              </li>
            ))}
          </ul>
          <p class="searchable-select-results">{helpText}</p>
          {suggestions.length === 0 ? <p class="searchable-select-empty">{emptyLabel}</p> : null}
        </div>,
        document.body,
      ) : null}
    </div>
  );
}
