import { useState } from "preact/hooks";
import type { AuditItem } from "../types";
import { StatusPill } from "../components/ui";
import { currentRoute, routeHref } from "../router";
import { formatConsoleCompactTimestamp, formatConsoleTimestamp } from "../time-format";
import { usePublishViewContext } from "../deck/context";
import { TERMS, agentTerm, composeGlossary } from "../deck/glossary";
import {
  auditContextRecord, auditEntryText, auditRecordedPhase, searchAuditItems,
  type AuditData, type AuditEntrySelection,
} from "./audit.model";
import { presentationLabel, t } from "./i18n/evidence";
import { AuditQueryControls } from "./audit.filters";

const w = (key: string) => t(`evidence.audit.workspace.${key}`);
const valueOrMissing = (value: string | null) => value ?? w("notRecorded");

function Mode({ mode }: { readonly mode: string }) {
  return <StatusPill kind={mode === "shadow" || mode === "enforce" ? mode : "neutral"}
    label={presentationLabel("status", mode)} />;
}

/** Show immutable record evidence without synthesizing ledger totals or verified effects. */
export function AuditWorkspace({ data, selection }: {
  readonly data: AuditData;
  readonly selection: AuditEntrySelection;
}) {
  const [chosen, setChosen] = useState<number | null>(null);
  const items = searchAuditItems(data.items, currentRoute().search.get("q") ?? "");
  const selected = selection.status === "selected"
    ? items.find((item) => item.seq === selection.seq)
    : selection.status === "none"
      ? items.find((item) => item.seq === chosen) ?? items[0]
      : undefined;
  const phase = selected ? auditRecordedPhase(selected) : null;
  const correlation = selected?.correlation_id ?? currentRoute().search.get("correlation");
  usePublishViewContext(
    () => ({
      routeId: "audit", routeLabel: t("route.audit"), purpose: t("evidence.audit.viewPurpose"),
      glossary: composeGlossary([
        TERMS.correlationId, TERMS.actionKind, TERMS.mode, TERMS.tier, TERMS.outcome, agentTerm(),
      ]),
      headline: t(data.nextCursor === null ? "evidence.audit.headlineEnd" : "evidence.audit.headlineMore",
        { count: data.items.length }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "loaded_rows", value: data.items.length, group: "page" },
        { key: "more_available", value: data.nextCursor !== null, group: "page" },
        { key: "selected_seq", value: selected?.seq ?? null, group: "page" },
      ],
      records: {
        items: data.items.map(auditContextRecord),
        selected_record: selected ? [auditContextRecord(selected)] : [],
      },
    }),
    [data.items, data.nextCursor, selected],
  );

  return (
    <>
      <section class="audit-context" aria-label={w("context")}>
        <dl>
          <div><dt>{w("target")}</dt><dd>{valueOrMissing(selected ? auditEntryText(selected.entry, "resource_id") : null)}</dd></div>
          <div><dt>{w("correlation")}</dt><dd class="mono">{valueOrMissing(correlation)}</dd></div>
          <div><dt>{w("receipt")}</dt><dd>{phase === "dispatch" ? w("dispatchRecord") : w("notInRecord")}</dd></div>
          <div><dt>{w("observation")}</dt><dd>{phase === "observe" ? w("observationRecord") : w("notInRecord")}</dd></div>
        </dl>
        <nav aria-label={t("evidence.audit.column.evidence")}>
          {correlation ? <a href={routeHref("trace", { params: { correlation } })}>{t("evidence.audit.trace")}</a> : null}
        </nav>
      </section>
      <section class="audit-metrics" aria-label={w("metrics")}>
        {["closed", "humanReview", "rollbacks", "integrity"].map((key) => (
          <a key={key} href="#audit-record-review">
            <span>{w(`metric.${key}`)}</span>
            <strong>{w("metricUnavailableValue")}</strong>
            <small>{w("metricUnavailable")}</small>
          </a>
        ))}
      </section>
      <AuditQueryControls search={currentRoute().search.toString()} />
      <section class="audit-workspace" id="audit-record-review" aria-label={w("review")}>
        <aside class="audit-record-rail" aria-labelledby="audit-records-title">
          <header>
            <div><h3 id="audit-records-title">{w("records")}</h3><p>{w("newest")}</p></div>
            <span>{items.length} / {data.items.length}</span>
          </header>
          {items.length ? (
            <ul class="audit-record-list">
              {items.map((item) => (
                <li key={item.seq}>
                  <button type="button" class="audit-record" aria-pressed={selected?.seq === item.seq}
                    aria-controls="audit-selected-record" onClick={() => setChosen(item.seq)}>
                    <strong>{item.action_kind}</strong>
                    <span class="audit-record-meta">
                      <span class="mono">#{item.seq}</span>
                      <Mode mode={item.mode} />
                    </span>
                    <time dateTime={item.recorded_at}>{formatConsoleCompactTimestamp(item.recorded_at)}</time>
                    <span class="audit-record-actor">{item.actor}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : <p class="audit-empty" role="status">{t(data.items.length ? "evidence.audit.workspace.noMatches" : "evidence.audit.empty")}</p>}
        </aside>
        <div id="audit-selected-record" class="audit-record-detail">
          {selected ? <AuditRecordDetail key={selected.seq} item={selected} /> : (
            <p class="audit-empty">{w("select")}</p>
          )}
        </div>
      </section>
    </>
  );
}

function AuditRecordDetail({ item }: { readonly item: AuditItem }) {
  const phase = auditRecordedPhase(item);
  const text = (key: string) => auditEntryText(item.entry, key);
  const correlation = item.correlation_id;
  const entryHref = routeHref("audit", {
    params: { ...Object.fromEntries(currentRoute().search), entry: item.seq },
  });
  return (
    <article aria-labelledby="audit-selected-title">
      <header class="audit-detail-head">
        <div>
          <span class="audit-kicker">{w("selected")} / #{item.seq}</span>
          <h3 id="audit-selected-title">{item.action_kind}</h3>
          <p>{text("summary") ?? text("reason") ?? w("recordDescription")}</p>
        </div>
        <Mode mode={item.mode} />
      </header>
      <dl class="audit-facts">
        <div><dt>{w("correlation")}</dt><dd class="mono">{valueOrMissing(correlation)}</dd></div>
        <div><dt>{w("idempotency")}</dt><dd class="mono">{valueOrMissing(text("idempotency_key"))}</dd></div>
        <div><dt>{t("evidence.audit.column.actor")}</dt><dd>{item.actor}</dd></div>
        <div><dt>{w("rollback")}</dt><dd>{valueOrMissing(text("rollback_reference"))}</dd></div>
      </dl>
      <div class="audit-detail-grid">
        <section class="audit-evidence" aria-labelledby="audit-path-title">
          <h4 id="audit-path-title">{w("path")}</h4>
          <ol class="audit-phases">
            {(["intent", "dispatch", "observe", "close"] as const).map((key, index) => (
              <li key={key} data-recorded={phase === key}>
                <span>{index + 1} / {w(`phase.${key}`)}</span>
                <strong>{phase === key ? w("stageRecorded") : w("notInRecord")}</strong>
                <small>{w(`phase.${key}Hint`)}</small>
              </li>
            ))}
          </ol>
          <p class="audit-note">{w("effectNote")}</p>
          <dl class="audit-decision-facts">
            {(["tier", "decision", "stage", "outcome"] as const).map((key) => {
              const value = text(key);
              return <div key={key}><dt>{w(`${key}Label`)}</dt><dd>{
                value ? presentationLabel(key === "stage" ? "traceStage" : "status", value) : w("notRecorded")
              }</dd></div>;
            })}
          </dl>
          <details class="audit-json-disclosure" open>
            <summary>{w("recordShape")}</summary>
            <pre class="audit-json" tabIndex={0} aria-label={t("evidence.audit.viewJson")}>{JSON.stringify(item.entry, null, 2)}</pre>
          </details>
        </section>
        <aside class="audit-ledger" aria-labelledby="audit-guarantees-title">
          <h4 id="audit-guarantees-title">{w("guarantees")}</h4>
          <ul>
            {["ordering", "replay", "redaction", "retention"].map((key) => (
              <li key={key}>
                <div><strong>{w(`guarantee.${key}`)}</strong><small>{w(`guarantee.${key}Hint`)}</small></div>
                <span>{w("notVerified")}</span>
              </li>
            ))}
          </ul>
          <details class="audit-provenance">
            <summary>{w("provenance")}</summary>
            <dl>
              <div><dt>{t("evidence.audit.column.recordedAt")}</dt><dd><time dateTime={item.recorded_at}>{formatConsoleTimestamp(item.recorded_at)}</time></dd></div>
              <div><dt>{t("evidence.audit.column.eventId")}</dt><dd class="mono">{item.event_id}</dd></div>
              <div><dt>{w("entryHash")}</dt><dd class="mono">{item.entry_hash}</dd></div>
              <div><dt>{w("previousHash")}</dt><dd class="mono">{valueOrMissing(item.previous_hash)}</dd></div>
            </dl>
            <p class="audit-note">{w("integrityNote")}</p>
          </details>
          <nav class="audit-evidence-links" aria-label={t("evidence.audit.column.evidence")}>
            <a href={entryHref}>{w("permalink")}</a>
            {correlation ? <>
              <a href={routeHref("trace", { params: { correlation } })}>{t("evidence.audit.trace")}</a>
              <a href={routeHref("rca", { params: { correlation } })}>{t("evidence.audit.rca")}</a>
              <a href={routeHref("incidents", { params: { status: "all", correlation } })}>{t("evidence.audit.incident")}</a>
            </> : null}
          </nav>
        </aside>
      </div>
    </article>
  );
}
