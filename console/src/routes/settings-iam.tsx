import { useEffect, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import type { AuthContext } from "../auth";
import { Tooltip } from "../components/tooltip";
import { DataTable, PageHeader, StatusPill, type PillKind } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { currentRoute, navigate, routeHref } from "../router";
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
  readonly client: ReadApiClient;
  readonly auth: AuthContext;
}

type IamTab = "my-access" | "users" | "roles" | "requests";

export function isCurrentIamLoad(currentGeneration: number, candidate: number): boolean {
  return currentGeneration === candidate;
}

export function SettingsIamRoute({ client, auth }: Props) {
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
  const loadGeneration = useRef(0);

  const load = async () => {
    const generation = ++loadGeneration.current;
    setLoading(true);
    setError(null);
    try {
      const nextOverview = await client.iamOverview();
      if (generation !== loadGeneration.current) return;
      setOverview(nextOverview);
      const manager = nextOverview.principal.capabilities.includes("manage-group-membership");
      if (manager) {
        const [requestResult, rosterResult] = await Promise.allSettled([
          client.listIamAccessRequests(),
          client.iamRoster(),
        ]);
        if (generation !== loadGeneration.current) return;
        if (requestResult.status === "fulfilled") {
          setRequests(requestResult.value.items);
          setRequestTotal(requestResult.value.total);
          setNextRequestCursor(requestResult.value.nextCursor);
          setRequestsError(null);
        } else {
          setRequestsError(errorMessage(requestResult.reason));
        }
        if (rosterResult.status === "fulfilled") {
          setRoster(rosterResult.value);
          setRosterAvailable(true);
          setRosterError(null);
        } else {
          setRoster([]);
          setRosterAvailable(false);
          setRosterError(errorMessage(rosterResult.reason));
        }
      } else {
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
      if (generation === loadGeneration.current) setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    return () => {
      loadGeneration.current += 1;
    };
  }, [client]);

  const username = auth.account?.username ?? null;
  const displayUsername = username ?? t("settings.unavailable");
  const roles = overview?.principal.roles ?? currentTokenRoles(auth);
  const canManage = overview?.principal.capabilities.includes("manage-group-membership") ?? false;

  const selectTab = (nextTab: IamTab) => {
    setTab(nextTab);
    const segment = nextTab === "my-access" ? [] : [nextTab];
    navigate(routeHref("settings-iam", { segments: segment }));
    if (nextTab === "users" || nextTab === "requests") {
      void load();
    }
  };

  const loadMoreRequests = async () => {
    if (nextRequestCursor === null) return;
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
    <div class="stack settings-route">
      <PageHeader title={t("route.settingsIam")} subtitle={t("settings.iam.subtitle")} />
      <div
        class="settings-tabs"
        role="tablist"
        aria-label={t("settings.iam.tabsLabel")}
        onKeyDown={(event) => handleTabKey(event, tab, canManage, selectTab)}
      >
        {([
          ["my-access", t("settings.iam.myAccess")],
          ["users", t("settings.iam.users")],
          ["roles", t("settings.iam.roles")],
          ["requests", t("settings.iam.requests")],
        ] as const).map(([id, label]) => (
          <button
            key={id}
            id={`settings-iam-tab-${id}`}
            type="button"
            role="tab"
            class={!invalidTab && tab === id ? "is-active" : undefined}
            aria-selected={!invalidTab && tab === id}
            aria-controls={`settings-iam-panel-${id}`}
            tabIndex={tab === id ? 0 : -1}
            disabled={!canManage && (id === "users" || id === "requests")}
            onClick={() => selectTab(id)}
          >
            {label}
          </button>
        ))}
      </div>
      {!canManage && overview ? (
        <p class="muted small">{t("settings.iam.ownerTabsHint")}</p>
      ) : null}

      {loading ? <p class="muted" role="status">{t("settings.iam.loading")}</p> : null}
      {error ? <div class="error" role="alert">{t("settings.iam.loadFailed", { error })}</div> : null}
      {!loading && !error && overview && invalidTab ? (
        <div class="state-block state-unavailable" role="alert">
          {t("settings.iam.invalidTab")}
        </div>
      ) : null}
      {!loading && !error && overview && !invalidTab ? (
        <div
          id={`settings-iam-panel-${tab}`}
          role="tabpanel"
          aria-labelledby={`settings-iam-tab-${tab}`}
        >
          {requestsError && tab === "requests" ? (
            <div class="error" role="alert">
              {t("settings.iam.requestsUnavailable", { error: requestsError })}
            </div>
          ) : null}
          {renderTab({
        tab,
        overview,
        requests,
        requestTotal,
        hasMoreRequests: nextRequestCursor !== null,
        loadMoreRequests,
        roster,
        rosterAvailable,
        rosterError,
        username,
        canManage,
        assignRole: async (identity, role, justification, idempotencyKey) => {
          await submitIamAccessRequest(auth, client.readApiBaseUrl, {
            idempotencyKey,
            identityProvider: identity.provider,
            targetSubjectId: identity.subjectId,
            targetUsername: identity.username ?? identity.displayName,
            operation: "set",
            role,
            justification,
          });
          await load();
        },
        auth,
        client,
        reload: load,
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
  readonly roster: readonly IdentityRosterItem[];
  readonly rosterAvailable: boolean;
  readonly rosterError: string | null;
  readonly username: string | null;
  readonly canManage: boolean;
  readonly assignRole: (
    identity: IdentityRosterItem | HumanIdentityResult,
    role: Exclude<IamRole, "BreakGlass">,
    justification: string,
    idempotencyKey: string,
  ) => Promise<void>;
  readonly auth: AuthContext;
  readonly client: ReadApiClient;
  readonly reload: () => Promise<void>;
}) {
  switch (props.tab) {
    case "my-access":
      return <MyAccess overview={props.overview} username={props.username} auth={props.auth} />;
    case "users":
      return (
        <UsersView
          overview={props.overview}
          username={props.username}
          requests={props.requests}
          roster={props.roster}
          rosterAvailable={props.rosterAvailable}
          rosterError={props.rosterError}
          client={props.client}
          canManage={props.canManage}
          onAssign={props.assignRole}
        />
      );
    case "roles":
      return <RolesView roles={props.overview.roles} />;
    case "requests":
      return (
        <AccessRequestsView
          requests={props.requests}
          total={props.requestTotal}
          hasMore={props.hasMoreRequests}
          loadMore={props.loadMoreRequests}
          roster={props.roster}
          canManage={props.canManage}
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
          <div class="settings-capability-chips">
            {overview.principal.capabilities.map((capability) => (
              <Tooltip key={capability} content={capability}>
                <span>{humanizeCapability(capability)}</span>
              </Tooltip>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
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

function humanizeCapability(capability: string): string {
  const acronyms: Readonly<Record<string, string>> = { pr: "PR", hil: "HIL", iam: "IAM" };
  return capability.split("-").map((word, index) => (
    acronyms[word] ?? (index === 0 ? word.charAt(0).toUpperCase() + word.slice(1) : word)
  )).join(" ");
}

function UsersView({
  overview,
  username,
  requests,
  roster,
  rosterAvailable,
  rosterError,
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
  readonly client: ReadApiClient;
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
  canManage: boolean,
  select: (tab: IamTab) => void,
): void {
  if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
  const available = canManage
    ? IAM_TABS
    : IAM_TABS.filter((tab) => tab !== "users" && tab !== "requests");
  const offset = event.key === "ArrowRight" ? 1 : -1;
  const currentIndex = Math.max(0, available.indexOf(current));
  const next = available[(currentIndex + offset + available.length) % available.length];
  if (next === undefined) return;
  event.preventDefault();
  select(next);
  requestAnimationFrame(() => document.getElementById(`settings-iam-tab-${next}`)?.focus());
}

function RolesView({ roles }: { readonly roles: readonly IamRoleDefinition[] }) {
  return (
    <section class="settings-iam-panel" aria-labelledby="settings-iam-roles">
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
              <span class="settings-capability-chips">
                {role.capabilities.map((capability) => (
                  <Tooltip key={capability} content={capability}>
                    <span>{humanizeCapability(capability)}</span>
                  </Tooltip>
                ))}
              </span>
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
  requests: readonly IamAccessRequest[],
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
  for (const request of requests) {
    const key = `${request.identityProvider}:${request.targetSubjectId}`;
    if (!users.has(key)) {
      users.set(key, {
        provider: request.identityProvider,
        subjectId: request.targetSubjectId,
        displayName: request.targetUsername,
        principalType: "person",
        username: request.targetUsername,
        roles: [request.role],
        active: request.status !== "rejected",
      });
    }
  }
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
