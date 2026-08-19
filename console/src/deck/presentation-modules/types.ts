import type { PresentationBlock } from "../backend-types";

export interface PresentationModuleProps {
  readonly block: PresentationBlock;
}

export type PresentationResponsivePolicy = "reflow" | "scroll" | "stack";
export type PresentationAccessibilityFallback = "description-list" | "exact-table" | "ordered-list";
