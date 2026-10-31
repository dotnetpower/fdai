import { PageHeader } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary } from "../deck/glossary";
import { t } from "../i18n";

export function LabsRoute() {
  const logoLabHref = `${import.meta.env.BASE_URL}brand/logo-lab.html`;
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
    <div class="stack labs-route">
      <PageHeader title={t("route.labs")} subtitle={t("labs.subtitle")} />
      <section class="labs-tool-list" aria-label={t("labs.toolsLabel")}>
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
