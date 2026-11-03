import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import { DataTable, StatusPill, type PillKind } from "../components/ui";
import { t } from "../i18n";
import { formatConsoleTimestamp } from "../time-format";
import { settingsIamText } from "./settings-iam.i18n";
import { reviewIamAccessRequest } from "./settings-iam.command";
import type { IamAccessRequest, IdentityRosterItem } from "./settings-iam.model";

export function pendingAccessRequestCountKey(hasMore: boolean): string {
  return hasMore ? "settings.iam.pendingLoadedCount" : "settings.iam.pendingCount";
}

export function canReviewAccessRequest(
  request: IamAccessRequest,
  reviewerOid: string,
): boolean {
  return request.requesterOid.trim().toLowerCase()
    !== reviewerOid.trim().toLowerCase();
}

export function AccessRequestsView({
  requests,
  total,
  stale = false,
  hasMore,
  loadMore,
  roster,
  canManage,
  reviewerOid,
  auth,
  client,
  reload,
}: {
  readonly requests: readonly IamAccessRequest[];
  readonly total: number;
  readonly stale?: boolean;
  readonly hasMore: boolean;
  readonly loadMore: () => Promise<void>;
  readonly roster: readonly IdentityRosterItem[];
  readonly canManage: boolean;
  readonly reviewerOid: string;
  readonly auth: AuthContext;
  readonly client: OperatorApiClient;
  readonly reload: () => Promise<void>;
}) {
  const [loadingMore, setLoadingMore] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [receipt, setReceipt] = useState<string | null>(null);
  const loadMoreGeneration = useRef(0);

  useEffect(() => {
    loadMoreGeneration.current += 1;
    setLoadingMore(false);
    setPageError(null);
    return () => {
      loadMoreGeneration.current += 1;
    };
  }, [client]);

  if (!canManage) {
    return (
      <section class="settings-iam-panel settings-locked-panel" role="alert">
        <LockIcon />
        <strong>{t("settings.iam.accessDenied")}</strong>
        <p>{t("settings.iam.ownerPermissionRequired")}</p>
      </section>
    );
  }

  const pending = requests.filter((item) => item.status === "pending").length;
  const visible = filterIamRequests(requests, statusFilter, query, roster);
  return (
    <section class="settings-iam-panel settings-requests-panel" aria-labelledby="settings-iam-requests">
      <header class="settings-iam-panel-head">
        <div>
          <h3 id="settings-iam-requests">{t("settings.iam.requests")}</h3>
          <p>{t("settings.iam.requestsAdminHint")}</p>
        </div>
        {!stale ? <div class="settings-roster-counts">
          <StatusPill
            kind="warning"
            label={t(pendingAccessRequestCountKey(hasMore), { count: pending })}
          />
          <StatusPill kind="neutral" label={t("settings.iam.totalCount", { count: total })} />
        </div> : null}
      </header>
      <div class="settings-access-lifecycle settings-access-lifecycle-compact" role="status">
        <strong>{settingsIamText("requestLifecycleTitle")}</strong>
        <span>{settingsIamText("requestLifecycleHint")}</span>
      </div>
      {receipt ? <p role="status">{receipt}</p> : null}
      <div class="settings-actions">
        <label>{settingsIamText("requestStatusFilter")}
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.currentTarget.value)}>
            <option value="all">{settingsIamText("allRequests")}</option>
            {(["pending", "approved", "rejected"] as const).map((value) =>
              <option key={value} value={value}>{t(`settings.iam.statusValue.${value}`)}</option>)}
          </select>
        </label>
        <label>{settingsIamText("requestSearch")}
          <input type="search" value={query} onInput={(event) => setQuery(event.currentTarget.value)} />
        </label>
        {query || statusFilter !== "all" ? <button type="button" class="secondary" onClick={() => {
          setQuery(""); setStatusFilter("all");
        }}>{settingsIamText("clearFilters")}</button> : null}
      </div>
      <p role="status">{stale
        ? settingsIamText("loadedStaleCount", { loaded: requests.length })
        : settingsIamText("loadedMatches", { count: visible.length, loaded: requests.length, total })}</p>
      <DataTable
        columns={[
          {
            key: "requester",
            header: t("settings.iam.requester"),
            render: (item: IamAccessRequest) => {
              const identity = rosterIdentity(roster, item.requesterOid);
              return identity?.username ?? identity?.displayName ?? <code>{item.requesterOid}</code>;
            },
          },
          {
            key: "target",
            header: t("settings.iam.targetPrincipal"),
            render: (item: IamAccessRequest) => {
              const identity = rosterIdentity(roster, item.targetSubjectId);
              return (
                <div>
                <span class="settings-request-principal">
                  <PersonIcon />
                  <span>
                    <strong>{identity?.displayName ?? item.targetUsername}</strong>
                    <small>{identity?.username ?? item.targetSubjectId}</small>
                  </span>
                </span>
                  <details>
                    <summary id={`iam-request-${item.requestId}`}>{settingsIamText("requestDetails")}</summary>
                    <dl class="settings-request-details">
                      <dt>{settingsIamText("requestIdentifier")}</dt><dd><code>{item.requestId}</code></dd>
                      <dt>{settingsIamText("requestReason")}</dt><dd>{item.justification}</dd>
                      <dt>{settingsIamText("targetIdentity")}</dt><dd><code>{item.identityProvider}: {item.targetSubjectId}</code></dd>
                      <dt>{settingsIamText("reviewedTime")}</dt><dd>{item.reviewedAt ? formatConsoleTimestamp(item.reviewedAt) : t("settings.unavailable")}</dd>
                      <dt>{settingsIamText("reviewNote")}</dt><dd>{item.reviewJustification ?? t("settings.unavailable")}</dd>
                    </dl>
                    <p class="muted">{settingsIamText("proposalOnlyHint")}</p>
                  </details>
                </div>
              );
            },
          },
          {
            key: "change",
            header: t("settings.iam.requestedAccess"),
            render: (item: IamAccessRequest) => (
              <span class="settings-request-change">
                <StatusPill kind="neutral" label={item.role} />
                <small>{t(`settings.iam.operationValue.${item.operation}`)}</small>
              </span>
            ),
          },
          {
            key: "status",
            header: t("settings.iam.status"),
            render: (item: IamAccessRequest) => {
              return (
                <StatusPill
                  kind={statusKind(item.status)}
                  label={item.status === "approved" ? settingsIamText("approvedPending") : t(`settings.iam.statusValue.${item.status}`)}
                />
              );
            },
          },
          {
            key: "requested",
            header: t("settings.iam.requestedAt"),
            render: (item: IamAccessRequest) => formatConsoleTimestamp(item.requestedAt),
          },
          {
            key: "review",
            header: t("settings.iam.action"),
            render: (item: IamAccessRequest) => item.status === "pending"
              ? (
                <RequestReviewActions
                  item={item}
                  reviewerOid={reviewerOid}
                  stale={stale}
                  auth={auth}
                  client={client}
                  reload={reload}
                  onReviewed={() => setReceipt(settingsIamText("reviewRecorded", { id: item.requestId }))}
                />
              )
              : reviewedByLabel(item, roster),
          },
        ]}
        rows={visible}
        keyOf={(item) => item.requestId}
        empty={settingsIamText("noMatchingRequests")}
      />
      {hasMore ? (
        <button
          type="button"
          class="secondary"
          disabled={loadingMore || stale}
          onClick={() => {
            const generation = ++loadMoreGeneration.current;
            setLoadingMore(true);
            setPageError(null);
            void loadMore().catch((reason: unknown) => {
              if (loadMoreGeneration.current === generation) {
                setPageError(reason instanceof Error ? reason.message : String(reason));
              }
            }).finally(() => {
              if (loadMoreGeneration.current === generation) {
                setLoadingMore(false);
              }
            });
          }}
        >
          {loadingMore ? t("settings.iam.loading") : t("settings.iam.loadMore")}
        </button>
      ) : null}
      {pageError ? <div class="error" role="alert">{pageError}</div> : null}
    </section>
  );
}

export function rosterIdentity(
  roster: readonly IdentityRosterItem[],
  subjectId: string,
): IdentityRosterItem | undefined {
  return roster.find(
    (identity) => identity.principalType === "person" && identity.subjectId === subjectId,
  );
}

export function isRoleAssigned(
  request: IamAccessRequest,
  roster: readonly IdentityRosterItem[],
): boolean {
  // This is a membership snapshot, never proof that this request caused a provider effect.
  const identity = rosterIdentity(roster, request.targetSubjectId);
  return request.status === "approved" && request.operation !== "revoke"
    && identity?.roles.includes(request.role) === true;
}

function reviewedByLabel(
  request: IamAccessRequest,
  roster: readonly IdentityRosterItem[],
): string {
  if (!request.reviewedBy) return t("settings.iam.reviewed");
  const identity = rosterIdentity(roster, request.reviewedBy);
  return identity?.username ?? identity?.displayName ?? request.reviewedBy;
}

function RequestReviewActions({ item, reviewerOid, auth, client, reload, onReviewed, stale }: {
  readonly item: IamAccessRequest;
  readonly reviewerOid: string;
  readonly auth: AuthContext;
  readonly client: OperatorApiClient;
  readonly reload: () => Promise<void>;
  readonly onReviewed: () => void;
  readonly stale: boolean;
}) {
  const [justification, setJustification] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const justificationLength = justification.trim().length;
  const helpId = `review-justification-${item.requestId}`;
  const selfReview = !canReviewAccessRequest(item, reviewerOid);
  const pending = useRef(false);

  const review = async (decision: "approve" | "reject") => {
    if (selfReview) {
      setError(t("settings.iam.selfReviewNotAllowed"));
      return;
    }
    if (pending.current || stale) return;
    pending.current = true;
    setSubmitting(true);
    setError(null);
    try {
      await reviewIamAccessRequest(auth, client.operatorApiBaseUrl, item.requestId, {
        decision,
        ...(justification.trim() ? { justification: justification.trim() } : {}),
      });
      onReviewed();
      await reload();
      requestAnimationFrame(() => document.getElementById(`iam-request-${item.requestId}`)?.focus());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSubmitting(false);
      pending.current = false;
    }
  };

  return (
    <div class="settings-request-review">
      <input
        aria-label={t("settings.iam.reviewJustification")}
        aria-describedby={helpId}
        maxLength={2000}
        disabled={submitting || selfReview || stale}
        value={justification}
        placeholder={t("settings.iam.reviewJustification")}
        onInput={(event) => setJustification(event.currentTarget.value)}
      />
      <small id={helpId} class="settings-review-hint">
        {t("settings.iam.reviewJustificationHint", { count: justificationLength })}
      </small>
      <div>
        <button
          type="button"
          class="btn primary"
          disabled={submitting || selfReview || stale}
          onClick={() => { void review("approve"); }}
        >
          {t("settings.iam.approve")}
        </button>
        <button
          type="button"
          class="secondary"
          disabled={submitting || selfReview || stale}
          onClick={() => { void review("reject"); }}
        >
          {t("settings.iam.reject")}
        </button>
      </div>
      {selfReview ? (
        <small class="settings-review-hint" role="status">
          {t("settings.iam.selfReviewNotAllowed")}
        </small>
      ) : null}
      {error ? <small class="error" role="alert">{error}</small> : null}
    </div>
  );
}

export function filterIamRequests(
  requests: readonly IamAccessRequest[],
  status: string,
  query: string,
  roster: readonly IdentityRosterItem[],
): readonly IamAccessRequest[] {
  const term = query.trim().toLocaleLowerCase();
  return requests.filter((request) => {
    if (status !== "all" && request.status !== status) return false;
    const requester = rosterIdentity(roster, request.requesterOid);
    const target = rosterIdentity(roster, request.targetSubjectId);
    return [
      request.requesterOid, request.targetUsername, request.targetSubjectId, request.requestId,
      requester?.displayName, requester?.username, target?.displayName, target?.username,
    ].some((value) => (value ?? "").toLocaleLowerCase().includes(term));
  });
}

function statusKind(status: IamAccessRequest["status"]): PillKind {
  if (status === "approved") return "success";
  if (status === "rejected") return "danger";
  return "warning";
}

function LockIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10" width="14" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg>;
}

function PersonIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="3" /><path d="M5 20c0-4 3-7 7-7s7 3 7 7" /></svg>;
}
