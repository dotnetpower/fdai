import { useLayoutEffect, useMemo, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { fetchHandoverGoal, reviewHandoverGoal } from "../handover-api";
import { HANDOVER_SLOTS, type HandoverGoal, type HandoverSlot } from "../handover-model";
import { handoverText } from "../deck/handover-i18n";
import { ErrorState, LoadingState, type AsyncState } from "./ui";
import "./handover-goal-checklist.css";

interface Props {
  readonly client: OperatorApiClient;
  readonly goalId: string;
  readonly selectedSlot: HandoverSlot | "";
  readonly onSlotChange: (slot: HandoverSlot | "") => void;
  readonly refreshToken: number;
}

/** Display server-owned evidence and submit revision-fenced review requests, never authority. */
export function HandoverGoalChecklist(props: Props) {
  const sequence = useRef(0);
  const session = useMemo(() => ++sequence.current, [props.client, props.goalId]);
  return <HandoverGoalSession key={session} {...props} />;
}

/** Keep inputs, in-flight replies and focus recovery private to one client and goal. */
function HandoverGoalSession({ client, goalId, selectedSlot, onSlotChange, refreshToken }: Props) {
  const [state, setState] = useState<AsyncState<HandoverGoal>>({ status: "loading" });
  const [refresh, setRefresh] = useState(0);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [sourceGoal, setSourceGoal] = useState("");
  const generation = useRef(0);
  const refreshButton = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);
  const currentSlot = useRef(selectedSlot);
  currentSlot.current = selectedSlot;
  const operations = state.status === "ready" ? state.data.allowedOperations : [];
  const sourceGoalInvalid = sourceGoal !== "" && !/^[a-f0-9]{64}$/.test(sourceGoal);
  useLayoutEffect(() => { onSlotChange(""); }, []);
  useLayoutEffect(() => {
    const current = ++generation.current;
    let cancelled = false;
    returnFocus.current = null;
    setError(null);
    setPending(false);
    setState({ status: "loading" });
    void fetchHandoverGoal(client, goalId).then(
      (goal) => {
        if (!cancelled && current === generation.current) {
          setState({ status: "ready", data: goal });
          if ((!goal.allowedOperations.includes("evidence") && !goal.allowedOperations.includes("not-applicable"))
            || goal.slots.some((slot) => slot.slot === currentSlot.current && (slot.evidenceRef || slot.reasonRef))) {
            setReason("");
            onSlotChange("");
          }
        }
      },
      (failure: unknown) => {
        if (!cancelled) setState({ status: "error", message: failure instanceof Error ? failure.message : handoverText("commandFailed") });
      },
    );
    return () => { cancelled = true; generation.current += 1; };
  }, [client, goalId, refresh, refreshToken]);

  useLayoutEffect(() => {
    const origin = returnFocus.current;
    if (pending || !origin) return;
    returnFocus.current = null;
    // Recover only a lost request focus, never steal focus after deliberate navigation.
    if (document.activeElement === document.body || document.activeElement === origin) {
      if (origin.isConnected && !origin.matches(":disabled")) origin.focus();
      else refreshButton.current?.focus();
    }
  }, [pending, state]);

  const submit = async (operation: "accept" | "acknowledge" | "not-applicable" | "reuse") => {
    if (state.status !== "ready" || pending || !state.data.allowedOperations.includes(operation)) return;
    const current = generation.current;
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setPending(true);
    setError(null);
    try {
      const extra = operation === "not-applicable" ? { slot: selectedSlot, reason_ref: reason.trim() }
        : operation === "reuse" ? { source_goal_id: sourceGoal.trim() } : {};
      const goal = await reviewHandoverGoal(client, goalId, state.data.revision, operation, extra);
      if (current !== generation.current) return;
      setState({ status: "ready", data: goal });
      setReason("");
      onSlotChange("");
    } catch (failure) {
      if (current === generation.current) setError(failure instanceof Error ? failure.message : handoverText("commandFailed"));
    } finally {
      if (current === generation.current) setPending(false);
    }
  };

  return (
    <section class="handover-checklist" aria-labelledby="handover-checklist-title">
      <header>
        <h3 id="handover-checklist-title" class="cs-type-section-title">{handoverText("checklist")}</h3>
        <button ref={refreshButton} type="button" class="cs-control-button" disabled={pending || state.status === "loading"}
          onClick={() => setRefresh((value) => value + 1)}>{handoverText("refresh")}</button>
      </header>
      <p>{handoverText("checklistHint")}</p>
      {state.status === "loading" ? <LoadingState label={handoverText("checklist")} /> : null}
      {pending ? <LoadingState label={handoverText("updating")} /> : null}
      {state.status === "error" ? <ErrorState message={state.message} /> : null}
      {state.status === "ready" ? <>
        <p role="status"><strong>{state.data.agentName}</strong>: {handoverText(
          state.data.state === "accepted" ? "accepted" : state.data.state === "ready_for_review" ? "reviewPending"
            : state.data.state === "stale" ? "stale" : state.data.state === "blocked" ? "blocked"
              : state.data.state === "declined" ? "declined" : state.data.state === "superseded" ? "superseded" : "incomplete",
        )}</p>
        {state.data.legacyState ? <p>{handoverText("legacyReview")}</p> : null}
        <details><summary>{handoverText("details")}</summary>
          <p>{handoverText("revision")}: {state.data.revision}</p>
          <code>{state.data.goalId}</code>
          {state.data.scopeRef ? <p><code>{state.data.scopeRef}</code></p> : null}
          {state.data.sourceRevision ? <p><code>{state.data.sourceRevision}</code></p> : null}
        </details>
        <ol class="handover-checklist-slots">
          {state.data.slots.map((item) => <li key={item.slot}>
            <span>{handoverText(item.slot)}</span>
            <span>{handoverText(item.evidenceRef ? "linked" : item.reasonRef ? "exempted" : "missing")}</span>
            {item.evidenceRef || item.reasonRef ? <details>
              <summary aria-label={handoverText("slotDetails", { slot: handoverText(item.slot) })}>{handoverText("slot")}</summary>
              <code>{item.evidenceRef ?? item.reasonRef}</code>
            </details> : null}
          </li>)}
        </ol>
        {operations.some((operation) => ["evidence", "not-applicable", "reuse"].includes(operation)) ? <div class="handover-checklist-form">
          {operations.includes("evidence") || operations.includes("not-applicable") ? <label class="cs-control-field">
            <span id="handover-slot-label" class="cs-control-label">{handoverText("slot")}</span>
            <select class="cs-control-select" value={selectedSlot} disabled={pending} aria-labelledby="handover-slot-label"
              aria-describedby="handover-slot-help" onChange={(event) => onSlotChange(event.currentTarget.value as HandoverSlot | "")}>
              <option value="">{handoverText("missing")}</option>
              {HANDOVER_SLOTS.filter((slot) => !state.data.slots.find((item) => item.slot === slot && (item.evidenceRef || item.reasonRef))).map((slot) => <option value={slot}>{handoverText(slot)}</option>)}
            </select>
            <span id="handover-slot-help" class="cs-control-help">{handoverText("slotHint")}</span>
          </label> : null}
          {operations.includes("not-applicable") ? <><label class="cs-control-field">
            <span id="handover-reason-label" class="cs-control-label">{handoverText("reason")}</span>
            <input class="cs-control-input" value={reason} maxLength={256} disabled={pending} aria-labelledby="handover-reason-label"
              aria-describedby="handover-reason-help" aria-invalid={reason !== "" && !reason.trim()} autoComplete="off"
              onInput={(event) => setReason(event.currentTarget.value)} />
            <span id="handover-reason-help" class="cs-control-help">{handoverText("reasonHint")}</span></label>
            <button type="button" class="cs-control-button" disabled={pending || !selectedSlot || !reason.trim()}
              onClick={() => void submit("not-applicable")}>{handoverText("exempt")}</button></> : null}
          {operations.includes("reuse") ? <><label class="cs-control-field">
            <span id="handover-source-label" class="cs-control-label">{handoverText("sourceGoal")}</span>
            <input class="cs-control-input" value={sourceGoal} maxLength={64} disabled={pending} aria-labelledby="handover-source-label"
              aria-describedby="handover-source-help" aria-invalid={sourceGoalInvalid} autoComplete="off" spellcheck={false}
              onInput={(event) => setSourceGoal(event.currentTarget.value)} />
            <span id="handover-source-help" class={sourceGoalInvalid ? "cs-control-error" : "cs-control-help"}>{handoverText("sourceGoalHint")}</span></label>
            <button type="button" class="cs-control-button" disabled={pending || !sourceGoal || sourceGoalInvalid}
              onClick={() => void submit("reuse")}>{handoverText("reuse")}</button></> : null}
        </div> : null}
        <div class="handover-checklist-actions">
          {state.data.allowedOperations.includes("accept") ? <button type="button" class="cs-control-button"
            disabled={pending || state.data.state !== "ready_for_review" || state.data.ownerReviewed}
            onClick={() => void submit("accept")}>{handoverText("accept")}</button> : null}
          {state.data.allowedOperations.includes("acknowledge") ? <button type="button" class="cs-control-button"
            disabled={pending || state.data.state !== "ready_for_review" || state.data.backupReviewed}
            onClick={() => void submit("acknowledge")}>{handoverText("acknowledge")}</button> : null}
        </div>
      </> : null}
      {error ? <ErrorState message={error} /> : null}
      <p class="cs-type-compact">{handoverText("reviewOnly")}</p>
    </section>
  );
}
