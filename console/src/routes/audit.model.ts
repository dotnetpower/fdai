import type { AuditPage } from "../types";

export interface AuditData {
  readonly items: AuditPage["items"];
  readonly nextCursor: string | null;
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
  };
}