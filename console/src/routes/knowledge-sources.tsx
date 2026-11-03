import { PageHeader, StatusPill, UnavailableState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary, TERMS } from "../deck/glossary";
import { getLocale, t } from "../i18n";
import type { PanelProps } from "../panels";
import { currentRoute, routeHref } from "../router";
import { CloudKnowledgePanel } from "./cloud-knowledge";
import { KnowledgeGithubRoute } from "./knowledge-github";
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

export function KnowledgeOverviewRoute(props: PanelProps) {
  usePublishViewContext(
    () => ({
      routeId: "knowledge",
      routeLabel: knowledgeText("sourcesTitle"),
      purpose: knowledgeText("viewPurpose"),
      glossary: composeGlossary([TERMS.documentCollection]),
      headline: knowledgeText("subtitle"),
      capturedAt: new Date().toISOString(),
      facts: KNOWLEDGE_SOURCE_DEFINITIONS.map((source) => ({
        key: source.id,
        value: source.id === "github" ? "server-owned-state" : source.connector ? "setup-required" : "managed-upload",
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
    <div class="stack knowledge-route cs-workspace-route">
      <PageHeader title={knowledgeText("overviewTitle")} subtitle={knowledgeText("subtitle")} />
      <div class="governance-readonly-banner">
        <strong>{knowledgeText("sourcesTitle")}</strong>
        <span>{knowledgeText("sourcesHint")}</span>
      </div>
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
                <StatusPill
                  kind={source.connector ? "neutral" : "info"}
                  label={knowledgeText(source.id === "github" ? "checkStatus" : source.connector ? "setupRequired" : "managedUpload")}
                />
              </div>
              <p>{knowledgeText(source.summaryKey)}</p>
              <span class="knowledge-source-open">{knowledgeText("openSource")}</span>
            </a>
          ))}
        </div>
      </section>
      <CloudKnowledgePanel {...props} />
      <section class="stack-section" aria-labelledby="knowledge-retrieval-contract-title">
        <h3 id="knowledge-retrieval-contract-title" class="section-title">
          {getLocale() === "ko" ? "지식 검색 계약" : "Retrieval contract"}
        </h3>
        <dl class="cs-facts-grid">
          <div><dt>{getLocale() === "ko" ? "목적" : "Purpose"}</dt><dd>{getLocale() === "ko" ? "근거에 기반한 운영자 답변" : "Evidence-grounded operator answers"}</dd></div>
          <div><dt>{getLocale() === "ko" ? "권한" : "Authorization"}</dt><dd>{getLocale() === "ko" ? "원본 및 컬렉션 범위 제한" : "Source and collection scoped"}</dd></div>
          <div><dt>{getLocale() === "ko" ? "최신성" : "Freshness"}</dt><dd>{getLocale() === "ko" ? "관측 시점별 보고" : "Reported per observation"}</dd></div>
          <div><dt>{getLocale() === "ko" ? "불완전한 커버리지" : "Incomplete coverage"}</dt><dd>{getLocale() === "ko" ? "명시적 사용 불가 표시" : "Explicitly unavailable"}</dd></div>
          <div><dt>{getLocale() === "ko" ? "실행 권한" : "Execution authority"}</dt><dd>{getLocale() === "ko" ? "없음" : "None"}</dd></div>
          <div><dt>{getLocale() === "ko" ? "출처 증적" : "Provenance"}</dt><dd>{getLocale() === "ko" ? "리비전 및 다이제스트 보존" : "Revision and digest retained"}</dd></div>
        </dl>
      </section>
    </div>
  );
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
      glossary: composeGlossary([TERMS.humanRbac]),
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
    <div class="stack knowledge-route cs-workspace-route">
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
        <ol class="cs-step-list" aria-label={getLocale() === "ko" ? "커넥터 준비 단계" : "Connector readiness"}>
          <li>
            <span class="cs-step-number">1</span>
            <div>
              <strong>{getLocale() === "ko" ? "통합 설정 구성" : "Configure integration"}</strong>
              <small>{getLocale() === "ko" ? "공급자 ID와 비밀 보관이 아직 기록되지 않았습니다." : "Provider identity and secret custody are not recorded."}</small>
            </div>
          </li>
          <li>
            <span class="cs-step-number">2</span>
            <div>
              <strong>{getLocale() === "ko" ? "허용 범위 승인" : "Authorize scope"}</strong>
              <small>{getLocale() === "ko" ? "리포지토리 및 브랜치 허용 목록이 기록되지 않았습니다." : "Repository and ref allowlists are not recorded."}</small>
            </div>
          </li>
          <li>
            <span class="cs-step-number">3</span>
            <div>
              <strong>{getLocale() === "ko" ? "동기화 관측" : "Observe synchronization"}</strong>
              <small>{getLocale() === "ko" ? "최신성 및 커버리지 근거가 아직 없습니다." : "No freshness or coverage evidence exists."}</small>
            </div>
          </li>
        </ol>
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
