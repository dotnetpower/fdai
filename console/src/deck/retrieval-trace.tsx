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

/** How many source cards stay in the slot window at once. */
const VISIBLE = 3;
/** Cadence of the source cascade. */
const FACT_INTERVAL_MS = 95;
const UNAVAILABLE_SOURCE_DETAILS = new Set(["n/a", "unavailable"]);

interface Stage {
  readonly id: "screen" | "route" | "backend";
  readonly glyph: string;
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

export function sourceCards(
  snapshot: ViewSnapshot | null,
  previews: readonly RetrievalSourcePreview[],
): readonly SourceCard[] {
  const cards = previews.length > 0
    ? previews
    : (snapshot?.facts ?? []).map((fact) => ({
        kind: fact.group ?? "fact",
        label: fact.key,
        detail: fact.value === null ? "-" : String(fact.value),
      }));
  return cards.filter(
    (card) => !UNAVAILABLE_SOURCE_DETAILS.has(card.detail.trim().toLocaleLowerCase()),
  );
}

export function buildStages(
  snapshot: ViewSnapshot | null,
  health: BackendHealth | null,
  progress: VerificationProgress | null,
): readonly Stage[] {
  const stages: Stage[] = [];
  if (snapshot) {
    stages.push({
      id: "screen",
      glyph: "S",
      label: t("deck.retrieval.readScreen"),
      detail: t("deck.retrieval.screenDetail", {
        route: snapshot.routeLabel,
        headline: snapshot.headline,
        count: snapshot.facts.length,
      }),
      side: "read",
      done: true,
    });
  }
  if (health?.router) {
    stages.push({
      id: "route",
      glyph: "R",
      label: t("deck.retrieval.routeChosen", { deployment: health.router.chose }),
      detail: health.router.reason,
      side: "route",
      done: true,
    });
  } else if (health?.model) {
    stages.push({
      id: "route",
      glyph: "R",
      label: t("deck.retrieval.route"),
      detail: health.model,
      side: "route",
      done: true,
    });
  }
  stages.push({
    id: "backend",
    glyph: progress?.phase === "generating" ? "G" : "B",
    label: progress?.label ?? t("deck.retrieval.consultBackend"),
    detail:
      progress && progress.completed !== null && progress.total !== null
        ? t("deck.retrieval.progressDetail", {
            checks: t("deck.retrieval.checks", {
              completed: progress.completed,
              total: progress.total,
            }),
            count: progress.sources?.length ?? 0,
          })
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
  const visibleSources = sources.slice(Math.max(0, shown - VISIBLE), shown);
  const iconUrl = `url("${typeof import.meta.env.BASE_URL === "string" ? import.meta.env.BASE_URL : "/"}agent-icons/bragi.svg")`;

  return (
    <article class="deck-rt-turn cs-deck-turn cs-deck-agent-turn">
      <header class="deck-turn-head deck-rt-agent-head cs-deck-turn-head">
        <span class="deck-turn-role deck-turn-agent cs-deck-agent-name">
          <span
            class="deck-turn-agent-icon cs-deck-agent-icon"
            aria-hidden="true"
            style={{ WebkitMaskImage: iconUrl, maskImage: iconUrl }}
          />
          Bragi
        </span>
        <span class="deck-turn-source cs-deck-agent-source">{t("deck.retrieval.groundingReadOnly")}</span>
      </header>
      <section class="deck-rt cs-grounding-panel" aria-label={t("deck.retrieval.preparingAnswer")}>
        <span class="sr-only" role="status" aria-live="polite">
          {t("deck.retrieval.status", {
            detail: progress?.label ?? t("deck.retrieval.readingCurrentSources"),
          })}
        </span>
        <header class="deck-rt-head cs-grounding-head">
          <span class="deck-rt-spin" aria-hidden="true" />
          <span class="deck-rt-title">{t("deck.retrieval.preparingAnswer")}</span>
          <span class="deck-rt-sub muted">
            {progress?.label ?? t("deck.retrieval.groundingReadOnly")}
          </span>
          <span class="deck-rt-elapsed muted" aria-hidden="true">
            {(elapsedMs / 1000).toFixed(1)}s
          </span>
          <span class="deck-rt-mode">{t("deck.retrieval.compact")}</span>
        </header>

        <ol class="deck-rt-stages">
        {stages.map((stage) => (
          <li
            key={stage.id}
            class={`deck-rt-stage cs-grounding-stage ${stage.done ? "is-done" : "is-active"}`}
          >
            <span class="deck-rt-ico" aria-hidden="true">{stage.glyph}</span>
            <span class="deck-rt-stage-copy">
              <span class="deck-rt-slabel">{stage.label}</span>
              <span class="deck-rt-detail muted">{stage.detail}</span>
            </span>
            <span class={`deck-rt-side deck-rt-side-${stage.side}`}>
              {t(`deck.retrieval.side.${stage.side}`)}
            </span>
            {stage.done ? <span class="deck-rt-check" aria-hidden="true">{"\u2713"}</span> : null}
          </li>
        ))}
        </ol>

        {sourceCount > 0 ? (
          <details open class="deck-rt-sources">
          <summary class="deck-rt-sources-label muted">
            <span>{t("deck.retrieval.readingSources")}</span>
            <span>{Math.min(shown, sourceCount)}/{sourceCount}</span>
          </summary>
          <div class="deck-rt-slot cs-grounding-source-window">
            <ul
              class="deck-rt-strip"
            >
              {visibleSources.map((source, index) => (
                <li key={`${source.kind}-${source.label}-${index}`} class="deck-rt-source cs-grounding-source">
                  <span class={`deck-rt-badge is-${source.kind}`}>{source.kind}</span>
                  <span class="deck-rt-txt">
                    <span class="deck-rt-k">{source.label}</span>
                    <span class="deck-rt-v">{source.detail}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
          </details>
        ) : null}
      </section>
    </article>
  );
}

export function PendingReplyIndicator() {
  const iconUrl = `url("${typeof import.meta.env.BASE_URL === "string" ? import.meta.env.BASE_URL : "/"}agent-icons/bragi.svg")`;
  return (
    <article class="deck-pending-reply cs-deck-turn cs-deck-agent-turn" aria-busy="true">
      <header class="deck-turn-head cs-deck-turn-head">
        <span class="deck-turn-role deck-turn-agent cs-deck-agent-name">
          <span
            class="deck-turn-agent-icon cs-deck-agent-icon"
            aria-hidden="true"
            style={{ WebkitMaskImage: iconUrl, maskImage: iconUrl }}
          />
          Bragi
        </span>
      </header>
      <div class="deck-pending-reply-body">
        <span class="deck-pending-reply-dots" aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
        <span>{t("deck.retrieval.preparingAnswer")}</span>
      </div>
    </article>
  );
}
