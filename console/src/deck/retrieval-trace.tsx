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
import { t } from "./i18n/conversation-layer";
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
  if (previews.length > 0) {
    return previews.filter((preview) => !isUnavailableDetail(preview.detail));
  }
  return (snapshot?.facts ?? [])
    .map((fact) => ({
      kind: fact.group ?? "fact",
      label: fact.key,
      detail: fact.value === null ? "-" : String(fact.value),
    }))
    .filter((fact) => !isUnavailableDetail(fact.detail));
}

function isUnavailableDetail(detail: string): boolean {
  return ["n/a", "unavailable"].includes(detail.trim().toLowerCase());
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

  // The conversation layer's live grounding trace: one panel with the plan's steps, a window of
  // the newest sources, and an answer skeleton in the place the answer will take.
  return (
    <article class="deck-rt-turn cs-deck-turn cs-deck-agent-turn">
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
      <section class="cs-grounding-panel cs-deck-enter" aria-label={t("deck.retrieval.preparingAnswer")}>
        <span class="sr-only" role="status" aria-live="polite">
          {t("deck.retrieval.status", {
            detail: progress?.label ?? t("deck.retrieval.readingCurrentSources"),
          })}
        </span>
        <header class="cs-grounding-head">
          <span class="cs-grounding-title">{t("deck.retrieval.preparingAnswer")}</span>
          <span class="cs-grounding-status">
            {progress?.label ?? t("deck.retrieval.groundingReadOnly")}
          </span>
          <span class="cs-grounding-elapsed" aria-hidden="true">
            {(elapsedMs / 1000).toFixed(1)} s
          </span>
          <span class="cs-grounding-authority">{t("deck.retrieval.readOnly")}</span>
        </header>

        <ol class="cs-grounding-stages" aria-label={t("deck.retrieval.stepsLabel")}>
          {stages.map((stage) => (
            <li
              key={stage.id}
              class={`cs-grounding-stage ${stage.done ? "is-done" : "is-active"}`}
              data-phase={stage.id}
              data-done={stage.done ? "true" : "false"}
              data-side={stage.side}
            >
              <span class="cs-grounding-mark" aria-hidden="true">
                {stage.done ? "\u2713" : <span class="cs-grounding-spinner" />}
              </span>
              <span class="cs-grounding-stage-copy">
                <span class="cs-grounding-stage-label">{stage.label}</span>
                <span class="cs-grounding-stage-detail">{stage.detail}</span>
              </span>
              <span class="cs-grounding-phase">{t(`deck.retrieval.side.${stage.side}`)}</span>
              <span class="sr-only">
                {t(stage.done ? "deck.retrieval.stageDone" : "deck.retrieval.stageActive")}
              </span>
            </li>
          ))}
        </ol>

        {sourceCount > 0 ? (
          <div class="cs-grounding-sources">
            <div class="cs-grounding-sources-head">
              <span>{t("deck.retrieval.readingSources")}</span>
              <span>{Math.min(shown, sourceCount)}/{sourceCount}</span>
            </div>
            <ul
              class="cs-grounding-source-list"
              style={`--cs-grounding-source-rows: ${Math.min(VISIBLE, sourceCount)}`}
            >
              {visibleSources.map((source, index) => (
                <li key={`${source.kind}-${source.label}-${index}`} class="cs-grounding-source">
                  <span class="cs-deck-kind">{source.kind}</span>
                  <span class="cs-grounding-source-copy">
                    <span class="cs-grounding-source-title">{source.label}</span>
                    <span class="cs-grounding-source-meta">{source.detail}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>
      <div class="cs-deck-answer-skeleton" aria-hidden="true">
        <span class="cs-deck-skeleton" />
        <span class="cs-deck-skeleton" />
        <span class="cs-deck-skeleton" />
      </div>
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
