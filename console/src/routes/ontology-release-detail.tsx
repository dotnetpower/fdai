import { useEffect, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable } from "../api";
import type { OperatorApiClient } from "../api";
import { AsyncBoundary, PageHeader, type AsyncState } from "../components/ui";
import { currentRoute } from "../router";
import { t } from "./i18n/ontology";
import {
  decodeOntologyReleaseDiff,
  type OntologyReleaseChange,
  type OntologyReleaseDiffResponse,
} from "./ontology.types";

export function ontologyReleaseHref(digest: string, base?: string): string {
  const path = `/ontology/releases/${encodeURIComponent(digest)}`;
  return base ? `${path}?base=${encodeURIComponent(base)}` : path;
}

export function OntologyReleaseDetailRoute({
  client,
  digest,
}: {
  readonly client: OperatorApiClient;
  readonly digest: string;
}) {
  const [state, setState] = useState<AsyncState<OntologyReleaseDiffResponse>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    (async () => {
      const base = currentRoute().search.get("base");
      const suffix = base ? `?base=${encodeURIComponent(base)}` : "";
      try {
        const payload = await client.panel<unknown>(
          `/ontology/releases/${encodeURIComponent(digest)}/diff${suffix}`,
        );
        const decoded = decodeOntologyReleaseDiff(payload, digest);
        if (!cancelled) setState({ status: "ready", data: decoded });
      } catch (error) {
        if (cancelled) return;
        if (isOptionalOperatorApiUnavailable(error)) {
          setState({ status: "unavailable", message: t("ontology.release.noComparison") });
        } else {
          setState({
            status: "error",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client, digest]);
  return (
    <div class="stack governance-route ontology-route ontology-release-route">
      <PageHeader
        title={t("ontology.release.title")}
        subtitle={<code>{digest}</code>}
        actions={<a class="button button-secondary" href="/ontology">{t("ontology.detail.back")}</a>}
      />
      <AsyncBoundary state={state} resourceLabel={t("ontology.release.loadingLabel")}>
        {(diff) => <OntologyReleaseDiffView diff={diff} />}
      </AsyncBoundary>
    </div>
  );
}

function OntologyReleaseDiffView({ diff }: { readonly diff: OntologyReleaseDiffResponse }) {
  return (
    <article class="ontology-detail-workbench">
      <section class="ontology-detail-identity">
        <div>
          <span class="eyebrow">{t("ontology.release.compatibility")}</span>
          <h3>{diff.compatibility_verdict}</h3>
          <p>{t("ontology.detail.declarationRefsOnly")}</p>
        </div>
        <dl class="ontology-detail-summary">
          <div><dt>{t("ontology.detail.added")}</dt><dd>{diff.added.length}</dd></div>
          <div><dt>{t("ontology.detail.changed")}</dt><dd>{diff.changed.length}</dd></div>
          <div><dt>{t("ontology.detail.removed")}</dt><dd>{diff.removed.length}</dd></div>
          <div><dt>{t("ontology.release.migrationRequired")}</dt><dd>{t(diff.migration_required ? "ontology.common.yes" : "ontology.common.no")}</dd></div>
        </dl>
      </section>
      <ReleaseChanges title={t("ontology.detail.added")} rows={diff.added} />
      <ReleaseChanges title={t("ontology.detail.changed")} rows={diff.changed} />
      <ReleaseChanges title={t("ontology.detail.removed")} rows={diff.removed} />
      <details class="governance-source-details ontology-technical-details">
        <summary class="details-summary">{t("ontology.detail.technicalDetails")}</summary>
        <dl>
          <div><dt>{t("ontology.release.base")}</dt><dd><code>{diff.base_release_digest}</code></dd></div>
          <div><dt>{t("ontology.release.candidate")}</dt><dd><code>{diff.candidate_release_digest}</code></dd></div>
          <div><dt>{t("ontology.release.diffDigest")}</dt><dd><code>{diff.diff_digest}</code></dd></div>
        </dl>
      </details>
    </article>
  );
}

function ReleaseChanges({ title, rows }: { readonly title: string; readonly rows: readonly OntologyReleaseChange[] }) {
  return (
    <section class="ontology-detail-section">
      <h3>{title}</h3>
      {rows.length === 0 ? <p class="muted">{t("ontology.common.noneDeclared")}</p> : (
        <div class="ontology-detail-table-wrap">
          <table class="ontology-detail-table">
            <thead><tr><th>{t("ontology.detail.dependent")}</th><th>{t("ontology.release.before")}</th><th>{t("ontology.release.after")}</th></tr></thead>
            <tbody>{rows.map((row) => (
              <tr key={`${row.kind}:${row.name}`}>
                <td data-label={t("ontology.detail.dependent")}><code>{row.kind}:{row.name}</code></td>
                <td data-label={t("ontology.release.before")}>{row.version_before ?? "-"}</td>
                <td data-label={t("ontology.release.after")}>{row.version_after ?? "-"}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </section>
  );
}
