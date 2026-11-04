import { useRef, useState } from "preact/hooks";
import { hubApi, HubApiError } from "../api";
import type { ExecutionSettings, MaintenanceWindow } from "../api";
import { useAsync } from "../hooks/use-async";
import { tr, useHubLocale } from "../locale";
import { AsyncBoundary } from "./async-boundary";

type Props = {
  installationId: string;
  blocked: boolean;
  onSaved: () => void;
};

export function ExecutionSettingsPanel(props: Props) {
  const [locale] = useHubLocale();
  const state = useAsync(
    () => hubApi.getExecutionSettings(props.installationId), [props.installationId],
  );
  return <section aria-label={tr(locale, "Execution schedule", "실행 일정")}>
    <h2 class="panel-title">{tr(locale, "Execution schedule", "실행 일정")}</h2>
    <p class="note">{tr(
      locale,
      "Changes only daily maintenance windows and the Plan duration. This does not change ownership, compute a Plan, or apply a release.",
      "일일 유지보수 구간과 계획 유효 시간만 변경합니다. 소유권을 변경하거나 계획을 계산하거나 릴리스를 적용하지는 않습니다.",
    )}</p>
    <AsyncBoundary state={state}>
      {current => <ScheduleForm {...props} current={current} reload={state.reload} />}
    </AsyncBoundary>
  </section>;
}

function ScheduleForm({
  installationId, blocked, onSaved, current, reload,
}: Props & { current: ExecutionSettings; reload: () => void }) {
  const [locale] = useHubLocale();
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
        ? tr(
            locale,
            `The Hub rejected this request (${failure.reasonCode}). Refresh settings before trying again.`,
            `Hub가 이 요청을 거부했습니다 (${failure.reasonCode}). 설정을 새로 고침한 뒤 다시 시도하세요.`,
          )
        : tr(
            locale,
            "The save outcome could not be confirmed. Refresh settings before another request. No automatic retry was made.",
            "저장 결과를 확인할 수 없습니다. 설정을 새로 고침한 뒤 다시 요청하세요. 자동 재시도는 수행하지 않았습니다.",
          ));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  return <form class="execution-settings" onSubmit={event => {
    event.preventDefault();
    void save();
  }}>
    {blocked && <p class="banner" role="status">{tr(
      locale,
      "An open Plan blocks schedule changes. Resolve the existing Plan, then refresh this installation.",
      "열린 계획이 있어 일정 변경이 차단되었습니다. 기존 계획을 해결한 뒤 이 설치 환경을 새로 고침하세요.",
    )}</p>}
    {error && <p class="banner fail" role="alert">{error}</p>}
    <fieldset class="execution-fields" disabled={disabled}>
      <legend>{tr(locale, "Daily maintenance windows", "일일 유지보수 구간")}</legend>
      {windows.length === 0 && <p class="note">{tr(
        locale,
        "No windows configured. This schedule adds no execution window.",
        "설정된 구간이 없습니다. 이 일정은 실행 구간을 추가하지 않습니다.",
      )}</p>}
      {windows.map((window, index) => <fieldset class="schedule-window" key={index}>
        <legend>{tr(locale, `Window ${index + 1}`, `구간 ${index + 1}`)}</legend>
        <div class="schedule-grid">
          <label class="execution-field">{tr(locale, "Local start time", "로컬 시작 시각")}
            <input class="input" type="time" step="any" required value={window.start}
              onInput={event => editWindow(index, { start: event.currentTarget.value })} />
          </label>
          <label class="execution-field">{tr(locale, "Duration (minutes)", "유지 시간(분)")}
            <input class="input" type="number" min="1" max="1440" step="any" required
              value={window.duration_minutes}
              onInput={event => editWindow(index, { duration_minutes: event.currentTarget.valueAsNumber })} />
          </label>
          <label class="execution-field">{tr(locale, "Time zone", "시간대")}
            <input class="input" required maxLength={128} placeholder="Asia/Seoul" value={window.timezone}
              onInput={event => editWindow(index, { timezone: event.currentTarget.value })} />
          </label>
        </div>
        <label class="execution-checkbox">
          <input type="checkbox" checked={window.allows_downtime}
            onChange={event => editWindow(index, { allows_downtime: event.currentTarget.checked })} />
          {tr(locale, "Allow downtime in this window", "이 구간에서 다운타임 허용")}
        </label>
        <button class="btn" type="button"
          onClick={() => setWindows(previous => previous.filter((_, at) => at !== index))}>
          {tr(locale, `Remove window ${index + 1}`, `구간 ${index + 1} 삭제`)}
        </button>
      </fieldset>)}
      <button class="btn" type="button" disabled={windows.length >= 32}
        onClick={() => setWindows(previous => [...previous, {
          start: "00:00:00", duration_minutes: 30, timezone: "UTC", allows_downtime: false,
        }])}>{tr(locale, "Add window", "구간 추가")}</button>
      <p class="note">{tr(
        locale,
        "Up to 32 windows. Use IANA time zones such as UTC or Asia/Seoul.",
        "최대 32개 구간까지 설정할 수 있습니다. UTC 또는 Asia/Seoul 같은 IANA 시간대를 사용하세요.",
      )}</p>
      <label class="execution-field">{tr(locale, "Plan duration (minutes)", "계획 유효 시간(분)")}
        <input class="input" type="number" required min="1" max="1440" step="1" value={duration}
          onInput={event => setDuration(event.currentTarget.value)} />
      </label>
      <label class="execution-field">{tr(locale, "Reason", "변경 사유")}
        <select class="input" required value={reason} onChange={event => setReason(event.currentTarget.value)}>
          <option value="" disabled>{tr(locale, "Choose the reviewed change", "검토된 변경 사유 선택")}</option>
          <option value="maintenance_window_change">{tr(locale, "Maintenance schedule change", "유지보수 일정 변경")}</option>
          <option value="plan_duration_change">{tr(locale, "Plan duration change", "계획 유효 시간 변경")}</option>
          <option value="operator_schedule_change">{tr(locale, "Schedule and duration change", "일정 및 유효 시간 변경")}</option>
        </select>
      </label>
      <p class="note">{tr(
        locale,
        "After reviewing the changes, copy this exact confirmation:",
        "변경 사항을 검토한 뒤 아래 확인 문구를 정확히 입력하세요:",
      )}</p>
      <code class="schedule-confirmation">{exactConfirmation}</code>
      <label class="execution-field">{tr(locale, "Exact confirmation", "정확한 확인 문구")}
        <input class="input" required maxLength={256} value={confirmation}
          onInput={event => setConfirmation(event.currentTarget.value)} />
      </label>
      <button class="btn primary" type="submit" disabled={confirmation !== exactConfirmation}>
        {busy
          ? tr(locale, "Saving schedule...", "일정 저장 중...")
          : tr(locale, "Save execution settings", "실행 설정 저장")}
      </button>
    </fieldset>
    <button class="btn" type="button" disabled={busy} onClick={reload}>
      {tr(locale, "Refresh settings", "설정 새로 고침")}
    </button>
  </form>;
}
