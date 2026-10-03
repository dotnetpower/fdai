import { Fragment } from "preact";
import { t } from "./i18n/investigation";
import { consoleDateTimeLocale } from "../time-format";
import type { ContextReceipt, TurnBudgetTelemetry, WorkProgressShape } from "./backend-types";
import { presentationTimestamp } from "./presentation-value";

// Turn-wide investigation roles from the work progress contract. They describe how the turn was
// shaped and measured; none of them is evidence, and none of them grants authority.

export function plannedWorkText(plan: WorkProgressShape): string {
  return t("deck.investigation.planned", {
    waves: t(plan.waves === 1 ? "deck.investigation.waveOne" : "deck.investigation.wavesMany", {
      count: plan.waves,
    }),
    reads: t(plan.planned_reads === 1 ? "deck.investigation.readOne" : "deck.investigation.readsMany", {
      count: plan.planned_reads,
    }),
  });
}

export interface TurnBudgetParts {
  /** Localized text before the measures, such as the used or limit-reached label. */
  readonly lead: string;
  readonly measures: readonly string[];
  /** Localized text after the measures, such as the incomplete-measurement note. */
  readonly trail: string;
}

const SLOT = "\u0000";

/**
 * The server's end-of-turn telemetry as used-of-maximum facts. Callers render it only after the
 * answer settles, so it never reads as a live remaining-budget meter.
 */
export function turnBudgetText(budget: TurnBudgetTelemetry): string {
  const { lead, measures, trail } = turnBudgetParts(budget);
  return `${lead}${measures.join(", ")}${trail}`;
}

/** The same facts split around their measures, so each measure can stay on one line. */
export function turnBudgetParts(budget: TurnBudgetTelemetry): TurnBudgetParts {
  const { model_calls: calls, tokens, elapsed_ms: elapsed } = budget;
  const measures = [
    t("deck.investigation.budgetCalls", { used: calls.used, maximum: calls.maximum }),
    tokens.reserved > 0
      ? t("deck.investigation.budgetTokensReserved", {
          used: tokenCount(tokens.used),
          reserved: tokenCount(tokens.reserved),
          maximum: tokenCount(tokens.maximum),
        })
      : t("deck.investigation.budgetTokens", {
          used: tokenCount(tokens.used),
          maximum: tokenCount(tokens.maximum),
        }),
    t("deck.investigation.budgetElapsed", {
      used: seconds(elapsed.used),
      maximum: seconds(elapsed.maximum),
    }),
  ];
  const [usageLead = "", usageTrail = ""] = (budget.exhaustion_reason
    ? t(`deck.investigation.budgetReached.${budget.exhaustion_reason}`, { usage: SLOT })
    : t("deck.investigation.budgetUsed", { usage: SLOT })).split(SLOT);
  const [noteLead = "", noteTrail = ""] = budget.complete
    ? []
    : t("deck.investigation.budgetIncomplete", { text: SLOT }).split(SLOT);
  return { lead: `${noteLead}${usageLead}`, measures, trail: `${usageTrail}${noteTrail}` };
}

/** Settled limits whose measures break only between one another, never inside a measure. */
export function TurnBudgetLimits({ budget }: { readonly budget: TurnBudgetTelemetry }) {
  const { lead, measures, trail } = turnBudgetParts(budget);
  return (
    <span class="cs-deck-investigation-limits">
      {lead}
      {measures.map((measure, index) => (
        <Fragment key={measure}>
          {index > 0 ? ", " : null}
          <span class="deck-investigation-measure">{measure}</span>
        </Fragment>
      ))}
      {trail}
    </span>
  );
}

function tokenCount(count: number): string {
  return count < 1000 ? String(count) : `${trimmed(count / 1000)}k`;
}

function seconds(milliseconds: number): string {
  return milliseconds < 1000 ? `${milliseconds} ms` : `${trimmed(milliseconds / 1000)} s`;
}

function trimmed(value: number): string {
  return value.toFixed(1).replace(/\.0$/, "");
}

/** An applied operator preference: context that shaped the turn, never evidence or instructions. */
export function ContextReceiptDisclosure({
  receipts,
}: {
  readonly receipts: readonly ContextReceipt[];
}) {
  const current = receipts.filter((receipt) => receipt.freshness === "fresh");
  return (
    <details class="cs-deck-context-receipt">
      <summary class="cs-deck-context-receipt-summary">
        <span class="cs-deck-context-receipt-label">{t("deck.investigation.contextApplied")}</span>
        <span class="cs-deck-context-receipt-value">
          {current.length > 0
            ? current.map((receipt) => receipt.label).join(", ")
            : t("deck.investigation.noCurrentPreference")}
        </span>
        <span class="cs-run-chevron" aria-hidden="true" />
      </summary>
      <div class="cs-deck-context-receipt-body">
        <p class="cs-deck-context-receipt-note">{t("deck.investigation.contextOnly")}</p>
        <ul class="cs-deck-context-receipt-list">
          {receipts.map((receipt) => {
            const observed = presentationTimestamp(receipt.observed_at, consoleDateTimeLocale());
            return (
              <li key={receipt.receipt_id} data-freshness={receipt.freshness}>
                <strong>{receipt.label}</strong>{" "}
                <span class="cs-deck-context-receipt-freshness">
                  {t(`deck.investigation.freshness.${receipt.freshness}`)}
                </span>{" "}
                {observed ? (
                  <>
                    <span>
                      {t("deck.investigation.receiptObserved", {
                        time: `${observed.date} ${observed.time}`,
                      })}
                    </span>{" "}
                  </>
                ) : null}
                <code>{receipt.digest.slice(0, 12)}</code>
              </li>
            );
          })}
        </ul>
      </div>
    </details>
  );
}

/** A workflow milestone: one quiet progress line between waves, never an evidence claim. */
export function MilestoneLine({
  text,
  recordedAt,
}: {
  readonly text: string;
  readonly recordedAt?: string;
}) {
  const recorded = recordedAt ? presentationTimestamp(recordedAt, consoleDateTimeLocale()) : null;
  return (
    <p class="deck-milestone cs-deck-milestone" role="status">
      <span class="cs-deck-milestone-label">{t("deck.investigation.progressUpdate")}</span>{" "}
      <span class="cs-deck-milestone-text">{text}</span>
      {recorded ? (
        <>
          {" "}
          <time class="cs-deck-milestone-time" dateTime={recorded.dateTime}>{recorded.time}</time>
        </>
      ) : null}
    </p>
  );
}
