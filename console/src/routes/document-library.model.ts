import type { DocumentVersionSummary } from "../ingestion-api";

export type DocumentIndexFilter = "all" | "indexed" | "attention";

export interface DocumentGroup {
  readonly key: string;
  readonly documents: readonly DocumentVersionSummary[];
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
    const key = document.document_id;
    const group = groups.get(key);
    if (group) group.push(document);
    else groups.set(key, [document]);
  }
  return [...groups].map(([key, values]) => ({ key, documents: values }));
}
