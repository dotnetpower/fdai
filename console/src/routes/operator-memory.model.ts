import {
  panelArray,
  panelBoolean,
  panelNullableString,
  panelRecord,
  panelString,
} from "./panel-decode";

export interface OperatorMemoryReviewItem {
  readonly id: string;
  readonly scopeKind: "resource-group" | "resource";
  readonly scopeRef: string;
  readonly category: string;
  readonly body: string;
  readonly sourceEvent: string;
  readonly sourceRef: string;
  readonly author: string;
  readonly approvedBy: string;
  readonly approvalState: "approved";
  readonly createdAt: string;
  readonly expiresAt: string | null;
  readonly expired: boolean;
  readonly supersededBy: string | null;
  readonly active: boolean;
}

export interface MemoryCompactionReviewItem {
  readonly candidateId: string;
  readonly scopeKind: string;
  readonly scopeRef: string;
  readonly category: string;
  readonly body: string;
  readonly sourceRefs: readonly string[];
  readonly proposedByAgent: string;
  readonly state: string;
  readonly reviewedBy: string | null;
  readonly reviewReason: string | null;
}

export interface OperatorMemoryReviewView {
  readonly items: readonly OperatorMemoryReviewItem[];
  readonly compactions: readonly MemoryCompactionReviewItem[];
}

export interface OperatorMemoryFilters {
  readonly scopeKind: "" | "resource-group" | "resource";
  readonly scopeRef: string;
}

export function parseOperatorMemoryFilters(params: URLSearchParams): OperatorMemoryFilters & { readonly invalid: boolean } {
  const kind = params.get("scope_kind") ?? "";
  const ref = (params.get("scope_ref") ?? "").trim();
  const validKind = kind === "" || kind === "resource-group" || kind === "resource";
  return {
    scopeKind: validKind ? kind : "",
    scopeRef: ref.length <= 256 ? ref : "",
    invalid: !validKind || ref.length > 256,
  };
}

export function operatorMemoryQuery(filters: OperatorMemoryFilters): Readonly<Record<string, string>> {
  return { limit: "100", ...(filters.scopeKind ? { scope_kind: filters.scopeKind } : {}),
    ...(filters.scopeRef.trim() ? { scope_ref: filters.scopeRef.trim() } : {}) };
}

export function operatorMemoryFilterHref(href: string, filters: OperatorMemoryFilters): string {
  const url = new URL(href);
  if (filters.scopeKind) url.searchParams.set("scope_kind", filters.scopeKind);
  else url.searchParams.delete("scope_kind");
  if (filters.scopeRef.trim()) url.searchParams.set("scope_ref", filters.scopeRef.trim());
  else url.searchParams.delete("scope_ref");
  return `${url.pathname}${url.search}${url.hash}`;
}

export function operatorMemoryFiltersEqual(left: OperatorMemoryFilters, right: OperatorMemoryFilters): boolean {
  return left.scopeKind === right.scopeKind && left.scopeRef.trim() === right.scopeRef.trim();
}

export type OperatorMemoryDisplayState = "active" | "expired" | "superseded";

export function operatorMemoryDisplayState(
  item: OperatorMemoryReviewItem,
  now: number,
): OperatorMemoryDisplayState {
  const expiresAt = item.expiresAt === null ? Number.NaN : Date.parse(item.expiresAt);
  if (item.expired || (Number.isFinite(expiresAt) && expiresAt <= now)) return "expired";
  return item.active ? "active" : "superseded";
}

export function nextOperatorMemoryExpiryDelay(
  items: readonly OperatorMemoryReviewItem[],
  now: number,
): number | null {
  const next = items
    .filter((item) => item.active && !item.expired)
    .map((item) => item.expiresAt === null ? Number.NaN : Date.parse(item.expiresAt))
    .filter((expiresAt) => Number.isFinite(expiresAt) && expiresAt > now)
    .sort((left, right) => left - right)[0];
  return next === undefined ? null : Math.min(2_147_483_647, Math.max(1, next - now + 20));
}

export function decodeOperatorMemory(value: unknown): OperatorMemoryReviewView {
  const root = panelRecord(value, "operator memory");
  const items = panelArray(root["items"], "operator memory.items").map((entry, index) => {
    const label = `operator memory.items[${index}]`;
    const item = panelRecord(entry, label);
    const scopeKind = panelString(item, "scope_kind", label);
    const approvalState = panelString(item, "approval_state", label);
    if (scopeKind !== "resource-group" && scopeKind !== "resource") {
      throw new Error(`${label}.scope_kind is invalid`);
    }
    if (approvalState !== "approved") throw new Error(`${label}.approval_state is invalid`);
    return {
      id: panelString(item, "id", label),
      scopeKind: scopeKind as OperatorMemoryReviewItem["scopeKind"],
      scopeRef: panelString(item, "scope_ref", label),
      category: panelString(item, "category", label),
      body: panelString(item, "body", label),
      sourceEvent: panelString(item, "source_event", label),
      sourceRef: panelString(item, "source_ref", label),
      author: panelString(item, "author", label),
      approvedBy: panelString(item, "approved_by", label),
      approvalState: approvalState as OperatorMemoryReviewItem["approvalState"],
      createdAt: panelString(item, "created_at", label),
      expiresAt: panelNullableString(item, "expires_at", label),
      expired: panelBoolean(item, "expired", label),
      supersededBy: panelNullableString(item, "superseded_by", label),
      active: panelBoolean(item, "active", label),
    };
  });
  const compactions = panelArray(root["compactions"], "operator memory.compactions").map(
    (entry, index) => {
      const label = `operator memory.compactions[${index}]`;
      const item = panelRecord(entry, label);
      return {
        candidateId: panelString(item, "candidate_id", label),
        scopeKind: panelString(item, "scope_kind", label),
        scopeRef: panelString(item, "scope_ref", label),
        category: panelString(item, "category", label),
        body: panelString(item, "body", label),
        sourceRefs: panelArray(item["source_refs"], `${label}.source_refs`).map(
          (source) => {
            if (typeof source !== "string") throw new Error(`${label}.source_refs is invalid`);
            return source;
          },
        ),
        proposedByAgent: panelString(item, "proposed_by_agent", label),
        state: panelString(item, "state", label),
        reviewedBy: panelNullableString(item, "reviewed_by", label),
        reviewReason: panelNullableString(item, "review_reason", label),
      };
    },
  );
  return { items, compactions };
}
