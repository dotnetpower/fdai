import { PageHeader, UnavailableState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { t } from "../i18n";
import type { PanelProps } from "../panels";
import { currentRoute, routeHref } from "../router";
import { knowledgeText, type KnowledgeMessageKey } from "./knowledge-sources.i18n";

export type KnowledgeSourceId = "documents" | "github" | "gitlab" | "azure-devops";

export interface KnowledgeSourceDefinition {
  readonly id: KnowledgeSourceId;
  readonly panelId: string;
  readonly summaryKey: KnowledgeMessageKey;
  readonly connector: boolean;
}

export const KNOWLEDGE_SOURCE_DEFINITIONS: readonly KnowledgeSourceDefinition[] = [
  {
    id: "documents",
    panelId: "documents",
    summaryKey: "documentsSummary",
    connector: false,
  },
  {
    id: "github",
    panelId: "github",
    summaryKey: "githubSummary",
    connector: true,
  },
  {
    id: "gitlab",
    panelId: "gitlab",
    summaryKey: "gitlabSummary",
    connector: true,
  },
  {
    id: "azure-devops",
    panelId: "azure-devops",
    summaryKey: "azureDevopsSummary",
    connector: true,
  },
];

export function KnowledgeOverviewRoute(_props: PanelProps) {
  usePublishViewContext(
    () => ({
      routeId: "knowledge",
      routeLabel: t("nav.group.knowledge"),
      purpose: knowledgeText("viewPurpose"),
      headline: knowledgeText("subtitle"),
      capturedAt: new Date().toISOString(),
      facts: KNOWLEDGE_SOURCE_DEFINITIONS.map((source) => ({
        key: source.id,
        value: source.connector ? "setup-required" : "managed-upload",
        group: "knowledge-source",
      })),
      records: {
        sources: KNOWLEDGE_SOURCE_DEFINITIONS.map((source) => ({
          id: source.id,
          panel_id: source.panelId,
          connector: source.connector,
        })),
      },
    }),
    [],
  );

  return (
    <div class="stack knowledge-route">
      <PageHeader title={t("nav.group.overview")} subtitle={knowledgeText("subtitle")} />
      <section aria-labelledby="knowledge-sources-title">
        <div class="knowledge-section-heading">
          <div>
            <h3 id="knowledge-sources-title">{knowledgeText("sourcesTitle")}</h3>
            <p>{knowledgeText("sourcesHint")}</p>
          </div>
          <a class="secondary knowledge-settings-link" href={routeHref("settings-integrations")}>
            {knowledgeText("openIntegrationSettings")}
          </a>
        </div>
        <div class="knowledge-source-grid">
          {KNOWLEDGE_SOURCE_DEFINITIONS.map((source) => (
            <a class="knowledge-source-card" href={routeHref(source.panelId)} key={source.id}>
              <div>
                <h3>{knowledgeSourceTitle(source.id)}</h3>
                <span class="knowledge-source-kind">
                  {knowledgeText(source.connector ? "connectedSource" : "managedUpload")}
                </span>
              </div>
              <p>{knowledgeText(source.summaryKey)}</p>
              <span class="knowledge-source-open">{knowledgeText("openSource")}</span>
            </a>
          ))}
        </div>
      </section>
    </div>
  );
}

function KnowledgeGithubRoute(props: PanelProps) {
  return <KnowledgeConnectorRoute {...props} sourceId="github" />;
}

function KnowledgeGitlabRoute(props: PanelProps) {
  return <KnowledgeConnectorRoute {...props} sourceId="gitlab" />;
}

function KnowledgeAzureDevopsRoute(props: PanelProps) {
  return <KnowledgeConnectorRoute {...props} sourceId="azure-devops" />;
}

export function KnowledgeSourcesRoute(props: PanelProps) {
  switch (currentRoute().panelId) {
    case "github":
      return <KnowledgeGithubRoute {...props} />;
    case "gitlab":
      return <KnowledgeGitlabRoute {...props} />;
    case "azure-devops":
      return <KnowledgeAzureDevopsRoute {...props} />;
    default:
      return <KnowledgeOverviewRoute {...props} />;
  }
}

function KnowledgeConnectorRoute({
  sourceId,
}: PanelProps & { readonly sourceId: Exclude<KnowledgeSourceId, "documents"> }) {
  const source = KNOWLEDGE_SOURCE_DEFINITIONS.find((candidate) => candidate.id === sourceId);
  if (source === undefined) {
    throw new Error(`Unknown knowledge source: ${sourceId}`);
  }
  const provider = knowledgeSourceTitle(source.id);

  usePublishViewContext(
    () => ({
      routeId: source.panelId,
      routeLabel: provider,
      purpose: knowledgeText("connectorViewPurpose", { provider }),
      headline: knowledgeText("connectorUnavailableTitle", { provider }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "provider", value: source.id, group: "knowledge-source" },
        { key: "connection_state", value: "setup-required", group: "knowledge-source" },
      ],
      records: {},
    }),
    [provider, source.id, source.panelId],
  );

  return (
    <div class="stack knowledge-route">
      <PageHeader
        title={provider}
        subtitle={knowledgeText("connectorSubtitle", { provider })}
      />
      <section class="knowledge-connector-state" aria-labelledby="knowledge-connector-title">
        <span class="knowledge-source-kind">{knowledgeText("setupRequired")}</span>
        <h3 id="knowledge-connector-title">
          {knowledgeText("connectorUnavailableTitle", { provider })}
        </h3>
        <UnavailableState
          evidenceState="not-connected"
          message={knowledgeText("connectorUnavailableBody", { provider })}
        />
        <p>{knowledgeText("connectorBoundary")}</p>
        <nav class="knowledge-connector-actions" aria-label={knowledgeText("connectorActions")}>
          <a class="primary" href={routeHref("settings-integrations")}>
            {knowledgeText("openIntegrationSettings")}
          </a>
          <a class="secondary" href={routeHref("knowledge")}>
            {knowledgeText("backToOverview")}
          </a>
        </nav>
      </section>
    </div>
  );
}

function knowledgeSourceTitle(sourceId: KnowledgeSourceId): string {
  switch (sourceId) {
    case "documents":
      return t("nav.panel.documents");
    case "github":
      return "GitHub";
    case "gitlab":
      return "GitLab";
    case "azure-devops":
      return "Azure DevOps";
  }
}
