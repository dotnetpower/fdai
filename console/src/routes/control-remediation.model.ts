import { OperatorApiError } from "../api";
import { panelArray, panelNonEmptyString, panelRecord, panelStringArray } from "./panel-decode";

export interface ControlRemediation {
  readonly status: "manual_guidance" | "governed_candidates" | "unavailable";
  readonly candidates: readonly { readonly rule_id: string; readonly action_type_ref: string }[];
  readonly limitations: readonly string[];
  readonly execution_authority: false;
}

export function decodeControlRemediation(value: unknown): ControlRemediation | null {
  if (value === undefined || value === null) return null;
  const raw = panelRecord(value, "control remediation");
  if (!["manual_guidance", "governed_candidates", "unavailable"].includes(String(raw["status"]))
    || raw["execution_authority"] !== false) {
    throw new OperatorApiError(502, "invalid Operator API response: control remediation has unsupported status or authority");
  }
  const candidates = panelArray(raw["candidates"], "control remediation.candidates").map((item) => {
    const candidate = panelRecord(item, "control remediation candidate");
    return {
      rule_id: panelNonEmptyString(candidate, "rule_id", "control remediation candidate"),
      action_type_ref: panelNonEmptyString(candidate, "action_type_ref", "control remediation candidate"),
    };
  });
  return {
    status: raw["status"] as ControlRemediation["status"], candidates,
    limitations: panelStringArray(raw["limitations"], "control remediation.limitations"),
    execution_authority: false,
  };
}
