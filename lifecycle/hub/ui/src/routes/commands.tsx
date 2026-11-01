import { useState } from "preact/hooks";
import { hubApi, HubApiError } from "../api";
import { AsyncBoundary } from "../components/async-boundary";
import { Link } from "../components/link";
import { useAsync } from "../hooks/use-async";
import { tr, useHubLocale } from "../locale";
import { installationPath } from "../router";

export function CommandsPage() {
  const [locale] = useHubLocale();
  const installations = useAsync(() => hubApi.listInstallations(), []);
  const [installationId, setInstallationId] = useState("");
  const [mode, setMode] = useState<"suppress" | "lift">("suppress");
  const [scope, setScope] = useState("installation");
  const [durationHours, setDurationHours] = useState("2");
  const [reason, setReason] = useState("maintenance_freeze");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const targetId = installationId.trim();
  const expectedConfirmation =
    mode === "suppress"
      ? `suppress ${targetId} ${scope.trim()}`
      : `lift suppression ${targetId} ${scope.trim()}`;

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (busy || !targetId || confirmation !== expectedConfirmation) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (mode === "suppress") {
        const now = new Date();
        const hours = Math.max(1, Math.min(720, Number.parseInt(durationHours, 10) || 2));
        const ends = new Date(now.getTime() + hours * 3600_000);
        await hubApi.addSuppression(targetId, {
          scope: scope.trim(),
          starts_at: now.toISOString(),
          ends_at: ends.toISOString(),
          reason: reason.trim(),
          confirmation,
        });
        setNotice(
          tr(
            locale,
            `Suppression window added for ${targetId} (${scope.trim()}) until ${ends.toISOString()}.`,
            `${targetId} (${scope.trim()})에 대한 억제 구간이 ${ends.toISOString()}까지 추가되었습니다.`,
          ),
        );
      } else {
        await hubApi.liftSuppression(targetId, {
          scope: scope.trim(),
          reason: reason.trim(),
          confirmation,
        });
        setNotice(
          tr(
            locale,
            `Active suppression lifted for ${targetId} (${scope.trim()}).`,
            `${targetId} (${scope.trim()})의 활성 억제가 해제되었습니다.`,
          ),
        );
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
        <p class="banner" role="status">
          {notice}{" "}
          {targetId && (
            <Link href={installationPath(targetId)}>
              {tr(locale, "Inspect installation", "설치 상세 보기")}
            </Link>
          )}
        </p>
      )}
      {error && (
        <p class="banner fail" role="alert">
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
                  setMode(event.currentTarget.value as "suppress" | "lift");
                  setConfirmation("");
                }}
              >
                <option value="suppress">
                  {tr(locale, "Create expiring suppression window", "만료형 억제 구간 생성")}
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
            {mode === "suppress" && (
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
                  : tr(locale, "Lift suppression", "억제 해제")}
              </button>
            </div>
          </form>
        )}
      </AsyncBoundary>
    </div>
  );
}
