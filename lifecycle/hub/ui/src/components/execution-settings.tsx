import { useRef, useState } from "preact/hooks";
import { hubApi, HubApiError } from "../api";
import type { ExecutionSettings, MaintenanceWindow } from "../api";
import { useAsync } from "../hooks/use-async";
import { AsyncBoundary } from "./async-boundary";

type Props = {
  installationId: string;
  blocked: boolean;
  onSaved: () => void;
};

export function ExecutionSettingsPanel(props: Props) {
  const state = useAsync(
    () => hubApi.getExecutionSettings(props.installationId), [props.installationId],
  );
  return <section aria-label="Execution schedule">
    <h2 class="panel-title">Execution schedule</h2>
    <p class="note">Changes only daily maintenance windows and the Plan duration.
      This does not change ownership, compute a Plan, or apply a release.</p>
    <AsyncBoundary state={state}>
      {current => <ScheduleForm {...props} current={current} reload={state.reload} />}
    </AsyncBoundary>
  </section>;
}

function ScheduleForm({
  installationId, blocked, onSaved, current, reload,
}: Props & { current: ExecutionSettings; reload: () => void }) {
  const [windows, setWindows] = useState<readonly MaintenanceWindow[]>(current.windows);
  const [duration, setDuration] = useState(String(current.plan_duration_minutes));
  const [reason, setReason] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  const exactConfirmation = `update execution settings ${installationId} ${current.settings_digest}`;
  const disabled = busy || blocked || error !== "";

  function editWindow(index: number, change: Partial<MaintenanceWindow>) {
    setWindows(previous => previous.map((window, at) => at === index ? { ...window, ...change } : window));
  }

  async function save() {
    if (inFlight.current || disabled) return;
    inFlight.current = true;
    setBusy(true);
    try {
      await hubApi.updateExecutionSettings(installationId, {
        request_id: crypto.randomUUID(),
        expected_settings_digest: current.settings_digest,
        windows,
        plan_duration_minutes: Number(duration),
        reason_code: reason,
        confirmation,
      });
      onSaved();
    } catch (failure: unknown) {
      setError(failure instanceof HubApiError
        ? `The Hub rejected this request (${failure.reasonCode}). Refresh settings before trying again.`
        : "The save outcome could not be confirmed. Refresh settings before another request. No automatic retry was made.");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return <form class="execution-settings" onSubmit={event => {
    event.preventDefault();
    void save();
  }}>
    {blocked && <p class="banner" role="status">An open Plan blocks schedule changes.
      Resolve the existing Plan, then refresh this installation.</p>}
    {error && <p class="banner fail" role="alert">{error}</p>}
    <fieldset class="execution-fields" disabled={disabled}>
      <legend>Daily maintenance windows</legend>
      {windows.length === 0 && <p class="note">No windows configured. This schedule adds no execution window.</p>}
      {windows.map((window, index) => <fieldset class="schedule-window" key={index}>
        <legend>Window {index + 1}</legend>
        <div class="schedule-grid">
          <label class="execution-field">Local start time
            <input class="input" type="time" step="any" required value={window.start}
              onInput={event => editWindow(index, { start: event.currentTarget.value })} />
          </label>
          <label class="execution-field">Duration (minutes)
            <input class="input" type="number" min="1" max="1440" step="any" required
              value={window.duration_minutes}
              onInput={event => editWindow(index, { duration_minutes: event.currentTarget.valueAsNumber })} />
          </label>
          <label class="execution-field">Time zone
            <input class="input" required maxLength={128} placeholder="Asia/Seoul" value={window.timezone}
              onInput={event => editWindow(index, { timezone: event.currentTarget.value })} />
          </label>
        </div>
        <label class="execution-checkbox">
          <input type="checkbox" checked={window.allows_downtime}
            onChange={event => editWindow(index, { allows_downtime: event.currentTarget.checked })} />
          Allow downtime in this window
        </label>
        <button class="btn" type="button"
          onClick={() => setWindows(previous => previous.filter((_, at) => at !== index))}>
          Remove window {index + 1}
        </button>
      </fieldset>)}
      <button class="btn" type="button" disabled={windows.length >= 32}
        onClick={() => setWindows(previous => [...previous, {
          start: "00:00:00", duration_minutes: 30, timezone: "UTC", allows_downtime: false,
        }])}>Add window</button>
      <p class="note">Up to 32 windows. Use IANA time zones such as UTC or Asia/Seoul.</p>
      <label class="execution-field">Plan duration (minutes)
        <input class="input" type="number" required min="1" max="1440" step="1" value={duration}
          onInput={event => setDuration(event.currentTarget.value)} />
      </label>
      <label class="execution-field">Reason
        <select class="input" required value={reason} onChange={event => setReason(event.currentTarget.value)}>
          <option value="" disabled>Choose the reviewed change</option>
          <option value="maintenance_window_change">Maintenance schedule change</option>
          <option value="plan_duration_change">Plan duration change</option>
          <option value="operator_schedule_change">Schedule and duration change</option>
        </select>
      </label>
      <p class="note">After reviewing the changes, copy this exact confirmation:</p>
      <code class="schedule-confirmation">{exactConfirmation}</code>
      <label class="execution-field">Exact confirmation
        <input class="input" required maxLength={256} value={confirmation}
          onInput={event => setConfirmation(event.currentTarget.value)} />
      </label>
      <button class="btn primary" type="submit" disabled={confirmation !== exactConfirmation}>
        {busy ? "Saving schedule..." : "Save execution settings"}
      </button>
    </fieldset>
    <button class="btn" type="button" disabled={busy} onClick={reload}>Refresh settings</button>
  </form>;
}
