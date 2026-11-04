import { useEffect, useState } from "preact/hooks";
import { hubApi, HubApiError, type LifecycleCommandItem } from "../api";
import { AsyncBoundary } from "../components/async-boundary";
import { Link } from "../components/link";
import { formatTimestamp } from "../format";
import { useAsync } from "../hooks/use-async";
import { tr, useHubLocale } from "../locale";
import { installationPath } from "../router";

type CommandActionMode = "suppress" | "authority-lowering" | "break-glass" | "lift";

export function CommandsPage() {
  const [locale] = useHubLocale();
  const installations = useAsync(() => hubApi.listInstallations(), []);
  const [activeCommands, setActiveCommands] = useState<readonly LifecycleCommandItem[]>([]);
  const [installationId, setInstallationId] = useState("");
  const [mode, setMode] = useState<CommandActionMode>("suppress");
  const [scope, setScope] = useState("installation");
  const [durationHours, setDurationHours] = useState("2");
  const [reason, setReason] = useState("maintenance_freeze");
  const [targetAutonomy, setTargetAutonomy] = useState<"shadow" | "hil">("shadow");
  const [engageKillSwitch, setEngageKillSwitch] = useState(false);
  const [bypassMaintenance, setBypassMaintenance] = useState(true);
  const [bypassSuppression, setBypassSuppression] = useState(true);
  const [bypassVersionRange, setBypassVersionRange] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  function loadCommands() {
    void hubApi
      .listCommands()
      .then((res) => setActiveCommands(res.commands))
      .catch(() => setActiveCommands([]));
  }

  useEffect(() => {
    loadCommands();
  }, []);

  const targetId = installationId.trim();
  const cleanScope = scope.trim();
  const expectedConfirmation =
    mode === "suppress"
      ? `suppress ${targetId} ${cleanScope}`
      : mode === "lift"
      ? `lift suppression ${targetId} ${cleanScope}`
      : `command ${mode} ${targetId} ${cleanScope}`;

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (busy || !targetId || confirmation !== expectedConfirmation) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const now = new Date();
      const hours = Math.max(1, Math.min(720, Number.parseInt(durationHours, 10) || 2));
      const ends = new Date(now.getTime() + hours * 3600_000);
      if (mode === "suppress") {
        await hubApi.addSuppression(targetId, {
          scope: cleanScope,
          starts_at: now.toISOString(),
          ends_at: ends.toISOString(),
          reason: reason.trim(),
          confirmation,
        });
        setNotice(
          tr(
            locale,
            `Suppression window added for ${targetId} (${cleanScope}) until ${ends.toISOString()}.`,
            `${targetId} (${cleanScope})에 대한 억제 구간이 ${ends.toISOString()}까지 추가되었습니다.`,
          ),
        );
      } else if (mode === "lift") {
        await hubApi.liftSuppression(targetId, {
          scope: cleanScope,
          reason: reason.trim(),
          confirmation,
        });
        setNotice(
          tr(
            locale,
            `Active suppression lifted for ${targetId} (${cleanScope}).`,
            `${targetId} (${cleanScope})의 활성 억제가 해제되었습니다.`,
          ),
        );
      } else {
        const bypassScopes = [
          ...(bypassMaintenance ? ["maintenance-window"] : []),
          ...(bypassSuppression ? ["suppression-window"] : []),
          ...(bypassVersionRange ? ["version-range"] : []),
        ];
        const commandId = `cmd-${mode}-${now.getTime()}`;
        await hubApi.issueCommand(targetId, {
          command_id: commandId,
          kind: mode,
          scope: cleanScope,
          starts_at: now.toISOString(),
          expires_at: ends.toISOString(),
          reason: reason.trim(),
          target_mode: mode === "authority-lowering" ? "shadow" : null,
          target_autonomy: mode === "authority-lowering" ? targetAutonomy : null,
          engage_kill_switch: mode === "authority-lowering" ? engageKillSwitch : false,
          bypass_scopes: mode === "break-glass" ? bypassScopes : [],
          confirmation,
        });
        setNotice(
          tr(
            locale,
            `Issued expiring ${mode} command (${commandId}) for ${targetId} until ${ends.toISOString()}.`,
            `${targetId}에 대해 ${ends.toISOString()}까지 유효한 ${mode} 명령(${commandId})을 발행했습니다.`,
          ),
        );
        loadCommands();
      }
      setConfirmation("");
      installations.reload();
    } catch (failure) {
      setError(
        failure instanceof HubApiError
          ? `The Hub rejected this command (${failure.reasonCode}). Refresh installation state before retrying.`
          : "The command outcome could not be confirmed. Refresh installation state before retrying.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div class="catalog-page" lang={locale}>
      <div class="m-head">
        <div>
          <h1>{tr(locale, "Lifecycle commands", "수명 주기 명령")}</h1>
          <div class="sub">
            {tr(
              locale,
              "Issue expiring suppression windows or lift active holds. Every command is recorded in the hash-chained Hub audit and never raises authority.",
              "만료 기한이 있는 억제 구간을 설정하거나 활성 보류를 해제합니다. 모든 명령은 해시 체인 감사에 기록되며 권한을 상향하지 않습니다.",
            )}
          </div>
        </div>
      </div>

      <div class="callout">
        <strong>{tr(locale, "Authority and expiry boundary", "권한 및 만료 경계")}</strong>
        <p>
          {tr(
            locale,
            "Suppression windows hold matching Plans immediately and always expire. Break-glass commands require the dedicated CLI and break-glass role, and reconcile back to the approved Git configuration revision upon expiry.",
            "억제 구간은 일치하는 계획을 즉시 보류하며 항상 만료 기한을 가집니다. 긴급(Break-glass) 명령은 전용 CLI 및 역할이 필요하며 만료 시 승인된 Git 구성 개정본으로 복원됩니다.",
          )}
        </p>
      </div>

      {notice && (
        <p class="banner" role="status" style={{ overflowWrap: "anywhere" }}>
          {notice}{" "}
          {targetId && (
            <Link href={installationPath(targetId)}>
              {tr(locale, "Inspect installation", "설치 상세 보기")}
            </Link>
          )}
        </p>
      )}
      {error && (
        <p class="banner fail" role="alert" style={{ overflowWrap: "anywhere" }}>
          {error}
        </p>
      )}

      <AsyncBoundary state={installations}>
        {({ installations: rows }) => (
          <form class="catalog-panel" onSubmit={submit}>
            <h2 class="panel-title">
              {tr(locale, "Suppression window command", "억제 구간 명령")}
            </h2>
            <label>
              {tr(locale, "Action", "작업 종류")}
              <select
                class="input"
                aria-label="Command action"
                value={mode}
                onChange={(event) => {
                  setMode(event.currentTarget.value as CommandActionMode);
                  setConfirmation("");
                }}
              >
                <option value="suppress">
                  {tr(locale, "Create expiring suppression window", "만료형 억제 구간 생성")}
                </option>
                <option value="authority-lowering">
                  {tr(
                    locale,
                    "Issue authority-lowering command (shadow / HIL / kill switch)",
                    "권한 하향 명령 발행 (shadow / HIL / 킬 스위치)",
                  )}
                </option>
                <option value="break-glass">
                  {tr(
                    locale,
                    "Issue break-glass command (reconciles to Git on expiry)",
                    "긴급(Break-glass) 명령 발행 (만료 시 Git 구성으로 복원)",
                  )}
                </option>
                <option value="lift">
                  {tr(locale, "Lift active suppression scope", "활성 억제 범위 해제")}
                </option>
              </select>
            </label>
            <label>
              {tr(locale, "Installation ID", "설치 ID")}
              {rows.length > 0 ? (
                <select
                  class="input"
                  aria-label="Command installation"
                  required
                  value={installationId}
                  onChange={(event) => {
                    setInstallationId(event.currentTarget.value);
                    setConfirmation("");
                  }}
                >
                  <option value="">
                    {tr(locale, "Select an enrolled installation", "등록된 설치 선택")}
                  </option>
                  {rows.map((row) => (
                    <option key={row.installation_id} value={row.installation_id}>
                      {row.installation_id} ({row.channel})
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  class="input"
                  aria-label="Command installation"
                  required
                  value={installationId}
                  placeholder="e.g. prod-korea"
                  onInput={(event) => {
                    setInstallationId(event.currentTarget.value);
                    setConfirmation("");
                  }}
                />
              )}
            </label>
            <label>
              {tr(locale, "Suppression scope", "억제 범위")}
              <input
                class="input mono"
                aria-label="Suppression scope"
                required
                value={scope}
                placeholder="installation, plan:upgrade, or entity:core"
                onInput={(event) => {
                  setScope(event.currentTarget.value);
                  setConfirmation("");
                }}
              />
            </label>
            {mode !== "lift" && (
              <label>
                {tr(locale, "Duration (hours, mandatory expiry)", "유지 시간(시간, 만료 필수)")}
                <input
                  class="input"
                  aria-label="Suppression duration hours"
                  type="number"
                  min="1"
                  max="720"
                  step="1"
                  required
                  value={durationHours}
                  onInput={(event) => setDurationHours(event.currentTarget.value)}
                />
              </label>
            )}
            {mode === "authority-lowering" && (
              <>
                <label>
                  {tr(locale, "Target autonomy ceiling", "목표 자율성 상한")}
                  <select
                    class="input"
                    aria-label="Target autonomy ceiling"
                    value={targetAutonomy}
                    onChange={(event) =>
                      setTargetAutonomy(event.currentTarget.value as "shadow" | "hil")
                    }
                  >
                    <option value="shadow">shadow (observe only)</option>
                    <option value="hil">hil (require human approval)</option>
                  </select>
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={engageKillSwitch}
                    onChange={(event) => setEngageKillSwitch(event.currentTarget.checked)}
                  />{" "}
                  {tr(
                    locale,
                    "Engage installation kill switch (never raises authority)",
                    "설치 킬 스위치 활성화 (권한을 상향하지 않음)",
                  )}
                </label>
              </>
            )}
            {mode === "break-glass" && (
              <fieldset class="catalog-panel">
                <legend>
                  {tr(
                    locale,
                    "Permitted break-glass constraint bypasses",
                    "허용된 긴급(Break-glass) 제약 우회 범위",
                  )}
                </legend>
                <label>
                  <input
                    type="checkbox"
                    checked={bypassMaintenance}
                    onChange={(event) => setBypassMaintenance(event.currentTarget.checked)}
                  />{" "}
                  maintenance-window
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={bypassSuppression}
                    onChange={(event) => setBypassSuppression(event.currentTarget.checked)}
                  />{" "}
                  suppression-window
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={bypassVersionRange}
                    onChange={(event) => setBypassVersionRange(event.currentTarget.checked)}
                  />{" "}
                  version-range
                </label>
              </fieldset>
            )}
            <label>
              {tr(locale, "Reason code", "사유 코드")}
              <input
                class="input mono"
                aria-label="Reason code"
                required
                pattern="[a-z][a-z0-9_]{0,95}"
                value={reason}
                onInput={(event) => setReason(event.currentTarget.value)}
              />
            </label>
            {targetId && (
              <>
                <p class="note">
                  {tr(locale, "Expected confirmation:", "확인 문구:")}{" "}
                  <code class="mono">{expectedConfirmation}</code>
                </p>
                <div class="acts">
                  <button
                    type="button"
                    class="btn"
                    disabled={busy || confirmation === expectedConfirmation}
                    onClick={() => setConfirmation(expectedConfirmation)}
                  >
                    {tr(locale, "Fill reviewed confirmation", "검토된 확인 문구 자동 입력")}
                  </button>
                </div>
              </>
            )}
            <label>
              {tr(locale, "Exact confirmation", "정확한 확인 문구")}
              <input
                class="input mono"
                required
                autoComplete="off"
                value={confirmation}
                onInput={(event) => setConfirmation(event.currentTarget.value)}
              />
            </label>
            <div class="acts">
              <button
                type="submit"
                class="btn primary"
                disabled={busy || !targetId || confirmation !== expectedConfirmation}
              >
                {busy
                  ? tr(locale, "Applying command...", "명령 적용 중...")
                  : mode === "suppress"
                  ? tr(locale, "Create suppression", "억제 구간 생성")
                  : mode === "authority-lowering"
                  ? tr(locale, "Issue authority-lowering command", "권한 하향 명령 발행")
                  : mode === "break-glass"
                  ? tr(locale, "Issue break-glass command", "긴급 명령 발행")
                  : tr(locale, "Lift suppression", "억제 해제")}
              </button>
            </div>
          </form>
        )}
      </AsyncBoundary>

      <div class="cols">
        <section aria-label="Active commands">
          <h2 class="panel-title">{tr(locale, "Active commands", "활성 및 최근 명령")}</h2>
          {activeCommands.length === 0 ? (
            <p class="note">
              {tr(
                locale,
                "No authority-lowering or break-glass commands recorded yet.",
                "아직 기록된 권한 하향 또는 긴급 명령이 없습니다.",
              )}
            </p>
          ) : (
            <table class="t">
              <thead>
                <tr>
                  <th>{tr(locale, "Kind", "종류")}</th>
                  <th>{tr(locale, "Scope", "범위")}</th>
                  <th>{tr(locale, "Expires", "만료 시각")}</th>
                </tr>
              </thead>
              <tbody>
                {activeCommands.map((cmd) => (
                  <tr key={cmd.command_id}>
                    <td>
                      <span class={`badge ${cmd.kind === "break-glass" ? "warn" : "info"}`}>
                        {cmd.kind}
                      </span>
                      <div class="soft">{cmd.reason}</div>
                    </td>
                    <td>
                      {cmd.installation_id} · <span class="mono">{cmd.scope}</span>
                    </td>
                    <td>
                      {formatTimestamp(cmd.expires_at)}
                      {cmd.reconciles_to_git_on_expiry && (
                        <div class="soft">
                          {tr(
                            locale,
                            "Reconciles to approved Git configuration on expiry",
                            "만료 시 승인된 Git 구성으로 자동 복원",
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section aria-label="Break-glass invariants">
          <h2 class="panel-title">
            {tr(locale, "Break-glass can bypass", "긴급(Break-glass) 우회 및 불변 경계")}
          </h2>
          <ul class="list">
            <li>
              <span class="ic ok">✓</span>
              <span>
                {tr(
                  locale,
                  "Maintenance windows, suppression windows, and version ranges",
                  "유지보수 구간, 억제 구간 및 버전 범위",
                )}
              </span>
              <span class="soft">{tr(locale, "Bypassed", "우회 가능")}</span>
            </li>
            <li>
              <span class="ic fail">✕</span>
              <span>
                {tr(
                  locale,
                  "Signatures, envelope, recall, destructive-change confirmation, and audit",
                  "서명, 효과 범위(envelope), 리콜, 파괴적 변경 확인 및 감사",
                )}
              </span>
              <span class="soft">{tr(locale, "Always enforced", "항상 강제")}</span>
            </li>
          </ul>
          <p class="note">
            {tr(
              locale,
              "No command can raise authority to enforce or auto, or disengage the kill switch.",
              "어떤 명령도 권한을 enforce나 auto로 상향하거나 킬 스위치를 해제할 수 없습니다.",
            )}
          </p>
        </section>
      </div>
    </div>
  );
}
