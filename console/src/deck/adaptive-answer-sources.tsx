import { t } from "../i18n";
import type { AdaptiveAnswer } from "./adaptive-answer";

/** Render source classifications per goal, never a whole-answer verification badge. */
export function AdaptiveAnswerSources({ answer }: { readonly answer: AdaptiveAnswer }) {
  return (
    <section aria-label={t("deck.adaptive.sources")}>
      <p class="muted">{t("deck.adaptive.owner", { agent: answer.role_agent })}</p>
      <ul>
        {answer.goals.map((goal) => (
          <li key={goal.goal_id} data-goal-id={goal.goal_id}>
            <span>
              {goal.kind === "knowledge"
                ? t("deck.adaptive.knowledge")
                : goal.kind === "environment_example"
                  ? t("deck.adaptive.environmentExample")
                  : t("deck.adaptive.operational")}
            </span>
            {goal.kind !== "knowledge" || goal.status !== "answered" ? (
              <span>
                {" - "}{t(`deck.adaptive.${goal.status}`)}
              </span>
            ) : null}
            {goal.limitation ? (
              <details>
                <summary>{t("deck.adaptive.limitationDetails")}</summary>
                <p style={{ overflowWrap: "anywhere" }}>{goal.limitation}</p>
              </details>
            ) : null}
            {goal.evidence_refs.length > 0 ? (
              <details>
                <summary>{t("deck.adaptive.references", { count: goal.evidence_refs.length })}</summary>
                <ul>{goal.evidence_refs.map((ref) => <li key={ref}><code>{ref}</code></li>)}</ul>
              </details>
            ) : null}
          </li>
        ))}
      </ul>
      <p class="muted">{t("deck.adaptive.authority")}</p>
    </section>
  );
}
