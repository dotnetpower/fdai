import type { OperatorApiClient } from "../api";
import { panelNonNegativeInteger, panelNonEmptyString, panelNullableString, panelRecord } from "./panel-decode";
import { decodeAnalyzerLifecycle, type DetectionLifecycleView } from "./detection-readiness";

export interface HistoryFilters {
  readonly q: string;
  readonly evidence: string;
  readonly delivery: string;
  readonly from: string;
  readonly to: string;
}

export interface DetectionHistoryPage {
  readonly lifecycle: DetectionLifecycleView;
  readonly totalReceipts: number;
  readonly totalAssessments: number;
  readonly totalTargets: number;
  readonly evidenceCounts: DetectionLifecycleView["evidence_counts"];
  readonly snapshotAt: string;
  readonly observedAt: string | null;
  readonly retainedFrom: string | null;
  readonly offset: number;
  readonly pageSize: number;
  readonly nextCursor: string | null;
}

export function decodeHistoryPage(value: unknown): DetectionHistoryPage {
  const root = panelRecord(value, "analyzer history");
  if (root.execution_authority !== false) throw new Error("Analyzer history widened authority");
  const lifecycle = decodeAnalyzerLifecycle(root.lifecycle);
  const page = panelRecord(root.pagination, "analyzer history pagination");
  const counts = panelRecord(page.evidence_counts, "analyzer history totals");
  const evidenceCounts = {
    complete: panelNonNegativeInteger(counts, "complete", "history totals"),
    incomplete: panelNonNegativeInteger(counts, "incomplete", "history totals"),
    conflicting: panelNonNegativeInteger(counts, "conflicting", "history totals"),
    missed: panelNonNegativeInteger(counts, "missed", "history totals"),
  };
  const totalAssessments = panelNonNegativeInteger(page, "total_assessments", "history");
  const totalReceipts = panelNonNegativeInteger(page, "total_receipts", "history");
  const totalTargets = panelNonNegativeInteger(page, "total_targets", "history");
  const offset = panelNonNegativeInteger(page, "offset", "history");
  const pageSize = panelNonNegativeInteger(page, "page_size", "history");
  const snapshotAt = panelNonEmptyString(page, "snapshot_at", "history");
  const nextCursor = page.next_cursor;
  if (Object.values(evidenceCounts).reduce((a, b) => a + b, 0) !== totalAssessments
      || totalReceipts < totalAssessments || totalTargets > totalAssessments
      || offset + lifecycle.assessment_count > totalAssessments
      || pageSize < 1 || pageSize > 100 || lifecycle.assessment_count > pageSize
      || Number.isNaN(Date.parse(snapshotAt))
      || !(nextCursor === null || (typeof nextCursor === "string" && nextCursor.length > 0 && nextCursor.length <= 1024))
      || (nextCursor !== null && lifecycle.assessment_count !== pageSize)
      || (nextCursor === null && offset + lifecycle.assessment_count !== totalAssessments)) {
    throw new Error("Analyzer history pagination totals do not reconcile");
  }
  return { lifecycle, totalReceipts, totalAssessments, totalTargets, evidenceCounts,
    snapshotAt, offset, pageSize, nextCursor,
    observedAt: panelNullableString(page, "observed_at", "history"),
    retainedFrom: panelNullableString(page, "retained_from", "history") };
}

/** Client-instance scoped LRU; stale pages and failed reads never become cache hits. */
export class DetectionHistoryCache {
  private readonly pages = new Map<string, { at: number; page: DetectionHistoryPage }>();
  private readonly snapshots = new Map<string, string>();
  private expiresAt = Date.now() + 5 * 60_000;
  private revision = 0;
  constructor(private readonly client: Pick<OperatorApiClient, "panel">) {}

  clear(): void {
    this.pages.clear();
    this.snapshots.clear();
    this.expiresAt = Date.now() + 5 * 60_000;
    this.revision++;
  }

  async load(filters: HistoryFilters, cursor: string | null, size: number): Promise<DetectionHistoryPage> {
    if (Date.now() >= this.expiresAt) {
      if (cursor) throw new Error("History cache expired; refresh history");
      this.clear();
    }
    const params = { view: "history", ...filters, limit: String(size), ...(cursor ? { cursor } : {}) };
    const scope = JSON.stringify([filters, size]);
    const key = JSON.stringify(params);
    const cached = this.pages.get(key);
    if (cached && Date.now() - cached.at < 5 * 60_000) {
      this.pages.delete(key);
      this.pages.set(key, cached);
      this.snapshots.delete(scope);
      this.snapshots.set(scope, cached.page.snapshotAt);
      return cached.page;
    }
    this.pages.delete(key);
    const revision = this.revision;
    const page = decodeHistoryPage(await this.client.panel<unknown>("/detection-coverage", params));
    if (page.pageSize !== size || (!cursor && page.offset !== 0)
        || (cursor && (page.offset === 0 || page.nextCursor === cursor))) {
      throw new Error("Analyzer history page did not make progress");
    }
    if (revision !== this.revision) throw new Error("History was refreshed during this read");
    const snapshot = this.snapshots.get(scope);
    if (snapshot && snapshot !== page.snapshotAt) throw new Error("History snapshot changed; refresh history");
    this.snapshots.delete(scope);
    this.snapshots.set(scope, page.snapshotAt);
    while (this.snapshots.size > 40) {
      const oldest = this.snapshots.keys().next().value;
      if (oldest !== undefined) this.snapshots.delete(oldest);
    }
    this.pages.set(key, { at: Date.now(), page });
    while (this.pages.size > 40) {
      const oldest = this.pages.keys().next().value;
      if (oldest !== undefined) this.pages.delete(oldest);
    }
    return page;
  }
}
