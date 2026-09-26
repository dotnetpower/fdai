import { useEffect, useRef, useState } from "preact/hooks";
import { t } from "../i18n";
import {
  BusyClientError,
  cancelBusyCurrent,
  inspectBusy,
  setBusyMode,
  submitBusy,
  type BusyMode,
  type BusyPending,
  type BusyState,
} from "./busy-input-client";

interface BusyInputControlsProps {
  readonly sessionId: string;
  readonly draft: string;
  readonly onConfirmedSubmit: (text: string) => void;
}

type Feedback = "checking" | "unavailable" | "conflict" | "pending" | "ready";

export function BusyInputControls({
  sessionId,
  draft,
  onConfirmedSubmit,
}: BusyInputControlsProps) {
  const [state, setState] = useState<BusyState | null>(null);
  const [feedback, setFeedback] = useState<Feedback>("checking");
  const [confirmedInput, setConfirmedInput] = useState<BusyPending | null>(null);
  const [working, setWorking] = useState(false);
  const generation = useRef(0);
  const mounted = useRef(true);
  const outstanding = useRef<{ id: string; text: string } | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      generation.current += 1;
    };
  }, []);

  const refresh = async () => {
    const current = ++generation.current;
    setWorking(true);
    setFeedback("checking");
    try {
      const observed = await inspectBusy(sessionId);
      if (mounted.current && current === generation.current) {
        setState(observed);
        const awaiting = outstanding.current;
        const entry = observed.pending.find((item) => item.inputId === awaiting?.id);
        setConfirmedInput(entry ?? null);
        setFeedback(awaiting && !entry ? "pending" : "ready");
        if (awaiting && entry) {
          outstanding.current = null;
          onConfirmedSubmit(awaiting.text);
        }
      }
    } catch {
      if (mounted.current && current === generation.current) {
        setState(null);
        setConfirmedInput(null);
        setFeedback("unavailable");
      }
    } finally {
      if (mounted.current && current === generation.current) setWorking(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, [sessionId]);

  const mutate = async (
    write: () => Promise<void>,
    confirm: (before: BusyState, after: BusyState) => boolean,
    submitted?: { id: string; text: string },
  ) => {
    if (!state || working) return;
    const before = state;
    const current = ++generation.current;
    setWorking(true);
    setFeedback("pending");
    setConfirmedInput(null);
    try {
      await write();
      if (!mounted.current || current !== generation.current) return;
      const after = await inspectBusy(sessionId);
      if (!mounted.current || current !== generation.current) return;
      setState(after);
      if (confirm(before, after)) {
        const entry = after.pending.find((item) => item.inputId === submitted?.id);
        setConfirmedInput(entry ?? null);
        setFeedback("ready");
        if (submitted && entry) {
          outstanding.current = null;
          onConfirmedSubmit(submitted.text);
        }
      } else {
        setFeedback("pending");
      }
    } catch (error) {
      if (!mounted.current || current !== generation.current) return;
      if (error instanceof BusyClientError && error.reason === "conflict") {
        outstanding.current = null;
      }
      setState(null);
      setFeedback(error instanceof BusyClientError && error.reason === "conflict"
        ? "conflict" : error instanceof BusyClientError && error.reason === "pending"
          ? "pending" : "unavailable");
    } finally {
      if (mounted.current && current === generation.current) setWorking(false);
    }
  };

  const submit = () => {
    const text = draft;
    const id = crypto.randomUUID();
    outstanding.current = { id, text };
    void mutate(
      () => submitBusy(sessionId, id, text),
      (_before, after) => after.pending.some((entry) => entry.inputId === id),
      { id, text },
    );
  };
  const changeMode = (mode: BusyMode) => {
    if (!state) return;
    void mutate(
      () => setBusyMode(state, mode),
      (before, after) => after.revision > before.revision && after.mode === mode,
    );
  };
  const cancel = () => {
    if (!state) return;
    void mutate(
      () => cancelBusyCurrent(state),
      () => false,
    );
  };

  return (
    <section class="deck-busy" aria-label={t("deck.busy.title")}>
      <div class="deck-busy-heading">
        <span>{t("deck.busy.title")}</span>
        <button type="button" class="deck-busy-link" disabled={working}
          onClick={() => void refresh()}>{t("deck.busy.inspect")}</button>
      </div>
      <p class="deck-busy-status" role="status" aria-live="polite">
        {feedback === "ready" && state
          ? t("deck.busy.state", {
            mode: t(`deck.busy.modes.${state.mode}`),
            active: t(state.active ? "deck.busy.active" : "deck.busy.idle"),
            count: state.pending.length,
          })
          : t(`deck.busy.${feedback}`)}
      </p>
      {confirmedInput
        ? <p class="deck-busy-status" role="status">
          {t("deck.busy.confirmed", {
            disposition: t(`deck.busy.dispositions.${confirmedInput.disposition}`),
          })}
        </p> : null}
      {state && feedback === "ready" ? (
        <div class="deck-busy-actions">
          <label class="deck-busy-mode">
            {t("deck.busy.mode")}
            <select value={state.mode} disabled={working}
              onChange={(event) => changeMode((event.currentTarget as HTMLSelectElement).value as BusyMode)}>
              {(["queue", "interrupt", "steer"] as const).map((mode) =>
                <option key={mode} value={mode}>{t(`deck.busy.modes.${mode}`)}</option>)}
            </select>
          </label>
          <button type="button" class="deck-busy-link"
            disabled={working || !draft.trim() || new TextEncoder().encode(draft).length > 4_000}
            onClick={submit}>{t("deck.busy.submit")}</button>
          <button type="button" class="deck-busy-link"
            disabled={working || !state.active} onClick={cancel}>{t("deck.busy.cancel")}</button>
        </div>
      ) : null}
      {state && state.pending.length > 0 && feedback === "ready"
        ? <details class="deck-busy-list">
          <summary>{t("deck.busy.pendingList", { count: state.pending.length })}</summary>
          <ol>
            {state.pending.map((entry) =>
              <li key={entry.sequence}>
                {t("deck.busy.pendingItem", {
                  sequence: entry.sequence,
                  disposition: t(`deck.busy.dispositions.${entry.disposition}`),
                  expires: entry.expiresAt,
                })}
              </li>)}
          </ol>
        </details> : null}
      <p class="deck-busy-hint">{t("deck.busy.boundary")}</p>
    </section>
  );
}
