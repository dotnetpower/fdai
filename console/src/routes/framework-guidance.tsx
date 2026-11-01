import { IllustratedGuidanceContent } from "./wara-guidance";
import type { FrameworkGuidance } from "./framework-guidance.model";
import { t } from "./i18n/governance";
import { resolveControlReferenceImage } from "./reference-images.catalog";

export function FrameworkGuidanceContent({ guidance, controlId, title, description, expanded, onExpand, unavailableReason }: {
  readonly guidance: FrameworkGuidance | null | undefined;
  readonly controlId: string;
  readonly title: string;
  readonly description?: string | undefined;
  readonly expanded: boolean;
  readonly onExpand: () => void;
  readonly unavailableReason?: string | null | undefined;
}) {
  const referenceImage = guidance ? (guidance.reference_image ?? resolveControlReferenceImage(guidance.framework_id, controlId)) : undefined;
  const enrichedGuidance = guidance && referenceImage ? { ...guidance, reference_image: referenceImage } : guidance;
  return <IllustratedGuidanceContent
    control={{ id: controlId, title, description, guidance: enrichedGuidance, source_version: guidance?.source_revision ?? "" }}
    expanded={expanded} onExpand={onExpand} prefix="framework"
    unavailableLabel={`${t("governance.rules.frameworkGuidance.unavailable")}${unavailableReason ? ` ${t("governance.rules.frameworkGuidance.reason", { reason: unavailableReason })}` : ""}`}
  />;
}
