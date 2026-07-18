import capabilityCatalog from "../../../rule-catalog/reports/widget-capabilities.json";

/** Canonical upstream report-widget contract for the generic Process renderer. */
export const UPSTREAM_REPORT_WIDGET_TYPES: readonly string[] =
  capabilityCatalog.widgets.map((widget) => widget.type);

/** Types deliberately not rendered by the generic workflow surface. */
export const BLOCKED_REPORT_WIDGET_TYPES: ReadonlySet<string> = new Set(
  capabilityCatalog.widgets
    .filter((widget) => widget.frontend === "blocked")
    .map((widget) => widget.type),
);

export function missingWidgetTypes(
  supported: ReadonlySet<string>,
): readonly string[] {
  return UPSTREAM_REPORT_WIDGET_TYPES.filter(
    (type) => !supported.has(type) && !BLOCKED_REPORT_WIDGET_TYPES.has(type),
  );
}
