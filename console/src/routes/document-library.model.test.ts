import { describe, expect, it } from "vitest";
import type { DocumentVersionSummary } from "../ingestion-api";
import { groupDocuments } from "./document-library.model";

const BASE = {
  document_id: "document-1",
  version_id: "version-1",
  source_name: "guide.txt",
  size_bytes: 10,
  media_type: "text/plain",
  observed_format: "text",
  state: "ready",
  classification: "unclassified",
  sensitivity_label: null,
  protection_state: "none",
  purposes: ["knowledge_base"],
  created_at: "2026-09-05T03:00:00Z",
  updated_at: "2026-09-05T03:01:00Z",
  active: true,
  available: true,
  warnings: [],
  failure_code: null,
  index_status: "indexed",
  preview_available: true,
  download_available: true,
  delete_available: true,
  disposition: "governed_knowledge",
  scope_kind: "collection",
  scope_ref: "shared-knowledge",
  source_expires_at: null,
  derived_expires_at: null,
  retention_state: "live",
  index_state: "active",
  promotable: false,
} as const satisfies DocumentVersionSummary;

describe("groupDocuments", () => {
  it("keeps independent documents separate even when source names match", () => {
    const older = { ...BASE, document_id: "document-2", version_id: "version-2" };
    const other = { ...BASE, document_id: "document-3", source_name: "runbook.pdf" };

    const groups = groupDocuments([BASE, older, other], "", "all");

    expect(groups.map((group) => group.documents.map((item) => item.document_id))).toEqual([
      ["document-1"],
      ["document-2"],
      ["document-3"],
    ]);
  });

  it("filters by source name and index attention state before grouping", () => {
    const pending = {
      ...BASE,
      document_id: "document-2",
      source_name: "pending-runbook.pdf",
      index_status: "pending",
    } as const satisfies DocumentVersionSummary;

    expect(groupDocuments([BASE, pending], "runbook", "attention"))
      .toEqual([{ key: "document-2", documents: [pending] }]);
  });
});
