import { t } from "../i18n";
import type { ConversationHydrationStatus } from "./use-command-deck-sessions";

interface ConversationHistoryStateProps {
  readonly status: Exclude<ConversationHydrationStatus, "idle">;
  readonly onRetry: () => void;
}

export function ConversationHistoryState({
  status,
  onRetry,
}: ConversationHistoryStateProps) {
  if (status === "loading") {
    return (
      <section
        class="deck-history-state is-loading"
        role="status"
        aria-busy="true"
        aria-label={t("deck.history.loading")}
      >
        <span aria-hidden="true" />
        <span aria-hidden="true" />
        <span aria-hidden="true" />
      </section>
    );
  }

  const failed = status === "error";
  return (
    <section
      class={`deck-history-state is-${status}`}
      role={failed ? "alert" : "status"}
    >
      <strong>{t(`deck.history.${status}Title`)}</strong>
      <p>{t(`deck.history.${status}Body`)}</p>
      {status !== "empty" ? (
        <button type="button" onClick={onRetry}>
          {t("deck.history.retry")}
        </button>
      ) : null}
    </section>
  );
}
