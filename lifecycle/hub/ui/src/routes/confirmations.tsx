import { useState } from "preact/hooks";
import { hubApi, HubApiError, type DestructiveConfirmationItem } from "../api";
import { AsyncBoundary } from "../components/async-boundary";
import { Link } from "../components/link";
import { useAsync } from "../hooks/use-async";
import { tr, useHubLocale } from "../locale";
import { installationPath, planPath } from "../router";

export function ConfirmationsPage() {
  const [locale] = useHubLocale();
  const confirmations = useAsync(() => hubApi.listConfirmations(), []);
  const [selectedKey, setSelectedKey] = useState("");
  const [decision, setDecision] = useState<"confirm" | "hold">("confirm");
  const [reason, setReason] = useState("approved_downtime_replacement");
  const [confirmationText, setConfirmationText] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  function itemKey(item: DestructiveConfirmationItem): string {
    return `${item.installation_id}/${item.plan_id}`;
  }

  async function submitDecision(item: DestructiveConfirmationItem, event: SubmitEvent) {
    event.preventDefault();
    const expectedPhrase = `${decision} ${item.installation_id} ${item.plan_id} ${item.exact_plan_digest}`;
    if (busy || confirmationText !== expectedPhrase) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const updated = await hubApi.decideConfirmation(item.installation_id, item.plan_id, {
        decision,
        expected_plan_digest: item.exact_plan_digest,
        confirmed_addresses: item.affected_addresses,
        reason: reason.trim(),
        confirmation: confirmationText,
      });
      setNotice(
        tr(
          locale,
          `Recorded ${updated.status} decision for ${item.installation_id} (${item.plan_id}) bound to ${item.exact_plan_digest}.`,
          `${item.installation_id} (${item.plan_id})에 대해 다이제스트 ${item.exact_plan_digest}에 바인딩된 ${updated.status} 결정을 기록했습니다.`,
        ),
      );
      setConfirmationText("");
      confirmations.reload();
    } catch (failure) {
      setError(
        failure instanceof HubApiError
          ? `Confirmation rejected (${failure.reasonCode}). A changed or superseded Plan invalidates the confirmation.`
          : "Could not verify the confirmation decision. Refresh before retrying.",
      );
      confirmations.reload();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div class="catalog-page" lang={locale}>
      <div class="m-head">
        <div>
          <h1>{tr(locale, "Confirmations", "파괴적 변경 확인")}</h1>
          <div class="sub">
            {tr(
              locale,
              "Confirm or hold Azure resource deletion, replacement, and uninstall Plans. Every confirmation is bound to an exact Plan digest and invalidated if the Plan changes.",
              "Azure 리소스 삭제, 교체 및 제거 계획을 확인하거나 보류합니다. 모든 확인은 정확한 계획 다이제스트에 바인딩되며 계획이 변경되면 무효화됩니다.",
            )}
          </div>
        </div>
        <button type="button" class="btn" onClick={confirmations.reload}>
          {tr(locale, "Refresh", "새로 고침")}
        </button>
      </div>

      <div class="callout">
        <strong>
          {tr(
            locale,
            "Exact plan digest and sanitized summary boundary",
            "정확한 계획 다이제스트 및 요약 경계",
          )}
        </strong>
        <p>
          {tr(
            locale,
            "Without confirmation, destructive Plans remain held. The infrastructure agent renders the exact Terraform plan inside the installation; the Hub receives only a sanitized summary and never holds Azure credentials.",
            "확인이 없으면 파괴적 계획은 보류 상태로 유지됩니다. 인프라 에이전트가 설치 내부에서 정확한 Terraform 계획을 렌더링하며, Hub는 요약본만 수신하고 Azure 자격 증명을 보유하지 않습니다.",
          )}
        </p>
      </div>

      {notice && (
        <p class="banner" role="status" style={{ overflowWrap: "anywhere" }}>
          {notice}
        </p>
      )}
      {error && (
        <p class="banner fail" role="alert" style={{ overflowWrap: "anywhere" }}>
          {error}
        </p>
      )}

      <AsyncBoundary state={confirmations}>
        {({ confirmations: items }) => {
          if (items.length === 0) {
            return (
              <p class="empty">
                {tr(
                  locale,
                  "No destructive resource replacements, deletions, or uninstalls are awaiting confirmation.",
                  "현재 확인 대기 중인 리소스 교체, 삭제 또는 제거 항목이 없습니다.",
                )}
              </p>
            );
          }
          const activeItem =
            items.find((candidate) => itemKey(candidate) === selectedKey) ?? items[0]!;
          const expectedPhrase = `${decision} ${activeItem.installation_id} ${activeItem.plan_id} ${activeItem.exact_plan_digest}`;
          return (
            <div class="stack">
              {items.map((item) => {
                const key = itemKey(item);
                const selected = key === itemKey(activeItem);
                const badgeClass =
                  item.status === "confirmed"
                    ? "ok"
                    : item.status === "held"
                    ? "warn"
                    : item.status === "invalidated"
                    ? "fail"
                    : "fail";
                return (
                  <article
                    key={key}
                    class={`card ${selected ? "sel" : ""}`}
                    aria-labelledby={`confirm-${item.installation_id}-${item.plan_id}`}
                  >
                    <div class="row1">
                      <span class={`badge ${badgeClass}`}>
                        {item.change_kind === "uninstall"
                          ? tr(locale, "Uninstall confirmation", "제거 확인")
                          : item.change_kind === "resource-deletion"
                          ? tr(locale, "Azure resource deletion", "Azure 리소스 삭제")
                          : tr(locale, "Azure resource replacement", "Azure 리소스 교체")}
                      </span>
                      <h2 id={`confirm-${item.installation_id}-${item.plan_id}`}>
                        {item.title}
                      </h2>
                      <span class="badge mute">{item.status}</span>
                    </div>
                    <div class="meta">
                      {item.summary} ·{" "}
                      <Link href={installationPath(item.installation_id)}>
                        {item.installation_id}
                      </Link>{" "}
                      ·{" "}
                      <Link href={planPath(item.installation_id, item.plan_id)}>
                        {item.plan_id}
                      </Link>{" "}
                      · plan digest{" "}
                      <span class="mono" style={{ overflowWrap: "anywhere" }}>
                        {item.exact_plan_digest}
                      </span>
                    </div>
                    <div class="banner warn">
                      <div>
                        <b>{tr(locale, "Impact:", "영향 범위:")}</b> {item.impact}
                      </div>
                      <span class="badge warn">
                        Replace {item.replace_count} · Delete {item.delete_count}
                      </span>
                    </div>
                    <ul class="list">
                      <li>
                        <span class={`ic ${item.foundation_ownership_verified ? "ok" : "fail"}`}>
                          {item.foundation_ownership_verified ? "✓" : "✕"}
                        </span>
                        <span>
                          {tr(
                            locale,
                            "FDAI ownership: signed Foundation creation receipt and matching Terraform state",
                            "FDAI 소유권: 서명된 Foundation 생성 영수증 및 일치하는 Terraform 상태",
                          )}
                        </span>
                        <span class="soft">
                          {tr(locale, "Tag alone not accepted", "태그 단독 불인정")}
                        </span>
                      </li>
                      <li>
                        <span class={`ic ${item.within_local_envelope ? "ok" : "fail"}`}>
                          {item.within_local_envelope ? "✓" : "✕"}
                        </span>
                        <span>
                          {tr(
                            locale,
                            "Inside the envelope that the installation derived locally",
                            "설치 환경이 로컬에서 도출한 범위 이내",
                          )}
                        </span>
                        <span class="soft">{tr(locale, "In envelope", "범위 내")}</span>
                      </li>
                      <li>
                        <span class={`ic ${item.dry_run_succeeded ? "ok" : "fail"}`}>
                          {item.dry_run_succeeded ? "✓" : "✕"}
                        </span>
                        <span>{tr(locale, "Dry run succeeded", "드라이런 성공")}</span>
                        <span class="soft" style={{ overflowWrap: "anywhere" }}>
                          {item.affected_addresses.join(", ")}
                        </span>
                      </li>
                    </ul>
                    {items.length > 1 && !selected && (
                      <div class="acts">
                        <button
                          type="button"
                          class="btn"
                          onClick={() => {
                            setSelectedKey(key);
                            setConfirmationText("");
                          }}
                        >
                          {tr(locale, "Select for review", "검토 항목 선택")}
                        </button>
                      </div>
                    )}
                  </article>
                );
              })}

              {activeItem.status === "pending" && activeItem.plan_current && (
                <form
                  class="catalog-panel"
                  onSubmit={(event) => void submitDecision(activeItem, event)}
                >
                  <h2 class="panel-title">
                    {tr(
                      locale,
                      "Record digest-bound confirmation decision",
                      "다이제스트 바인딩 확인 결정 기록",
                    )}
                  </h2>
                  <label>
                    {tr(locale, "Decision", "결정 종류")}
                    <select
                      class="input"
                      aria-label="Confirmation decision"
                      value={decision}
                      onChange={(event) => {
                        setDecision(event.currentTarget.value as "confirm" | "hold");
                        setConfirmationText("");
                      }}
                    >
                      <option value="confirm">
                        {tr(
                          locale,
                          "Confirm destructive change for exact plan digest",
                          "정확한 계획 다이제스트에 대한 파괴적 변경 확인",
                        )}
                      </option>
                      <option value="hold">
                        {tr(locale, "Hold plan and add suppression", "계획 보류 및 억제 추가")}
                      </option>
                    </select>
                  </label>
                  <label>
                    {tr(locale, "Reason code", "사유 코드")}
                    <input
                      class="input mono"
                      aria-label="Confirmation reason code"
                      required
                      pattern="[a-z][a-z0-9_]{0,95}"
                      value={reason}
                      onInput={(event) => setReason(event.currentTarget.value)}
                    />
                  </label>
                  <p class="note" style={{ overflowWrap: "anywhere" }}>
                    {tr(locale, "Expected confirmation:", "필수 확인 문구:")}{" "}
                    <code class="mono">{expectedPhrase}</code>
                  </p>
                  <div class="acts">
                    <button
                      type="button"
                      class="btn"
                      disabled={busy || confirmationText === expectedPhrase}
                      onClick={() => setConfirmationText(expectedPhrase)}
                    >
                      {tr(locale, "Fill reviewed confirmation", "검토된 확인 문구 자동 입력")}
                    </button>
                  </div>
                  <label>
                    {tr(locale, "Exact confirmation", "정확한 확인 문구")}
                    <input
                      class="input mono"
                      aria-label="Exact confirmation phrase"
                      required
                      autoComplete="off"
                      value={confirmationText}
                      onInput={(event) => setConfirmationText(event.currentTarget.value)}
                    />
                  </label>
                  <div class="acts">
                    <button
                      type="submit"
                      class={`btn ${decision === "confirm" ? "danger" : "primary"}`}
                      disabled={busy || confirmationText !== expectedPhrase}
                    >
                      {busy
                        ? tr(locale, "Recording decision...", "결정 기록 중...")
                        : decision === "confirm"
                        ? tr(locale, "Confirm replacement", "교체/삭제 확인")
                        : tr(locale, "Hold Plan", "계획 보류")}
                    </button>
                  </div>
                </form>
              )}
            </div>
          );
        }}
      </AsyncBoundary>
    </div>
  );
}
