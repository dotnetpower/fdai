import type { ComponentChildren } from "preact";
import { getLocale } from "../i18n";
import { t } from "./i18n/governance";
import { waraDisplayTitle, type WaraControl } from "./wara-controls.model";
import { WaraGuidanceDiagram } from "./wara-guidance-diagram";
import { WaraGuidanceReferenceImage } from "./wara-guidance-image";
import { guidanceMissingKoreanFields, guidanceText, type GuidancePresentation, type GuidanceText } from "./wara-guidance.model";
import "./wara-guidance.css";

function Section({ name, children, prefix = "wara" }: { readonly name: string; readonly children: ComponentChildren; readonly prefix?: string }) {
  const label = t(`governance.rules.wara.guidance.${name}`);
  return <section id={`${prefix}-${name}`} tabIndex={-1} class={`wara-guidance-section wara-guidance-${name}`} aria-label={name === "explanation" ? label : undefined}>
    {name !== "explanation" ? <h3>{label}</h3> : null}{children}
  </section>;
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
  return IllustratedGuidanceContent({
    control: { ...control, title: waraDisplayTitle(control, getLocale()) },
    expanded, onExpand, recommendationId: control.id,
  });
}

export function IllustratedGuidanceContent({ control, expanded, onExpand, prefix = "wara", unavailableLabel, recommendationId }: {
  readonly control: {
    readonly id: string;
    readonly title: string;
    readonly description?: string | null | undefined;
    readonly potential_benefits?: string | null;
    readonly lifecycle?: string;
    readonly guidance?: GuidancePresentation | null | undefined;
    readonly source_url?: string;
    readonly source_version: string;
  };
  readonly expanded: boolean;
  readonly onExpand: () => void;
  readonly prefix?: string;
  readonly unavailableLabel?: string;
  readonly recommendationId?: string;
}) {
  const guidance = control.guidance;
  const locale = getLocale();
  return <div class="wara-guidance-content" data-recommendation-id={recommendationId} data-guidance-id={control.id} data-locale={locale}>
    {control.lifecycle === "disabled" ? <p class="wara-guidance-history" role="note">{t("governance.rules.wara.guidance.disabledHistory")}</p> : null}
    <h2 class="wara-guidance-title">{guidance ? guidanceText(guidance.title, locale) : control.title}</h2>
    <Section name="explanation" prefix={prefix}>
      {guidance ? <div class="wara-guidance-intro">
        <div class="wara-guidance-intro-columns">
          <p class="wara-guidance-lead">{guidanceText(guidance.summary, locale)}</p>
          <p><strong>{t("governance.rules.wara.guidance.benefits")}</strong> {guidanceText(guidance.benefits, locale)}</p>
        </div>
        <nav class="wara-guidance-nav" aria-labelledby={`${prefix}-guidance-nav-title`}>
          <strong id={`${prefix}-guidance-nav-title`}>{t("governance.rules.wara.guidance.onThisPage")}</strong>
          {["configuration", "implementation", "verification", "runtime"].map((name) => <a key={name} href={`#${prefix}-${name}`} onClick={(event) => {
            event.preventDefault();
            const target = document.getElementById(`${prefix}-${name}`);
            target?.focus({ preventScroll: true });
            target?.scrollIntoView({ block: "start" });
          }}>{t(`governance.rules.wara.guidance.${name}`)}</a>)}
        </nav>
      </div> : <>
        <p class="wara-guidance-lead">{control.description || t("governance.rules.wara.guidance.baseUnavailable")}</p>
        {control.potential_benefits ? <p><strong>{t("governance.rules.wara.guidance.benefits")}</strong> {control.potential_benefits}</p> : null}
        <p class="wara-guidance-unavailable" role="status">{unavailableLabel ?? t("governance.rules.wara.guidance.unavailable")}</p>
        {control.source_url ? <a href={control.source_url} target="_blank" rel="noreferrer">{t("governance.rules.wara.detail.aprlSource")} ({control.source_version})</a> : null}
      </>}
    </Section>
    {guidance ? <>
      {getLocale() === "ko" && guidanceMissingKoreanFields(guidance) > 0
        ? <p class="wara-guidance-translation-note" role="note">{t("governance.rules.wara.guidance.partialTranslation")}</p>
        : null}
      {guidance.reference_image
        ? <>
          <WaraGuidanceReferenceImage key={guidance.reference_image.asset_id} image={guidance.reference_image} />
          <details class="wara-guidance-supplement" open={prefix !== "wara"}>
            <summary>{t("governance.rules.wara.guidance.supplementaryDiagram")}</summary>
            <WaraGuidanceDiagram diagram={guidance.diagram} expanded={expanded} onExpand={onExpand} />
          </details>
        </>
        : <WaraGuidanceDiagram diagram={guidance.diagram} expanded={expanded} onExpand={onExpand} />}
      <div class="wara-guidance-pair">
        <Section name="applicability" prefix={prefix}><TextList items={guidance.applicability} /></Section>
        <Section name="rationale" prefix={prefix}><p>{guidanceText(guidance.rationale, locale)}</p></Section>
      </div>
      <Section name="configuration" prefix={prefix}>
        <p class="wara-guidance-context">{t("governance.rules.wara.guidance.exampleBoundary")}</p>
        <div class="wara-guidance-comparison">
          {(["before", "after"] as const).map((side) => <section key={side} aria-label={t(`governance.rules.wara.guidance.${side}`)}>
            <h4>{t(`governance.rules.wara.guidance.${side}`)}</h4>
            <TextList items={guidance.configuration[side]} />
          </section>)}
        </div>
      </Section>
      <div class="wara-guidance-procedures">
        <Section name="implementation" prefix={prefix}><TextList items={guidance.implementation_steps} ordered /></Section>
        <Section name="verification" prefix={prefix}><TextList items={guidance.verification_steps} ordered /></Section>
      </div>
      <div class="wara-guidance-pair">
        <Section name="cautions" prefix={prefix}><TextList items={guidance.cautions} /></Section>
        <section class="wara-guidance-sources" aria-label={t("governance.rules.wara.guidance.sources")}>
          <h3>{t("governance.rules.wara.guidance.sources")}</h3>
          <ul>{guidance.sources.map((source) => <li key={source.url}><a href={source.url} target="_blank" rel="noreferrer">{guidanceText(source.label, locale)}</a></li>)}</ul>
          {control.source_version ? <p>{t("governance.rules.wara.detail.sourceVersion")}: <code>{control.source_version}</code></p> : null}
        </section>
      </div>
    </> : null}
  </div>;
}
