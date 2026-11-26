import { useEffect, useRef, useState } from "preact/hooks";
import { request } from "../api";
import { tr, useHubLocale } from "../locale";

type Entry = {
  revision: number; channel: string; release_id: string; release_digest: string;
  actor: string; reason: string; eligible: boolean; hold_reason: string | null;
};
export type LocalChannels = {
  revision: number; digest: string; accepted_sha256: string; source_revision: number;
  entries: Entry[]; available_releases: { release_id: string; release_digest: string }[];
  execution_authority: false;
};

export function localChannelConfirmation(release: string, channel: string): string {
  return `add ${release} to ${channel}`;
}

export function LocalChannelsPanel({ acceptedDigest }: { acceptedDigest: string }) {
  const [locale] = useHubLocale();
  const [state, setState] = useState<LocalChannels | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [channel, setChannel] = useState("");
  const [releaseId, setReleaseId] = useState("");
  const [reason, setReason] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const generation = useRef(0);
  useEffect(() => {
    let current = true;
    generation.current += 1;
    setState(null); setError(""); setBusy(false); setReleaseId(""); setConfirmation("");
    void request<LocalChannels>("/v1/catalog/local-channels", { signal: AbortSignal.timeout(10_000) }).then(value => {
      if (!current) return;
      if (value.accepted_sha256 !== acceptedDigest) {
        setError(tr(
          locale,
          "Accepted catalog changed. Refresh and review before local curation.",
          "수락된 카탈로그가 변경되었습니다. 로컬 채널을 구성하기 전에 새로 고침하여 확인하세요.",
        ));
        return;
      }
      setState(value);
    }).catch(failure => {
      if (current) {
        setError(
          failure instanceof Error
            ? failure.message
            : tr(locale, "Local curation is unavailable.", "로컬 채널 구성을 사용할 수 없습니다."),
        );
      }
    });
    return () => { current = false; generation.current += 1; };
  }, [acceptedDigest]);
  const release = state?.available_releases.find(value => value.release_id === releaseId);
  const target = localChannelConfirmation(releaseId, channel);

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (!state || !release || busy || error) return;
    if (state.accepted_sha256 !== acceptedDigest) {
      setError(tr(
        locale,
        "Accepted catalog changed. Refresh and review before local curation.",
        "수락된 카탈로그가 변경되었습니다. 로컬 채널을 구성하기 전에 새로 고침하여 확인하세요.",
      ));
      return;
    }
    const submittedGeneration = generation.current;
    setBusy(true); setError("");
    try {
      const result = await request<LocalChannels>("/v1/catalog/local-channels", {
        method: "POST",
        signal: AbortSignal.timeout(10_000),
        body: JSON.stringify({
          revision: state.revision, accepted_sha256: state.accepted_sha256,
          channel, release_id: release.release_id, release_digest: release.release_digest,
          reason, confirmation,
        }),
      });
      if (submittedGeneration !== generation.current) return;
      if (result.accepted_sha256 !== acceptedDigest) {
        throw new Error(tr(
          locale,
          "Accepted catalog changed. Refresh retained evidence before retrying.",
          "수락된 카탈로그가 변경되었습니다. 보존된 근거를 새로 고침한 뒤 다시 시도하세요.",
        ));
      }
      setState(result);
      setConfirmation(""); setReason("");
    } catch (failure) {
      if (submittedGeneration === generation.current) {
        setError(
          failure instanceof Error
            ? failure.message
            : tr(locale, "Curation rejected. Refresh and review.", "로컬 채널 구성이 거부되었습니다. 새로 고침하여 확인하세요."),
        );
      }
    } finally {
      if (submittedGeneration === generation.current) setBusy(false);
    }
  }

  return <section class="catalog-panel local-channels">
    <h2 class="panel-title">{tr(locale, "Customer-local channel eligibility", "고객 로컬 채널 적격성 구성")}</h2>
    <p class="note">{tr(
      locale,
      "Add an exact imported RELEASE member to a local-name channel. This does not change any installation subscription, approve a Plan or grant execution authority.",
      "가져온 RELEASE 채널의 특정 릴리스를 로컬 이름 채널에 추가합니다. 설치 구독 변경, 계획 승인 또는 실행 권한 부여는 수행하지 않습니다.",
    )}</p>
    {error && <p class="banner fail" role="alert">{error} {tr(
      locale,
      "Refresh this page and review the current pin before retrying.",
      "이 화면을 새로 고침하고 현재 고정값을 확인한 뒤 다시 시도하세요.",
    )}</p>}
    {!state && !error && <p role="status">{tr(locale, "Loading verified local eligibility...", "검증된 로컬 채널 적격성을 불러오는 중...")}</p>}
    {state && <>
      <p class="note" aria-live="polite">{tr(
        locale,
        `Local revision ${state.revision}; accepted catalog revision ${state.source_revision}.`,
        `로컬 개정 번호 ${state.revision}; 수락된 카탈로그 개정 번호 ${state.source_revision}.`,
      )}</p>
      {state.entries.length === 0 ? <p>{tr(locale, "No local members have been approved.", "승인된 로컬 채널 릴리스가 없습니다.")}</p> : <ul class="local-channel-members">
        {state.entries.map(entry => <li key={entry.revision}>
          <strong>{entry.channel} / {entry.release_id}</strong>
          <p>{error
            ? tr(locale, "Held: refresh to verify current eligibility", "보류됨: 현재 적격성을 확인하려면 새로 고침하세요")
            : entry.eligible
            ? tr(locale, "Eligible for planning only", "계획 수립에 한해 적격")
            : `${tr(locale, "Held:", "보류됨:")} ${entry.hold_reason}`}</p>
          <p class="note">{tr(locale, "Revision", "개정 번호")} {entry.revision}; {entry.actor}; {entry.reason}</p>
        </li>)}
      </ul>}
      <form onSubmit={submit}>
        <label>{tr(locale, "Local channel", "로컬 채널")} <input class="input" required maxLength={64}
          pattern="local-[a-z0-9]+(-[a-z0-9]+)*" placeholder="local-reviewed"
          value={channel} onInput={event => setChannel(event.currentTarget.value)} /></label>
        <p class="note">{tr(
          locale,
          "Lowercase letters, numbers and single hyphens after local-; 64 characters maximum.",
          "local- 접두사 뒤에 영문 소문자, 숫자, 단일 하이픈만 사용할 수 있습니다 (최대 64자).",
        )}</p>
        <label>{tr(locale, "Imported RELEASE member", "가져온 RELEASE 채널 릴리스")} <select class="input" required value={releaseId}
          onChange={event => setReleaseId(event.currentTarget.value)}>
          <option value="">{tr(locale, "Select an independently imported release", "독립적으로 가져온 릴리스 선택")}</option>
          {state.available_releases.map(value => <option key={value.release_id}>{value.release_id}</option>)}
        </select></label>
        {release && <p class="note mono">{tr(locale, "Exact Release digest:", "정확한 릴리스 다이제스트:")} {release.release_digest}</p>}
        {state.available_releases.length === 0 && <p class="note">{tr(
          locale,
          "No current RELEASE member is eligible. Review source membership, recall and trust.",
          "현재 적격한 RELEASE 채널 릴리스가 없습니다. 원본 채널 소속, 회수 여부 및 신뢰 설정을 확인하세요.",
        )}</p>}
        <label>{tr(locale, "Curation reason", "구성 사유")} <input class="input" required minLength={3} maxLength={500}
          value={reason} onInput={event => setReason(event.currentTarget.value)} /></label>
        <label>{locale === "ko"
          ? <><span class="mono">{target}</span> 확인 문구를 입력하세요</>
          : <>Type <span class="mono">{target}</span> to confirm</>}
          <input class="input" required autoComplete="off" value={confirmation}
            onInput={event => setConfirmation(event.currentTarget.value)} /></label>
        <button class="btn primary" type="submit"
          disabled={busy || !!error || !release || !channel || state.accepted_sha256 !== acceptedDigest || confirmation !== target || reason.trim().length < 3}>
          {busy
            ? tr(locale, "Recording local membership...", "로컬 채널 소속 기록 중...")
            : tr(locale, "Add reviewed local member", "검토된 로컬 릴리스 추가")}
        </button>
      </form>
    </>}
  </section>;
}
