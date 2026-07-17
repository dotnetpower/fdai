import { t } from "../i18n";
import type { BackendHealth } from "./backend";
import { BackendBadge } from "./command-deck-presenters";

export function CommandDeckLauncher({
  open,
  routeLabel,
  health,
  onInvoke,
}: {
  readonly open: boolean;
  readonly routeLabel: string;
  readonly health: BackendHealth | null;
  readonly onInvoke: () => void;
}) {
  return (
    <button
      type="button"
      class={`deck-invoke ${open ? "deck-invoke-open" : ""}`}
      onClick={onInvoke}
      aria-label={open ? t("deck.close") : t("deck.open")}
    >
      <span class="deck-invoke-glyph" aria-hidden="true">
        <svg viewBox="0 0 16 16" width="14" height="14">
          <path
            d="M3 2.75h10a1.5 1.5 0 0 1 1.5 1.5v6a1.5 1.5 0 0 1-1.5 1.5H7L3.5 14v-2.25H3a1.5 1.5 0 0 1-1.5-1.5v-6A1.5 1.5 0 0 1 3 2.75Z"
            fill="none"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </span>
      <span class="deck-invoke-label">{t("deck.invoke")}</span>
      <span class="deck-invoke-context muted">{routeLabel}</span>
      <BackendBadge health={health} placement="invoke" />
      <kbd class="deck-invoke-kbd">
        {navigator.platform.toLowerCase().includes("mac") ? "⌘K" : "Ctrl K"}
      </kbd>
      <kbd class="deck-invoke-kbd">/</kbd>
    </button>
  );
}
