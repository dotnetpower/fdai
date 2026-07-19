import { useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import type { AuthContext } from "../auth";
import { DataTable, StatusPill, type PillKind } from "../components/ui";
import { t } from "../i18n";
import { reviewIamAccessRequest } from "./settings-iam.command";
import type { IamAccessRequest, IdentityRosterItem } from "./settings-iam.model";

export function pendingAccessRequestCountKey(hasMore: boolean): string {
  return hasMore ? "settings.iam.pendingLoadedCount" : "settings.iam.pendingCount";
}

export function AccessRequestsView({
  requests,
  total,
  hasMore,
  loadMore,
  roster,
  canManage,
  auth,
  client,
  reload,
}: {
  readonly requests: readonly IamAccessRequest[];
  readonly total: number;
  readonly hasMore: boolean;
  readonly loadMore: () => Promise<void>;
  readonly roster: readonly IdentityRosterItem[];
  readonly canManage: boolean;
  readonly auth: AuthContext;
  readonly client: ReadApiClient;
  readonly reload: () => Promise<void>;
}) {
  const [loadingMore, setLoadingMore] = useState(false);
  const [pageError, setPageError] = useState<string | null>(null);

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
  return (
    <section class="settings-iam-panel" aria-labelledby="settings-iam-requests">
      <header class="settings-iam-panel-head">
        <div>
          <h3 id="settings-iam-requests">{t("settings.iam.requests")}</h3>
          <p>{t("settings.iam.requestsAdminHint")}</p>
        </div>
        <div class="settings-roster-counts">
          <StatusPill
            kind="warning"
            label={t(pendingAccessRequestCountKey(hasMore), { count: pending })}
          />
          <StatusPill kind="neutral" label={t("settings.iam.totalCount", { count: total })} />
        </div>
      </header>
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
                <span class="settings-request-principal">
                  <PersonIcon />
                  <span>
                    <strong>{identity?.displayName ?? item.targetUsername}</strong>
                    <small>{identity?.username ?? item.targetSubjectId}</small>
                  </span>
                </span>
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
              const statusKey = isRoleAssigned(item, roster)
                ? "approvedAssigned"
                : item.status;
              return (
                <StatusPill
                  kind={statusKind(item.status)}
                  label={t(`settings.iam.statusValue.${statusKey}`)}
                />
              );
            },
          },
          {
            key: "requested",
            header: t("settings.iam.requestedAt"),
            render: (item: IamAccessRequest) => new Date(item.requestedAt).toLocaleString(),
          },
          {
            key: "review",
            header: t("settings.iam.action"),
            render: (item: IamAccessRequest) => item.status === "pending"
              ? <RequestReviewActions item={item} auth={auth} client={client} reload={reload} />
              : reviewedByLabel(item, roster),
          },
        ]}
        rows={requests}
        keyOf={(item) => item.requestId}
        empty={t("settings.iam.noRequests")}
      />
      {hasMore ? (
        <button
          type="button"
          disabled={loadingMore}
          onClick={() => {
            setLoadingMore(true);
            setPageError(null);
            void loadMore().catch((reason: unknown) => {
              setPageError(reason instanceof Error ? reason.message : String(reason));
            }).finally(() => setLoadingMore(false));
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
  const identity = rosterIdentity(roster, request.targetSubjectId);
  return request.status === "approved" && identity?.roles.includes(request.role) === true;
}

function reviewedByLabel(
  request: IamAccessRequest,
  roster: readonly IdentityRosterItem[],
): string {
  if (!request.reviewedBy) return t("settings.iam.reviewed");
  const identity = rosterIdentity(roster, request.reviewedBy);
  return identity?.username ?? identity?.displayName ?? request.reviewedBy;
}

function RequestReviewActions({ item, auth, client, reload }: {
  readonly item: IamAccessRequest;
  readonly auth: AuthContext;
  readonly client: ReadApiClient;
  readonly reload: () => Promise<void>;
}) {
  const [justification, setJustification] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const justificationLength = justification.trim().length;
  const helpId = `review-justification-${item.requestId}`;

  const review = async (decision: "approve" | "reject") => {
    if (justificationLength < 20) {
      setError(t("settings.iam.reviewJustificationMinimum", { count: justificationLength }));
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await reviewIamAccessRequest(auth, client.readApiBaseUrl, item.requestId, {
        decision,
        justification,
      });
      await reload();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div class="settings-request-review">
      <input
        aria-label={t("settings.iam.reviewJustification")}
        aria-describedby={helpId}
        minLength={20}
        maxLength={2000}
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
          disabled={submitting}
          onClick={() => { void review("approve"); }}
        >
          {t("settings.iam.approve")}
        </button>
        <button
          type="button"
          disabled={submitting}
          onClick={() => { void review("reject"); }}
        >
          {t("settings.iam.reject")}
        </button>
      </div>
      {error ? <small class="error" role="alert">{error}</small> : null}
    </div>
  );
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
