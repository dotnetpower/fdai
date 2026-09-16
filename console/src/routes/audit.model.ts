import type { AuditItem, AuditPage, AuditSummary } from "../types";

export interface AuditData {
  readonly items: AuditPage["items"];
  readonly nextCursor: string | null;
  readonly summary: AuditSummary | null;
}

/** Return only a recorded non-empty text value; absent evidence stays absent. */
export function auditEntryText(entry: AuditItem["entry"], key: string): string | null {
  const value = entry[key];
  return typeof value === "string" && value.trim() ? value : null;
}

/** Keep causal fields attached to exact record identity in current-screen context. */
export function auditContextRecord(item: AuditItem) {
  const context = item.context;
  return {
    seq: item.seq, recorded_at: item.recorded_at, actor: item.actor,
    action_kind: item.action_kind, mode: item.mode, event_id: item.event_id,
    correlation_id: item.correlation_id ?? "-",
    record_kind: context?.record_kind ?? "audit_record",
    target: context?.target ?? "-",
    tier: context?.tier ?? auditEntryText(item.entry, "tier") ?? "-",
    outcome: context?.outcome ?? auditEntryText(item.entry, "outcome") ?? "-",
    summary: auditEntryText(item.entry, "summary") ?? "-",
    detail: auditEntryText(item.entry, "detail") ?? "-",
    reason: auditEntryText(item.entry, "reason") ?? "-",
  };
}

/** Search the loaded page, never imply a search across the complete ledger. */
export function searchAuditItems(items: readonly AuditItem[], query: string): readonly AuditItem[] {
  const search = query.trim().toLocaleLowerCase();
  if (!search) return items;
  return items.filter((item) => [
    String(item.seq), item.action_kind, item.actor, item.event_id, item.correlation_id,
    item.context?.target, item.context?.idempotency_key,
    auditEntryText(item.entry, "rule_id"), auditEntryText(item.entry, "idempotency_key"),
  ].some((value) => value?.toLocaleLowerCase().includes(search)));
}

/** A named stage is evidence of that record only, not proof of an operational effect. */
export function auditRecordedPhase(item: AuditItem): NonNullable<AuditItem["context"]>["phase"] {
  if (item.context) return item.context.phase;
  const stage = auditEntryText(item.entry, "stage");
  switch (stage) {
    case "intent": case "plan": case "propose": return "intent";
    case "dispatch": case "execute": return "dispatch";
    case "observe": case "verify": return "observe";
    case "close": case "audit": return "close";
    default: return null;
  }
}

export type AuditEntrySelection =
  | { readonly status: "none" }
  | { readonly status: "invalid"; readonly value: string }
  | { readonly status: "selected"; readonly seq: number }
  | { readonly status: "pending"; readonly seq: number }
  | { readonly status: "unavailable"; readonly seq: number };

export function resolveAuditEntry(
  data: AuditData,
  requested: string | null,
): AuditEntrySelection {
  if (requested === null) return { status: "none" };
  if (!/^[1-9][0-9]*$/.test(requested)) {
    return { status: "invalid", value: requested };
  }
  const seq = Number(requested);
  if (!Number.isSafeInteger(seq)) return { status: "invalid", value: requested };
  if (data.items.some((item) => item.seq === seq)) return { status: "selected", seq };
  return data.nextCursor === null
    ? { status: "unavailable", seq }
    : { status: "pending", seq };
}

export function appendAuditPage(
  current: AuditData,
  requestedCursor: string,
  page: AuditPage,
): AuditData {
  if (current.nextCursor !== requestedCursor) return current;
  const seen = new Set(current.items.map((item) => item.seq));
  return {
    items: [...current.items, ...page.items.filter((item) => !seen.has(item.seq))],
    nextCursor: page.next_cursor,
    summary: current.summary,
  };
}
