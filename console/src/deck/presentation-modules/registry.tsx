import type { ComponentType } from "preact";
import type { PresentationBlock } from "../backend-types";
import { CalloutModule } from "./callout";
import { ChartModule } from "./charts";
import { EvidenceModule } from "./evidence";
import { ListModule } from "./list";
import { SummaryModule } from "./summary";
import { TableModule } from "./table";
import { TimelineModule } from "./timeline";
import type {
  PresentationAccessibilityFallback,
  PresentationModuleProps,
  PresentationResponsivePolicy,
} from "./types";

interface PresentationModuleRegistration {
  readonly component: ComponentType<PresentationModuleProps>;
  readonly responsivePolicy: PresentationResponsivePolicy;
  readonly accessibilityFallback: PresentationAccessibilityFallback;
}

const REGISTRY: Readonly<Record<PresentationBlock["kind"], PresentationModuleRegistration>> = {
  summary: registration(SummaryModule, "reflow", "description-list"),
  callout: registration(CalloutModule, "reflow", "ordered-list"),
  table: registration(TableModule, "stack", "exact-table"),
  threshold_table: registration(TableModule, "stack", "exact-table"),
  list: registration(ListModule, "stack", "description-list"),
  coverage: registration(ChartModule, "stack", "exact-table"),
  bar: registration(ChartModule, "stack", "exact-table"),
  time_series: registration(ChartModule, "scroll", "exact-table"),
  comparison: registration(ChartModule, "stack", "exact-table"),
  timeline: registration(TimelineModule, "stack", "ordered-list"),
  evidence: registration(EvidenceModule, "reflow", "description-list"),
};

export function PresentationModuleView({ block }: PresentationModuleProps) {
  const registered = REGISTRY[block.kind];
  const Component = registered.component;
  return (
    <div
      class="deck-presentation-module"
      data-responsive-policy={registered.responsivePolicy}
      data-accessibility-fallback={registered.accessibilityFallback}
    >
      <Component block={block} />
    </div>
  );
}

export function presentationModuleRegistration(kind: PresentationBlock["kind"]) {
  return REGISTRY[kind];
}

function registration(
  component: ComponentType<PresentationModuleProps>,
  responsivePolicy: PresentationResponsivePolicy,
  accessibilityFallback: PresentationAccessibilityFallback,
): PresentationModuleRegistration {
  return { component, responsivePolicy, accessibilityFallback };
}
