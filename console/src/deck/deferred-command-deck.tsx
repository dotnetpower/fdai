import { lazy, Suspense } from "preact/compat";
import { useEffect, useLayoutEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { offerProactiveHandover } from "../handover-invitation";
import { t } from "../i18n";
import {
  hasPendingDeckOpen,
  openDeckWithContext,
} from "./open-deck";

const DECK_ACTIVATE_EVENT = "fdai:deck:activate";

const CommandDeck = lazy(async () => {
  const module = await import("./command-deck");
  return { default: module.CommandDeck };
});

export function DeferredCommandDeck({
  client,
  routeLabel,
}: {
  readonly client: OperatorApiClient;
  readonly routeLabel: string;
}) {
  const [requested, setRequested] = useState(hasPendingDeckOpen);

  useEffect(() => {
    const storage = typeof window === "undefined" ? null : window.sessionStorage;
    void offerProactiveHandover(client, storage).catch((error: unknown) => {
      console.warn("proactive_handover_unavailable", {
        error_type: error instanceof Error ? error.name : "UnknownError",
      });
    });
  }, [client]);

  useLayoutEffect(() => {
    if (requested) return undefined;
    const activate = () => setRequested(true);
    const activateFromKeyboard = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const inField = target?.tagName === "INPUT"
        || target?.tagName === "TEXTAREA"
        || target?.isContentEditable === true;
      const commandKey = (event.key === "k" || event.key === "K")
        && (event.metaKey || event.ctrlKey);
      const slashKey = !inField && event.key === "/";
      if (!commandKey && !slashKey) return;
      event.preventDefault();
      openDeckWithContext({ contextMode: "screen" });
    };
    window.addEventListener(DECK_ACTIVATE_EVENT, activate);
    window.addEventListener("keydown", activateFromKeyboard);
    return () => {
      window.removeEventListener(DECK_ACTIVATE_EVENT, activate);
      window.removeEventListener("keydown", activateFromKeyboard);
    };
  }, [requested]);

  if (!requested) {
    return (
      <button
        type="button"
        class="deck-invoke"
        onClick={() => openDeckWithContext({ contextMode: "screen" })}
        aria-label={t("deck.screenOpen", { route: routeLabel })}
        aria-expanded="false"
      >
        <span class="deck-invoke-label">{t("deck.invoke")}</span>
        <span class="deck-invoke-context muted">{routeLabel}</span>
        <kbd class="deck-invoke-kbd">
          {navigator.platform.toLowerCase().includes("mac") ? "⌘K" : "Ctrl K"}
        </kbd>
        <kbd class="deck-invoke-kbd">/</kbd>
      </button>
    );
  }
  return (
    <Suspense
      fallback={(
        <span class="sr-only" role="status">
          {t("shared.loadingResource", { resource: t("deck.conversation") })}
        </span>
      )}
    >
      <CommandDeck client={client} />
    </Suspense>
  );
}
