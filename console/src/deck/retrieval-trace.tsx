/**
 * RetrievalTrace - the deck's "preparing answer" surface.
 *
 * Shown while a turn is pending, in place of a bare typing indicator. It
 * makes the grounding visible: the deck streams the read-only sources it
 * is consulting (the current screen snapshot) in a slot-machine window
 * while it waits for the backend reply. This asserts the console's
 * read-only, narrator-is-a-translator contract as a UI gesture - the
 * deck reads and cites, it never executes.
 *
 * Honest-data only: every row here comes from data the deck actually
 * holds right now - the published ViewSnapshot (facts) and the backend
 * health descriptor (router / model / mode). It fabricates nothing. When
 * the chat backend later streams real per-stage retrieval events (SSE),
 * this component is the seam that renders them; until then it grounds on
 * the screen the operator is looking at.
 *
 * Single responsibility: render the pending retrieval trace. No I/O, no
 * privileged calls, no side effects beyond a self-cancelling timer.
 */

import { useEffect, useState } from "preact/hooks";
import { t } from "../i18n";
import type {
  BackendHealth,
  RetrievalSourcePreview,
  VerificationProgress,
} from "./backend";
import type { ViewSnapshot } from "./context";

/** Fixed card pitch: card height + gap. Keep in sync with styles.css
 *  (.deck-rt-card height + .deck-rt-strip gap). */
const CARD_PITCH_PX = 40;
/** How many source cards stay in the slot window at once. */
const VISIBLE = 3;
/** Cadence of the source cascade. */
const FACT_INTERVAL_MS = 95;

interface Stage {
  readonly label: string;
  readonly detail: string;
  readonly side: "read" | "route";
  readonly done: boolean;
}

interface SourceCard {
  readonly kind: string;
  readonly label: string;
  readonly detail: string;
}

function sourceCards(
  snapshot: ViewSnapshot | null,
  previews: readonly RetrievalSourcePreview[],
): readonly SourceCard[] {
  if (previews.length > 0) return previews;
  return (snapshot?.facts ?? []).map((fact) => ({
    kind: fact.group ?? "fact",
    label: fact.key,
    detail: fact.value === null ? "-" : String(fact.value),
  }));
}

function buildStages(
  snapshot: ViewSnapshot | null,
  health: BackendHealth | null,
  progress: VerificationProgress | null,
): readonly Stage[] {
  const stages: Stage[] = [];
  if (snapshot) {
    stages.push({
      label: t("deck.retrieval.readScreen"),
      detail: snapshot.routeLabel,
      side: "read",
      done: true,
    });
  }
  if (health?.router) {
    stages.push({
      label: t("deck.retrieval.routeChose", { deployment: health.router.chose }),
      detail: health.router.reason,
      side: "route",
      done: true,
    });
  } else if (health?.model) {
    stages.push({ label: t("deck.retrieval.route"), detail: health.model, side: "route", done: true });
  }
  stages.push({
    label: progress?.label ?? t("deck.retrieval.consultBackend"),
    detail:
      progress && progress.completed !== null && progress.total !== null
        ? t("deck.retrieval.checks", { completed: progress.completed, total: progress.total })
        : health
          ? health.mode
          : t("deck.retrieval.connecting"),
    side: progress?.phase === "generating" ? "route" : "read",
    done: false,
  });
  return stages;
}

export function RetrievalTrace({
  snapshot,
  health,
  progress,
}: {
  readonly snapshot: ViewSnapshot | null;
  readonly health: BackendHealth | null;
  readonly progress: VerificationProgress | null;
}) {
  const sources = sourceCards(snapshot, progress?.sources ?? []);
  const sourceCount = sources.length;
  const sourceSignature = sources
    .map((source) => `${source.kind}:${source.label}:${source.detail}`)
    .join("|");
  const routeId = snapshot?.routeId ?? "";
  const [shown, setShown] = useState(0);
  const [elapsedMs, setElapsedMs] = useState(0);

  useEffect(() => {
    const startedAt = performance.now();
    const id = window.setInterval(() => {
      setElapsedMs(performance.now() - startedAt);
    }, 100);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    setShown(0);
  }, [routeId]);

  // Roll source cards in one at a time. When server-owned sources replace the
  // initial screen preview, preserve the visible count instead of rewinding.
  useEffect(() => {
    setShown((current) =>
      sourceCount === 0 ? 0 : Math.min(sourceCount, Math.max(current, 1)));
    if (sourceCount <= 1) return;
    const id = window.setInterval(() => {
      setShown((current) => {
        const next = Math.min(sourceCount, current + 1);
        if (next >= sourceCount) window.clearInterval(id);
        return next;
      });
    }, FACT_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [routeId, sourceCount, sourceSignature]);

  const stages = buildStages(snapshot, health, progress);
  const rolled = Math.max(0, shown - VISIBLE);
  const visibleSources = sources.slice(0, shown);

  return (
    <article class="deck-rt" aria-label={t("deck.retrieval.preparingAnswer")}>
      <span class="sr-only" role="status" aria-live="polite">
        {t("deck.retrieval.status", {
          detail: progress?.label ?? t("deck.retrieval.readingCurrentScreenSources"),
        })}
      </span>
      <header class="deck-rt-head">
        <span class="deck-rt-spin" aria-hidden="true" />
        <span class="deck-rt-title">{t("deck.retrieval.preparingAnswer")}</span>
        <span class="deck-rt-sub muted">
          {progress?.label ?? t("deck.retrieval.groundingReadOnlySources")}
        </span>
        <span class="deck-rt-elapsed muted" aria-hidden="true">
          {(elapsedMs / 1000).toFixed(1)}s
        </span>
      </header>

      <ol class="deck-rt-stages">
        {stages.map((s, i) => (
          <li key={`${s.label}-${i}`} class={`deck-rt-stage ${s.done ? "is-done" : "is-active"}`}>
            <span class="deck-rt-ico" aria-hidden="true" />
            <span class="deck-rt-slabel">{s.label}</span>
            <span class="deck-rt-detail muted">{s.detail}</span>
            <span class={`deck-rt-side deck-rt-side-${s.side}`}>{s.side}</span>
            {s.done ? <span class="deck-rt-check" aria-hidden="true">{"\u2713"}</span> : null}
            {!s.done ? (
              <span class="deck-rt-activity" aria-hidden="true">
                <span />
                <span />
                <span />
              </span>
            ) : null}
          </li>
        ))}
      </ol>

      {sourceCount > 0 ? (
        <div class="deck-rt-sources">
          <div class="deck-rt-sources-label muted">
            <span>{t("deck.retrieval.readingSources")}</span>
            <span>{Math.min(shown, sourceCount)}/{sourceCount}</span>
          </div>
          <div class="deck-rt-slot">
            <ul
              class="deck-rt-strip"
              style={{ transform: `translateY(${-rolled * CARD_PITCH_PX}px)` }}
            >
              {visibleSources.map((source, i) => (
                <li key={`${source.kind}-${source.label}-${i}`} class="deck-rt-card">
                  <span class={`deck-rt-badge is-${source.kind}`}>{source.kind}</span>
                  <span class="deck-rt-txt">
                    <span class="deck-rt-k">{source.label}</span>
                    <span class="deck-rt-v">{source.detail}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}
    </article>
  );
}
