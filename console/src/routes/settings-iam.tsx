import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import {
  DataTable,
  ErrorState,
  LoadingState,
  PageHeader,
  StatusPill,
  type PillKind,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { currentRoute, navigate, routeHref, ROUTE_STATE_EVENT } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import "./settings-iam.css";
import { settingsIamText } from "./settings-iam.i18n";
import { IamCapabilityDisclosure } from "./settings-iam-capabilities";
import { AccessRequestsView } from "./settings-iam-requests";
import { DirectoryUserSearch } from "./settings-iam-users";
import { submitIamAccessRequest } from "./settings-iam.command";
import type {
  HumanIdentityResult,
  IamAccessRequest,
  IamOverview,
  IamRole,
  IamRoleDefinition,
  IdentityRosterItem,
} from "./settings-iam.model";

interface Props {
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
}

type IamTab = "my-access" | "users" | "roles" | "requests";

export function isIamTabRestricted(
  tab: IamTab,
  canManage: boolean | null,
): boolean {
  return canManage === false && (tab === "users" || tab === "requests");
}

export function isCurrentIamLoad(currentGeneration: number, candidate: number): boolean {
  return currentGeneration === candidate;
}

export function SettingsIamRoute({ client, auth }: Props) {
  const [, setRouteRevision] = useState(0);
  useEffect(() => {
    const sync = () => setRouteRevision((revision) => revision + 1);
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    window.addEventListener(ROUTE_STATE_EVENT, sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
      window.removeEventListener(ROUTE_STATE_EVENT, sync);
    };
  }, []);
  const requestedTab = iamTabFromSegment(currentRoute().segments[0]);
  const invalidTab = requestedTab === null;
  const [tab, setTab] = useState<IamTab>(requestedTab ?? "my-access");
  const [overview, setOverview] = useState<IamOverview | null>(null);
  const [requests, setRequests] = useState<readonly IamAccessRequest[]>([]);
  const [requestTotal, setRequestTotal] = useState(0);
  const [nextRequestCursor, setNextRequestCursor] = useState<number | null>(null);
  const [roster, setRoster] = useState<readonly IdentityRosterItem[]>([]);
  const [requestsError, setRequestsError] = useState<string | null>(null);
  const [rosterError, setRosterError] = useState<string | null>(null);
  const [rosterAvailable, setRosterAvailable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [requestsLoading, setRequestsLoading] = useState(false);
  const [rosterLoading, setRosterLoading] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const loadGeneration = useRef(0);

  const loadRequests = async (generation = loadGeneration.current, desired = Math.max(50, requests.length)) => {
    setRequestsLoading(true);
    setRequestsError(null);
    try {
      const items: IamAccessRequest[] = [];
      let cursor: number | null = 0;
      let total = 0;
      let pages = 0;
      do {
        const page = await client.listIamAccessRequests(50, cursor);
        if (generation !== loadGeneration.current) return;
        items.push(...page.items);
        pages += 1;
        total = page.total;
        if (page.nextCursor !== null && page.nextCursor <= cursor) {
          throw new Error("IAM access-request cursor did not advance.");
        }
        cursor = page.nextCursor;
      } while (cursor !== null && items.length < desired && pages < Math.ceil(desired / 50));
      setRequests(items);
      setRequestTotal(total);
      setNextRequestCursor(cursor);
    } catch (reason) {
      if (generation === loadGeneration.current) setRequestsError(errorMessage(reason));
    } finally {
      if (generation === loadGeneration.current) setRequestsLoading(false);
    }
  };
  const loadRoster = async (generation = loadGeneration.current) => {
    setRosterLoading(true);
    setRosterError(null);
    try {
      const items = await client.iamRoster();
      if (generation !== loadGeneration.current) return;
      setRoster(items);
      setRosterAvailable(true);
    } catch (reason) {
      if (generation === loadGeneration.current) {
        setRosterError(errorMessage(reason));
        setRosterAvailable(false);
      }
    } finally {
      if (generation === loadGeneration.current) setRosterLoading(false);
    }
  };
  const load = async (initial = false) => {
    const generation = ++loadGeneration.current;
    setLoading(initial || overview === null);
    setError(null);
    try {
      const nextOverview = await client.iamOverview();
      if (generation !== loadGeneration.current) return;
      setOverview(nextOverview);
      setLoading(false);
      const manager = nextOverview.authority.canManageGroupMembership;
      if (manager) {
        await Promise.all([loadRequests(generation, initial ? 50 : undefined), loadRoster(generation)]);
      } else {
        setRequestsLoading(false);
        setRosterLoading(false);
        setRequests([]);
        setRequestTotal(0);
        setNextRequestCursor(null);
        setRoster([]);
        setRequestsError(null);
        setRosterError(null);
        setRosterAvailable(false);
      }
    } catch (reason) {
      if (generation !== loadGeneration.current) return;
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      if (generation === loadGeneration.current) {
        setLoading(false);
      }
    }
  };

  useEffect(() => {
    setOverview(null);
    setRequests([]);
    setRequestTotal(0);
    setNextRequestCursor(null);
    setRoster([]);
    setRequestsError(null);
    setRosterError(null);
    setRosterAvailable(false);
    void load(true);
    return () => {
      loadGeneration.current += 1;
    };
  }, [client]);

  useEffect(() => {
    if (requestedTab !== null) setTab(requestedTab);
  }, [requestedTab]);

  const username = auth.account?.username ?? null;
  const displayUsername = username ?? t("settings.unavailable");
  const roles = overview?.principal.roles ?? currentTokenRoles(auth);
  const canManage = overview === null
    ? null
    : error === null && overview.authority.canManageGroupMembership;

  const selectTab = (nextTab: IamTab) => {
    setTab(nextTab);
    const segment = nextTab === "my-access" ? [] : [nextTab];
    navigate(routeHref("settings-iam", {
      segments: segment,
      params: { data: currentRoute().search.get("data") === "sample" ? "sample" : null },
    }));
  };

  const loadMoreRequests = async () => {
    if (nextRequestCursor === null || requestsLoading) return;
    const generation = loadGeneration.current;
    const cursor = nextRequestCursor;
    const page = await client.listIamAccessRequests(50, cursor);
    if (!isCurrentIamLoad(loadGeneration.current, generation)) return;
    setRequests((current) => [...current, ...page.items]);
    setRequestTotal(page.total);
    setNextRequestCursor(page.nextCursor);
  };

  usePublishViewContext(
    () => ({
      routeId: "settings-iam",
      routeLabel: t("route.settingsIam"),
      purpose: "Human identity roles, effective capabilities, and governed access requests.",
      glossary: composeGlossary([TERMS.humanRbac]),
      headline: `${displayUsername}: ${roles.join(", ") || "unassigned"}`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "principal", value: username, group: "identity" },
        { key: "roles", value: roles.join(",") || "unassigned", group: "identity" },
        { key: "access_request_count", value: requestTotal, group: "identity" },
      ],
      records: {},
    }),
    [displayUsername, requestTotal, roles, username],
  );

  return (
    <div class="stack settings-route settings-iam-route">
      <PageHeader title={t("route.settingsIam")} subtitle={t("settings.iam.subtitle")} />
      <div
        class="settings-tabs"
        role="tablist"
        aria-label={t("settings.iam.tabsLabel")}
        onKeyDown={(event) => handleTabKey(event, tab, selectTab)}
      >
        {([
          ["my-access", t("settings.iam.myAccess")],
          ["users", t("settings.iam.users")],
          ["roles", t("settings.iam.roles")],
          ["requests", t("settings.iam.requests")],
        ] as const).map(([id, label]) => {
          const restricted = isIamTabRestricted(id, canManage);
          return (
          <button
            key={id}
            id={`settings-iam-tab-${id}`}
            type="button"
            role="tab"
            class={[
              !invalidTab && tab === id ? "is-active" : "",
              restricted ? "is-restricted" : "",
            ].filter(Boolean).join(" ") || undefined}
            aria-selected={!invalidTab && tab === id}
            aria-controls={`settings-iam-panel-${id}`}
            tabIndex={tab === id ? 0 : -1}
            onClick={() => selectTab(id)}
          >
            <span>{label}</span>
            {restricted ? <LockIcon /> : null}
          </button>
          );
        })}
      </div>
      {canManage === false ? (
        <p class="muted small">{t("settings.iam.ownerTabsHint")}</p>
      ) : null}

      {loading ? <LoadingState label={t("settings.iam.loading")} /> : null}
      {error ? (
        <ErrorState
          message={t("settings.iam.loadFailed", { error })}
          onRetry={() => { void load(); }}
          retryLabel={t("settings.retry")}
        />
      ) : null}
      {notice ? <p role="status">{notice}</p> : null}
      {!loading && !error && overview && invalidTab ? (
        <div class="state-block state-unavailable" role="alert">
          {t("settings.iam.invalidTab")}
        </div>
      ) : null}
      {!loading && overview && !invalidTab ? (
        <div
          id={`settings-iam-panel-${tab}`}
          role="tabpanel"
          aria-labelledby={`settings-iam-tab-${tab}`}
        >
          {requestsError && tab === "requests" ? (
            <div class="state-block" role="alert">
              <p>{settingsIamText(requests.length > 0 ? "requestsStale" : "requestsReadUnavailable")}</p>
              <button type="button" class="secondary" disabled={requestsLoading} onClick={() => { void loadRequests(); }}>{t("settings.retry")}</button>
            </div>
          ) : null}
          {renderTab({
        tab,
        overview,
        requests,
        requestTotal,
        hasMoreRequests: nextRequestCursor !== null,
        loadMoreRequests,
        requestsLoading,
        rosterLoading,
        requestsUnavailable: requestsError !== null,
        roster,
        rosterAvailable,
        rosterError,
        retryRoster: () => { void loadRoster(); },
        username,
        canManage: canManage ?? false,
        assignRole: async (identity, role, justification, idempotencyKey) => {
          const receipt = await submitIamAccessRequest(auth, client.operatorApiBaseUrl, {
            idempotencyKey,
            identityProvider: identity.provider,
            targetSubjectId: identity.subjectId,
            targetUsername: identity.username ?? identity.displayName,
            operation: "set",
            role,
            justification,
          });
          setNotice(settingsIamText("requestRecorded", { id: receipt.requestId }));
          await load();
        },
        auth,
        client,
        reload: () => load(),
          })}
        </div>
      ) : null}
    </div>
  );
}

function renderTab(props: {
  readonly tab: IamTab;
  readonly overview: IamOverview;
  readonly requests: readonly IamAccessRequest[];
  readonly requestTotal: number;
  readonly hasMoreRequests: boolean;
  readonly loadMoreRequests: () => Promise<void>;
  readonly requestsLoading: boolean;
  readonly rosterLoading: boolean;
  readonly requestsUnavailable: boolean;
  readonly roster: readonly IdentityRosterItem[];
  readonly rosterAvailable: boolean;
  readonly rosterError: string | null;
  readonly retryRoster: () => void;
  readonly username: string | null;
  readonly canManage: boolean;
  readonly assignRole: (
    identity: IdentityRosterItem | HumanIdentityResult,
    role: Exclude<IamRole, "BreakGlass">,
    justification: string,
    idempotencyKey: string,
  ) => Promise<void>;
  readonly auth: AuthContext;
  readonly client: OperatorApiClient;
  readonly reload: () => Promise<void>;
}) {
  switch (props.tab) {
    case "my-access":
      return <MyAccess overview={props.overview} username={props.username} auth={props.auth} />;
    case "users":
      if (props.rosterLoading && props.roster.length === 0) {
        return <LoadingState label={t("settings.iam.loading")} />;
      }
      return (
        <UsersView
          overview={props.overview}
          username={props.username}
          requests={props.requests}
          roster={props.roster}
          rosterAvailable={props.rosterAvailable}
          rosterError={props.rosterError}
          retryRoster={props.retryRoster}
          rosterLoading={props.rosterLoading}
          client={props.client}
          canManage={props.canManage}
          onAssign={props.assignRole}
        />
      );
    case "roles":
      return <RolesView roles={props.overview.roles} />;
    case "requests":
      if (props.requestsLoading && props.requests.length === 0) {
        return <LoadingState label={t("settings.iam.loading")} />;
      }
      if (props.requestsUnavailable && props.requests.length === 0) return null;
      return (
        <AccessRequestsView
          requests={props.requests}
          total={props.requestTotal}
          stale={props.requestsUnavailable || props.requestsLoading}
          hasMore={props.hasMoreRequests}
          loadMore={props.loadMoreRequests}
          roster={props.roster}
          canManage={props.canManage}
          reviewerOid={props.overview.principal.oid}
          auth={props.auth}
          client={props.client}
          reload={props.reload}
        />
      );
  }
}

function MyAccess({ overview, username, auth }: {
  readonly overview: IamOverview;
  readonly username: string | null;
  readonly auth: AuthContext;
}) {
  const identity = iamIdentityPresentation(auth, overview);
  return (
    <section class="settings-iam-panel" aria-labelledby="settings-iam-my-access">
      <header class="settings-iam-panel-head">
        <div>
          <h3 id="settings-iam-my-access">{t("settings.iam.currentAccess")}</h3>
          <p>{t("settings.iam.currentAccessHint")}</p>
        </div>
        <div class="settings-role-list" aria-label={t("settings.iam.currentRoles")}>
          {overview.principal.roles.length > 0
            ? overview.principal.roles.map((role) => (
                <StatusPill key={role} kind={roleKind(role)} label={role} />
              ))
            : <StatusPill kind="danger" label={t("settings.iam.unassigned")} />}
        </div>
      </header>

      <div class="settings-access-strip" aria-label={t("settings.iam.accessSummary")}>
        <div>
          <span>{t("settings.iam.identityProvider")}</span>
          <strong>{t(`settings.iam.identitySource.${identity.source}`)}</strong>
        </div>
        <div>
          <span>{t("settings.iam.role")}</span>
          <strong>{overview.principal.roles.join(", ") || t("settings.iam.unassigned")}</strong>
        </div>
        <div>
          <span>{t("settings.iam.capabilities")}</span>
          <strong>{overview.principal.capabilities.length}</strong>
        </div>
        <div>
          <span>{settingsIamText("managementAccess")}</span>
          <strong>
            {overview.authority.canManageGroupMembership
              ? settingsIamText("managementAccessEnabled")
              : settingsIamText("managementAccessUnavailable")}
          </strong>
        </div>
      </div>

      <div
        class={[
          "settings-iam-authority",
          overview.authority.canManageGroupMembership ? "is-owner" : "is-limited",
        ].join(" ")}
        role="status"
      >
        <div>
          <strong>
            {overview.authority.isOwner
              ? settingsIamText("fdaiOwnerConfirmed")
              : settingsIamText("fdaiOwnerNotAssigned")}
          </strong>
          <p>{settingsIamText("tenantAdminDistinction")}</p>
          {!overview.authority.isOwner ? (
            <p>{settingsIamText("ownerRecoveryHint")}</p>
          ) : null}
        </div>
        <StatusPill
          kind={overview.authority.isOwner ? "success" : "neutral"}
          label={overview.authority.isOwner ? "FDAI Owner" : settingsIamText("notFdaiOwner")}
        />
      </div>

      <div class="settings-access-body">
        <dl class="settings-access-details">
          <dt>{t("settings.iam.signedInAs")}</dt>
          <dd>{username ?? t("settings.unavailable")}</dd>
          {identity.subjectId ? (
            <>
              <dt>{t("settings.iam.subjectId")}</dt>
              <dd><code>{identity.subjectId}</code></dd>
            </>
          ) : null}
          <dt>{t("settings.iam.authorizationMode")}</dt>
          <dd>
            <strong>{t(`settings.iam.authorizationValue.${identity.authorization}`)}</strong>
            {identity.authorization === "local-ceiling" ? (
              <small>{t("settings.iam.localCeilingHint")}</small>
            ) : null}
          </dd>
        </dl>
        <div class="settings-capability-panel">
          <span>{t("settings.iam.effectiveCapabilities")}</span>
          <IamCapabilityDisclosure capabilities={overview.principal.capabilities} />
        </div>
      </div>
      <IamWorkflowSummary overview={overview} />
    </section>
  );
}

function IamWorkflowSummary({ overview }: { readonly overview: IamOverview }) {
  const directoryKind: PillKind = overview.directory.availability === "available"
    ? "success"
    : overview.directory.availability === "unavailable"
    ? "danger"
    : "neutral";
  return (
    <section class="settings-iam-workflow" aria-labelledby="settings-iam-workflow-title">
      <div>
        <span>{settingsIamText("directoryStatus")}</span>
        <StatusPill
          kind={directoryKind}
          label={directoryAvailabilityLabel(overview.directory.availability)}
        />
        <small>
          {overview.directory.observedAt
            ? settingsIamText("directoryObservedAt", {
                time: formatConsoleTimestamp(overview.directory.observedAt),
              })
            : overview.directory.detail ?? settingsIamText("directoryNotObserved")}
        </small>
      </div>
      <div>
        <span id="settings-iam-workflow-title">{settingsIamText("accessWorkflow")}</span>
        <strong>{settingsIamText("proposalOnly")}</strong>
        <small>{settingsIamText("proposalOnlyHint")}</small>
      </div>
      <div>
        <span>{settingsIamText("providerMutation")}</span>
        <strong>{settingsIamText("promotionRequired")}</strong>
        <small>{settingsIamText("promotionRequiredHint")}</small>
      </div>
    </section>
  );
}

function directoryAvailabilityLabel(
  availability: IamOverview["directory"]["availability"],
): string {
  switch (availability) {
    case "available": return settingsIamText("directoryAvailabilityAvailable");
    case "unavailable": return settingsIamText("directoryAvailabilityUnavailable");
    case "not_configured": return settingsIamText("directoryAvailabilityNotConfigured");
    case "unknown": return settingsIamText("directoryAvailabilityUnknown");
  }
}

export interface IamIdentityPresentation {
  readonly source: "local-entra" | "azure-cli" | "entra" | "development";
  readonly subjectId: string | null;
  readonly authorization: "local-ceiling" | "provider-roles";
}

export function iamIdentityPresentation(
  auth: AuthContext,
  overview: IamOverview,
): IamIdentityPresentation {
  if (auth.localAzureCli && auth.account) {
    return {
      source: "azure-cli",
      subjectId: auth.account.localAccountId,
      authorization: "local-ceiling",
    };
  }
  if (auth.devMode && auth.account) {
    return {
      source: "local-entra",
      subjectId: auth.account.localAccountId,
      authorization: "local-ceiling",
    };
  }
  if (auth.account) {
    return {
      source: "entra",
      subjectId: auth.account.localAccountId,
      authorization: "provider-roles",
    };
  }
  return {
    source: "development",
    subjectId: null,
    authorization: "local-ceiling",
  };
}

function UsersView({
  overview,
  username,
  requests,
  roster,
  rosterAvailable,
  rosterError,
  retryRoster,
  rosterLoading,
  client,
  canManage,
  onAssign,
}: {
  readonly overview: IamOverview;
  readonly username: string | null;
  readonly requests: readonly IamAccessRequest[];
  readonly roster: readonly IdentityRosterItem[];
  readonly rosterAvailable: boolean;
  readonly rosterError: string | null;
  readonly retryRoster: () => void;
  readonly rosterLoading: boolean;
  readonly client: OperatorApiClient;
  readonly canManage: boolean;
  readonly onAssign: (
    identity: IdentityRosterItem | HumanIdentityResult,
    role: Exclude<IamRole, "BreakGlass">,
    justification: string,
    idempotencyKey: string,
  ) => Promise<void>;
}) {
  const users = referencedUsers(overview, username, requests);
  return (
    <DirectoryUserSearch
      client={client}
      canManage={canManage}
      roster={roster}
      rosterAvailable={rosterAvailable}
      rosterError={rosterError}
      retryRoster={retryRoster}
      rosterLoading={rosterLoading}
      referencedUsers={users}
      onAssign={onAssign}
    />
  );
}

const IAM_TABS: readonly IamTab[] = ["my-access", "users", "roles", "requests"];

export function iamTabFromSegment(segment: string | undefined): IamTab | null {
  if (segment === undefined) return "my-access";
  return IAM_TABS.includes(segment as IamTab) ? segment as IamTab : null;
}

function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason);
}

function handleTabKey(
  event: KeyboardEvent,
  current: IamTab,
  select: (tab: IamTab) => void,
): void {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  const next = nextIamTab(current, event.key);
  event.preventDefault();
  select(next);
  requestAnimationFrame(() => document.getElementById(`settings-iam-tab-${next}`)?.focus());
}

export function nextIamTab(current: IamTab, key: string): IamTab {
  const offset = key === "ArrowRight" ? 1 : -1;
  const currentIndex = Math.max(0, IAM_TABS.indexOf(current));
  return IAM_TABS[(currentIndex + offset + IAM_TABS.length) % IAM_TABS.length] ?? "my-access";
}

function RolesView({ roles }: { readonly roles: readonly IamRoleDefinition[] }) {
  return (
    <section class="settings-iam-panel settings-roles-panel" aria-labelledby="settings-iam-roles">
      <header class="settings-iam-panel-head">
        <div>
          <h3 id="settings-iam-roles">{t("settings.iam.roles")}</h3>
          <p>{t("settings.iam.rolesHint")}</p>
        </div>
        <StatusPill kind="neutral" label={t("settings.iam.roleCount", { count: roles.length })} />
      </header>
      <DataTable
        columns={[
          {
            key: "role",
            header: t("settings.iam.role"),
            render: (role: IamRoleDefinition) => (
              <StatusPill kind={roleKind(role.value)} label={role.value} />
            ),
          },
          {
            key: "capabilities",
            header: t("settings.iam.capabilities"),
            render: (role: IamRoleDefinition) => (
              <IamCapabilityDisclosure capabilities={role.capabilities} />
            ),
          },
          {
            key: "assignment",
            header: t("settings.iam.assignment"),
            render: (role: IamRoleDefinition) => role.routineAssignment
              ? t("settings.iam.routine")
              : t("settings.iam.emergencyOnly"),
          },
        ]}
        rows={roles}
        keyOf={(role) => role.value}
        caption={t("settings.iam.roleTableCaption")}
      />
      <p class="settings-iam-panel-foot">{t("settings.iam.assignmentBoundaryHint")}</p>
    </section>
  );
}

export function referencedUsers(
  overview: IamOverview,
  username: string | null,
  _requests: readonly IamAccessRequest[],
): readonly IdentityRosterItem[] {
  const users = new Map<string, IdentityRosterItem>();
  users.set(`current:${overview.principal.oid}`, {
    provider: "authenticated",
    subjectId: overview.principal.oid,
    displayName: username ?? overview.principal.oid,
    principalType: "person",
    username,
    roles: overview.principal.roles,
    active: true,
  });
  return [...users.values()];
}

function currentTokenRoles(auth: AuthContext): readonly IamRole[] {
  const claims = (auth.account?.idTokenClaims ?? {}) as Record<string, unknown>;
  const rawRoles = claims["roles"];
  if (!Array.isArray(rawRoles)) return [];
  return rawRoles.filter((role): role is IamRole =>
    typeof role === "string"
    && ["Reader", "Contributor", "Approver", "Owner", "BreakGlass"].includes(role)
  );
}

function roleKind(role: IamRole): PillKind {
  switch (role) {
    case "Reader": return "neutral";
    case "Contributor": return "info";
    case "Approver": return "success";
    case "Owner": return "warning";
    case "BreakGlass": return "danger";
  }
}

function LockIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="5" y="10" width="14" height="10" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </svg>
  );
}
