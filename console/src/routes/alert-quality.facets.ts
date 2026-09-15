/** Filter returned findings only; never recompute report totals or infer missing team ownership. */
import type { AlertNoiseFinding } from "./alert-quality.model";

export const ALERT_UNKNOWN_FACET = "__unknown__";

export interface AlertFindingFilters {
  readonly rule: string | null;
  readonly service: string;
  readonly team: string;
  readonly audience: string;
}

/** Empty selection means all; unknown is distinct from an explicitly empty destination set. */
export function filterAlertFindings(rows: readonly AlertNoiseFinding[], filters: AlertFindingFilters): readonly AlertNoiseFinding[] {
  const matches = (values: readonly string[] | null | undefined, selected: string) => selected === ""
    || (selected === ALERT_UNKNOWN_FACET ? values == null : values?.includes(selected) === true);
  return rows.filter((row) => (filters.rule === null || row.rule_ref === filters.rule)
    && (filters.service === "" || row.service_ref === filters.service)
    && matches(row.team_refs, filters.team) && matches(row.audience_kinds, filters.audience));
}
