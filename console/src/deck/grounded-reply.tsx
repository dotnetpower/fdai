/**
 * GroundedReply - renders a deck (assistant) turn the way the source-streaming
 * mock does: the answer text types in token by token, then a "Grounded on N
 * sources" pill summarises the reply, and expanding it rolls the cited sources
 * through a slot-machine window (reusing the retrieval-trace slot styles).
 *
 * Honest-data only: every source card is a real ``Citation`` the backend
 * returned (a fact the answer is grounded in). The pill's summary line is the
 * real reply ``source`` descriptor (``llm:<model> - <ms>`` or
 * ``deterministic``). Nothing here is fabricated - it re-presents what the
 * reply already carries.
 *
 * Single responsibility: present one grounded deck reply. No I/O, no
 * privileged calls, only self-cancelling timers.
 */

import { useState } from "preact/hooks";
import { RichContent } from "./rich-content";
import { relevantCitations, type Citation } from "./citations";

export function GroundedReply({
  turnId,
  text,
  citations,
  source,
  streaming,
  onRegenerate,
}: {
  readonly turnId: string;
  readonly text: string;
  readonly citations: readonly Citation[] | undefined;
  readonly source: string | undefined;
  /** True while the answer is still streaming tokens in from the backend. */
  readonly streaming: boolean;
  /** Re-run the operator question that produced this reply, if known. */
  readonly onRegenerate?: () => void;
}) {
  void turnId;
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const cites = relevantCitations(citations ?? [], text);

  const copy = () => {
    void navigator.clipboard?.writeText(text).then(
      () => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      },
      () => {
        /* clipboard denied - leave the label unchanged */
      },
    );
  };

  return (
    <div class="deck-gr">
      <div class="deck-turn-body">
        <RichContent text={text} streaming={streaming} />
      </div>

      {!streaming && text.trim().length > 0 ? (
        <div class="deck-gr-tools">
          <button type="button" class="deck-gr-tool" onClick={copy} title="Copy reply">
            {copied ? "Copied" : "Copy"}
          </button>
          {onRegenerate ? (
            <button
              type="button"
              class="deck-gr-tool"
              onClick={onRegenerate}
              title="Ask this question again"
            >
              Regenerate
            </button>
          ) : null}
          {source && cites.length === 0 ? (
            <span class="deck-gr-src deck-gr-src-inline muted" title="reply source">
              {source}
            </span>
          ) : null}
        </div>
      ) : null}

      {!streaming && cites.length > 0 ? (
        <>
          <button
            type="button"
            class="deck-gr-pill"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
          >
            <span class="deck-gr-check" aria-hidden="true">
              {"\u2713"}
            </span>
            <span>
              Grounded on <strong>{cites.length}</strong>{" "}
              {cites.length === 1 ? "source" : "sources"}
            </span>
            {source ? <span class="deck-gr-src muted">{source}</span> : null}
            <span class="deck-gr-more">{open ? "hide sources" : "show sources"}</span>
          </button>

          {open ? (
            <ul class="deck-gr-list">
              {cites.map((c, i) => (
                <li key={`${c.label}-${i}`} class="deck-gr-item">
                  <span class="deck-gr-k">{c.label}</span>
                  {c.value !== undefined ? <span class="deck-gr-v">{c.value}</span> : null}
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
