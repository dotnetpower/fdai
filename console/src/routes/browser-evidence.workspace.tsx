import {
  EmptyState,
  KpiCard,
  KpiGrid,
  StatusPill,
} from "../components/ui";
import { currentRoute, routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import {
  browserEvidenceAttentionLabel,
  browserEvidenceAttentionTone,
  BrowserEvidenceDetail,
  shortBrowserEvidenceId,
} from "./browser-evidence.detail";
import type {
  BrowserEvidenceData,
  BrowserEvidenceItem,
} from "./browser-evidence.model";
import { t } from "./i18n/browser-evidence";

interface WorkspaceProps {
  readonly data: BrowserEvidenceData;
  readonly selectedId: string | null;
  readonly loadingMore: boolean;
  readonly pageError: string | null;
  readonly onSelect: (artifactId: string) => void;
  readonly onLoadMore: (cursor: string) => Promise<void>;
}

export function BrowserEvidenceWorkspace({
  data,
  selectedId,
  loadingMore,
  pageError,
  onSelect,
  onLoadMore,
}: WorkspaceProps) {
  const selected = data.items.find((item) => item.artifact_id === selectedId)
    ?? data.items[0];
  const page = data.page;
  const nextCursor = page.next_cursor;
  return (
    <div class="browser-evidence-body">
      <BrowserEvidenceMetrics data={data} />
      {page.snapshot_admitted_count === 0 ? (
        <EmptyState
          title={t("browserEvidence.empty.title")}
          body={t("browserEvidence.empty.body", {
            withheld: page.snapshot_withheld_count,
          })}
        />
      ) : page.matching_admitted_count === 0 ? (
        <EmptyState
          title={t("browserEvidence.noMatches.title")}
          body={t("browserEvidence.noMatches.body")}
        />
      ) : (
        <section
          id="browser-evidence-artifacts"
          class="browser-evidence-workbench"
          aria-label={t("browserEvidence.workspaceLabel")}
        >
          <aside class="browser-evidence-rail" aria-label={t("browserEvidence.artifacts")}>
            <header class="browser-evidence-pane-head">
              <div>
                <h2>{t("browserEvidence.artifacts")}</h2>
                <p>{t("browserEvidence.loadedSummary", {
                  loaded: data.items.length,
                  matching: page.matching_admitted_count,
                })}</p>
              </div>
              <span class="browser-evidence-count">{data.items.length}</span>
            </header>
            <BrowserEvidenceRecords
              items={data.items}
              selectedId={selected?.artifact_id ?? null}
              onSelect={onSelect}
            />
            <div class="browser-evidence-page-actions">
              {pageError ? <p role="alert">{pageError}</p> : null}
              {nextCursor ? (
                <button
                  type="button"
                  class="btn"
                  disabled={loadingMore}
                  onClick={() => void onLoadMore(nextCursor)}
                >
                  {t(loadingMore
                    ? "browserEvidence.loadingMore"
                    : "browserEvidence.loadMore")}
                </button>
              ) : (
                <span>{t("browserEvidence.pageComplete")}</span>
              )}
            </div>
          </aside>
          <div id="browser-evidence-selected" class="browser-evidence-detail">
            {selected ? <BrowserEvidenceDetail item={selected} /> : null}
          </div>
        </section>
      )}
      <WithheldSummary data={data} />
    </div>
  );
}

function BrowserEvidenceRecords({
  items,
  selectedId,
  onSelect,
}: {
  readonly items: readonly BrowserEvidenceItem[];
  readonly selectedId: string | null;
  readonly onSelect: (artifactId: string) => void;
}) {
  return (
    <ul class="browser-evidence-records">
      {items.map((item) => (
        <li key={item.artifact_id}>
          <button
            type="button"
            class="browser-evidence-record"
            aria-pressed={item.artifact_id === selectedId}
            aria-controls="browser-evidence-selected"
            onClick={() => onSelect(item.artifact_id)}
          >
            <span class="browser-evidence-record-copy">
              <strong>{item.source_host}</strong>
              <span class="mono">{shortBrowserEvidenceId(item.artifact_id)}</span>
              <small>
                {item.policy_id}@{item.policy_version}
                {" / "}
                {formatConsoleTimestamp(item.captured_at)}
              </small>
            </span>
            <StatusPill
              kind={browserEvidenceAttentionTone(item)}
              label={browserEvidenceAttentionLabel(item)}
            />
          </button>
        </li>
      ))}
    </ul>
  );
}

function BrowserEvidenceMetrics({ data }: { readonly data: BrowserEvidenceData }) {
  const page = data.page;
  return (
    <KpiGrid>
      <KpiCard
        href={page.matching_admitted_count > 0
          ? "#browser-evidence-artifacts"
          : "#browser-evidence-withheld"}
        label={t("browserEvidence.metrics.loaded")}
        value={`${data.items.length}/${page.matching_admitted_count}`}
        hint={t("browserEvidence.metrics.loadedHint")}
      />
      <KpiCard
        href={filteredHref({ finding: "present" })}
        label={t("browserEvidence.metrics.findings")}
        value={page.summary.security_finding_count}
        hint={t("browserEvidence.metrics.findingsHint")}
        tone={page.summary.security_finding_count > 0 ? "danger" : "positive"}
      />
      <KpiCard
        href={filteredHref({ retention: "expiring" })}
        label={t("browserEvidence.metrics.expiring")}
        value={page.summary.expiring_count}
        hint={t("browserEvidence.metrics.expiringHint")}
        tone={page.summary.expiring_count > 0 ? "warning" : "positive"}
      />
      <KpiCard
        href={filteredHref({ retention: "held" })}
        label={t("browserEvidence.metrics.holds")}
        value={page.summary.legal_hold_count}
        hint={t("browserEvidence.metrics.holdsHint")}
      />
      <KpiCard
        href="#browser-evidence-withheld"
        label={t("browserEvidence.metrics.withheld")}
        value={page.snapshot_withheld_count}
        hint={t("browserEvidence.metrics.withheldHint")}
        tone={page.snapshot_withheld_count > 0 ? "warning" : "positive"}
      />
    </KpiGrid>
  );
}

function WithheldSummary({ data }: { readonly data: BrowserEvidenceData }) {
  const page = data.page;
  return (
    <section id="browser-evidence-withheld" class="browser-evidence-withheld">
      <header>
        <div>
          <h2>{t("browserEvidence.withheld.title")}</h2>
          <p>{t("browserEvidence.withheld.body")}</p>
        </div>
        <StatusPill
          kind={page.snapshot_withheld_count > 0 ? "warning" : "success"}
          label={t("browserEvidence.withheld.count", {
            count: page.snapshot_withheld_count,
          })}
        />
      </header>
      <dl>
        {(["invalid_metadata", "trust_invalid", "isolation_unverified"] as const)
          .map((reason) => (
            <div key={reason}>
              <dt>{t(`browserEvidence.withheld.reason.${reason}`)}</dt>
              <dd>{page.withheld_reasons[reason]}</dd>
            </div>
          ))}
      </dl>
      <small>{t("browserEvidence.withheld.scope")}</small>
    </section>
  );
}

function filteredHref(overrides: Readonly<Record<string, string>>): string {
  const params = Object.fromEntries(currentRoute().search);
  delete params["artifact"];
  delete params["cursor"];
  return routeHref("browser-evidence", { params: { ...params, ...overrides } });
}
