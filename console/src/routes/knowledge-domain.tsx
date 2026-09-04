import type { PanelProps } from "../panels";
import { currentRoute } from "../router";
import { DocumentIngestionRoute } from "./document-ingestion";
import { KnowledgeSourcesRoute } from "./knowledge-sources";

export default function KnowledgeDomainRoute(props: PanelProps) {
  return currentRoute().panelId === "documents"
    ? <DocumentIngestionRoute client={props.client} />
    : <KnowledgeSourcesRoute {...props} />;
}
