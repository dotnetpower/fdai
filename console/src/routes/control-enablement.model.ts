import { OperatorApiError } from "../api";
import { panelBoolean, panelNonEmptyString, panelRecord } from "./panel-decode";

export interface ControlEnablement {
  readonly severity: "critical" | "high" | "medium" | "low" | "informational";
  readonly default_enabled: boolean;
  readonly enabled: boolean;
  readonly source: "severity_default" | "profile_override" | "lifecycle_disabled";
  readonly mode: "shadow";
  readonly execution_authority: false;
  readonly available?: boolean;
  readonly unavailable_reason?: string | null;
}

export type SeveritySource = "source" | "fdai_default";

export function decodeSeveritySource(value: unknown): SeveritySource | null {
  if (value === undefined || value === null) return null;
  if (value !== "source" && value !== "fdai_default") {
    throw new OperatorApiError(502, "invalid Operator API response: unknown severity source");
  }
  return value;
}

export function decodeControlEnablement(value: unknown): ControlEnablement | null {
  if (value === undefined || value === null) return null;
  const label = "control enablement";
  const raw = panelRecord(value, label);
  const severity = panelNonEmptyString(raw, "severity", label);
  const source = panelNonEmptyString(raw, "source", label);
  if (!["critical", "high", "medium", "low", "informational"].includes(severity)
    || !["severity_default", "profile_override", "lifecycle_disabled"].includes(source)
    || raw["mode"] !== "shadow" || raw["execution_authority"] !== false) {
    throw new OperatorApiError(502, "invalid Operator API response: control enablement has unsupported severity, source or authority");
  }
  const reason = raw["unavailable_reason"];
  if (reason !== undefined && reason !== null && (typeof reason !== "string" || !reason.trim())) {
    throw new OperatorApiError(502, "invalid Operator API response: control enablement unavailable_reason MUST be non-empty text");
  }
  return {
    severity: severity as ControlEnablement["severity"],
    default_enabled: panelBoolean(raw, "default_enabled", label),
    enabled: panelBoolean(raw, "enabled", label),
    source: source as ControlEnablement["source"], mode: "shadow", execution_authority: false,
    ...(raw["available"] === undefined ? {} : { available: panelBoolean(raw, "available", label) }),
    ...(reason === undefined ? {} : { unavailable_reason: reason as string | null }),
  };
}
