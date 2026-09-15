import {
  CopyButton,
  StatusPill,
  type PillKind,
} from "../components/ui";
import { currentRoute, routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { t } from "./i18n/browser-evidence";
import type { BrowserEvidenceItem } from "./browser-evidence.model";

export function BrowserEvidenceDetail({ item }: { readonly item: BrowserEvidenceItem }) {
  const deepLink = routeHref("browser-evidence", {
    params: { artifact: item.artifact_id, locale: currentRoute().search.get("locale") },
  });
  return (
    <article>
      <header class="browser-evidence-detail-head">
        <div>
          <span>{t("browserEvidence.detail.selected")}</span>
          <h2>{item.source_host}</h2>
          <p class="mono">{item.policy_id}@{item.policy_version}</p>
        </div>
        <StatusPill
          kind={browserEvidenceAttentionTone(item)}
          label={browserEvidenceAttentionLabel(item)}
        />
      </header>
      {item.prompt_injection_finding_count > 0 ? (
        <aside class="browser-evidence-security" role="alert">
          <strong>{t("browserEvidence.detail.securityReview")}</strong>
          <span>{t("browserEvidence.detail.securityReviewBody", {
            count: item.prompt_injection_finding_count,
          })}</span>
        </aside>
      ) : null}
      <dl class="browser-evidence-facts">
        <div>
          <dt>{t("browserEvidence.column.captured")}</dt>
          <dd>{formatConsoleTimestamp(item.captured_at)}</dd>
        </div>
        <div>
          <dt>{t("browserEvidence.column.expires")}</dt>
          <dd>{formatConsoleTimestamp(item.expires_at)}</dd>
        </div>
        <div>
          <dt>{t("browserEvidence.column.policy")}</dt>
          <dd class="mono">{item.policy_id}@{item.policy_version}</dd>
        </div>
        <div>
          <dt>{t("browserEvidence.column.retention")}</dt>
          <dd>{t(`browserEvidence.retention.${item.retention_state}`)}</dd>
        </div>
      </dl>
      <div class="browser-evidence-detail-grid">
        <section>
          <h3>{t("browserEvidence.detail.source")}</h3>
          <dl class="browser-evidence-detail-list">
            <div>
              <dt>{t("browserEvidence.detail.requestedHost")}</dt>
              <dd class="mono">{item.source_host}</dd>
            </div>
            <div>
              <dt>{t("browserEvidence.detail.finalHost")}</dt>
              <dd class="mono">{item.final_host}</dd>
            </div>
            <div>
              <dt>{t("browserEvidence.detail.redirect")}</dt>
              <dd>{t(item.redirected
                ? "browserEvidence.detail.redirected"
                : "browserEvidence.detail.notRedirected")}</dd>
            </div>
          </dl>
        </section>
        <section>
          <h3>{t("browserEvidence.detail.sanitization")}</h3>
          <dl class="browser-evidence-detail-list">
            <div>
              <dt>{t("browserEvidence.detail.selectors")}</dt>
              <dd>{item.selector_count}</dd>
            </div>
            <div>
              <dt>{t("browserEvidence.detail.redactions")}</dt>
              <dd>{item.redaction_count}</dd>
            </div>
            <div>
              <dt>{t("browserEvidence.detail.findings")}</dt>
              <dd>{item.prompt_injection_finding_count}</dd>
            </div>
          </dl>
        </section>
        <section>
          <h3>{t("browserEvidence.detail.digestCoverage")}</h3>
          <ul class="browser-evidence-digests">
            {([
              ["screenshot", item.digest_presence.screenshot],
              ["text", item.digest_presence.text],
              ["accessibilitySnapshot", item.digest_presence.accessibility_snapshot],
            ] as const).map(([key, present]) => (
              <li key={key}>
                <span>{t(`browserEvidence.detail.digest.${key}`)}</span>
                <StatusPill
                  kind={present ? "success" : "neutral"}
                  label={t(present
                    ? "browserEvidence.detail.digest.present"
                    : "browserEvidence.detail.digest.absent")}
                />
              </li>
            ))}
          </ul>
        </section>
        <section>
          <h3>{t("browserEvidence.detail.custody")}</h3>
          <dl class="browser-evidence-detail-list">
            <div>
              <dt>{t("browserEvidence.detail.browserRuntime")}</dt>
              <dd class="mono">{item.browser_version}</dd>
            </div>
            <div>
              <dt>{t("browserEvidence.detail.custodyReference")}</dt>
              <dd class="mono">{item.custody_audit_ref}</dd>
            </div>
            <div>
              <dt>{t("browserEvidence.detail.auditLink")}</dt>
              <dd><AuditNavigation item={item} /></dd>
            </div>
          </dl>
        </section>
        <section>
          <h3>{t("browserEvidence.detail.retention")}</h3>
          <dl class="browser-evidence-detail-list">
            <div>
              <dt>{t("browserEvidence.column.retention")}</dt>
              <dd>{t(`browserEvidence.retention.${item.retention_state}`)}</dd>
            </div>
            <div>
              <dt>{t("browserEvidence.detail.holdReference")}</dt>
              <dd class="mono">{item.legal_hold_ref ?? t("browserEvidence.detail.notApplicable")}</dd>
            </div>
            <div>
              <dt>{t("browserEvidence.detail.holdApplied")}</dt>
              <dd>{item.legal_hold_at
                ? formatConsoleTimestamp(item.legal_hold_at)
                : t("browserEvidence.detail.notApplicable")}</dd>
            </div>
          </dl>
        </section>
        <section>
          <h3>{t("browserEvidence.detail.identity")}</h3>
          <div class="browser-evidence-identity">
            <code>{item.artifact_id}</code>
            <div>
              <CopyButton
                text={item.artifact_id}
                label={t("browserEvidence.detail.copyIdentity")}
              />
              <a class="btn" href={deepLink}>
                {t("browserEvidence.detail.openDeepLink")}
              </a>
            </div>
          </div>
        </section>
      </div>
      <footer class="browser-evidence-payload-boundary">
        <strong>{t("browserEvidence.detail.payloadHidden")}</strong>
        <span>{t("browserEvidence.detail.payloadHiddenBody")}</span>
      </footer>
    </article>
  );
}

function AuditNavigation({ item }: { readonly item: BrowserEvidenceItem }) {
  if (item.audit.state !== "exact" || item.audit.sequence === null) {
    return <span>{t(`browserEvidence.audit.${item.audit.state}`)}</span>;
  }
  return (
    <span class="browser-evidence-links">
      <a href={routeHref("audit", { params: { entry: item.audit.sequence } })}>
        {t("browserEvidence.detail.openAudit")}
      </a>
      {item.audit.correlation_id ? (
        <a href={routeHref("trace", {
          params: { correlation: item.audit.correlation_id },
        })}>
          {t("browserEvidence.detail.openTrace")}
        </a>
      ) : null}
    </span>
  );
}

export function browserEvidenceAttentionTone(item: BrowserEvidenceItem): PillKind {
  if (
    item.prompt_injection_finding_count > 0
    || item.retention_state === "expired_pending_purge"
  ) return "danger";
  if (item.retention_state === "expiring") return "warning";
  if (item.retention_state === "held") return "info";
  return "success";
}

export function browserEvidenceAttentionLabel(item: BrowserEvidenceItem): string {
  if (item.prompt_injection_finding_count > 0) {
    return t("browserEvidence.attention.security");
  }
  return t(`browserEvidence.retention.${item.retention_state}`);
}

export function shortBrowserEvidenceId(value: string): string {
  return `${value.slice(0, 15)}...${value.slice(-8)}`;
}
