import type { AuditItem } from "../types";

export type IncidentMilestoneStatus = "initial" | "progress" | "issue" | "success" | "resolved";

export interface IncidentMilestone {
  readonly item: AuditItem;
  readonly status: IncidentMilestoneStatus;
  readonly evidenceRefs: readonly string[];
  readonly evidenceRefsTruncated: boolean;
  readonly gaps: readonly string[];
  readonly gapsTruncated: boolean;
  readonly evaluationReceipt: string | null;
  readonly learningCandidate: string | null;
}

const MAX_MILESTONES = 8;
const MAX_REFERENCES = 5;

export function incidentMilestones(items: readonly AuditItem[]): readonly IncidentMilestone[] {
  const bounded = items.length <= MAX_MILESTONES
    ? items
    : [items[0]!, ...items.slice(-(MAX_MILESTONES - 1))];
  return bounded.map((item) => {
    const evidenceRefs = evidenceReferences(item);
    const gaps = stringArray(item.entry["evidence_gaps"] ?? item.entry["unavailable_evidence"]);
    return {
      item,
      status: milestoneStatus(item),
      evidenceRefs: evidenceRefs.slice(0, MAX_REFERENCES),
      evidenceRefsTruncated: evidenceRefs.length > MAX_REFERENCES,
      gaps: gaps.slice(0, MAX_REFERENCES),
      gapsTruncated: gaps.length > MAX_REFERENCES,
      evaluationReceipt: exactString(item.entry["evaluation_receipt_id"]),
      learningCandidate: learningCandidate(item),
    };
  });
}

function milestoneStatus(item: AuditItem): IncidentMilestoneStatus {
  if (item.action_kind === "incident.open") return "initial";
  const tokens = [
    item.action_kind,
    exactString(item.entry["status"]),
    exactString(item.entry["state"]),
    exactString(item.entry["to_state"]),
    exactString(item.entry["outcome"]),
    exactString(item.entry["decision"]),
  ].filter((value): value is string => value !== null).map((value) => value.toLowerCase());
  if (tokens.some((value) => /(^|[._-])(resolved|closed)($|[._-])/.test(value))) return "resolved";
  if (tokens.some((value) => /(^|[._-])(failed|failure|deny|denied|abstain|abstained|error)($|[._-])/.test(value))) {
    return "issue";
  }
  if (tokens.some((value) => /(^|[._-])(success|succeeded|verified|applied|mitigated)($|[._-])/.test(value))) {
    return "success";
  }
  return "progress";
}

function evidenceReferences(item: AuditItem): readonly string[] {
  const references = [
    ...stringArray(item.entry["evidence_refs"]),
    exactString(item.entry["evidence_id"]),
    exactString(item.entry["audit_id"]),
    exactString(item.entry["verification_receipt"]),
  ].filter((value): value is string => value !== null);
  const citations = item.entry["citations"];
  if (Array.isArray(citations)) {
    for (const citation of citations) {
      if (citation !== null && typeof citation === "object" && !Array.isArray(citation)) {
        const ref = exactString((citation as Record<string, unknown>)["ref"]);
        if (ref !== null) references.push(ref);
      }
    }
  }
  return [...new Set(references)];
}

function learningCandidate(item: AuditItem): string | null {
  const state = exactString(item.entry["learning_candidate_state"]);
  if (state !== "inert" && state !== "draft" && state !== "review_pending") return null;
  return exactString(item.entry["learning_candidate_ref"]);
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map(exactString).filter((item): item is string => item !== null);
}

function exactString(value: unknown): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : null;
}
