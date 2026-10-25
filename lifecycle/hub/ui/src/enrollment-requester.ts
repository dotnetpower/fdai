import type { PendingEnrollment } from "./api";

const SHORT_ID_LENGTH = 8;

export interface EnrollmentRequester {
  label: string;
  // True only for a request the installation Agent proposed; approval still belongs to a human.
  fromAgent: boolean;
}

export function enrollmentRequester(
  request: Pick<PendingEnrollment, "requested_by" | "requested_via">,
): EnrollmentRequester {
  const via = request.requested_via ?? null;
  const by = request.requested_by ?? null;
  if (via === "agent" && by) {
    return {
      label: `Requested by installation Agent ${by.slice(0, SHORT_ID_LENGTH)}`,
      fromAgent: true,
    };
  }
  if (via === "operator" && by) {
    return { label: "Requested by operator", fromAgent: false };
  }
  return { label: "Requested from a signed file", fromAgent: false };
}
