import { PageHeader } from "../components/ui";
import { t } from "../i18n";

export function LabsRoute() {
  const logoLabHref = `${import.meta.env.BASE_URL}brand/logo-lab.html`;
  return (
    <div class="stack labs-route">
      <PageHeader title={t("route.labs")} subtitle={t("labs.subtitle")} />
      <section class="labs-tool-list" aria-label={t("labs.toolsLabel")}>
        <a class="card labs-tool" href={logoLabHref} target="_blank" rel="noopener noreferrer">
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