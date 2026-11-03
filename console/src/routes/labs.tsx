import { KpiCard, KpiGrid, PageHeader } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary } from "../deck/glossary";
import { getLocale, t } from "../i18n";
import { routeHref } from "../router";

export function LabsRoute() {
  const logoLabHref = `${import.meta.env.BASE_URL}brand/logo-lab.html`;
  const toolsHref = `${routeHref("labs")}#labs-tools`;
  const ko = getLocale() === "ko";
  usePublishViewContext(
    () => ({
      routeId: "labs",
      routeLabel: t("route.labs"),
      purpose: t("labs.subtitle"),
      glossary: composeGlossary([]),
      headline: t("labs.logoLab"),
      capturedAt: new Date().toISOString(),
      facts: [{ key: "tool_count", value: 1, group: "labs" }],
      records: {
        tools: [{ id: "logo-lab", label: t("labs.logoLab"), href: logoLabHref }],
      },
    }),
    [logoLabHref],
  );
  return (
    <div class="stack labs-route cs-workspace-route">
      <PageHeader title={t("route.labs")} subtitle={t("labs.subtitle")} />
      <div class="governance-readonly-banner">
        <strong>{t("route.labs")}</strong>
        <span>{t("labs.subtitle")}</span>
      </div>
      <KpiGrid>
        <KpiCard href={toolsHref} label={t("labs.toolsLabel")} value="1" />
        <KpiCard href={toolsHref} label={ko ? "디자인 시스템" : "Design system"} value="Calm Slate" />
        <KpiCard href={toolsHref} label={ko ? "변경 권한" : "Mutation authority"} value="0" />
      </KpiGrid>
      <section id="labs-tools" class="labs-tool-list" aria-label={t("labs.toolsLabel")}>
        <a
          class="card labs-tool"
          href={logoLabHref}
          target="_blank"
          rel="noopener noreferrer"
          aria-label={`${t("labs.logoLab")} - ${t("labs.logoLabDescription")}`}
        >
          <span class="labs-tool-mark" aria-hidden="true">F</span>
          <span>
            <strong>{t("labs.logoLab")}</strong>
            <small>{t("labs.logoLabDescription")}</small>
          </span>
          <span class="labs-tool-open" aria-hidden="true">↗</span>
        </a>
      </section>
    </div>
  );
}
