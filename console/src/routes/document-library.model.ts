import type { DocumentVersionSummary } from "../ingestion-api";

export type DocumentIndexFilter = "all" | "indexed" | "attention";

export interface DocumentGroup {
  readonly key: string;
  readonly documents: readonly DocumentVersionSummary[];
}

function newestFirst(
  left: DocumentVersionSummary,
  right: DocumentVersionSummary,
): number {
  return right.created_at.localeCompare(left.created_at)
    || right.version_id.localeCompare(left.version_id);
}

export function mergeDocumentVersions(
  groups: readonly (readonly DocumentVersionSummary[])[],
): readonly DocumentVersionSummary[] {
  const versions = new Map<string, DocumentVersionSummary>();
  for (const group of groups) {
    for (const document of group) {
      versions.set(`${document.document_id}:${document.version_id}`, document);
    }
  }
  return [...versions.values()].sort(newestFirst);
}

export function groupDocuments(
  documents: readonly DocumentVersionSummary[],
  query: string,
  filter: DocumentIndexFilter,
): readonly DocumentGroup[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const groups = new Map<string, DocumentVersionSummary[]>();
  for (const document of documents) {
    if (
      normalizedQuery
      && !document.source_name.toLocaleLowerCase().includes(normalizedQuery)
    ) {
      continue;
    }
    if (filter === "indexed" && document.index_status !== "indexed") continue;
    if (filter === "attention" && document.index_status === "indexed") continue;
    const key = document.source_name;
    const group = groups.get(key);
    if (group) group.push(document);
    else groups.set(key, [document]);
  }
  return [...groups]
    .map(([key, values]) => ({ key, documents: values.sort(newestFirst) }))
    .sort((left, right) => newestFirst(left.documents[0]!, right.documents[0]!));
}
