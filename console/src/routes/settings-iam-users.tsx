import { useEffect, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { DataTable, StatusPill } from "../components/ui";
import { t } from "../i18n";
import {
  identityForMutationIntent,
  type MutationIntentIdentity,
} from "../mutation-intent";
import type {
  HumanIdentityResult,
  IamRole,
  IdentityRosterItem,
} from "./settings-iam.model";

type RosterFilter = "all" | "person" | "group";
type AssignableRole = Exclude<IamRole, "BreakGlass">;

const ASSIGNABLE_ROLES: readonly AssignableRole[] = [
  "Reader",
  "Contributor",
  "Approver",
  "Owner",
];

export function isCurrentDirectorySearch(currentGeneration: number, candidate: number): boolean {
  return currentGeneration === candidate;
}

interface Props {
  readonly client: ReadApiClient;
  readonly canManage: boolean;
  readonly roster: readonly IdentityRosterItem[];
  readonly rosterAvailable: boolean;
  readonly rosterError: string | null;
  readonly referencedUsers: readonly IdentityRosterItem[];
  readonly onAssign: (
    identity: IdentityRosterItem | HumanIdentityResult,
    role: AssignableRole,
    justification: string,
    idempotencyKey: string,
  ) => Promise<void>;
}

export function DirectoryUserSearch({
  client,
  canManage,
  roster,
  rosterAvailable,
  rosterError,
  referencedUsers,
  onAssign,
}: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<readonly HumanIdentityResult[]>([]);
  const [filter, setFilter] = useState<RosterFilter>("all");
  const [searching, setSearching] = useState(false);
  const [pendingSubject, setPendingSubject] = useState<string | null>(null);
  const [assignmentDraft, setAssignmentDraft] = useState<{
    readonly identity: IdentityRosterItem | HumanIdentityResult;
    readonly role: AssignableRole;
  } | null>(null);
  const [justification, setJustification] = useState("");
  const [error, setError] = useState<string | null>(null);
  const assignmentIntent = useRef<MutationIntentIdentity | null>(null);
  const searchGeneration = useRef(0);

  useEffect(() => () => {
    searchGeneration.current += 1;
  }, []);

  if (!canManage) {
    return <LockedIamPanel message={t("settings.iam.usersOwnerOnly")} />;
  }

  const search = async (event: SubmitEvent) => {
    event.preventDefault();
    const generation = searchGeneration.current + 1;
    searchGeneration.current = generation;
    const submittedQuery = query.trim();
    setSearching(true);
    setError(null);
    try {
      const next = await client.searchIamUsers(submittedQuery);
      if (isCurrentDirectorySearch(searchGeneration.current, generation)) setResults(next);
    } catch (reason) {
      if (!isCurrentDirectorySearch(searchGeneration.current, generation)) return;
      setError(reason instanceof Error ? reason.message : String(reason));
      setResults([]);
    } finally {
      if (isCurrentDirectorySearch(searchGeneration.current, generation)) setSearching(false);
    }
  };

  const assign = async () => {
    if (assignmentDraft === null || justification.trim().length < 20) return;
    const { identity, role } = assignmentDraft;
    const normalizedJustification = justification.trim();
    const intent = identityForMutationIntent(
      assignmentIntent.current,
      JSON.stringify({
        provider: identity.provider,
        subjectId: identity.subjectId,
        role,
        justification: normalizedJustification,
      }),
    );
    assignmentIntent.current = intent;
    setPendingSubject(identity.subjectId);
    setError(null);
    try {
      await onAssign(identity, role, normalizedJustification, intent.idempotencyKey);
      assignmentIntent.current = null;
      if ("userType" in identity) setResults([]);
      setAssignmentDraft(null);
      setJustification("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setPendingSubject(null);
    }
  };

  const source = rosterAvailable ? roster : referencedUsers;
  const visibleRoster = source.filter(
    (item) => filter === "all" || item.principalType === filter,
  );

  return (
    <div class="settings-iam-panel settings-users-panel">
      <header class="settings-iam-panel-head">
        <div>
          <h3>{t("settings.iam.directoryRoster")}</h3>
          <p>{t("settings.iam.directoryRosterHint")}</p>
        </div>
        <div class="settings-roster-counts">
          <StatusPill kind="neutral" label={t("settings.iam.peopleCount", {
            count: source.filter((item) => item.principalType === "person").length,
          })} />
          <StatusPill kind="neutral" label={t("settings.iam.groupsCount", {
            count: source.filter((item) => item.principalType === "group").length,
          })} />
        </div>
      </header>

      <div class="settings-user-picker">
        <form class="settings-directory-search-form" onSubmit={search}>
          <label for="iam-user-search">{t("settings.iam.addByAlias")}</label>
          <div>
            <input
              id="iam-user-search"
              type="search"
              minLength={2}
              maxLength={128}
              required
              value={query}
              placeholder={t("settings.iam.aliasPlaceholder")}
              onInput={(event) => {
                searchGeneration.current += 1;
                setQuery(event.currentTarget.value);
                setResults([]);
                setSearching(false);
              }}
            />
            <button type="submit" disabled={searching}>
              {searching ? t("settings.iam.searching") : t("settings.iam.search")}
            </button>
          </div>
        </form>
        {results.length > 0 ? (
          <div class="settings-search-results">
            {results.map((identity) => (
              <div key={`${identity.provider}:${identity.subjectId}`}>
                <PrincipalLabel
                  displayName={identity.displayName}
                  secondary={identity.username}
                  type="person"
                />
                <RoleDropdown
                  label={t("settings.iam.selectRoleAndAdd")}
                  disabled={!identity.active || pendingSubject === identity.subjectId}
                  onSelect={(role) => setAssignmentDraft({ identity, role })}
                />
              </div>
            ))}
          </div>
        ) : null}
        {error ? <div class="error" role="alert">{error}</div> : null}
      </div>

      {assignmentDraft ? (
        <div class="settings-role-request-form" role="group" aria-label={t("settings.iam.roleRequest") }>
          <div>
            <strong>
              {assignmentDraft.identity.displayName} - {assignmentDraft.role}
            </strong>
            <small>{t("settings.iam.roleRequestHint")}</small>
          </div>
          <textarea
            minLength={20}
            maxLength={2000}
            value={justification}
            placeholder={t("settings.iam.roleRequestJustification")}
            onInput={(event) => setJustification(event.currentTarget.value)}
          />
          <div>
            <button
              type="button"
              disabled={justification.trim().length < 20 || pendingSubject !== null}
              onClick={() => { void assign(); }}
            >
              {t("settings.iam.submitRoleRequest")}
            </button>
            <button
              type="button"
              disabled={pendingSubject !== null}
              onClick={() => { setAssignmentDraft(null); setJustification(""); }}
            >
              {t("settings.iam.cancel")}
            </button>
          </div>
        </div>
      ) : null}

      {!rosterAvailable && rosterError ? (
        <div class="settings-roster-unavailable" role="status">
          {t("settings.iam.rosterUnavailable", { error: rosterError })}
        </div>
      ) : null}

      <div class="settings-roster-toolbar" role="group" aria-label={t("settings.iam.rosterFilter")}>
        {(["all", "person", "group"] as const).map((value) => (
          <button
            key={value}
            type="button"
            class={filter === value ? "is-active" : undefined}
            aria-pressed={filter === value}
            onClick={() => setFilter(value)}
          >
            {t(`settings.iam.rosterFilterValue.${value}`)}
          </button>
        ))}
      </div>

      <DataTable
        columns={[
          {
            key: "principal",
            header: t("settings.iam.principal"),
            render: (item: IdentityRosterItem) => (
              <PrincipalLabel
                displayName={item.displayName}
                secondary={item.username ?? item.subjectId}
                type={item.principalType}
              />
            ),
          },
          {
            key: "type",
            header: t("settings.iam.type"),
            render: (item: IdentityRosterItem) => (
              t(`settings.iam.principalType.${item.principalType}`)
            ),
          },
          {
            key: "roles",
            header: t("settings.iam.currentRoles"),
            render: (item: IdentityRosterItem) => (
              <span class="settings-role-list">
                {item.roles.map((role) => (
                  <StatusPill key={role} kind="neutral" label={role} />
                ))}
              </span>
            ),
          },
          {
            key: "change",
            header: t("settings.iam.changeRole"),
            render: (item: IdentityRosterItem) => (
              <RoleDropdown
                label={t("settings.iam.changeRole")}
                disabled={
                  item.principalType !== "person"
                  || !item.active
                  || pendingSubject === item.subjectId
                }
                onSelect={(role) => setAssignmentDraft({ identity: item, role })}
              />
            ),
          },
        ]}
        rows={visibleRoster}
        keyOf={(item) => `${item.provider}:${item.subjectId}`}
        empty={t("settings.iam.noRosterEntries")}
      />
    </div>
  );
}

function RoleDropdown({ label, disabled, onSelect }: {
  readonly label: string;
  readonly disabled: boolean;
  readonly onSelect: (role: AssignableRole) => void;
}) {
  return (
    <select
      class="settings-role-select"
      aria-label={label}
      disabled={disabled}
      value=""
      onChange={(event) => {
        const role = event.currentTarget.value as AssignableRole;
        if (role) onSelect(role);
      }}
    >
      <option value="">{label}</option>
      {ASSIGNABLE_ROLES.map((role) => <option key={role} value={role}>{role}</option>)}
    </select>
  );
}

function PrincipalLabel({ displayName, secondary, type }: {
  readonly displayName: string;
  readonly secondary: string;
  readonly type: "person" | "group";
}) {
  return (
    <span class="settings-principal-label">
      <span class="settings-principal-icon" aria-hidden="true">
        {type === "group" ? <GroupIcon /> : <PersonIcon />}
      </span>
      <span><strong>{displayName}</strong><small>{secondary}</small></span>
    </span>
  );
}

function LockedIamPanel({ message }: { readonly message: string }) {
  return (
    <div class="settings-locked-panel" role="alert">
      <LockIcon />
      <strong>{t("settings.iam.accessDenied")}</strong>
      <p>{message}</p>
    </div>
  );
}

function PersonIcon() {
  return <svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="3" /><path d="M5 20c0-4 3-7 7-7s7 3 7 7" /></svg>;
}

function GroupIcon() {
  return <svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="3" /><circle cx="17" cy="10" r="2" /><path d="M3 20c0-4 3-7 6-7s6 3 6 7M14 15c3 0 5 2 5 5" /></svg>;
}

function LockIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10" width="14" height="10" rx="2" /><path d="M8 10V7a4 4 0 0 1 8 0v3" /></svg>;
}
