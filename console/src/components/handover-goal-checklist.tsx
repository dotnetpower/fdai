import { useEffect, useRef, useState } from "preact/hooks";
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
export function HandoverGoalChecklist({ client, goalId, selectedSlot, onSlotChange, refreshToken }: Props) {
  const [state, setState] = useState<AsyncState<HandoverGoal>>({ status: "loading" });
  const [refresh, setRefresh] = useState(0);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [sourceGoal, setSourceGoal] = useState("");
  const generation = useRef(0);
  useEffect(() => {
    const current = ++generation.current;
    let cancelled = false;
    setPending(false);
    setState({ status: "loading" });
    void fetchHandoverGoal(client, goalId).then(
      (goal) => {
        if (!cancelled && current === generation.current) {
          setState({ status: "ready", data: goal });
          if (!goal.allowedOperations.includes("evidence") || goal.slots.some((slot) => slot.slot === selectedSlot && (slot.evidenceRef || slot.reasonRef))) onSlotChange("");
        }
      },
      (failure: unknown) => {
        if (!cancelled) setState({ status: "error", message: failure instanceof Error ? failure.message : handoverText("commandFailed") });
      },
    );
    return () => { cancelled = true; generation.current += 1; };
  }, [client, goalId, refresh, refreshToken]);

  const submit = async (operation: "accept" | "acknowledge" | "not-applicable" | "reuse") => {
    if (state.status !== "ready" || pending || !state.data.allowedOperations.includes(operation)) return;
    const current = generation.current;
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
        <button type="button" class="cs-control-button" disabled={pending || state.status === "loading"}
          onClick={() => setRefresh((value) => value + 1)}>{handoverText("refresh")}</button>
      </header>
      <p>{handoverText("checklistHint")}</p>
      {state.status === "loading" ? <LoadingState label={handoverText("checklist")} /> : null}
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
              <summary>{handoverText("slot")}</summary>
              <code>{item.evidenceRef ?? item.reasonRef}</code>
            </details> : null}
          </li>)}
        </ol>
        {state.data.allowedOperations.includes("evidence") ? <div class="handover-checklist-form">
          <label><span>{handoverText("slot")}</span>
            <select value={selectedSlot} disabled={pending} onChange={(event) => onSlotChange(event.currentTarget.value as HandoverSlot | "")}>
              <option value="">{handoverText("missing")}</option>
              {HANDOVER_SLOTS.filter((slot) => !state.data.slots.find((item) => item.slot === slot && (item.evidenceRef || item.reasonRef))).map((slot) => <option value={slot}>{handoverText(slot)}</option>)}
            </select>
          </label>
          <label><span>{handoverText("reason")}</span><input value={reason} maxLength={256} disabled={pending}
            onInput={(event) => setReason(event.currentTarget.value)} /></label>
          <button type="button" class="cs-control-button" disabled={pending || !selectedSlot || !reason.trim()}
            onClick={() => void submit("not-applicable")}>{handoverText("exempt")}</button>
          <label><span>{handoverText("sourceGoal")}</span><input value={sourceGoal} maxLength={64} disabled={pending}
            onInput={(event) => setSourceGoal(event.currentTarget.value)} /></label>
          <button type="button" class="cs-control-button" disabled={pending || !/^[a-f0-9]{64}$/.test(sourceGoal)}
            onClick={() => void submit("reuse")}>{handoverText("reuse")}</button>
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
