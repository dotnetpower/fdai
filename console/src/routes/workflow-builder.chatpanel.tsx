/**
 * Workflow-builder conversational UI - the chat surface that replaces the
 * form. It renders the deterministic interview (workflow-builder.chat.ts)
 * as a message thread with option chips, and at the `ready` stage it runs
 * the existing pure validate path on the accumulated draft and shows the
 * generated YAML, a visual "when -> do" flow, the dry-test result, and a
 * one-click "open a PR" link.
 *
 * Read-only by construction: `POST /workflows/validate` is a pure check
 * and nothing here mutates control-plane state. The operator copies the
 * YAML into a remediation PR through the git-native path, never a console
 * button (app-shape.instructions.md § Operator console).
 *
 * SRP: React tree + local view state only. All decision logic lives in
 * the engine; all draft assembly / validation reuse the shared helpers.
 */

import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { Fragment, type ComponentChildren } from "preact";
import { CopyButton } from "../components/ui";
import type { ActionTypePaletteEntry, ValidateResponse } from "../workflow/validate";
import { buildDraft, githubNewFileUrl, humanizeActionName, signalLabel } from "./workflow-builder.helpers";
import type { FormState } from "./workflow-builder.model";
import { validateWorkflowDraft } from "../workflow/validate";
import {
  respondToChat,
  startChat,
  type BotTurn,
  type ChatOption,
  type ChatSlots,
} from "./workflow-builder.chat";

interface Props {
  readonly palette: readonly ActionTypePaletteEntry[];
  readonly onBack: () => void;
}

/** One rendered message in the thread. */
interface Message {
  readonly id: number;
  readonly role: "bot" | "operator";
  readonly text: string;
  readonly options?: readonly ChatOption[];
  /** Present on the final bot message: the finished draft to preview. */
  readonly preview?: FormState | undefined;
}

export function WorkflowChat({ palette, onBack }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [slots, setSlots] = useState<ChatSlots | null>(null);
  const [input, setInput] = useState("");
  const idRef = useRef(0);
  const threadRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const nextId = () => (idRef.current += 1);

  // Open with the welcome turn.
  useEffect(() => {
    const turn = startChat(palette);
    setSlots(turn.slots);
    setMessages([botMessage(turn, nextId())]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [palette]);

  // Focus the composer on mount so an operator can start typing immediately.
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Keep the newest message in view, honoring reduced-motion preference.
  useEffect(() => {
    const behavior: ScrollBehavior = prefersReducedMotion() ? "auto" : "smooth";
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight, behavior });
  }, [messages]);

  function send(raw: string): void {
    const text = raw.trim();
    if (text.length === 0 || slots === null) return;
    const shown = displayInput(text, messages);
    const opMsg: Message = { id: nextId(), role: "operator", text: shown };
    const turn = respondToChat(slots, text, palette);
    setSlots(turn.slots);
    setMessages((prev) => [...prev, opMsg, botMessage(turn, nextId())]);
    setInput("");
  }

  return (
    <div class="stack wf-chat">
      <div class="section-header">
        <button type="button" class="btn btn-small" onClick={onBack}>
          ← Back to workflows
        </button>
        <span class="muted small">
          Conversational designer - deterministic, read-only. Nothing is created until you open a
          PR.
        </span>
      </div>

      <div class="wf-chat-thread" ref={threadRef} role="log" aria-live="polite">
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} palette={palette} onChip={send} />
        ))}
      </div>

      <form
        class="wf-chat-input"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <textarea
          class="form-input"
          rows={2}
          ref={inputRef}
          value={input}
          placeholder="Describe what should happen, or answer the question above..."
          aria-label="Message the workflow designer"
          onInput={(e) => setInput((e.target as HTMLTextAreaElement).value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(input);
            }
          }}
        />
        <button type="submit" class="btn" disabled={input.trim().length === 0}>
          Send
        </button>
      </form>
    </div>
  );
}

function botMessage(turn: BotTurn, id: number): Message {
  return {
    id,
    role: "bot",
    text: turn.text,
    options: turn.options,
    preview: turn.draftReady ? turn.slots.form : undefined,
  };
}

/** True when the operator asked the OS to minimize motion; falls back to
 * animated scrolling when the API is unavailable (SSR / older browsers). */
function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/** What to echo as the operator's bubble: a clicked chip shows its human
 * label (found in the previous bot turn), free text shows verbatim. */
function displayInput(raw: string, messages: readonly Message[]): string {
  const lastBot = [...messages].reverse().find((m) => m.role === "bot");
  const opt = lastBot?.options?.find((o) => o.value === raw);
  if (opt) return opt.label;
  if (raw.startsWith("seed:")) return raw.slice("seed:".length);
  return raw;
}

// ---------------------------------------------------------------------------
// Message rendering
// ---------------------------------------------------------------------------

function MessageBubble({
  message,
  palette,
  onChip,
}: {
  readonly message: Message;
  readonly palette: readonly ActionTypePaletteEntry[];
  readonly onChip: (value: string) => void;
}) {
  const isBot = message.role === "bot";
  return (
    <div class={isBot ? "wf-msg wf-msg-bot" : "wf-msg wf-msg-op"}>
      <div class="wf-msg-body">
        <span class="sr-only">{isBot ? "Assistant:" : "You:"} </span>
        <RichText text={message.text} />
        {message.preview ? <WorkflowPreview form={message.preview} palette={palette} /> : null}
        {message.options && message.options.length > 0 ? (
          <div class="wf-chip-row" role="group" aria-label="Suggested replies">
            {message.options.map((o) => (
              <button
                type="button"
                class="wf-chip"
                key={o.value}
                title={o.hint}
                aria-label={o.hint ? `${o.label} - ${o.hint}` : o.label}
                onClick={() => onChip(o.value)}
              >
                {o.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** Minimal inline markdown: paragraphs, `- ` bullets, `**bold**`, `*em*`,
 * and `` `code` ``. Deliberately tiny - the engine text is trusted and
 * plain; this is presentation only, never HTML injection. */
function RichText({ text }: { readonly text: string }) {
  const blocks = text.split("\n");
  const out: ComponentChildren[] = [];
  let bullets: ComponentChildren[] = [];
  const flush = (key: string) => {
    if (bullets.length > 0) {
      out.push(<ul class="wf-md-list" key={`ul-${key}`}>{bullets}</ul>);
      bullets = [];
    }
  };
  blocks.forEach((line, i) => {
    const trimmed = line.trim();
    if (trimmed.startsWith("- ")) {
      bullets.push(<li key={i}>{inline(trimmed.slice(2))}</li>);
      return;
    }
    flush(String(i));
    if (trimmed.length > 0) out.push(<p key={i}>{inline(trimmed)}</p>);
  });
  flush("end");
  return <Fragment>{out}</Fragment>;
}

/** Parse a single line into <strong>/<em>/<code> spans. */
function inline(text: string): ComponentChildren {
  const parts: ComponentChildren[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith("**")) parts.push(<strong key={k}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`")) parts.push(<code key={k}>{tok.slice(1, -1)}</code>);
    else parts.push(<em key={k}>{tok.slice(1, -1)}</em>);
    last = m.index + tok.length;
    k += 1;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

// ---------------------------------------------------------------------------
// Ready-stage preview: visualization + generated YAML + dry test + PR
// ---------------------------------------------------------------------------

function WorkflowPreview({
  form,
  palette,
}: {
  readonly form: FormState;
  readonly palette: readonly ActionTypePaletteEntry[];
}) {
  const [result, setResult] = useState<ValidateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [validating, setValidating] = useState(true);

  const draft = useMemo(() => buildDraft(form), [form]);

  useEffect(() => {
    let cancelled = false;
    setValidating(true);
    setError(null);
    validateWorkflowDraft(draft)
      .then((res) => {
        if (!cancelled) setResult(res);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setValidating(false);
      });
    return () => {
      cancelled = true;
    };
  }, [draft]);

  const yaml = result?.yaml_preview ?? null;
  const prUrl = yaml ? githubNewFileUrl(`rule-catalog/workflows/${form.name}.yaml`, yaml) : null;

  return (
    <div class="wf-preview">
      <WorkflowViz form={form} palette={palette} />

      <div class="wf-preview-section">
        <h4 class="wf-preview-title">Generated workflow</h4>
        {yaml ? (
          <>
            <div class="code-actions">
              <CopyButton text={yaml} label="Copy YAML" />
            </div>
            <pre class="mono scroll code-block">{yaml}</pre>
          </>
        ) : (
          <p class="muted small">
            {validating ? "Generating YAML..." : "YAML is available once the draft validates."}
          </p>
        )}
      </div>

      <div class="wf-preview-section">
        <h4 class="wf-preview-title">Dry test</h4>
        {validating ? (
          <p class="muted small" aria-busy="true">
            Testing the draft against the server-side loader...
          </p>
        ) : error ? (
          <p class="wf-test-fail">Could not reach the validator: {error}</p>
        ) : result ? (
          <TestResult result={result} />
        ) : null}
      </div>

      {yaml ? (
        <div class="wf-preview-section wf-preview-cta">
          {prUrl ? (
            <a class="btn" href={prUrl} target="_blank" rel="noopener noreferrer">
              Open a PR on GitHub →
            </a>
          ) : null}
          <span class="muted small">
            The console never commits. This opens a pre-filled new-file PR at
            {" "}
            <code>rule-catalog/workflows/{form.name}.yaml</code>; it lands in <strong>shadow</strong>
            {" "}
            mode until a separate promotion PR.
          </span>
        </div>
      ) : null}
    </div>
  );
}

function TestResult({ result }: { readonly result: ValidateResponse }) {
  if (result.valid) {
    return (
      <p class="wf-test-pass">
        Passed - the draft is structurally valid, every step resolves to a real ActionType, and it
        loads cleanly. Running it now would execute in shadow (judge-and-log, no mutation).
      </p>
    );
  }
  return (
    <div class="wf-test-fail">
      <p>
        {result.issues.length} issue{result.issues.length === 1 ? "" : "s"} to fix before this can
        be published:
      </p>
      <ul class="wf-issue-list">
        {result.issues.map((iss, i) => (
          <li key={i}>
            <code>{iss.key}</code> - {iss.message}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Visualization: a vertical "when -> do" node chain (mirrors the mock)
// ---------------------------------------------------------------------------

function WorkflowViz({
  form,
  palette,
}: {
  readonly form: FormState;
  readonly palette: readonly ActionTypePaletteEntry[];
}) {
  const catOf = useMemo(() => {
    const m = new Map<string, string>();
    for (const p of palette) m.set(p.name, p.category ?? "other");
    return m;
  }, [palette]);

  const triggerLabel =
    form.triggerKind === "signal"
      ? signalLabel(form.signalType) || form.signalType || "an event"
      : form.schedule || "a schedule";
  const steps = form.steps.filter((s) => s.action_type_ref.trim().length > 0);

  return (
    <div class="wf-viz" aria-label="Workflow visualization">
      <div class="wf-viz-node wf-viz-trigger">
        <span class="wf-viz-kind">when</span>
        <span class="wf-viz-name">{triggerLabel}</span>
        <span class="wf-viz-ref mono">
          {form.triggerKind === "signal" ? form.signalType : form.schedule}
        </span>
      </div>
      {steps.map((s, i) => {
        const cat = catOf.get(s.action_type_ref) ?? "other";
        return (
          <Fragment key={s.key}>
            <div class="wf-viz-edge" aria-hidden="true">
              <span class="wf-viz-edge-label">{i === 0 ? "then do" : "then"}</span>
            </div>
            <div class={`wf-viz-node wf-viz-action is-${cat}`}>
              <span class="wf-viz-kind">{cat === "tool" ? "notify" : "do"}</span>
              <span class="wf-viz-name">{humanizeActionName(s.action_type_ref)}</span>
              <span class="wf-viz-ref mono">{s.action_type_ref}</span>
            </div>
          </Fragment>
        );
      })}
      <div class="wf-viz-edge" aria-hidden="true"></div>
      <div class="wf-viz-node wf-viz-end">
        <span class="wf-viz-name">done</span>
      </div>
    </div>
  );
}
