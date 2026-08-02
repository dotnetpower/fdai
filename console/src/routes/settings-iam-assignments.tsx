import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import { DataTable, LoadingState, StatusPill } from "../components/ui";
import { t } from "../i18n";
import { identityForMutationIntent, type MutationIntentIdentity } from "../mutation-intent";
import {
  createAssignmentCase,
  reviewAssignmentCase,
  submitAssignmentCase,
} from "./settings-iam-assignments.command";
import {
  assignmentValidation,
  filterAssignments,
  type AssignmentCase,
  type AssignmentDraft,
  type AssignmentDuty,
  type AssignmentDutyBinding,
  type AssignmentFilters,
  type AssignmentProjectionItem,
  type AssignmentProjectionPage,
} from "./settings-iam-assignments.model";
import type { HumanIdentityResult, IamRole } from "./settings-iam.model";

const AGENTS = [
  "Odin", "Thor", "Forseti", "Huginn", "Heimdall", "Var", "Vidar", "Bragi",
  "Saga", "Mimir", "Norns", "Muninn", "Njord", "Freyr", "Loki",
] as const;
const ROLES: readonly Exclude<IamRole, "BreakGlass">[] = [
  "Reader", "Contributor", "Approver", "Owner",
];
const DUTIES: readonly AssignmentDuty[] = ["primary", "backup", "escalation"];
const EMPTY_FILTERS: AssignmentFilters = { query: "", role: "all", agent: "", coverage: "all" };

interface Props {
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
  readonly canManage: boolean;
  readonly principalOid: string;
}

export function SettingsIamAssignments({ client, auth, canManage, principalOid }: Props) {
  const [page, setPage] = useState<AssignmentProjectionPage | null>(null);
  const [loading, setLoading] = useState(canManage);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<AssignmentFilters>(EMPTY_FILTERS);
  const [selected, setSelected] = useState<AssignmentProjectionItem | null>(null);
  const generation = useRef(0);

  const load = async () => {
    const current = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const next = await client.listHumanAssignments();
      if (generation.current === current) setPage(next);
    } catch (reason) {
      if (generation.current === current) setError(message(reason));
    } finally {
      if (generation.current === current) setLoading(false);
    }
  };

  useEffect(() => {
    if (canManage) void load();
    return () => { generation.current += 1; };
  }, [canManage, client]);

  if (!canManage) return <AssignmentLocked />;
  if (loading && page === null) return <LoadingState label={t("settings.iam.assignmentsLoading")} />;
  if (error && page === null) return <div class="error" role="alert">{error}</div>;

  const items = filterAssignments(page?.items ?? [], filters);
  return (
    <div class="settings-assignment-workspace">
      <section class="settings-assignment-boundary" aria-label={t("settings.iam.observationTitle")}>
        <strong>{t("settings.iam.observationTitle")}</strong>
        <span>{t("settings.iam.observationCopy")}</span>
      </section>

      <section class="settings-iam-panel" aria-labelledby="assignment-roster-heading">
        <header class="settings-iam-panel-head">
          <div>
            <h3 id="assignment-roster-heading">{t("settings.iam.assignments")}</h3>
            <p>{t("settings.iam.assignmentsHint")}</p>
          </div>
          <StatusPill kind="neutral" label={t("settings.iam.assignmentCount", { count: page?.total ?? 0 })} />
        </header>
        {page?.caseProjectionTruncated ? (
          <div class="state-block state-unavailable" role="status">
            {t("settings.iam.assignmentProjectionTruncated")}
          </div>
        ) : null}
        <AssignmentFilterBar filters={filters} onChange={setFilters} />
        {error ? <div class="error" role="alert">{error}</div> : null}
        {items.length === 0 ? (
          <div class="state-block state-empty">{t("settings.iam.noAssignments")}</div>
        ) : <DataTable
          columns={[
            {
              key: "person",
              header: t("settings.iam.principal"),
              render: (item: AssignmentProjectionItem) => (
                <span class="assignment-principal">
                  <strong>{item.subject.displayName ?? t("settings.unavailable")}</strong>
                  <small>{item.subject.username ?? item.subject.subjectId}</small>
                </span>
              ),
            },
            {
              key: "role",
              header: t("settings.iam.role"),
              render: (item: AssignmentProjectionItem) => item.roles?.join(", ") ?? t("settings.iam.notObserved"),
            },
            {
              key: "duties",
              header: t("settings.iam.agentDuties"),
              render: (item: AssignmentProjectionItem) => item.duties.length
                ? item.duties.map((duty) => `${duty.agentName}: ${duty.duty ? t(`settings.iam.dutyValue.${duty.duty}`) : duty.responsibility}`).join(", ")
                : t("settings.iam.notObserved"),
            },
            {
              key: "coverage",
              header: t("settings.iam.coverage"),
              render: (item: AssignmentProjectionItem) => <CoveragePill item={item} />,
            },
            {
              key: "case",
              header: t("settings.iam.caseState"),
              render: (item: AssignmentProjectionItem) => item.assignmentCase ? assignmentStateLabel(item.assignmentCase) : t("settings.iam.notObserved"),
            },
            {
              key: "evidence",
              header: t("settings.iam.evidence"),
              render: (item: AssignmentProjectionItem) => (
                <button type="button" class="secondary" onClick={() => setSelected(item)}>
                  {t("settings.iam.viewEvidence")}
                </button>
              ),
            },
          ]}
          rows={items}
          keyOf={(item) => `${item.subject.provider}:${item.subject.subjectId}`}
          caption={t("settings.iam.assignmentTableCaption")}
        />}
      </section>

      <AssignmentEditor client={client} auth={auth} onCreated={load} />
      {selected ? (
        <AssignmentEvidence
          item={selected}
          auth={auth}
          client={client}
          principalOid={principalOid}
          onClose={() => setSelected(null)}
          onChanged={async () => { setSelected(null); await load(); }}
        />
      ) : null}
    </div>
  );
}

function AssignmentFilterBar({ filters, onChange }: {
  readonly filters: AssignmentFilters;
  readonly onChange: (next: AssignmentFilters) => void;
}) {
  return (
    <div class="settings-assignment-filters" role="group" aria-label={t("settings.iam.assignmentFilters")}>
      <input
        type="search"
        value={filters.query}
        placeholder={t("settings.iam.assignmentSearch")}
        aria-label={t("settings.iam.assignmentSearch")}
        onInput={(event) => onChange({ ...filters, query: event.currentTarget.value })}
      />
      <select aria-label={t("settings.iam.role")} value={filters.role} onChange={(event) => onChange({ ...filters, role: event.currentTarget.value as AssignmentFilters["role"] })}>
        <option value="all">{t("settings.iam.allRoles")}</option>
        {ROLES.map((role) => <option key={role} value={role}>{role}</option>)}
      </select>
      <select aria-label={t("settings.iam.agent")} value={filters.agent} onChange={(event) => onChange({ ...filters, agent: event.currentTarget.value })}>
        <option value="">{t("settings.iam.allAgents")}</option>
        {AGENTS.map((agent) => <option key={agent} value={agent}>{agent}</option>)}
      </select>
      <select aria-label={t("settings.iam.coverage")} value={filters.coverage} onChange={(event) => onChange({ ...filters, coverage: event.currentTarget.value as AssignmentFilters["coverage"] })}>
        {(["all", "covered", "gap", "unavailable"] as const).map((value) => (
          <option key={value} value={value}>{t(`settings.iam.coverageFilter.${value}`)}</option>
        ))}
      </select>
    </div>
  );
}

function AssignmentEditor({ client, auth, onCreated }: {
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
  readonly onCreated: () => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<readonly HumanIdentityResult[]>([]);
  const [draft, setDraft] = useState<AssignmentDraft>({
    identity: null,
    role: "Reader",
    duties: [{ agentName: "Odin", duty: "primary", scopeRef: "scope:platform" }],
    goalRefs: [],
    justification: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const intent = useRef<MutationIntentIdentity | null>(null);
  const issues = assignmentValidation(draft);

  const search = async () => {
    setBusy(true);
    setError(null);
    try { setResults(await client.searchIamUsers(query.trim())); }
    catch (reason) { setError(message(reason)); setResults([]); }
    finally { setBusy(false); }
  };

  const create = async () => {
    if (issues.length > 0) return;
    const mutation = identityForMutationIntent(intent.current, JSON.stringify(draft));
    intent.current = mutation;
    setBusy(true);
    setError(null);
    let createdCase: AssignmentCase | null = null;
    try {
      createdCase = await createAssignmentCase(
        auth,
        client.operatorApiBaseUrl,
        draft,
        mutation.idempotencyKey,
      );
      await submitAssignmentCase(auth, client.operatorApiBaseUrl, createdCase);
      intent.current = null;
      setDraft({ ...draft, identity: null, goalRefs: [], justification: "" });
      setResults([]);
      await onCreated();
    } catch (reason) {
      setError(createdCase
        ? t("settings.iam.assignmentCreatedNotSubmitted", { error: message(reason) })
        : message(reason));
    }
    finally { setBusy(false); }
  };

  return (
    <section class="settings-iam-panel settings-assignment-editor" aria-labelledby="assignment-editor-heading">
      <header class="settings-iam-panel-head">
        <div>
          <h3 id="assignment-editor-heading">{t("settings.iam.assignmentEditor")}</h3>
          <p>{t("settings.iam.assignmentEditorHint")}</p>
        </div>
      </header>
      <form class="assignment-editor-grid" onSubmit={(event) => { event.preventDefault(); void create(); }}>
        <fieldset>
          <legend>{t("settings.iam.identity")}</legend>
          <div class="assignment-inline-search">
            <input type="search" required minLength={2} maxLength={128} value={query} placeholder={t("settings.iam.assignmentSearch")} onInput={(event) => setQuery(event.currentTarget.value)} />
            <button type="button" disabled={busy || query.trim().length < 2} onClick={() => { void search(); }}>{t("settings.iam.search")}</button>
          </div>
          <div class="assignment-identity-results">
            {results.map((identity) => (
              <button key={identity.subjectId} type="button" disabled={!identity.active} class={draft.identity?.subjectId === identity.subjectId ? "is-selected" : undefined} onClick={() => setDraft({ ...draft, identity })}>
                <strong>{identity.displayName}</strong><small>{identity.username}</small>
              </button>
            ))}
          </div>
        </fieldset>
        <label>{t("settings.iam.requestedRole")}<select value={draft.role} onChange={(event) => setDraft({ ...draft, role: event.currentTarget.value as AssignmentDraft["role"] })}>{ROLES.map((role) => <option key={role}>{role}</option>)}</select></label>
        <fieldset>
          <legend>{t("settings.iam.agentDuties")}</legend>
          {draft.duties.map((duty, index) => <DutyRow key={index} duty={duty} onChange={(next) => setDraft({ ...draft, duties: draft.duties.map((item, itemIndex) => itemIndex === index ? next : item) })} onRemove={() => setDraft({ ...draft, duties: draft.duties.filter((_, itemIndex) => itemIndex !== index) })} />)}
          <button type="button" class="secondary" disabled={draft.duties.length >= 30} onClick={() => setDraft({ ...draft, duties: [...draft.duties, { agentName: "Odin", duty: "backup", scopeRef: "scope:platform" }] })}>{t("settings.iam.addDuty")}</button>
        </fieldset>
        <label>{t("settings.iam.handoverGoals")}<textarea maxLength={2000} placeholder={t("settings.iam.handoverGoalsHint")} onInput={(event) => setDraft({ ...draft, goalRefs: event.currentTarget.value.split(/[,\n]/).map((value) => value.trim()).filter(Boolean).slice(0, 20) })} /></label>
        <label>{t("settings.iam.justification")}<textarea required minLength={20} maxLength={2000} value={draft.justification} onInput={(event) => setDraft({ ...draft, justification: event.currentTarget.value })} /></label>
        <div class="assignment-validation" role="status">
          <strong>{t("settings.iam.validationSummary")}</strong>
          {issues.length === 0 ? <span>{t("settings.iam.validationReady")}</span> : <ul>{issues.map((issue) => <li key={issue}>{t(`settings.iam.validation.${issue}`)}</li>)}</ul>}
        </div>
        {error ? <div class="error" role="alert">{error}</div> : null}
        <button type="submit" disabled={busy || issues.length > 0}>{busy ? t("settings.iam.submitting") : t("settings.iam.createAssignmentCase")}</button>
      </form>
    </section>
  );
}

function DutyRow({ duty, onChange, onRemove }: { readonly duty: AssignmentDutyBinding; readonly onChange: (next: AssignmentDutyBinding) => void; readonly onRemove: () => void }) {
  return <div class="assignment-duty-row"><select aria-label={t("settings.iam.agent")} value={duty.agentName} onChange={(event) => onChange({ ...duty, agentName: event.currentTarget.value })}>{AGENTS.map((agent) => <option key={agent}>{agent}</option>)}</select><select aria-label={t("settings.iam.duty")} value={duty.duty} onChange={(event) => onChange({ ...duty, duty: event.currentTarget.value as AssignmentDuty })}>{DUTIES.map((value) => <option key={value} value={value}>{t(`settings.iam.dutyValue.${value}`)}</option>)}</select><input type="text" aria-label={t("settings.iam.scope")} value={duty.scopeRef} maxLength={256} onInput={(event) => onChange({ ...duty, scopeRef: event.currentTarget.value })} /><button type="button" class="secondary" onClick={onRemove} aria-label={t("settings.iam.removeDuty")}>×</button></div>;
}

function AssignmentEvidence({ item, auth, client, principalOid, onClose, onChanged }: { readonly item: AssignmentProjectionItem; readonly auth: AuthContext; readonly client: OperatorApiClient; readonly principalOid: string; readonly onClose: () => void; readonly onChanged: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const assignmentCase = item.assignmentCase;
  const decide = async (decision: "approve" | "reject") => {
    if (!assignmentCase) return;
    setBusy(true);
    setError(null);
    try { await reviewAssignmentCase(auth, client.operatorApiBaseUrl, assignmentCase, decision); await onChanged(); }
    catch (reason) { setError(message(reason)); }
    finally { setBusy(false); }
  };
  return <section class="settings-iam-panel assignment-evidence" aria-labelledby="assignment-evidence-heading"><header class="settings-iam-panel-head"><div><h3 id="assignment-evidence-heading">{t("settings.iam.evidenceDetails")}</h3><p>{item.subject.displayName ?? item.subject.subjectId}</p></div><button type="button" class="secondary" onClick={onClose}>{t("settings.iam.close")}</button></header><dl><dt>{t("settings.iam.caseState")}</dt><dd>{assignmentCase ? assignmentStateLabel(assignmentCase) : t("settings.iam.notObserved")}</dd><dt>{t("settings.iam.caseRevision")}</dt><dd>{assignmentCase?.revision ?? t("settings.iam.notObserved")}</dd><dt>{t("settings.iam.reviewEvidence")}</dt><dd>{assignmentCase?.reviews.length ?? 0}</dd><dt>{t("settings.iam.effectEvidence")}</dt><dd>{assignmentCase?.effectReceipts.map((receipt) => `${receipt.kind}: ${receipt.receiptRef}`).join(", ") || t("settings.iam.notObserved")}</dd><dt>{t("settings.iam.handoverEvidence")}</dt><dd>{item.handover.availability === "not_connected" ? t("settings.iam.notConnected") : item.handover.state}</dd></dl>{error ? <div class="error" role="alert">{error}</div> : null}{assignmentCase?.state === "pending_review" && canReviewAssignmentCase(assignmentCase.requesterRef, principalOid) ? <div class="assignment-review-actions"><button type="button" disabled={busy} onClick={() => { void decide("approve"); }}>{t("settings.iam.approve")}</button><button type="button" class="secondary" disabled={busy} onClick={() => { void decide("reject"); }}>{t("settings.iam.reject")}</button></div> : null}</section>;
}

function CoveragePill({ item }: { readonly item: AssignmentProjectionItem }) { const kind = item.coverage === null ? "neutral" : item.coverage.some((entry) => entry.primaryCount < 1 || entry.backupOrEscalationCount < 1) ? "warning" : "success"; const label = item.coverage === null ? t("settings.iam.notObserved") : kind === "warning" ? t("settings.iam.coverageGap") : t("settings.iam.covered"); return <StatusPill kind={kind} label={label} />; }
function AssignmentLocked() { return <section class="settings-iam-panel settings-locked-panel" role="alert"><strong>{t("settings.iam.accessDenied")}</strong><p>{t("settings.iam.assignmentsOwnerOnly")}</p></section>; }
function assignmentStateLabel(assignmentCase: AssignmentCase): string { return t(`settings.iam.assignmentState.${assignmentCase.state}`); }
export function canReviewAssignmentCase(requesterRef: string, principalOid: string): boolean {
  return requesterRef.trim().toLowerCase() !== principalOid.trim().toLowerCase();
}
function message(reason: unknown): string { return reason instanceof Error ? reason.message : String(reason); }
