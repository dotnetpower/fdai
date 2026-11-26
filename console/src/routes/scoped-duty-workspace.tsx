/** Structured ownership-only tooling inside Mapping reviews; no case list, polling or browser authority. */
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import { SelectField, TextInput, TextareaField } from "../components/form-controls";
import { AsyncBoundary, LoadingState, type AsyncState } from "../components/ui";
import { currentRoute, replaceRouteState, routeHref, ROUTE_STATE_EVENT } from "../router";
import { PANTHEON } from "./agents.model";
import { ScopedDutyApi } from "./scoped-duty-api";
import { scopedDutyText as text } from "./scoped-duty-copy";
import {
  ScopedDutyError, emptyScopedDutyDraft, isScopedDutyCaseId, isScopedDutyFresh,
  newScopedDutyBinding, scopedDutyControls, scopedDutyCreationFor, scopedDutyDraftIssues,
  scopedDutyInstant, type ScopedDutyBinding, type ScopedDutyCase, type ScopedDutyCaseRead,
  type ScopedDutyCatalog, type ScopedDutyCreation, type ScopedDutyDraft, type ScopedDutyErrorCode,
  type ScopedDutyIssue, type ScopedDutyKind, type ScopedDutyProjection, type ScopedDutyProposal,
  type ScopedDutyWindow,
} from "./scoped-duty-model";
import "./scoped-duty-workspace.css";

interface Props {
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
  readonly canManage: boolean;
  readonly principalOid: string;
}
type ReadState<T> = Exclude<AsyncState<T>, { status: "error" | "unavailable" }>
  | { readonly status: "failure"; readonly code: ScopedDutyErrorCode };
type ReadKind = "catalog" | "case" | "projection";
interface CommandAttempt {
  readonly caseId: string;
  readonly revision: number;
  readonly decision: "approve" | "reject" | null;
  readonly digest: string;
}
const DUTIES = ["primary", "backup", "escalation"] as const;
const KINDS: readonly ScopedDutyKind[] = ["user", "group", "schedule"];

/** Reset all private input/results when the authenticated client, principal or capability changes. */
export function ScopedDutyWorkspace(props: Props) {
  const sequence = useRef(0);
  const accountId = props.auth.account?.homeAccountId, localId = props.auth.account?.localAccountId;
  const version = useMemo(() => ++sequence.current,
    [props.client, props.auth, props.principalOid, props.canManage, accountId, localId]);
  if (!props.canManage) return <section class="scoped-duty-workspace state-block state-unavailable"><p>{text("ownerOnly")}</p></section>;
  return <ScopedDutySession key={version} {...props} contextCurrent={() => sequence.current === version
    && props.auth.account?.homeAccountId === accountId && props.auth.account?.localAccountId === localId} />;
}

function ScopedDutySession({ client, canManage, principalOid, contextCurrent }: Props & { readonly contextCurrent: () => boolean }) {
  const api = useMemo(() => new ScopedDutyApi(client), [client]);
  const initial = useMemo(routeSelection, []);
  const [catalogState, setCatalogState] = useState<ReadState<ScopedDutyCatalog>>({ status: "loading" });
  const [caseState, setCaseState] = useState<ReadState<ScopedDutyCaseRead>>(initial.value && !initial.invalid ? { status: "loading" } : { status: "idle" });
  const [projectionState, setProjectionState] = useState<ReadState<ScopedDutyProjection>>({ status: "idle" });
  const [draft, setDraft] = useState<ScopedDutyDraft>(emptyScopedDutyDraft);
  const [caseInput, setCaseInput] = useState(initial.value);
  const [caseId, setCaseId] = useState(initial.invalid ? "" : initial.value);
  const [badCaseId, setBadCaseId] = useState(initial.invalid);
  const [agent, setAgent] = useState(PANTHEON[0]!.name);
  const [scope, setScope] = useState("");
  const [busy, setBusy] = useState(false);
  const [createError, setCreateError] = useState<ScopedDutyErrorCode | null>(null);
  const [commandError, setCommandError] = useState<ScopedDutyErrorCode | null>(null);
  const [createdFingerprint, setCreatedFingerprint] = useState<string | null>(null);
  const [proposal, setProposal] = useState<ScopedDutyProposal | null>(null);
  const [command, setCommand] = useState<CommandAttempt | null>(null);
  const alive = useRef(true), writing = useRef(false);
  const selected = useRef(caseId), selectionEpoch = useRef(0);
  const generations = useRef<Record<ReadKind, number>>({ catalog: 0, case: 0, projection: 0 });
  const controllers = useRef(new Map<ReadKind | "write", AbortController>());
  const pinned = useRef<ScopedDutyCaseRead | undefined>(undefined);
  const creation = useRef<ScopedDutyCreation | null>(null);
  const pendingCommand = useRef<CommandAttempt | null>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const refreshCaseButton = useRef<HTMLButtonElement>(null);
  const catalog = catalogState.status === "ready" ? catalogState.data : null;
  const current = caseState.status === "ready" ? caseState.data : null;
  const now = useObservationClock(catalog, projectionState.status === "ready" ? projectionState.data : null);
  const issues = scopedDutyDraftIssues(draft, catalog, now);
  const controls = scopedDutyControls(current, catalog, principalOid, canManage, now);
  const valid = () => alive.current && contextCurrent();

  const read = async <T,>(kind: ReadKind, operation: (signal: AbortSignal) => Promise<T>,
    publish: (state: ReadState<T>) => void, accept?: (value: T) => void) => {
    if (!valid()) return;
    controllers.current.get(kind)?.abort();
    const controller = new AbortController(), generation = ++generations.current[kind];
    const epoch = selectionEpoch.current;
    controllers.current.set(kind, controller);
    const owns = () => valid() && generations.current[kind] === generation
      && (kind === "catalog" || selectionEpoch.current === epoch);
    publish({ status: "loading" });
    try {
      const value = await operation(controller.signal);
      if (owns()) { publish({ status: "ready", data: value }); accept?.(value); }
    } catch (error) {
      if (owns()) publish({ status: "failure", code: errorCode(error) });
    } finally {
      if (controllers.current.get(kind) === controller) controllers.current.delete(kind);
    }
  };
  const loadCatalog = () => read("catalog", (signal) => api.catalog(signal), setCatalogState, (value) => {
    setDraft((previous) => previous.request.source_revision !== "" ? previous
      : { ...previous, request: { ...previous.request, source_revision: value.source_revision } });
  });
  const loadCase = (id: string) => read("case", (signal) => api.getCase(id, signal, pinned.current), setCaseState, (value) => {
    pinned.current = value;
    if (value.state !== "awaiting_core" && (!pendingCommand.current || value.revision > pendingCommand.current.revision)) {
      pendingCommand.current = null;
      setCommand(null); setCommandError(null); setProposal(null);
    }
  });
  const resetSelection = (id: string) => {
    selectionEpoch.current += 1;
    returnFocus.current = null;
    for (const kind of ["case", "projection", "write"] as const) controllers.current.get(kind)?.abort();
    selected.current = id; setCaseId(id); pinned.current = undefined;
    pendingCommand.current = null; setCommand(null); setProposal(null); setCommandError(null);
    setCaseState({ status: "idle" }); setProjectionState({ status: "idle" });
  };
  const openCase = (id: string, updateUrl = true) => {
    if (!isScopedDutyCaseId(id)) { setBadCaseId(true); document.getElementById("scoped-case-id")?.focus(); return; }
    setBadCaseId(false); setCaseInput(id);
    if (selected.current !== id) resetSelection(id);
    if (updateUrl) rememberCase(id);
    void loadCase(id);
  };

  useLayoutEffect(() => {
    alive.current = true;
    void loadCatalog();
    if (initial.value && !initial.invalid) void loadCase(initial.value);
    const onRoute = () => {
      const next = routeSelection();
      if (next.value === selected.current && !next.invalid) return;
      resetSelection(""); setCaseInput(next.value); setBadCaseId(next.invalid);
      if (next.value && !next.invalid) openCase(next.value, false);
    };
    window.addEventListener("popstate", onRoute);
    window.addEventListener("fdai:route-changed", onRoute);
    window.addEventListener(ROUTE_STATE_EVENT, onRoute);
    return () => {
      alive.current = false;
      for (const controller of controllers.current.values()) controller.abort();
      window.removeEventListener("popstate", onRoute);
      window.removeEventListener("fdai:route-changed", onRoute);
      window.removeEventListener(ROUTE_STATE_EVENT, onRoute);
    };
  }, [api]);

  useLayoutEffect(() => {
    const origin = returnFocus.current;
    if (busy || !origin) return;
    returnFocus.current = null;
    if (document.activeElement === document.body || document.activeElement === origin) {
      if (origin.isConnected && !origin.matches(":disabled")) origin.focus();
      else if (refreshCaseButton.current && !refreshCaseButton.current.disabled) refreshCaseButton.current.focus();
      else document.getElementById("scoped-catalog")?.focus();
    }
  }, [busy]);

  const changeDraft = (next: ScopedDutyDraft) => {
    if (writing.current || JSON.stringify(draft) === JSON.stringify(next)) return;
    creation.current = null; setCreatedFingerprint(null); setCreateError(null); setDraft(next);
  };
  const write = async (operation: (signal: AbortSignal) => Promise<ScopedDutyProposal>,
    accept: (value: ScopedDutyProposal) => void, fail: (code: ScopedDutyErrorCode | null) => void, begin?: () => void) => {
    if (!valid() || writing.current || !canManage || !isScopedDutyFresh(catalog, Date.now())) return;
    const origin = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    writing.current = true; setBusy(true); fail(null); begin?.();
    generations.current.case += 1;
    controllers.current.get("case")?.abort();
    setCaseState((previous) => previous.status === "loading" ? { status: "idle" } : previous);
    const controller = new AbortController(), epoch = selectionEpoch.current;
    controllers.current.set("write", controller);
    // This deadline only lowers eligibility. It never renews the server observation window.
    const expiry = window.setTimeout(() => controller.abort(), Math.max(0, scopedDutyInstant(catalog!.expires_at) - Date.now()));
    try {
      const value = await operation(controller.signal);
      if (valid() && selectionEpoch.current === epoch) { accept(value); returnFocus.current = origin; }
    } catch (error) {
      if (valid() && selectionEpoch.current === epoch) {
        fail(errorCode(error));
        returnFocus.current = origin;
        if (error instanceof ScopedDutyError && ["conflict", "denied", "unauthorized"].includes(error.code)) {
          setCaseState({ status: "failure", code: error.code });
        }
      }
    } finally {
      window.clearTimeout(expiry);
      if (controllers.current.get("write") === controller) controllers.current.delete("write");
      writing.current = false;
      if (valid()) setBusy(false);
    }
  };
  const create = async () => {
    if (writing.current || scopedDutyDraftIssues(draft, catalog, Date.now()).length > 0) return;
    let intent: ScopedDutyCreation;
    try { intent = scopedDutyCreationFor(creation.current, draft); }
    catch (error) { setCreateError(errorCode(error)); return; }
    creation.current = intent;
    await write((signal) => api.create(intent, signal), (value) => {
      resetSelection(value.case_id); setCaseInput(value.case_id); setBadCaseId(false);
      // An expected creation request fences the next GET; it is not rendered as a Core case.
      pinned.current = { case_id: value.case_id, state: "awaiting_core", revision: null,
        request: draft.request, execution_authority: false };
      rememberCase(value.case_id); setProposal(value); setCreatedFingerprint(intent.fingerprint);
    }, setCreateError);
  };
  const sendCommand = async (attempt: CommandAttempt) => {
    if (writing.current || selected.current !== attempt.caseId || !current
      || current.state === "awaiting_core" || current.revision !== attempt.revision) return;
    const eligible = scopedDutyControls(current, catalog, principalOid, canManage, Date.now());
    if (!(attempt.decision === null ? eligible.submit : eligible.review)) return;
    await write((signal) => attempt.decision === null
      ? api.submit(attempt.caseId, attempt.revision, signal)
      : api.review(attempt.caseId, attempt.revision, attempt.decision, attempt.digest, signal),
    setProposal, setCommandError, () => { pendingCommand.current = attempt; setCommand(attempt); });
  };
  const decide = (decision: "approve" | "reject" | null) => {
    if (!current || current.state === "awaiting_core" || pendingCommand.current) return;
    const eligible = scopedDutyControls(current, catalog, principalOid, canManage, Date.now());
    if (!(decision === null ? eligible.submit : eligible.review)) return;
    void sendCommand({ caseId: current.case_id, revision: current.revision, decision, digest: current.plan.digest });
  };
  const changeObservation = (nextAgent: string, nextScope: string) => {
    generations.current.projection += 1; controllers.current.get("projection")?.abort();
    setAgent(nextAgent); setScope(nextScope); setProjectionState({ status: "idle" });
  };

  return <section class="scoped-duty-workspace" aria-labelledby="scoped-duty-title">
    <header><h3 id="scoped-duty-title" class="cs-type-section-title">{text("title")}</h3><p>{text("subtitle")}</p></header>
    <p class="scoped-duty-boundary">{text("boundary")}</p>
    <section aria-labelledby="scoped-catalog-title">
      <div class="scoped-duty-heading"><h4 id="scoped-catalog-title" tabIndex={-1}>{text("catalog")}</h4>
        <button id="scoped-catalog" type="button" class="cs-control-button" disabled={busy || catalogState.status === "loading"} onClick={() => void loadCatalog()}>{text("refreshCatalog")}</button></div>
      <AsyncBoundary state={boundaryState(catalogState)} resourceLabel={text("catalog")}>
        {(value) => <><WindowEvidence value={value} now={now} /><p>{text(value.artifact_delivery_available ? "deliveryAvailable" : "deliveryUnavailable")}</p></>}
      </AsyncBoundary>
    </section>
    <DraftEditor draft={draft} catalog={catalog} now={now} busy={busy} issues={issues}
      error={createError} accepted={createdFingerprint === JSON.stringify(draft)} onChange={changeDraft} onCreate={() => void create()} />
    {busy ? <LoadingState label={text("busy")} /> : null}
    <section aria-labelledby="scoped-case-title">
      <h4 id="scoped-case-title">{text("caseTitle")}</h4><p>{text("caseHint")}</p>
      <form class="scoped-duty-inline" onSubmit={(event) => { event.preventDefault(); if (!writing.current) openCase(caseInput); }}>
        <TextInput
          id="scoped-case-id"
          label={text("caseId")}
          value={caseInput}
          maxLength={41}
          autoComplete="off"
          mono
          disabled={busy}
          {...(badCaseId ? { error: text("invalidCaseId") } : {})}
          onInput={(next) => { resetSelection(""); setCaseInput(next); setBadCaseId(false); }}
        />
        <button type="submit" class="cs-control-button" disabled={busy || !caseInput}>{text("openCase")}</button>
        <button ref={refreshCaseButton} type="button" class="cs-control-button" disabled={busy || !caseId || caseState.status === "loading"} onClick={() => void loadCase(caseId)}>{text("refreshCase")}</button>
      </form>
      {caseId ? <a class="scoped-duty-link" href={routeHref("handover", { segments: ["mapping-reviews"], params: { scoped_case: caseId } })}>{text("caseLink")}</a> : null}
      {proposal ? <div class="scoped-duty-notice" role="status"><p>{text("accepted")}</p><code>{proposal.case_id}</code><time dateTime={proposal.accepted_at}>{proposal.accepted_at}</time></div> : null}
      <AsyncBoundary state={boundaryState(caseState)} resourceLabel={text("caseTitle")} idle={proposal ? null : <p>{text("caseEmpty")}</p>}>
        {(value) => <><dl class="scoped-duty-facts"><dt>{text("state")}</dt><dd>{text(`state.${value.state}`)}</dd></dl>
          {value.state === "awaiting_core" ? <p>{text("awaitingCase")}</p> : <CaseEvidence value={value} />}</>}
      </AsyncBoundary>
      {command ? <div class="scoped-duty-notice"><p role="status">{text("commandPending")}</p>
        {commandError ? <button type="button" class="cs-control-button" disabled={busy || !isScopedDutyFresh(catalog, now)
          || current?.revision !== command.revision || !(command.decision === null ? controls.submit : controls.review)}
          onClick={() => void sendCommand(command)}>{text("retryCommand")}</button> : null}</div> : null}
      {commandError ? <p class="cs-control-error" role="alert">{text(`error.${commandError}`)}</p> : null}
      {current && current.state !== "awaiting_core" ? <div class="scoped-duty-actions">
        {controls.reason ? <p>{text(`control.${controls.reason}`)}</p> : null}
        {current.state === "draft" ? <button type="button" class="cs-control-button is-primary" disabled={busy || command !== null || !controls.submit} onClick={() => decide(null)}>{text("submit")}</button> : null}
        {current.state === "pending_review" ? <><button type="button" class="cs-control-button is-primary" disabled={busy || command !== null || !controls.review} onClick={() => decide("approve")}>{text("approve")}</button>
          <button type="button" class="cs-control-button" disabled={busy || command !== null || !controls.review} onClick={() => decide("reject")}>{text("reject")}</button></> : null}
      </div> : null}
    </section>
    <section aria-labelledby="scoped-observation-title"><h4 id="scoped-observation-title">{text("observationTitle")}</h4>
      <form class="scoped-duty-grid" onSubmit={(event) => {
        event.preventDefault();
        if (!writing.current && isScopedDutyFresh(catalog, Date.now()) && catalog?.scopes.includes(scope)) {
          void read("projection", (signal) => api.projection(agent, scope, signal), setProjectionState);
        }
      }}>
        <SelectField
          id="scoped-observation-agent"
          label={text("agent")}
          disabled={busy}
          value={agent}
          options={PANTHEON.map((item) => ({ value: item.name, label: item.name }))}
          onChange={(next) => changeObservation(next, scope)}
        />
        <ScopeSelect
          id="scoped-observation-scope"
          label={text("scope")}
          value={scope}
          catalog={catalog}
          disabled={busy}
          onChange={(value) => changeObservation(agent, value)}
        />
        <button class="cs-control-button" type="submit" disabled={busy || projectionState.status === "loading" || !isScopedDutyFresh(catalog, now) || !catalog?.scopes.includes(scope)}>{text("readObservation")}</button>
      </form>
      <AsyncBoundary state={boundaryState(projectionState)} resourceLabel={text("observationTitle")} idle={<p>{text("observationEmpty")}</p>}>
        {(value) => <ProjectionEvidence value={value} now={now} catalog={catalog} />}
      </AsyncBoundary>
    </section>
  </section>;
}

function DraftEditor({ draft, catalog, now, busy, issues, error, accepted, onChange, onCreate }: {
  readonly draft: ScopedDutyDraft; readonly catalog: ScopedDutyCatalog | null; readonly now: number;
  readonly busy: boolean; readonly issues: readonly ScopedDutyIssue[]; readonly error: ScopedDutyErrorCode | null;
  readonly accepted: boolean; readonly onChange: (value: ScopedDutyDraft) => void; readonly onCreate: () => void;
}) {
  const [touched, setTouched] = useState(false);
  const visibleIssues = touched ? issues : [];
  const update = (next: ScopedDutyDraft) => { setTouched(true); onChange(next); };
  const changeBinding = (index: number, next: ScopedDutyBinding) => update({ ...draft,
    request: { ...draft.request, bindings: draft.request.bindings.map((row, at) => at === index ? next : row) } });
  return <section aria-labelledby="scoped-draft-title"><h4 id="scoped-draft-title">{text("createTitle")}</h4><p>{text("createHint")}</p>
    <form onSubmit={(event) => { event.preventDefault(); setTouched(true); if (!busy) onCreate(); }} autoComplete="off">
      <fieldset disabled={busy}><legend class="sr-only">{text("createTitle")}</legend>
        <div id="scoped-source_revision" tabIndex={-1} {...issueAttributes(visibleIssues, "source_revision")}><strong>{text("sourceRevision")}</strong><code>{draft.request.source_revision || text("notRecorded")}</code></div>
        {catalog && catalog.source_revision !== draft.request.source_revision ? <div class="scoped-duty-notice"><p>{text("sourceChanged")}</p>
          <button type="button" class="cs-control-button" disabled={!isScopedDutyFresh(catalog, now)} onClick={() => update({ ...draft, request: { ...draft.request, source_revision: catalog.source_revision } })}>{text("useCatalog")}</button></div> : null}
        <p id="scoped-subject-help">{text("subjectHint")}</p><p id="scoped-time-help">{text("timeHint")}</p>
        <div id="scoped-bindings" tabIndex={-1} {...issueAttributes(visibleIssues, "bindings")}>{draft.request.bindings.map((row, index) => <BindingEditor key={index} value={row} index={index} catalog={catalog}
          issues={visibleIssues} onChange={(next) => changeBinding(index, next)} onRemove={() => {
            update({ ...draft, request: { ...draft.request, bindings: draft.request.bindings.filter((_, at) => at !== index) } });
            queueMicrotask(() => document.getElementById("scoped-add-binding")?.focus());
          }} />)}</div>
        <button id="scoped-add-binding" class="cs-control-button" type="button" disabled={draft.request.bindings.length >= 30} onClick={() => {
          update({ ...draft, request: { ...draft.request, bindings: [...draft.request.bindings, newScopedDutyBinding()] } });
          queueMicrotask(() => document.getElementById(`scoped-binding-${draft.request.bindings.length}-agent_name`)?.focus());
        }}>{text("addBinding")}</button>
        <TextInput
          id="scoped-supersedes"
          label={text("supersedes")}
          value={draft.request.supersedes_case_id ?? ""}
          maxLength={36}
          mono
          hint={text("supersedesHint")}
          {...errorProp(firstIssueText(visibleIssues, "supersedes"))}
          onInput={(next) => update({ ...draft, request: { ...draft.request, supersedes_case_id: next || null } })}
        />
        <TextareaField
          id="scoped-justification"
          label={text("justification")}
          required
          maxLength={2000}
          showCounter
          value={draft.justification}
          {...errorProp(firstIssueText(visibleIssues, "justification"))}
          onInput={(next) => update({ ...draft, justification: next })}
        />
        <p>{text("noSecrets")}</p>
        {touched && issues.length > 0 ? <div class="scoped-duty-validation" role="status"><strong>{text("validation")}</strong><ul>{issues.map((issue, index) => {
          const label = text(`issue.${issue.code}`);
          return <li key={index} id={`scoped-issue-${index}`}><a href={`#${issueTarget(issue)}`} onClick={(event) => { event.preventDefault(); document.getElementById(issueTarget(issue))?.focus(); }}>
            {issue.binding === null ? label : text("bindingIssue", { number: issue.binding + 1, message: label })}</a></li>;
        })}</ul></div> : null}
        {error ? <div role="alert"><p class="cs-control-error">{text(`error.${error}`)}</p><p>{text("createUncertain")}</p></div> : null}
        <button class="cs-control-button is-primary" type="submit" disabled={busy || issues.length > 0 || accepted}>{text(error ? "retryCreate" : "create")}</button>
      </fieldset>
    </form>
  </section>;
}

function BindingEditor({ value, index, catalog, issues, onChange, onRemove }: {
  readonly value: ScopedDutyBinding; readonly index: number; readonly catalog: ScopedDutyCatalog | null;
  readonly issues: readonly ScopedDutyIssue[]; readonly onChange: (value: ScopedDutyBinding) => void; readonly onRemove: () => void;
}) {
  const id = (field: string) => `scoped-binding-${index}-${field}`;
  return <fieldset class="scoped-duty-binding"><legend>{text("binding", { number: index + 1 })}</legend><div class="scoped-duty-grid">
    <SelectField
      id={id("agent_name")}
      label={text("agent")}
      value={value.agent_name}
      {...errorProp(firstIssueText(issues, "agent_name", index))}
      options={PANTHEON.map((agent) => ({ value: agent.name, label: agent.name }))}
      onChange={(next) => onChange({ ...value, agent_name: next })}
    />
    <ScopeSelect
      id={id("scope_ref")}
      label={text("scope")}
      value={value.scope_ref}
      catalog={catalog}
      {...errorProp(firstIssueText(issues, "scope_ref", index))}
      onChange={(scope) => onChange({ ...value, scope_ref: scope })}
    />
    <SelectField
      id={id("kind")}
      label={text("kind")}
      value={value.subject.kind}
      options={KINDS.map((kind) => ({ value: kind, label: text(`kind.${kind}`) }))}
      onChange={(next) => {
        const kind = next as ScopedDutyKind;
        onChange({ ...value, subject: { kind, ref: value.subject.ref }, fallback: kind === "schedule" ? { kind: "user", ref: "" } : null });
      }}
    />
    <TextInput
      id={id("subject_ref")}
      label={text("subjectRef")}
      required
      maxLength={256}
      mono
      value={value.subject.ref}
      {...errorProp(firstIssueText(issues, "subject_ref", index))}
      onInput={(next) => onChange({ ...value, subject: { ...value.subject, ref: next } })}
    />
    <SelectField
      id={id("duty")}
      label={text("duty")}
      value={value.duty}
      {...errorProp(firstIssueText(issues, "duty", index))}
      options={DUTIES.map((duty) => ({ value: duty, label: text(`duty.${duty}`) }))}
      onChange={(next) => onChange({ ...value, duty: next as ScopedDutyBinding["duty"] })}
    />
    {(["effective_from", "effective_until"] as const).map((field) => (
      <TextInput
        key={field}
        id={id(field)}
        label={text(field === "effective_from" ? "effectiveFrom" : "effectiveUntil")}
        required
        maxLength={40}
        mono
        value={value[field]}
        placeholder="YYYY-MM-DDTHH:mm:ssZ"
        {...errorProp(firstIssueText(issues, field, index))}
        onInput={(next) => onChange({ ...value, [field]: next })}
      />
    ))}
    {value.subject.kind === "schedule" ? (
      <TextInput
        id={id("fallback")}
        label={text("fallback")}
        required
        maxLength={256}
        mono
        value={value.fallback?.ref ?? ""}
        hint={text("fallbackHint")}
        {...errorProp(firstIssueText(issues, "fallback", index))}
        onInput={(next) => onChange({ ...value, fallback: { kind: "user", ref: next } })}
      />
    ) : null}
  </div><button type="button" class="cs-control-button" onClick={onRemove}>{text("removeBinding", { number: index + 1 })}</button></fieldset>;
}

function errorProp(error: string | undefined): { readonly error: string } | Record<never, never> {
  return error !== undefined ? { error } : {};
}

function firstIssueText(
  issues: readonly ScopedDutyIssue[],
  field: string,
  binding: number | null = null,
): string | undefined {
  const matched = issues.find((issue) => issue.field === field && issue.binding === binding);
  return matched ? text(`issue.${matched.code}`) : undefined;
}

function ScopeSelect({ id, label, value, catalog, disabled = false, error, onChange }: {
  readonly id: string; readonly label: string; readonly value: string; readonly catalog: ScopedDutyCatalog | null;
  readonly disabled?: boolean; readonly error?: string; readonly onChange: (value: string) => void;
}) {
  const options = [
    { value: "", label: text("chooseScope") },
    ...(value && !catalog?.scopes.includes(value) ? [{ value, label: text("scopeUnlisted"), disabled: true }] : []),
    ...(catalog?.scopes.map((scope) => ({ value: scope, label: scope })) ?? []),
  ];
  return (
    <div class="cs-field">
      <SelectField
        id={id}
        label={label}
        required
        value={value}
        disabled={disabled || catalog === null}
        {...errorProp(error)}
        options={options}
        onChange={onChange}
      />
      {value ? <code id={`${id}-exact`}>{value}</code> : null}
    </div>
  );
}
function WindowEvidence({ value, now }: { readonly value: ScopedDutyWindow; readonly now: number }) {
  return <><dl class="scoped-duty-facts"><dt>{text("sourceRevision")}</dt><dd><code>{value.source_revision}</code></dd>
    <dt>{text("observedAt")}</dt><dd><time dateTime={value.observed_at}>{value.observed_at}</time></dd>
    <dt>{text("expiresAt")}</dt><dd><time dateTime={value.expires_at}>{value.expires_at}</time></dd></dl>
    {!isScopedDutyFresh(value, now) ? <p role="status">{text("expired")}</p> : null}</>;
}
function CaseEvidence({ value }: { readonly value: ScopedDutyCase }) {
  return <><dl class="scoped-duty-facts"><dt>{text("coreCaseId")}</dt><dd><code>{value.core_case_id}</code></dd>
    <dt>{text("revision")}</dt><dd>{value.revision}</dd><dt>{text("requester")}</dt><dd><code>{value.requester_ref}</code></dd>
    <dt>{text("sourceRevision")}</dt><dd><code>{value.request.source_revision}</code></dd>
    <dt>{text("planAt")}</dt><dd><time dateTime={value.plan.checked_at}>{value.plan.checked_at}</time></dd>
    <dt>{text("planDigest")}</dt><dd><code>{value.plan.digest}</code></dd>
    <dt>{text("pr")}</dt><dd><ArtifactReference value={value.pr_ref} /></dd>
    <dt>{text("candidateDigest")}</dt><dd><code>{value.candidate_digest ?? text("notRecorded")}</code></dd>
    <dt>{text("merge")}</dt><dd><code>{value.merge_commit_sha ?? text("notRecorded")}</code></dd></dl>
    <p>{text(value.plan.current_coverage ? "planObserved" : "planHeld")}</p><p>{text("planHistoric")}</p>
    <h5>{text("reviews", { count: value.reviews.length })}</h5><p>{text("reviewsHint")}</p>
    {value.reviews.length === 0 ? <p>{text("noReviews")}</p> : <ol class="scoped-duty-reviews">{value.reviews.map((review) => <li key={review.reviewer_ref}>
      <code>{review.reviewer_ref}</code><span>{text(`decision.${review.decision}`)}</span><time dateTime={review.reviewed_at}>{review.reviewed_at}</time>
      <code>{review.plan_digest}</code></li>)}</ol>}
    <details><summary>{text("retainedEvidence")}</summary><pre>{JSON.stringify({ request: value.request, plan: value.plan }, null, 2)}</pre></details>
  </>;
}
function ArtifactReference({ value }: { readonly value: string | null }) {
  let href: string | null = null;
  if (value) {
    try { const url = new URL(value); if (url.protocol === "https:" && !url.username && !url.password) href = url.href; }
    catch { href = null; }
  }
  return href ? <a class="scoped-duty-link" href={href} target="_blank" rel="noopener noreferrer">{value}</a> : <code>{value ?? text("notRecorded")}</code>;
}
function ProjectionEvidence({ value, now, catalog }: { readonly value: ScopedDutyProjection; readonly now: number; readonly catalog: ScopedDutyCatalog | null }) {
  return <div class="scoped-duty-observation"><p><strong>{text(`observation.${value.state}`)}</strong></p><p>{text("observationHint")}</p>
    <WindowEvidence value={value} now={now} />
    {catalog && catalog.source_revision !== value.source_revision ? <p role="status">{text("control.source_revision")}</p> : null}
    <dl class="scoped-duty-facts"><dt>{text("agent")}</dt><dd>{value.agent_name}</dd><dt>{text("scope")}</dt><dd><code>{value.scope_ref}</code></dd>
      {DUTIES.map((duty) => <><dt key={`${duty}-label`}>{text(`duty.${duty}`)}</dt><dd key={duty}>{value[`${duty}_refs`].join(", ") || text("notRecorded")}</dd></>)}
      <dt>{text("partial")}</dt><dd>{text(value.partial ? "yes" : "no")}</dd><dt>{text("invalidCases")}</dt><dd>{value.invalid_cases}</dd></dl>
    {value.held_reasons.length > 0 ? <details open><summary>{text("heldReasons")}</summary><ul>{value.held_reasons.map((reason) => <li key={reason}><code>{reason}</code></li>)}</ul></details> : null}
    {value.artifact ? <details><summary>{text("observationEvidence")}</summary><ArtifactReference value={value.artifact.pr_ref} /><pre>{JSON.stringify(value.artifact, null, 2)}</pre></details> : null}
  </div>;
}
function errorCode(error: unknown): ScopedDutyErrorCode {
  return error instanceof ScopedDutyError ? error.code : "network";
}
function boundaryState<T>(state: ReadState<T>): AsyncState<T> {
  if (state.status !== "failure") return state;
  return { status: ["unavailable", "not_found"].includes(state.code) ? "unavailable" : "error", message: text(`error.${state.code}`) };
}
function issueTarget(issue: ScopedDutyIssue): string {
  if (issue.field === "catalog") return "scoped-catalog-title";
  return issue.binding === null ? `scoped-${issue.field}` : `scoped-binding-${issue.binding}-${issue.field}`;
}
/** Describe the same visible corrections at their input without replacing existing help. */
function issueAttributes(issues: readonly ScopedDutyIssue[], field: string, binding: number | null = null, help?: string) {
  const ids = issues.flatMap((issue, index) => issue.field === field && issue.binding === binding ? [`scoped-issue-${index}`] : []);
  return { "aria-invalid": ids.length > 0, "aria-describedby": [help, ...ids].filter(Boolean).join(" ") || undefined };
}
function routeSelection(): { readonly value: string; readonly invalid: boolean } {
  const values = currentRoute().search.getAll("scoped_case"), value = values[0] ?? "";
  return { value, invalid: values.length > 1 || (value !== "" && !isScopedDutyCaseId(value)) };
}
function rememberCase(id: string): void {
  const route = currentRoute(), search = new URLSearchParams(route.search);
  search.set("scoped_case", id);
  replaceRouteState(`${route.pathname}?${search}`);
}
/** One-shot expiry and browser-resume repaint only. This hook never fetches or renews evidence. */
function useObservationClock(catalog: ScopedDutyWindow | null, projection: ScopedDutyWindow | null): number {
  const [, render] = useState(0);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const resume = () => {
      if (timer !== undefined) clearTimeout(timer);
      render((value) => value + 1);
      const now = Date.now();
      const deadlines = [catalog, projection].flatMap((item) => item && isScopedDutyFresh(item, now)
        ? [scopedDutyInstant(item.expires_at)] : []);
      if (deadlines.length > 0) timer = setTimeout(resume, Math.min(...deadlines) - now + 1);
    };
    resume(); window.addEventListener("focus", resume); document.addEventListener("visibilitychange", resume);
    return () => { if (timer !== undefined) clearTimeout(timer); window.removeEventListener("focus", resume); document.removeEventListener("visibilitychange", resume); };
  }, [catalog, projection]);
  return Date.now();
}
