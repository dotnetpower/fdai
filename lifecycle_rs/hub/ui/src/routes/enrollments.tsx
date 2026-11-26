import { useEffect, useState } from "preact/hooks";
import { hubApi, HubApiError, type BindableInstallation } from "../api";
import { effectiveSelection, isSelectable, optionLabel } from "../bindable-installations";
import { enrollmentRequester } from "../enrollment-requester";
import { AsyncBoundary } from "../components/async-boundary";
import { Link } from "../components/link";
import { formatTimestamp } from "../format";
import { useAsync } from "../hooks/use-async";
import { tr, useHubLocale } from "../locale";
import { enrollmentPath, enrollmentsPath, navigate } from "../router";

const APPROVER_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._@-]{0,127}$/;

export function isValidApprover(value: string): boolean {
  return APPROVER_PATTERN.test(value.trim());
}

export interface SortableEnrollment {
  readonly installation_id: string;
  readonly requested_at: string;
  readonly request_id?: string | null;
  readonly channel?: string;
}

export function sortEnrollments<T extends SortableEnrollment>(rows: readonly T[]): T[] {
  return [...rows].sort((a, b) => {
    const byRequestedAt = a.requested_at.localeCompare(b.requested_at);
    if (byRequestedAt !== 0) return byRequestedAt;
    const byRequestId = (a.request_id ?? "").localeCompare(b.request_id ?? "");
    if (byRequestId !== 0) return byRequestId;
    return a.installation_id.localeCompare(b.installation_id);
  });
}

export function filterAndSortEnrollments<T extends SortableEnrollment>(
  rows: readonly T[],
  query = "",
): T[] {
  const needle = query.trim().toLowerCase();
  const filtered =
    needle === ""
      ? rows
      : rows.filter(
          (row) =>
            row.installation_id.toLowerCase().includes(needle) ||
            (row.request_id ?? "").toLowerCase().includes(needle) ||
            (row.channel ?? "").toLowerCase().includes(needle),
        );
  return sortEnrollments(filtered);
}

export function EnrollmentsPage({ selectedId }: { selectedId: string | null }) {
  return selectedId === null ? (
    <EnrollmentsList />
  ) : (
    <EnrollmentDetail key={selectedId} installationId={selectedId} />
  );
}

function EnrollmentsList() {
  const [locale] = useHubLocale();
  const pending = useAsync(() => hubApi.listPendingEnrollments(), []);

  return (
    <>
      <div class="m-head">
        <h1>{tr(locale, "Enrollment requests", "등록 요청")}</h1>
        <div class="acts">
          <button type="button" class="btn" onClick={pending.reload} disabled={pending.status === "loading"}>
            {tr(locale, "Refresh", "새로 고침")}
          </button>
        </div>
      </div>
      <EnrollmentRequestForm onSubmitted={pending.reload} />
      <AsyncBoundary state={pending} layout="table">
        {({ enrollments }) =>
          enrollments.length === 0 ? (
            <p class="empty">
              {tr(locale, "No enrollment requests pending.", "대기 중인 등록 요청이 없습니다.")}
            </p>
          ) : (
            <div class="table-scroll"><table class="t">
              <thead>
                <tr>
                  <th>{tr(locale, "Installation", "설치 환경")}</th>
                  <th>{tr(locale, "Requested", "요청 시각")}</th>
                  <th>{tr(locale, "Requested by", "요청 주체")}</th>
                  <th>{tr(locale, "Channel", "채널")}</th>
                  <th>{tr(locale, "Entities", "엔티티 수")}</th>
                </tr>
              </thead>
              <tbody>
                {filterAndSortEnrollments(enrollments).map((request) => (
                  <tr key={request.installation_id}>
                    <td>
                      <Link href={enrollmentPath(request.installation_id)}>
                        {request.installation_id}
                      </Link>
                    </td>
                    <td>{formatTimestamp(request.requested_at, undefined, locale)}</td>
                    <td>
                      {enrollmentRequester(request, locale).fromAgent
                        ? tr(locale, "Installation Agent", "설치 에이전트")
                        : tr(locale, "Operator or file", "운영자 또는 파일")}
                    </td>
                    <td class="mono">{request.channel}</td>
                    <td>{request.entities.length}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )
        }
      </AsyncBoundary>
    </>
  );
}

function EnrollmentRequestForm({ onSubmitted }: { onSubmitted: () => void }) {
  const [locale] = useHubLocale();
  const [installationId, setInstallationId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);
  // undefined while loading; null when the Hub offers no bound list (404, error, or empty),
  // which keeps the typed Installation ID input available.
  const [bindable, setBindable] = useState<readonly BindableInstallation[] | null | undefined>(undefined);
  const [refreshes, setRefreshes] = useState(0);

  useEffect(() => {
    let current = true;
    hubApi.listBindableInstallations().then(
      list => { if (current) setBindable(list && list.length > 0 ? list : null); },
      () => { if (current) setBindable(null); },
    );
    return () => { current = false; };
  }, [refreshes]);

  const selected = bindable ? effectiveSelection(bindable, installationId) : installationId.trim();

  async function submit() {
    if (!file || busy || !selected) return;
    setBusy(true);
    setError("");
    setSubmitted(false);
    try {
      await hubApi.requestEnrollment(selected, file);
      setSubmitted(true);
      onSubmitted();
      setRefreshes(value => value + 1);
    } catch (cause) {
      setError(cause instanceof HubApiError
        ? tr(
            locale,
            `${cause.message}. Refresh before retrying. Check the installation binding and request freshness.`,
            `${cause.message}. 새로 고침한 뒤 다시 시도하세요. 설치 바인딩과 요청 유효 시간을 확인하세요.`,
          )
        : tr(
            locale,
            `${cause instanceof Error ? cause.message : "Submission could not be confirmed."} Refresh before retrying.`,
            `${cause instanceof Error ? cause.message : "제출 결과를 확인할 수 없습니다."} 새로 고침한 뒤 다시 시도하세요.`,
          ));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form class="catalog-panel" onSubmit={event => {
      event.preventDefault();
      void submit();
    }}>
      <h2 class="panel-title">
        {tr(locale, "Submit a signed enrollment request", "서명된 등록 요청 제출")}
      </h2>
      <p class="note">{tr(
        locale,
        "Remote development only. The installation must already be bound to its Agent identity. Upload a request signed within five minutes, never a private key. Submission does not approve enrollment, manage Entities, or apply a Plan.",
        "원격 개발 프로필 전용입니다. 설치 환경이 먼저 에이전트 신원에 바인딩되어 있어야 합니다. 개인 키가 아닌 5분 이내에 서명된 요청 파일만 업로드하세요. 제출만으로 등록 승인, 엔티티 관리 또는 계획 적용이 이루어지지는 않습니다.",
      )}</p>
      <p class="note">{tr(
        locale,
        "Create the file with `fdai-lifecycle-hub sign-enrollment` inside the installation boundary; it prints the key id to compare at approval. An installation whose Agent can reach this Hub may instead run `fdai-lifecycle-agent enroll`: the Agent submits the pending request itself and it appears in the list below.",
        "설치 경계 내부에서 `fdai-lifecycle-hub sign-enrollment` 명령으로 파일을 생성하세요 (승인 시 대조할 키 ID가 출력됩니다). 에이전트가 이 Hub에 연결할 수 있는 설치 환경에서는 `fdai-lifecycle-agent enroll`을 실행해 에이전트가 직접 대기 요청을 제출할 수도 있습니다.",
      )}</p>
      {bindable === undefined && (
        <p class="note" role="status">
          {tr(locale, "Loading bound installations...", "바인딩된 설치 환경을 불러오는 중...")}
        </p>
      )}
      {bindable && <>
        <label>{tr(locale, "Installation", "설치 환경")}
          <select class="input" aria-label={tr(locale, "Installation", "설치 환경")} disabled={busy} value={selected} onChange={event => {
            setInstallationId(event.currentTarget.value);
            setSubmitted(false);
            setError("");
          }}>
            {selected === "" && (
              <option value="" disabled>
                {tr(locale, "No installation can take a new request", "새 요청을 받을 수 있는 설치 환경 없음")}
              </option>
            )}
            {bindable.map(item => <option key={item.installation_id} value={item.installation_id}
              disabled={!isSelectable(item)}>{optionLabel(item, locale)}</option>)}
          </select>
        </label>
        {selected === "" && <p class="note">{tr(
          locale,
          "Every bound installation already has a pending request or is enrolled.",
          "모든 바인딩된 설치 환경에 이미 대기 중인 요청이 있거나 등록이 완료되었습니다.",
        )}</p>}
      </>}
      {bindable === null && <label>{tr(locale, "Installation ID", "설치 ID")}
        <input class="input" required pattern="[a-z][a-z0-9-]{0,62}" maxLength={63}
          disabled={busy} value={installationId} onInput={event => {
            setInstallationId(event.currentTarget.value);
            setSubmitted(false);
            setError("");
          }} />
      </label>}
      <label>{tr(locale, "Signed request JSON", "서명된 요청 JSON 파일")}
        <input class="input" required type="file" accept=".json,application/json" disabled={busy}
          onChange={event => {
            setFile(event.currentTarget.files?.[0] ?? null);
            setSubmitted(false);
            setError("");
          }} />
      </label>
      <button class="btn primary" type="submit" disabled={busy || !file || submitted || !selected}>
        {busy
          ? tr(locale, "Submitting request...", "요청 제출 중...")
          : tr(locale, "Submit request", "요청 제출")}
      </button>
      {error && <p class="banner fail" role="alert">{error}</p>}
      {submitted && <p class="banner" role="status">{tr(
        locale,
        "Request submitted as pending. Verify the installation key ID independently before approving enrollment.",
        "요청이 대기 상태로 제출되었습니다. 등록을 승인하기 전에 설치 키 ID를 별도 경로로 검증하세요.",
      )}</p>}
    </form>
  );
}

function EnrollmentDetail({ installationId }: { installationId: string }) {
  const [locale] = useHubLocale();
  const pending = useAsync(() => hubApi.getPendingEnrollment(installationId), [installationId]);
  const [approver, setApprover] = useState("");
  const [reason, setReason] = useState("");
  // Deliberately not pre-filled from the request: the approver must retype the key id they
  // verified through an independent, out-of-band channel. Auto-submitting the id the request
  // already claims for itself would make the check a no-op (it would always match itself).
  const [keyId, setKeyId] = useState("");
  const [busy, setBusy] = useState<"accept" | "reject" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function decide(kind: "accept" | "reject", action: (approver: string) => Promise<unknown>) {
    setBusy(kind);
    setError(null);
    try {
      await action(approver.trim());
      navigate(enrollmentsPath());
    } catch (cause) {
      setError(
        cause instanceof HubApiError
          ? cause.message
          : tr(
              locale,
              "Could not confirm the decision. Refresh the request before trying again.",
              "결정 결과를 확인할 수 없습니다. 요청을 새로 고침한 뒤 다시 시도하세요.",
            ),
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <AsyncBoundary state={pending}>
      {(request) => (
        <>
          <div class="crumb">
            <Link href={enrollmentsPath()}>{tr(locale, "Enrollment requests", "등록 요청")}</Link> ›{" "}
            {request.installation_id}
          </div>
          <div class="m-head">
            <div>
              <h1>{request.installation_id}</h1>
              <div class="sub">
                {enrollmentRequester(request, locale).label} ·{" "}
                {formatTimestamp(request.requested_at, undefined, locale)}
              </div>
            </div>
          </div>

          <div class="callout">
            <strong>
              {tr(locale, "Verify the installation before accepting", "수락하기 전에 설치 환경을 검증하세요")}
            </strong>
            <p>
              {locale === "ko" ? (
                <>
                  수락하기 전에 이 화면 외부(예: 설치 환경 자체의 등록 출력)에서 확인한 키 ID와{" "}
                  <code>{request.installation_key_id}</code> 값을 대조하세요. 화면에 표시된 키 ID만 보고 그대로 수락하지 마세요.
                </>
              ) : (
                <>
                  Verify <code>{request.installation_key_id}</code> against the key id you obtained
                  outside this screen (for example, from the installation's own enrollment output)
                  before accepting. Do not accept solely because this screen shows a key id.
                </>
              )}
            </p>
            {enrollmentRequester(request, locale).fromAgent && (
              <p>
                {tr(
                  locale,
                  "The installation Agent can propose this request but cannot accept or reject it. Your decision is still required.",
                  "설치 에이전트는 이 요청을 제안할 수만 있으며 직접 수락하거나 거부할 수 없습니다. 운영자의 결정이 필요합니다.",
                )}
              </p>
            )}
          </div>

          <div class="kv">
            <div>
              <div class="k">{tr(locale, "Channel", "채널")}</div>
              <div class="v small mono">{request.channel}</div>
            </div>
            <div>
              <div class="k">{tr(locale, "Version range", "버전 범위")}</div>
              <div class="v small mono">{request.version_range}</div>
            </div>
            <div>
              <div class="k">{tr(locale, "Region", "리전")}</div>
              <div class="v small">{request.region}</div>
            </div>
            <div>
              <div class="k">{tr(locale, "Schema revision", "스키마 개정 번호")}</div>
              <div class="v small">{request.schema_revision}</div>
            </div>
          </div>

          <section aria-label={tr(locale, "Discovered Entities", "발견된 엔티티")}>
            <h2 class="panel-title">
              {tr(locale, "Discovered Entities", "발견된 엔티티")}{" "}
              <span class="hint">
                {tr(
                  locale,
                  "All start unmanaged after acceptance",
                  "수락 직후에는 모두 비관리 상태로 시작합니다",
                )}
              </span>
            </h2>
            <div class="table-scroll"><table class="t">
              <thead>
                <tr>
                  <th>{tr(locale, "Name", "이름")}</th>
                  <th>{tr(locale, "Kind", "종류")}</th>
                  <th>{tr(locale, "Reported release", "보고된 릴리스")}</th>
                </tr>
              </thead>
              <tbody>
                {request.entities.map((entity) => (
                  <tr key={entity.entity_id}>
                    <td>{entity.entity_id}</td>
                    <td>{entity.kind}</td>
                    <td>{entity.release_id ?? tr(locale, "Not reported", "미보고")}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          </section>

          <section aria-label={tr(locale, "Decision", "등록 결정")}>
            <h2 class="panel-title">{tr(locale, "Enrollment decision", "등록 결정")}</h2>
            <p class="note">
              {tr(
                locale,
                "Accepting enrolls this installation; it does not manage its Entities or deploy a release.",
                "수락하면 이 설치 환경이 등록되지만, 엔티티가 즉시 관리 상태로 전환되거나 릴리스가 배포되지는 않습니다.",
              )}
            </p>
            <fieldset disabled={busy !== null} class="decision-fields">
              <div class="form-row">
                <label class="lbl" for="approver">
                  {tr(locale, "Approver", "승인자")}
                </label>
                <input
                  id="approver"
                  class="input"
                  value={approver}
                  required
                  pattern="[A-Za-z0-9][A-Za-z0-9._@-]{0,127}"
                  maxLength={128}
                  aria-describedby="approver-help"
                  placeholder={tr(
                    locale,
                    "name or email (e.g. operator@example.com)",
                    "이름 또는 이메일 (예: operator@example.com)",
                  )}
                  onInput={(event) => setApprover(event.currentTarget.value)}
                />
              </div>
              <p class="note" id="approver-help">
                {tr(
                  locale,
                  "Use 1-128 ASCII letters, digits, dots, underscores, hyphens, or @ (must start with a letter or digit).",
                  "영문자 또는 숫자로 시작하는 1~128자의 ASCII 영문자, 숫자, 점(.), 밑줄(_), 하이픈(-), @를 사용하세요.",
                )}
              </p>
              {approver.trim().length > 0 && !isValidApprover(approver) && (
                <p class="banner fail" role="alert">
                  {tr(
                    locale,
                    "Approver must match [A-Za-z0-9][A-Za-z0-9._@-]{0,127}.",
                    "승인자 형식은 [A-Za-z0-9][A-Za-z0-9._@-]{0,127} 규칙과 일치해야 합니다.",
                  )}
                </p>
              )}
              <div class="form-row">
                <label class="lbl" for="key-id">
                  {tr(locale, "Verified key id", "검증된 키 ID")}
                </label>
                <input
                  id="key-id"
                  class="input"
                  value={keyId}
                  aria-describedby="key-help"
                  placeholder={tr(
                    locale,
                    "the key id you verified out of band",
                    "별도 경로로 확인한 키 ID",
                  )}
                  onInput={(event) => setKeyId(event.currentTarget.value)}
                />
              </div>
              <p class="note" id="key-help">
                {tr(
                  locale,
                  "Required only to accept. Use the independently verified key id.",
                  "수락 시에만 필수입니다. 독립적으로 확인한 키 ID를 입력하세요.",
                )}
              </p>
              <div class="form-row">
                <label class="lbl" for="reason">
                  {tr(locale, "Rejection reason", "거부 사유")}
                </label>
                <input
                  id="reason"
                  class="input"
                  value={reason}
                  placeholder={tr(
                    locale,
                    "a reason code, e.g. unknown_key",
                    "사유 코드 (예: unknown_key)",
                  )}
                  aria-describedby="rejection-help"
                  onInput={(event) => setReason(event.currentTarget.value)}
                />
              </div>
              <p class="note" id="rejection-help">
                {tr(
                  locale,
                  "Required only to reject. The installation ID remains reserved after rejection.",
                  "거부 시에만 필수입니다. 거부 후에도 해당 설치 ID는 예약된 상태로 유지됩니다.",
                )}
              </p>
            </fieldset>
            {error && <p class="banner fail" role="alert">{error}</p>}
            <div role="status" class="note">
              {busy === "accept"
                ? tr(locale, "Accepting enrollment...", "등록 수락 처리 중...")
                : busy === "reject"
                ? tr(locale, "Rejecting enrollment...", "등록 거부 처리 중...")
                : ""}
            </div>
            <div class="acts">
              <button
                type="button"
                class="btn"
                disabled={busy !== null || !isValidApprover(approver) || reason.trim().length === 0}
                onClick={() =>
                  decide("reject", (who) => hubApi.rejectEnrollment(installationId, who, reason.trim()))
                }
              >
                {busy === "reject" && <span class="spinner" aria-hidden="true" />}
                {tr(locale, "Reject", "거부")}
              </button>
              <button
                type="button"
                class="btn primary"
                disabled={busy !== null || !isValidApprover(approver) || keyId.trim().length === 0}
                onClick={() =>
                  decide("accept", (who) => hubApi.approveEnrollment(installationId, who, keyId.trim()))
                }
              >
                {busy === "accept" && <span class="spinner" aria-hidden="true" />}
                {tr(locale, "Accept enrollment", "등록 수락")}
              </button>
            </div>
          </section>
        </>
      )}
    </AsyncBoundary>
  );
}
