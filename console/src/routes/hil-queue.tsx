import { useEffect, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import {
  decideHilApproval,
  type HilDecisionReceipt,
} from "../api-hil-decision";
import { architectureHref } from "../components/architecture-map.model";
import type { HilQueueItem } from "../types";
import type { ReportLineContactRequest } from "./report-lines.model";
import {
  AsyncBoundary,
  CopyButton,
  EmptyState,
  PageHeader,
  StatusPill,
  type AsyncState,
  type PillKind,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { currentRoute, replaceRouteState, routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { t } from "./i18n/approvals";
import { decisionFailureMessage } from "./hil-decision-error";
import type { ConsoleDataMode } from "../console-data-mode";
import { SlackApprovalHandoff } from "./slack-approval-handoff";
import {
  clearDevelopmentReauthentication,
  hasDevelopmentReauthentication,
  markDevelopmentReauthentication,
} from "./development-approval";
import {
  identityForMutationIntent,
  type MutationIntentIdentity,
} from "../mutation-intent";

interface Props {
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
  readonly dataMode: ConsoleDataMode;
}

export async function loadHilQueueState(
  client: Pick<OperatorApiClient, "listHilQueue">,
  query: string,
): Promise<AsyncState<HilQueueData>> {
  try {
    const page = await client.listHilQueue({
      limit: 100,
      ...(query ? { query } : {}),
    });
    return {
      status: "ready",
      data: { items: page.items, total: page.total, detailLevel: page.detail_level },
    };
  } catch (error) {
    return isOptionalOperatorApiUnavailable(error)
      ? { status: "unavailable", message: t("nav.source.unavailable") }
      : { status: "error", message: error instanceof Error ? error.message : String(error) };
  }
}

export function HilQueueRoute({ client, auth, dataMode }: Props) {
  const [query, setQuery] = useState(() => currentRoute().search.get("q") ?? "");
  const [serverQuery, setServerQuery] = useState(query.trim());
  const [state, setState] = useState<AsyncState<HilQueueData>>({
    status: "loading",
  });
  const [refreshRevision, setRefreshRevision] = useState(0);
  const [decisionReceipt, setDecisionReceipt] = useState<HilDecisionReceipt | null>(null);
  const [contactState, setContactState] = useState<AsyncState<readonly ReportLineContactRequest[]>>({
    status: "loading",
  });
  const [contactMessage, setContactMessage] = useState<string | null>(null);

  useEffect(() => {
    const sync = () => setQuery(currentRoute().search.get("q") ?? "");
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => setServerQuery(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    let cancelled = false;
    void loadHilQueueState(client, serverQuery).then((nextState) => {
      if (!cancelled) setState(nextState);
    });
    return () => {
      cancelled = true;
    };
  }, [client, serverQuery, refreshRevision]);

  useEffect(() => {
    if (dataMode !== "live") {
      setContactState({ status: "ready", data: [] });
      return undefined;
    }
    let cancelled = false;
    void client.reportLineContactRequests().then(
      (items) => {
        if (!cancelled) setContactState({ status: "ready", data: items });
      },
      (error: unknown) => {
        if (!cancelled) {
          setContactState(
            isOptionalOperatorApiUnavailable(error)
              ? { status: "unavailable", message: t("nav.source.unavailable") }
              : {
                status: "error",
                message: error instanceof Error ? error.message : String(error),
              },
          );
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [client, dataMode, refreshRevision]);

  return (
    <div class="stack approvals-route">
      <PageHeader
        title={t("route.hilQueue")}
        subtitle={<>{t("approvals.subtitle")}</>}
        actions={
          <div class="approvals-header-actions">
            <StatusPill kind="neutral" label={t("approvals.requestOnly")} />
            <button
              type="button"
              class="btn secondary btn-sm"
              disabled={state.status === "loading"}
              onClick={() => setRefreshRevision((revision) => revision + 1)}
            >
              {t("approvals.refresh")}
            </button>
          </div>
        }
      />
      <SlackApprovalHandoff client={client} auth={auth} dataMode={dataMode} />
      {contactMessage !== null ? (
        <div class="state-block state-success" role="status">{contactMessage}</div>
      ) : null}
      <AsyncBoundary state={contactState} resourceLabel={t("approvals.contactTitle")}>
        {(items) => (
          <ReportLineContactRequests
            items={items}
            client={client}
            onRecorded={() => {
              setContactMessage(t("approvals.contactQueued"));
              setRefreshRevision((revision) => revision + 1);
            }}
          />
        )}
      </AsyncBoundary>
      <AsyncBoundary state={state} resourceLabel={t("approvals.resource")}>
        {(data) => (
          <HilBody
            data={data}
            query={query}
            dataMode={dataMode}
            client={client}
            auth={auth}
            decisionReceipt={decisionReceipt}
            onQueryChange={setQuery}
            onDecisionRecorded={(receipt) => {
              setDecisionReceipt(receipt);
              setRefreshRevision((revision) => revision + 1);
            }}
          />
        )}
      </AsyncBoundary>
    </div>
  );
}

function ReportLineContactRequests({
  items,
  client,
  onRecorded,
}: {
  readonly items: readonly ReportLineContactRequest[];
  readonly client: OperatorApiClient;
  readonly onRecorded: () => void;
}) {
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (items.length === 0) return null;

  const decide = async (item: ReportLineContactRequest, consent: boolean) => {
    setPendingId(item.approvalId);
    setError(null);
    try {
      await client.decideReportLineContact(
        item.approvalId,
        consent,
        item.consentRevision,
        `report-line-contact:${item.approvalId}:${item.consentRevision}:${consent}`,
      );
      onRecorded();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setPendingId(null);
    }
  };

  return (
    <section class="settings-iam-panel" aria-labelledby="report-line-contact-title">
      <header class="settings-iam-panel-head">
        <div>
          <h2 id="report-line-contact-title">{t("approvals.contactTitle")}</h2>
          <p>{t("approvals.contactBody")}</p>
        </div>
      </header>
      {error !== null ? <div class="state-block state-error" role="alert">{error}</div> : null}
      <div class="approval-card-list">
        {items.map((item) => (
          <article class="approval-card" key={item.approvalId}>
            <div class="approval-card-body">
              <header class="approval-card-head">
                <div class="approval-card-title-group">
                  <h3>{actionKindTitle(item.actionType)}</h3>
                  {actionKindTitle(item.actionType) !== item.actionType ? (
                    <code class="approval-action-token mono">{item.actionType}</code>
                  ) : null}
                </div>
                <StatusPill kind="hil" label={t("approvals.requestOnly")} />
              </header>
              <div class="approval-proposal-grid">
                <div class="approval-proposal-cell">
                  <span class="approval-proposal-label">{t("approvals.fieldTarget")}</span>
                  <p class="mono">{item.targetRef}</p>
                </div>
                <div class="approval-proposal-cell">
                  <span class="approval-proposal-label">{t("approvals.contactRoute")}</span>
                  <div class="approval-route-chain">
                    {item.routeSubjects.map((subject, index) => (
                      <span key={`${index}:${subject}`} class="approval-route-step">
                        {index > 0 ? <span class="approval-route-arrow" aria-hidden="true">-&gt;</span> : null}
                        <code class="mono">{subject}</code>
                      </span>
                    ))}
                  </div>
                </div>
              </div>
              <p class="muted small">{t("approvals.contactExpires", {
                timestamp: formatConsoleTimestamp(item.expiresAt),
              })}</p>
              <details>
                <summary>{t("approvals.contactTechnicalDetails")}</summary>
                <dl class="approval-facts">
                  <div>
                    <dt>{t("approvals.contactApprovalId")}</dt>
                    <dd class="approval-fact-copy-row">
                      <code>{item.approvalId}</code>
                      <CopyButton text={item.approvalId} />
                    </dd>
                  </div>
                  <div>
                    <dt>{t("approvals.contactConsentId")}</dt>
                    <dd class="approval-fact-copy-row">
                      <code>{item.consentId}</code>
                      <CopyButton text={item.consentId} />
                    </dd>
                  </div>
                </dl>
              </details>
              <div class="approval-decision-actions">
                <button
                  type="button"
                  class="btn btn-primary"
                  disabled={pendingId !== null}
                  onClick={() => void decide(item, true)}
                >
                  {pendingId === item.approvalId
                    ? t("approvals.contactRecording")
                    : t("approvals.sendContact")}
                </button>
                <button
                  type="button"
                  class="btn"
                  disabled={pendingId !== null}
                  onClick={() => void decide(item, false)}
                >
                  {t("approvals.declineContact")}
                </button>
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

interface HilQueueData {
  readonly items: readonly HilQueueItem[];
  readonly total: number;
  readonly detailLevel: "full" | "count_only";
}

function HilBody({
  data,
  query,
  dataMode,
  client,
  auth,
  decisionReceipt,
  onQueryChange,
  onDecisionRecorded,
}: {
  readonly data: HilQueueData;
  readonly query: string;
  readonly dataMode: ConsoleDataMode;
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
  readonly decisionReceipt: HilDecisionReceipt | null;
  readonly onQueryChange: (value: string) => void;
  readonly onDecisionRecorded: (receipt: HilDecisionReceipt) => void;
}) {
  const { items, total, detailLevel } = data;
  const [now, setNow] = useState(Date.now);
  const [statusFilter, setStatusFilter] = useState<"all" | "actionable" | "expired">("all");
  const [sortBy, setSortBy] = useState<"expiry" | "newest" | "impact" | "action">("expiry");
  useEffect(() => {
    const delay = nextApprovalExpiryDelay(items, now);
    if (delay === null) return undefined;
    const timer = window.setTimeout(() => setNow(Date.now()), delay);
    return () => window.clearTimeout(timer);
  }, [items, now]);
  const truncated = total > items.length;
  const updateQuery = (value: string): void => {
    onQueryChange(value);
    replaceRouteState(routeHref("hil-queue", {
      params: {
        q: value || null,
        data: dataMode === "sample" ? "sample" : null,
      },
    }));
  };
  usePublishViewContext(
    () => ({
      routeId: "hil-queue",
      routeLabel: t("route.hilQueue"),
      purpose: t("approvals.subtitle"),
      glossary: composeGlossary([
        TERMS.hil,
        TERMS.actionKind,
        TERMS.gateDecision,
        TERMS.correlationId,
      ]),
      headline: total === 0
        ? t("approvals.headlineEmpty")
        : t("approvals.headlineWaiting", { count: total }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "pending", value: total, group: "queue" },
        { key: "displayed", value: items.length, group: "queue" },
        { key: "truncated", value: truncated, group: "queue" },
        { key: "detail_level", value: detailLevel, group: "access" },
      ],
      records: {
        items: items.map((i) => ({
          approval_id: i.approval_id,
          action_kind: i.action_kind,
          reason: i.reason,
          target_resource_ref: i.target_resource_ref,
          mode: i.mode,
          stop_condition: i.stop_condition,
          rollback_kind: i.rollback_kind,
          blast_radius_scope: i.blast_radius_scope,
          blast_radius_count: i.blast_radius_count,
          citing_rule_ids: i.citing_rule_ids,
          requested_at: i.requested_at,
          ttl_expires_at: i.ttl_expires_at,
          idempotency_key: i.idempotency_key,
          correlation_id: i.correlation_id,
        })),
      },
    }),
    [items, total, truncated, detailLevel],
  );

  if (total === 0) {
    return (
      <EmptyState
        title={t("approvals.emptyTitle")}
        body={t("approvals.emptyBody")}
      />
    );
  }

  if (detailLevel === "count_only") {
    return (
      <section class="approvals-count-only" aria-label={t("approvals.pendingCount", { count: total })}>
        <StatusPill kind="hil" label={t("approvals.pendingCount", { count: total })} />
        <div>
          <h3>{t("approvals.detailsRoleTitle")}</h3>
          <p>{t("approvals.detailsRoleBody")}</p>
        </div>
      </section>
    );
  }

  const normalizedQuery = query.trim().toLowerCase();
  const expiredCount = items.filter((item) => approvalIsExpired(item, now)).length;
  const actionableCount = items.length - expiredCount;
  const visibleItems = items
    .filter((item) => {
      if (statusFilter === "actionable" && approvalIsExpired(item, now)) return false;
      if (statusFilter === "expired" && !approvalIsExpired(item, now)) return false;
      if (!normalizedQuery) return true;
      return approvalSearchText(item).includes(normalizedQuery);
    })
    .slice()
    .sort((left, right) => compareApprovals(left, right, sortBy));

  return (
    <div class="stack approvals-view">
      {decisionReceipt !== null ? (
        <div class="state-block state-success" role="status">
          {decisionReceipt.delivered
            ? t("approvals.decisionDelivered", { decision: decisionReceipt.decision })
            : t("approvals.decisionPendingDelivery", { decision: decisionReceipt.decision })}
        </div>
      ) : null}
      <section class="approvals-mechanics" aria-label={t("approvals.mechanicsTitle")}>
        <strong>{t("approvals.mechanicsTitle")}</strong>
        <span>{t("approvals.mechanicsBody")}</span>
      </section>
      <div class="approvals-toolbar">
        <div class="approvals-summary" aria-label={t("approvals.resource")}>
          <StatusPill kind="hil" label={t("approvals.pendingCount", { count: total })} />
          <StatusPill kind="neutral" label={t("approvals.shownCount", { count: visibleItems.length })} />
          {expiredCount > 0 ? (
            <StatusPill kind="danger" label={t("approvals.expiredCount", { count: expiredCount })} />
          ) : null}
          <StatusPill
            kind="shadow"
            label={dataMode === "sample"
              ? t("approvals.readOnly")
              : t("approvals.requestOnly")}
          />
        </div>
        <div class="approvals-controls">
          {items.length > 1 ? (
            <>
              <div class="governance-chipset" role="group" aria-label={t("approvals.resource")}>
                <button
                  type="button"
                  class={statusFilter === "all" ? "is-active" : undefined}
                  onClick={() => setStatusFilter("all")}
                >
                  {t("approvals.filterAll")} ({items.length})
                </button>
                <button
                  type="button"
                  class={statusFilter === "actionable" ? "is-active" : undefined}
                  onClick={() => setStatusFilter("actionable")}
                >
                  {t("approvals.filterActionable")} ({actionableCount})
                </button>
                {expiredCount > 0 ? (
                  <button
                    type="button"
                    class={statusFilter === "expired" ? "is-active" : undefined}
                    onClick={() => setStatusFilter("expired")}
                  >
                    {t("approvals.filterExpired")} ({expiredCount})
                  </button>
                ) : null}
              </div>
              <label class="approvals-sort">
                <span class="sr-only">{t("approvals.sortLabel")}</span>
                <select
                  class="form-input"
                  aria-label={t("approvals.sortLabel")}
                  value={sortBy}
                  onChange={(event) => setSortBy(
                    event.currentTarget.value as "expiry" | "newest" | "impact" | "action",
                  )}
                >
                  <option value="expiry">{t("approvals.sortExpiry")}</option>
                  <option value="newest">{t("approvals.sortNewest")}</option>
                  <option value="impact">{t("approvals.sortImpact")}</option>
                  <option value="action">{t("approvals.sortAction")}</option>
                </select>
              </label>
            </>
          ) : null}
          <label class="approvals-search">
            <span class="sr-only">{t("approvals.filter")}</span>
            <input
              type="search"
              value={query}
              placeholder={t("approvals.filterPlaceholder")}
              onInput={(event) => updateQuery(event.currentTarget.value)}
            />
          </label>
          {query || statusFilter !== "all" ? (
            <button
              type="button"
              class="btn secondary btn-sm"
              onClick={() => {
                setStatusFilter("all");
                updateQuery("");
              }}
            >
              {t("approvals.clearFilter")}
            </button>
          ) : null}
        </div>
      </div>
      {truncated ? (
        <p class="muted footnote">
          {t("approvals.showingLatest", { shown: items.length, total })}
        </p>
      ) : null}
      {visibleItems.length === 0 ? (
        <EmptyState
          title={t("approvals.noMatchTitle")}
          body={t("approvals.noMatchBody")}
        />
      ) : (
        <div class="approval-card-list">
          {visibleItems.map((item) => (
            <ApprovalCard
              key={item.idempotency_key}
              item={item}
              now={now}
              dataMode={dataMode}
              client={client}
              auth={auth}
              decisionRecorded={decisionReceipt?.approval_id === item.approval_id}
              onDecisionRecorded={onDecisionRecorded}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function nextApprovalExpiryDelay(
  items: readonly HilQueueItem[],
  now: number,
): number | null {
  const next = items
    .map((item) => item.ttl_expires_at === null ? Number.NaN : Date.parse(item.ttl_expires_at))
    .filter((expiresAt) => Number.isFinite(expiresAt) && expiresAt > now)
    .sort((left, right) => left - right)[0];
  return next === undefined ? null : Math.min(2_147_483_647, Math.max(1, next - now + 20));
}

export function approvalSearchText(item: HilQueueItem): string {
  return [
    item.action_kind,
    item.target_resource_ref,
    item.event_id,
    item.correlation_id,
    item.reason,
    ...item.reasons,
    ...item.citing_rule_ids,
  ].filter(Boolean).join(" ").toLowerCase();
}

function ApprovalCard({
  item,
  now,
  dataMode,
  client,
  auth,
  decisionRecorded,
  onDecisionRecorded,
}: {
  readonly item: HilQueueItem;
  readonly now: number;
  readonly dataMode: ConsoleDataMode;
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
  readonly decisionRecorded: boolean;
  readonly onDecisionRecorded: (receipt: HilDecisionReceipt) => void;
}) {
  const ownDevelopment = item.development_self_approval_available;
  const approvable = approvalCanApprove(item);
  const [reauthenticated, setReauthenticated] = useState(
    () => ownDevelopment && hasDevelopmentReauthentication(item.approval_id),
  );
  const expired = approvalIsExpired(item, now);
  const [justification, setJustification] = useState("");
  const [pendingDecision, setPendingDecision] = useState<"approve" | "reject" | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [intent, setIntent] = useState<MutationIntentIdentity | null>(null);
  const canDecide = !decisionRecorded && approvalCanDecide(item, now, dataMode);
  // The Owner signs in again before approving; rejecting a category-only park grants nothing.
  const awaitingSignIn = ownDevelopment && !reauthenticated;
  const reasons = [...new Set(item.reasons.length > 0 ? item.reasons : [item.reason])];
  const parsedTarget = item.target_resource_ref
    ? shortTargetDisplay(item.target_resource_ref)
    : null;
  const blastScope = item.blast_radius_scope
    ? blastScopeLabel(item.blast_radius_scope)
    : "";
  const blastRadius = item.blast_radius_summary || [
    item.blast_radius_count !== null
      ? t(item.blast_radius_count === 1 ? "approvals.resourceCountOne" : "approvals.resourceCountMany", { count: item.blast_radius_count })
      : "",
    blastScope,
    item.blast_radius_rate_per_minute !== null
      ? t("approvals.rateCap", { count: item.blast_radius_rate_per_minute })
      : "",
  ].filter(Boolean).join(" · ");
  const rollback = [
    item.rollback_kind ? rollbackKindLabel(item.rollback_kind) : "",
    item.rollback_reference,
  ].filter(Boolean).join(" · ");
  const expiryBadge = approvalExpiryBadge(item.ttl_expires_at, now);
  const actionTitle = actionKindTitle(item.action_kind);
  const facts = [
    [t("approvals.fieldApprovalId"), item.approval_id],
    [t("approvals.fieldActionId"), item.action_id],
    [t("approvals.fieldTarget"), item.target_resource_ref],
    [t("approvals.fieldBlastRadius"), blastRadius],
    [t("approvals.fieldRollback"), rollback],
    [t("approvals.fieldStopCondition"), item.stop_condition],
    [t("approvals.fieldGroundedOn"), item.citing_rule_ids.join(", ")],
    ...(ownDevelopment && item.development_binding !== null
      ? [
        [t("approvals.fieldTargetRevision"), item.development_binding.target_revision],
        [t("approvals.fieldDryRunDigest"), item.development_binding.dry_run_digest],
        [t("approvals.fieldScopeDigest"), item.development_binding.scope_digest],
        [t("approvals.fieldBindingDigest"), item.development_binding.binding_digest],
      ] as const
      : []),
  ] as const;
  const submitDecision = async (decision: "approve" | "reject"): Promise<void> => {
    const reason = justification.trim();
    const nextIntent = identityForMutationIntent(
      intent,
      `${item.approval_id}\0${decision}\0${reason}`,
    );
    setIntent(nextIntent);
    setPendingDecision(decision);
    setDecisionError(null);
    try {
      const receipt = await decideHilApproval(
        client.authorizationHeader,
        client.operatorApiBaseUrl,
        item.approval_id,
        decision,
        reason,
        nextIntent.idempotencyKey,
      );
      if (ownDevelopment) clearDevelopmentReauthentication();
      onDecisionRecorded(receipt);
    } catch (error) {
      setDecisionError(decisionFailureMessage(error));
      if (ownDevelopment) {
        // A refused or stale sign-in needs a new one; never leave the Owner on a dead approve.
        clearDevelopmentReauthentication();
        setReauthenticated(false);
      }
    } finally {
      setPendingDecision(null);
    }
  };

  return (
    <article class={`approval-card${expired ? " is-expired" : ""}${decisionRecorded ? " is-decided" : ""}`}>
      <div class="approval-card-body">
        <header class="approval-card-head">
          <div class="approval-card-title-group">
            <h3>
              {actionTitle !== item.action_kind ? `${actionTitle} (${item.action_kind})` : item.action_kind}
            </h3>
            {parsedTarget ? (
              <span class="approval-target-subtitle mono">
                {parsedTarget.shortName}
                {parsedTarget.resourceGroup ? ` · ${parsedTarget.resourceGroup}` : ""}
              </span>
            ) : null}
          </div>
          <div class="approval-card-badges">
            <StatusPill
              kind={expired ? "danger" : "hil"}
              label={expired ? t("approvals.expiredApproval") : t("approvals.pendingApproval")}
            />
            {expiryBadge ? (
              <StatusPill kind={expiryBadge.kind} label={expiryBadge.label} />
            ) : null}
            {item.mode ? (
              <StatusPill
                kind={item.mode === "enforce" ? "enforce" : "shadow"}
                label={item.mode === "enforce"
                  ? t("approvals.modeEnforce")
                  : t("approvals.modeShadow")}
              />
            ) : null}
          </div>
        </header>
        <div class="approval-proposal-grid">
          <div class="approval-proposal-cell">
            <span class="approval-proposal-label">{t("approvals.what")}</span>
            <p class="approval-card-what">
              {item.target_resource_ref
                ? t("approvals.applyTarget", { action: item.action_kind, target: item.target_resource_ref })
                : t("approvals.applyRecorded", { action: item.action_kind })}
            </p>
          </div>
          <div class="approval-proposal-cell">
            <span class="approval-proposal-label">{t("approvals.why")}</span>
            <div class="approval-card-why">
              <ul>{reasons.map((reason, index) => <li key={`${index}:${reason}`}>{reason}</li>)}</ul>
            </div>
          </div>
        </div>
        <div class="approval-safeguards-bar" aria-label={t("approvals.safeguardsTitle")}>
          <span class="approval-safeguards-label">{t("approvals.safeguardsTitle")}</span>
          <div class="approval-safeguards-pills">
            <StatusPill kind={item.stop_condition ? "success" : "neutral"} label={t("approvals.safeguardStop")} />
            <StatusPill kind={rollback ? "success" : "neutral"} label={t("approvals.safeguardRollback")} />
            <StatusPill kind={blastRadius ? "success" : "neutral"} label={t("approvals.safeguardBlast")} />
            <StatusPill kind={item.idempotency_key ? "success" : "neutral"} label={t("approvals.safeguardIdempotency")} />
            <StatusPill kind={item.correlation_id ? "success" : "neutral"} label={t("approvals.safeguardAudit")} />
          </div>
        </div>
        <dl class="approval-facts">
          {facts.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>
                {label === t("approvals.fieldTarget") && item.target_resource_ref ? (
                  dataMode === "live"
                    ? <a class="mono" href={architectureHref(item.target_resource_ref)}>{item.target_resource_ref}</a>
                    : <span class="mono">{item.target_resource_ref}</span>
                ) : label === t("approvals.fieldGroundedOn") && item.citing_rule_ids.length > 0 ? (
                  <span class="approval-rule-links">
                    {[...new Set(item.citing_rule_ids)].map((ruleId) =>
                      dataMode === "live"
                        ? (
                          <a key={ruleId} class="approval-rule-chip mono" href={routeHref("rules", { params: { rule: ruleId } })}>
                            {ruleId}
                          </a>
                        )
                        : <span key={ruleId} class="approval-rule-chip mono">{ruleId}</span>
                    )}
                  </span>
                ) : (label === t("approvals.fieldApprovalId") || label === t("approvals.fieldActionId")) && value ? (
                  <span class="approval-fact-copy-row">
                    <code class="mono">{value}</code>
                    <CopyButton text={String(value)} />
                  </span>
                ) : value || <span class="muted">{t("approvals.notRecorded")}</span>}
              </dd>
            </div>
          ))}
        </dl>
        <footer class="approval-card-foot">
          <span>{t("approvals.requested", { timestamp: formatConsoleTimestamp(item.requested_at) })}</span>
          {item.ttl_expires_at ? (
            <span>{t("approvals.expires", { timestamp: formatConsoleTimestamp(item.ttl_expires_at) })}</span>
          ) : <span class="muted">{t("approvals.ttlNotRecorded")}</span>}
          <span class="approval-foot-token">
            <span>{t("approvals.eventLabel")}:</span>
            <code>{item.event_id}</code>
          </span>
          {item.correlation_id ? (
            <span class="approval-foot-token">
              <span>{t("approvals.correlationLabel")}:</span>
              <code>{item.correlation_id}</code>
            </span>
          ) : null}
        </footer>
        {item.correlation_id ? (
          <nav class="approval-card-actions" aria-label={t("approvals.relatedEvidence")}>
            {item.incident_available ? (
              <a href={routeHref("incidents", { params: {
                status: "all",
                correlation: item.correlation_id,
                data: dataMode === "sample" ? "sample" : null,
              } })}>
                {t("approvals.openIncident")}
              </a>
            ) : null}
            <a href={routeHref("trace", { params: {
              correlation: item.correlation_id,
              data: dataMode === "sample" ? "sample" : null,
            } })}>
              {t("approvals.openTrace")}
            </a>
            <a href={routeHref("audit", { params: {
              correlation: item.correlation_id,
              data: dataMode === "sample" ? "sample" : null,
            } })}>
              {t("approvals.openAudit")}
            </a>
            <a href={routeHref("rca", { params: {
              correlation: item.correlation_id,
              data: dataMode === "sample" ? "sample" : null,
            } })}>
              {t("approvals.openRca")}
            </a>
            {dataMode === "live" && item.target_resource_ref ? (
              <a href={`${routeHref("detection-readiness", { params: { resource: item.target_resource_ref, data: "live" } })}#detection-resources`}>
                {t("approvals.openDetectionCoverage")}
              </a>
            ) : null}
          </nav>
        ) : null}
        {canDecide && awaitingSignIn && item.development_owner_only !== true ? (
          <div class="approval-decision-form">
            <p class="muted">{t("approvals.developmentNote")}</p>
            {decisionError !== null ? (
              <div class="state-block state-error" role="alert">{decisionError}</div>
            ) : null}
            <div class="approval-decision-actions">
              <button
                type="button"
                class="btn btn-primary"
                disabled={!auth.interactiveSignIn}
                onClick={() => {
                  markDevelopmentReauthentication(item.approval_id);
                  void auth.signIn({ reauthenticate: true });
                }}
              >
                {t("approvals.developmentReauthenticate")}
              </button>
            </div>
          </div>
        ) : canDecide ? (
          <form
            class="approval-decision-form"
            onSubmit={(event) => event.preventDefault()}
          >
            {awaitingSignIn ? (
              <p class="muted">{t("approvals.developmentNote")}</p>
            ) : ownDevelopment ? (
              <p class="muted" role="status">{t("approvals.developmentReady")}</p>
            ) : null}
            {approvable ? null : (
              <p class="muted" role="status">{t("approvals.developmentOwnerOnly")}</p>
            )}
            <label>
              <span class="approval-justification-head">
                <span>{t("approvals.justification")}</span>
                <small class="muted mono">{justification.trim().length}/2000</small>
              </span>
              <textarea
                class="form-input"
                value={justification}
                maxLength={2000}
                placeholder={t("approvals.justificationPlaceholder")}
                disabled={pendingDecision !== null}
                onInput={(event) => setJustification(event.currentTarget.value)}
              />
            </label>
            {decisionError !== null ? (
              <div class="state-block state-error" role="alert">{decisionError}</div>
            ) : null}
            <div class="approval-decision-actions">
              {awaitingSignIn ? (
                <button
                  type="button"
                  class="btn btn-primary"
                  disabled={!auth.interactiveSignIn || pendingDecision !== null}
                  onClick={() => {
                    markDevelopmentReauthentication(item.approval_id);
                    void auth.signIn({ reauthenticate: true });
                  }}
                >
                  {t("approvals.developmentReauthenticate")}
                </button>
              ) : approvable ? (
                <button
                  type="button"
                  class="btn btn-primary"
                  disabled={pendingDecision !== null}
                  onClick={() => void submitDecision("approve")}
                >
                  {pendingDecision === "approve"
                    ? t("approvals.recordingDecision")
                    : ownDevelopment ? t("approvals.developmentApprove") : t("approvals.approve")}
                </button>
              ) : null}
              {approvalCanReject(item) ? (
                <button
                  type="button"
                  class="btn"
                  disabled={pendingDecision !== null}
                  onClick={() => void submitDecision("reject")}
                >
                  {pendingDecision === "reject"
                    ? t("approvals.recordingDecision")
                    : t("approvals.reject")}
                </button>
              ) : null}
            </div>
          </form>
        ) : item.decision_unavailable_reason !== null && dataMode === "live" ? (
          <p class="muted approval-decision-unavailable">
            {t("approvals.decisionUnavailable")}
            {unavailableReasonLabel(item.decision_unavailable_reason)
              ? ` (${unavailableReasonLabel(item.decision_unavailable_reason)})`
              : ""}
          </p>
        ) : null}
      </div>
    </article>
  );
}

/** A parked category-only denial offers approval only to its development Owner. */
export function approvalCanApprove(item: HilQueueItem): boolean {
  return item.development_owner_only !== true || item.development_self_approval_available === true;
}

/** The requesting Owner may reject only a category-only park; everyone else may always reject. */
export function approvalCanReject(item: HilQueueItem): boolean {
  return item.development_self_approval_available !== true || item.development_owner_only === true;
}

export function approvalCanDecide(
  item: HilQueueItem,
  now: number,
  dataMode: ConsoleDataMode,
): boolean {
  if (
    dataMode !== "live"
    || !item.decision_requestable
    || !item.approval_id
    || item.decision_unavailable_reason !== null
    || item.ttl_expires_at === null
  ) {
    return false;
  }
  const expiresAt = Date.parse(item.ttl_expires_at);
  return Number.isFinite(expiresAt) && expiresAt > now;
}

function approvalIsExpired(item: HilQueueItem, now: number): boolean {
  return item.ttl_expires_at !== null && Date.parse(item.ttl_expires_at) <= now;
}

function shortTargetDisplay(resourceRef: string): {
  readonly shortName: string;
  readonly resourceGroup: string | null;
} {
  const match = /^(?:scope-[^/]+\/resource-group|\/?subscriptions\/[^/]+\/resourcegroups)\/([^/]+)\/providers\/[^/]+\/[^/]+\/(.+)$/i.exec(
    resourceRef,
  );
  if (!match) return { shortName: resourceRef, resourceGroup: null };
  const [, resourceGroup = "", tail = ""] = match;
  const parts = tail.split("/").filter(Boolean);
  return { shortName: parts[parts.length - 1] ?? tail, resourceGroup };
}

export function actionKindTitle(actionKind: string): string {
  const known = new Set([
    "ops.start-vm",
    "ops.deallocate-vm",
    "ops.restart-service",
    "ops.scale-out",
    "ops.scale-in",
    "ops.rollback-kubernetes-rollout",
    "ops.failover-primary",
    "ops.rotate-cert",
    "ops.flush-cache",
    "ops.drain-connection",
    "remediate.right-size-role",
    "remediate.enable-zone-redundancy",
    "remediate.enable-backup-protection",
    "remediate.enable-diagnostic-settings",
    "remediate.disable-public-access",
  ]);
  return known.has(actionKind) ? t(`approvals.actionTitles.${actionKind}`) : actionKind;
}

export function rollbackKindLabel(rollbackKind: string): string {
  const known = new Set([
    "pr_revert",
    "scripted",
    "pitr",
    "snapshot_restore",
    "state_forward_only",
  ]);
  return known.has(rollbackKind) ? t(`approvals.rollbackKinds.${rollbackKind}`) : rollbackKind;
}

export function blastScopeLabel(scope: string): string {
  const known = new Set([
    "single_resource",
    "resource_group",
    "subscription",
    "cluster",
    "namespace",
  ]);
  return known.has(scope) ? t(`approvals.blastScopes.${scope}`) : scope;
}

function unavailableReasonLabel(reason: string): string | null {
  const known = new Set([
    "missing_expiry",
    "missing_action_hash",
    "expired",
    "sample_mode",
  ]);
  return known.has(reason) ? t(`approvals.unavailableReasons.${reason}`) : reason;
}

export function approvalExpiryBadge(
  expiresAt: string | null,
  now: number,
): { readonly kind: PillKind; readonly label: string } | null {
  if (expiresAt === null) return null;
  const parsed = Date.parse(expiresAt);
  if (!Number.isFinite(parsed)) return null;
  const deltaMinutes = Math.round((parsed - now) / 60_000);
  if (deltaMinutes <= 0) {
    const elapsedMinutes = Math.max(1, Math.abs(deltaMinutes));
    const label = elapsedMinutes >= 60
      ? t("approvals.expiredHoursAgo", { count: Math.round(elapsedMinutes / 60) })
      : t("approvals.expiredMinutesAgo", { count: elapsedMinutes });
    return { kind: "danger", label };
  }
  const label = deltaMinutes >= 60
    ? t("approvals.expiresInHours", { count: Math.round(deltaMinutes / 60) })
    : t("approvals.expiresInMinutes", { count: Math.max(1, deltaMinutes) });
  return {
    kind: deltaMinutes <= 15 ? "warning" : "neutral",
    label,
  };
}

function compareApprovals(
  left: HilQueueItem,
  right: HilQueueItem,
  sortBy: "expiry" | "newest" | "impact" | "action",
): number {
  if (sortBy === "newest") {
    const delta = Date.parse(right.requested_at) - Date.parse(left.requested_at);
    if (Number.isFinite(delta) && delta !== 0) return delta;
  }
  if (sortBy === "impact") {
    const delta = (right.blast_radius_count ?? 0) - (left.blast_radius_count ?? 0);
    if (delta !== 0) return delta;
  }
  if (sortBy === "action") {
    const delta = left.action_kind.localeCompare(right.action_kind);
    if (delta !== 0) return delta;
  }
  const leftExpiry = left.ttl_expires_at === null ? Number.POSITIVE_INFINITY : Date.parse(left.ttl_expires_at);
  const rightExpiry = right.ttl_expires_at === null ? Number.POSITIVE_INFINITY : Date.parse(right.ttl_expires_at);
  if (Number.isFinite(leftExpiry) && Number.isFinite(rightExpiry) && leftExpiry !== rightExpiry) {
    return leftExpiry - rightExpiry;
  }
  return left.approval_id.localeCompare(right.approval_id);
}
