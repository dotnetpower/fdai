/**
 * Workflow-builder conversational UI - the chat surface that replaces the
 * form. It renders the deterministic interview (workflow-builder.chat.ts)
 * as a message thread with option chips, and at the `ready` stage it runs
 * the existing pure validate path on the accumulated draft and shows the
 * generated YAML, a visual "when -> do" flow, the structural validation result, and a
 * one-click "open a PR" link.
 *
 * Safe authoring by construction: `POST /workflows/validate` is a pure check,
 * and an explicitly confirmed save creates only a private DRAFT. Publishing,
 * binding, enabling, and executing remain separate reviewed paths.
 *
 * SRP: React tree + local view state only. All decision logic lives in
 * the engine; all draft assembly / validation reuse the shared helpers.
 */

import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { Fragment, type ComponentChildren } from "preact";
import { Tooltip } from "../components/tooltip";
import { CopyButton } from "../components/ui";
import {
  createWorkflowDefinition,
  type ActionTypePaletteEntry,
  type SavedWorkflowDraft,
  type ValidateResponse,
} from "../workflow/validate";
import { buildDraft, githubNewFileUrl } from "./workflow-builder.helpers";
import type { FormState } from "./workflow-builder.model";
import { validateWorkflowDraft } from "../workflow/validate";
import { parseBlocks, type InlineToken } from "./workflow-builder.richtext";
import { buildVizModel } from "./workflow-builder.viz";
import { WorkflowDraftEditor } from "./workflow-builder.draft-editor";
import { validateDraftStructure } from "./workflow-builder.structure";
import {
  loadWorkflowChatSession,
  saveWorkflowChatSession,
} from "./workflow-builder.session";
import { formatNumber, t } from "./i18n/workflow";
import {
  respondToChat,
  startChat,
  SEED_PREFIX,
  type BotTurn,
  type ChatOption,
  type ChatSlots,
} from "./workflow-builder.chat";

interface Props {
  readonly palette: readonly ActionTypePaletteEntry[];
  readonly gateRefs: readonly string[];
  readonly onBack: () => void;
}

/** One rendered message in the thread. */
export interface Message {
  readonly id: number;
  readonly role: "bot" | "operator";
  readonly text: string;
  readonly options?: readonly ChatOption[];
  /** Present on the final bot message: the finished draft to preview. */
  readonly preview?: FormState | undefined;
}

export function WorkflowChat({ palette, gateRefs, onBack }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [slots, setSlots] = useState<ChatSlots | null>(null);
  const [input, setInput] = useState("");
  const [restored, setRestored] = useState(false);
  const idRef = useRef(0);
  const threadRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  // One send per render cycle: set on send, cleared when the thread re-renders.
  // Stops an Enter-press racing a chip click into two turns off the same slots.
  const busyRef = useRef(false);

  const nextId = () => (idRef.current += 1);

  // Open with the welcome turn - once, on mount. The parent only renders this
  // component after the palette has loaded, so palette is always present here;
  // keying the init on mount (not on palette identity) means a parent that
  // ever hands back a fresh array reference cannot silently reset a
  // conversation in progress.
  useEffect(() => {
    const recovered = loadWorkflowChatSession(workflowSessionStorage());
    if (recovered !== null) {
      setSlots(recovered.slots);
      setMessages([...recovered.messages]);
      idRef.current = Math.max(0, ...recovered.messages.map((message) => message.id));
      setRestored(true);
      return;
    }
    const turn = startChat(palette);
    setSlots(turn.slots);
    setMessages([botMessage(turn, nextId())]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (slots !== null && messages.length > 0) {
      saveWorkflowChatSession(workflowSessionStorage(), { messages, slots });
    }
  }, [messages, slots]);

  // Focus the composer on mount so an operator can start typing immediately.
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Keep the newest message in view, honoring reduced-motion preference; also
  // release the per-cycle send guard now that the new turn has rendered.
  useEffect(() => {
    busyRef.current = false;
    const behavior: ScrollBehavior = prefersReducedMotion() ? "auto" : "smooth";
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight, behavior });
  }, [messages]);

  function send(raw: string): void {
    const text = raw.trim();
    if (busyRef.current || text.length === 0 || slots === null) return;
    busyRef.current = true;
    const shown = displayInput(text, messages);
    const opMsg: Message = { id: nextId(), role: "operator", text: shown };
    const turn = respondToChat(slots, text, palette);
    setSlots(turn.slots);
    setMessages((prev) => [...prev, opMsg, botMessage(turn, nextId())]);
    setInput("");
  }

  function updatePreview(messageId: number, form: FormState): void {
    setSlots((current) => current === null ? current : { ...current, form });
    setMessages((current) => current.map((message) =>
      message.id === messageId ? { ...message, preview: form } : message
    ));
  }

  // Only the newest bot turn's chips stay interactive; older chips go inert so
  // a click on a stale suggestion cannot apply to a later stage.
  const latestBotId = messages.reduce((acc, m) => (m.role === "bot" ? m.id : acc), -1);
  // With no ActionType palette the deployment did not wire authoring, so there
  // are no building blocks - the composer is disabled and the welcome turn
  // already explains how to enable it.
  const paletteReady = palette.length > 0;

  return (
    <div class="stack wf-chat">
      <div class="section-header">
        <button type="button" class="btn btn-small" onClick={onBack}>
          &larr; {t("workflow.chat.back")}
        </button>
        <span class="muted small">
          {t("workflow.chat.disclaimer")}
        </span>
        {restored ? (
          <span class="muted small" role="status">{t("workflow.chat.recovered")}</span>
        ) : null}
      </div>

      <div class="wf-chat-thread" ref={threadRef} role="log" aria-live="polite">
        {messages.map((m) => (
          <MessageBubble
            key={m.id}
            message={m}
            palette={palette}
            gateRefs={gateRefs}
            onChip={send}
            interactive={m.id === latestBotId}
            onPreviewChange={(form) => updatePreview(m.id, form)}
          />
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
          disabled={!paletteReady}
          placeholder={
            paletteReady
              ? t("workflow.chat.placeholderReady")
              : t("workflow.chat.placeholderDisabled")
          }
          aria-label={t("workflow.chat.composerAria")}
          onInput={(e) => setInput((e.target as HTMLTextAreaElement).value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(input);
            }
          }}
        />
        <button type="submit" class="btn" disabled={!paletteReady || input.trim().length === 0}>
          {t("workflow.chat.send")}
        </button>
      </form>
    </div>
  );
}

function workflowSessionStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    return null;
  }
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
 * label (found in the previous bot turn), free text shows verbatim. Pure and
 * exported for tests. */
export function displayInput(raw: string, messages: readonly Message[]): string {
  const lastBot = [...messages].reverse().find((m) => m.role === "bot");
  const opt = lastBot?.options?.find((o) => o.value === raw);
  if (opt) return opt.label;
  if (raw.startsWith(SEED_PREFIX)) return raw.slice(SEED_PREFIX.length);
  return raw;
}

// ---------------------------------------------------------------------------
// Message rendering
// ---------------------------------------------------------------------------

function MessageBubble({
  message,
  palette,
  gateRefs,
  onChip,
  interactive,
  onPreviewChange,
}: {
  readonly message: Message;
  readonly palette: readonly ActionTypePaletteEntry[];
  readonly gateRefs: readonly string[];
  readonly onChip: (value: string) => void;
  readonly interactive: boolean;
  readonly onPreviewChange: (form: FormState) => void;
}) {
  const isBot = message.role === "bot";
  return (
    <div class={isBot ? "wf-msg wf-msg-bot" : "wf-msg wf-msg-op"}>
      <div class="wf-msg-body">
        <span class="sr-only">{t(isBot ? "workflow.chat.assistant" : "workflow.chat.you")} </span>
        {isBot ? (
          <RichText text={message.text} />
        ) : (
          // The operator's text is untrusted echo: render it as plain text,
          // never through the markdown parser (correctness + defense in depth).
          <p class="wf-msg-plain">{message.text}</p>
        )}
        {message.preview ? (
          <WorkflowPreview
            form={message.preview}
            palette={palette}
            gateRefs={gateRefs}
            onChange={onPreviewChange}
          />
        ) : null}
        {message.options && message.options.length > 0 ? (
          <div
            class={interactive ? "wf-chip-row" : "wf-chip-row is-inert"}
            role="group"
            aria-label={t("workflow.chat.suggestedReplies")}
          >
            {message.options.map((o) => (
              <Tooltip key={o.value} content={o.hint}>
                <button
                  type="button"
                  class="wf-chip"
                  aria-label={o.hint ? `${o.label} - ${o.hint}` : o.label}
                  disabled={!interactive}
                  onClick={() => onChip(o.value)}
                >
                  {o.label}
                </button>
              </Tooltip>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** Minimal inline markdown: paragraphs, `- ` bullets, `**bold**`, `*em*`,
 * and `` `code` ``. Rendering only - all parsing lives in the pure
 * `workflow-builder.richtext` tokenizer (trusted, plain engine text; never
 * HTML injection). */
function RichText({ text }: { readonly text: string }) {
  const blocks = parseBlocks(text);
  const out: ComponentChildren[] = [];
  let bullets: ComponentChildren[] = [];
  const flush = (key: string) => {
    if (bullets.length > 0) {
      out.push(
        <ul class="wf-md-list" key={`ul-${key}`}>
          {bullets}
        </ul>,
      );
      bullets = [];
    }
  };
  blocks.forEach((block, i) => {
    if (block.type === "bullet") {
      bullets.push(<li key={i}>{renderSpans(block.spans)}</li>);
      return;
    }
    flush(String(i));
    out.push(<p key={i}>{renderSpans(block.spans)}</p>);
  });
  flush("end");
  return <Fragment>{out}</Fragment>;
}

/** Map parsed inline tokens to <strong>/<em>/<code>/text nodes. */
function renderSpans(spans: readonly InlineToken[]): ComponentChildren {
  return spans.map((span, k) => {
    switch (span.type) {
      case "strong":
        return <strong key={k}>{span.value}</strong>;
      case "em":
        return <em key={k}>{span.value}</em>;
      case "code":
        return <code key={k}>{span.value}</code>;
      default:
        return span.value;
    }
  });
}

// ---------------------------------------------------------------------------
// Ready-stage preview: visualization + generated YAML + dry test + PR
// ---------------------------------------------------------------------------

function WorkflowPreview({
  form,
  palette,
  gateRefs,
  onChange,
}: {
  readonly form: FormState;
  readonly palette: readonly ActionTypePaletteEntry[];
  readonly gateRefs: readonly string[];
  readonly onChange: (form: FormState) => void;
}) {
  const [result, setResult] = useState<ValidateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [validating, setValidating] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<SavedWorkflowDraft | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  // Bumped by the Retry button to re-run a validation that failed on a
  // transient network error, without rebuilding the draft.
  const [retryKey, setRetryKey] = useState(0);

  const draft = useMemo(() => buildDraft(form), [form]);

  useEffect(() => {
    let cancelled = false;
    setValidating(true);
    setResult(null);
    setError(null);
    setSaved(null);
    setSaveError(null);
    const timer = setTimeout(() => {
      validateWorkflowDraft(draft)
        .then((res) => {
          if (cancelled) return;
          const structureIssues = validateDraftStructure(form, gateRefs);
          setResult(structureIssues.length === 0
            ? res
            : {
                valid: false,
                issues: [...structureIssues, ...res.issues],
                yaml_preview: null,
              });
        })
        .catch((err: unknown) => {
          if (!cancelled) setError(err instanceof Error ? err.message : String(err));
        })
        .finally(() => {
          if (!cancelled) setValidating(false);
        });
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [draft, form, gateRefs, retryKey]);

  const yaml = result?.yaml_preview ?? null;
  const prUrl = yaml ? githubNewFileUrl(`rule-catalog/workflows/${form.name}.yaml`, yaml) : null;

  const saveDraft = async (): Promise<void> => {
    if (!result?.valid || saving || saved !== null) return;
    setSaving(true);
    setSaveError(null);
    try {
      setSaved(await createWorkflowDefinition(draft));
    } catch (caught) {
      setSaveError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div class="wf-preview">
      <WorkflowViz form={form} palette={palette} />
      <WorkflowDraftEditor
        form={form}
        palette={palette}
        gateRefs={gateRefs}
        onChange={onChange}
      />

      <div class="wf-preview-section">
        <h4 class="wf-preview-title">{t("workflow.chat.generatedWorkflow")}</h4>
        {yaml ? (
          <>
            <div class="code-actions">
              <CopyButton text={yaml} label={t("workflow.chat.copyYaml")} />
            </div>
            <pre class="mono scroll code-block">{yaml}</pre>
          </>
        ) : (
          <p class="muted small">
            {t(validating ? "workflow.chat.generatingYaml" : "workflow.chat.yamlReady")}
          </p>
        )}
      </div>

      <div class="wf-preview-section">
        <h4 class="wf-preview-title">{t("workflow.chat.structuralValidation")}</h4>
        {validating ? (
          <p class="muted small" aria-busy="true">
            {t("workflow.chat.validating")}
          </p>
        ) : error ? (
          <div class="wf-test-fail" role="alert">
            <p>{t("workflow.chat.validationError", { error })}</p>
            <p class="muted small">
              {t("workflow.chat.retryHint")}
            </p>
            <button
              type="button"
              class="btn btn-small"
              onClick={() => setRetryKey((k) => k + 1)}
            >
              {t("workflow.chat.retryTest")}
            </button>
          </div>
        ) : result ? (
          <TestResult result={result} />
        ) : null}
      </div>

      {yaml ? (
        <div class="wf-preview-section wf-preview-cta">
          <button
            type="button"
            class="btn"
            disabled={!result?.valid || saving || saved !== null}
            onClick={() => void saveDraft()}
          >
            {t(saving ? "workflow.chat.saving" : saved ? "workflow.chat.saved" : "workflow.chat.save")}
          </button>
          {prUrl ? (
            <a class="btn secondary" href={prUrl} target="_blank" rel="noopener noreferrer">
              {t("workflow.chat.propose")} &rarr;
            </a>
          ) : (
            <span class="muted small">{t("workflow.chat.proposeUnavailable")}</span>
          )}
          <span class="muted small">
            {t("workflow.chat.saveHintBeforePath")} {" "}
            <code>rule-catalog/workflows/{form.name}.yaml</code>{" "}
            {t("workflow.chat.saveHintAfterPath")}
          </span>
          {saved ? (
            <p class="wf-test-pass" role="status">
              {t("workflow.chat.saveSuccess", {
                name: saved.workflowName,
                lifecycle: saved.lifecycle,
                definitionId: saved.definitionId,
              })}
            </p>
          ) : null}
          {saveError ? <p class="wf-test-fail" role="alert">{t("workflow.chat.saveError", { error: saveError })}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

function TestResult({ result }: { readonly result: ValidateResponse }) {
  if (result.valid) {
    return (
      <p class="wf-test-pass">
        {t("workflow.chat.validationPassed")}
      </p>
    );
  }
  return (
    <div class="wf-test-fail" role="alert">
      <p>
        {t(result.issues.length === 1 ? "workflow.chat.issueOne" : "workflow.chat.issueMany", {
          count: formatNumber(result.issues.length),
        })}
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
  const nodes = useMemo(() => buildVizModel(form, palette), [form, palette]);
  const trigger = nodes[0];
  const steps = nodes.filter((n) => n.kind !== "when" && n.kind !== "done");

  return (
    <div class="wf-viz" role="list" aria-label={t("workflow.chat.visualization")}>
      <div class="wf-viz-node wf-viz-trigger" role="listitem">
        <span class="wf-viz-kind">{t("workflow.chat.when")}</span>
        <span class="wf-viz-name">{trigger?.name}</span>
        <span class="wf-viz-ref mono">{trigger?.ref}</span>
      </div>
      {steps.map((n, i) => (
        <Fragment key={`${n.ref}-${i}`}>
          <div class="wf-viz-edge" aria-hidden="true">
            <span class="wf-viz-edge-label">{t(i === 0 ? "workflow.chat.thenDo" : "workflow.chat.then")}</span>
          </div>
          <div class={`wf-viz-node wf-viz-action is-${n.category}`} role="listitem">
            <span class="wf-viz-kind">{t(`workflow.stepKind.${n.kind}`)}</span>
            <span class="wf-viz-name">{n.name}</span>
            <span class="wf-viz-ref mono">{n.ref}</span>
          </div>
        </Fragment>
      ))}
      <div class="wf-viz-edge" aria-hidden="true"></div>
      <div class="wf-viz-node wf-viz-end" role="listitem">
        <span class="wf-viz-name">{t("workflow.chat.done")}</span>
      </div>
    </div>
  );
}
