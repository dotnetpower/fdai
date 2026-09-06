import type { ComponentChildren } from "preact";
import { Tooltip } from "../components/tooltip";
import { t } from "../i18n";
import "./conversation-entry.css";

/** Explicit starter activation sends a question through the normal composer path. */
export function GeneralConversationIntro({
  onPick,
  children,
}: {
  readonly onPick: (prompt: string) => void;
  readonly children?: ComponentChildren;
}) {
  return (
    <section class="deck-general-intro" aria-label={t("deck.generalOpen")}>
      <h2>{t("deck.generalWelcome")}</h2>
      <p>{t("deck.generalIntro")}</p>
      {children}
      <div class="deck-general-suggestions" aria-label={t("deck.generalExamples")}>
        {["explain", "compare", "summarize"].map((key) => (
          <Tooltip key={key} content={t("deck.generalStarterSendHint", {
            prompt: t(`deck.generalStarters.${key}.prompt`),
          })}>
            <button type="button" onClick={() => onPick(t(`deck.generalStarters.${key}.prompt`))}>
              {t(`deck.generalStarters.${key}.label`)}
            </button>
          </Tooltip>
        ))}
      </div>
    </section>
  );
}
