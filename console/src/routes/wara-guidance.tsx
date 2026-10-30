import type { ComponentChildren } from "preact";
import { getLocale } from "../i18n";
import { t } from "./i18n/governance";
import type { WaraControl } from "./wara-controls.model";
import { WaraGuidanceDiagram } from "./wara-guidance-diagram";
import { WaraGuidanceReferenceImage } from "./wara-guidance-image";
import { guidanceMissingKoreanFields, guidanceText, type GuidanceText } from "./wara-guidance.model";
import "./wara-guidance.css";

function Section({ name, children }: { readonly name: string; readonly children: ComponentChildren }) {
  return <section class={`wara-guidance-section wara-guidance-${name}`}><h3>{t(`governance.rules.wara.guidance.${name}`)}</h3>{children}</section>;
}

function TextList({ items, ordered = false }: { readonly items: readonly GuidanceText[]; readonly ordered?: boolean }) {
  const contents = items.map((item, index) => <li key={index}>{guidanceText(item, getLocale())}</li>);
  return ordered ? <ol class="wara-guidance-steps">{contents}</ol> : <ul>{contents}</ul>;
}

export function WaraGuidanceContent({ control, expanded, onExpand }: {
  readonly control: WaraControl;
  readonly expanded: boolean;
  readonly onExpand: () => void;
}) {
  const guidance = control.guidance;
  const locale = getLocale();
  return <div class="wara-guidance-content" data-recommendation-id={control.id}>
    {control.lifecycle === "disabled" ? <p class="wara-guidance-history" role="note">{t("governance.rules.wara.guidance.disabledHistory")}</p> : null}
    <h2 class="wara-guidance-title">{guidance ? guidanceText(guidance.title, locale) : control.title}</h2>
    <Section name="explanation">
      {guidance ? <div class="wara-guidance-intro-columns">
        <p class="wara-guidance-lead">{guidanceText(guidance.summary, locale)}</p>
        <p><strong>{t("governance.rules.wara.guidance.benefits")}</strong> {guidanceText(guidance.benefits, locale)}</p>
      </div> : <>
        <p class="wara-guidance-lead">{control.description || t("governance.rules.wara.guidance.baseUnavailable")}</p>
        {control.potential_benefits ? <p><strong>{t("governance.rules.wara.guidance.benefits")}</strong> {control.potential_benefits}</p> : null}
        <p class="wara-guidance-unavailable" role="status">{t("governance.rules.wara.guidance.unavailable")}</p>
        <a href={control.source_url} target="_blank" rel="noreferrer">{t("governance.rules.wara.detail.aprlSource")} ({control.source_version})</a>
      </>}
    </Section>
    {guidance ? <>
      {getLocale() === "ko" && guidanceMissingKoreanFields(guidance) > 0
        ? <p class="wara-guidance-translation-note" role="note">{t("governance.rules.wara.guidance.partialTranslation")}</p>
        : null}
      {guidance.reference_image
        ? <>
          <WaraGuidanceReferenceImage key={guidance.reference_image.asset_id} image={guidance.reference_image} />
          <details class="wara-guidance-supplement">
            <summary>{t("governance.rules.wara.guidance.supplementaryDiagram")}</summary>
            <WaraGuidanceDiagram diagram={guidance.diagram} expanded={expanded} onExpand={onExpand} />
          </details>
        </>
        : <WaraGuidanceDiagram diagram={guidance.diagram} expanded={expanded} onExpand={onExpand} />}
      <div class="wara-guidance-configuration-context">
      <Section name="applicability"><TextList items={guidance.applicability} /></Section>
      <Section name="configuration">
        <p class="wara-guidance-context">{t("governance.rules.wara.guidance.exampleBoundary")}</p>
        <table class="wara-guidance-comparison">
          <thead><tr><th scope="col">{t("governance.rules.wara.guidance.before")}</th><th scope="col">{t("governance.rules.wara.guidance.after")}</th></tr></thead>
          <tbody>{Array.from({ length: Math.max(guidance.configuration.before.length, guidance.configuration.after.length) }, (_, index) => <tr key={index}>
            <td>{guidance.configuration.before[index] ? guidanceText(guidance.configuration.before[index]!, locale) : "-"}</td>
            <td>{guidance.configuration.after[index] ? guidanceText(guidance.configuration.after[index]!, locale) : "-"}</td>
          </tr>)}</tbody>
        </table>
      </Section>
      </div>
      <Section name="rationale"><p>{guidanceText(guidance.rationale, locale)}</p></Section>
      <div class="wara-guidance-procedures">
        <Section name="implementation"><TextList items={guidance.implementation_steps} ordered /></Section>
        <Section name="verification"><TextList items={guidance.verification_steps} ordered /></Section>
      </div>
      <Section name="cautions"><TextList items={guidance.cautions} /></Section>
      <section class="wara-guidance-sources" aria-label={t("governance.rules.wara.guidance.sources")}>
        <h3>{t("governance.rules.wara.guidance.sources")}</h3>
        <ul>{guidance.sources.map((source) => <li key={source.url}><a href={source.url} target="_blank" rel="noreferrer">{guidanceText(source.label, locale)}</a></li>)}</ul>
        <p>{t("governance.rules.wara.detail.sourceVersion")}: <code>{control.source_version}</code></p>
      </section>
    </> : null}
  </div>;
}
