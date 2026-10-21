import { useEffect, useRef, useState } from "preact/hooks";
import { request } from "../api";

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
        setError("Accepted catalog changed. Refresh and review before local curation.");
        return;
      }
      setState(value);
    }).catch(failure => {
      if (current) setError(failure instanceof Error ? failure.message : "Local curation is unavailable.");
    });
    return () => { current = false; generation.current += 1; };
  }, [acceptedDigest]);
  const release = state?.available_releases.find(value => value.release_id === releaseId);
  const target = localChannelConfirmation(releaseId, channel);

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (!state || !release || busy || error) return;
    if (state.accepted_sha256 !== acceptedDigest) {
      setError("Accepted catalog changed. Refresh and review before local curation.");
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
        throw new Error("Accepted catalog changed. Refresh retained evidence before retrying.");
      }
      setState(result);
      setConfirmation(""); setReason("");
    } catch (failure) {
      if (submittedGeneration === generation.current) {
        setError(failure instanceof Error ? failure.message : "Curation rejected. Refresh and review.");
      }
    } finally {
      if (submittedGeneration === generation.current) setBusy(false);
    }
  }

  return <section class="catalog-panel local-channels">
    <h2 class="panel-title">Customer-local channel eligibility</h2>
    <p class="note">Add an exact imported RELEASE member to a local-name channel.
      This does not change any installation subscription, approve a Plan or grant execution authority.</p>
    {error && <p class="banner fail" role="alert">{error} Refresh this page and review the current pin before retrying.</p>}
    {!state && !error && <p role="status">Loading verified local eligibility...</p>}
    {state && <>
      <p class="note" aria-live="polite">Local revision {state.revision}; accepted catalog revision {state.source_revision}.</p>
      {state.entries.length === 0 ? <p>No local members have been approved.</p> : <ul class="local-channel-members">
        {state.entries.map(entry => <li key={entry.revision}>
          <strong>{entry.channel} / {entry.release_id}</strong>
          <p>{error ? "Held: refresh to verify current eligibility" : entry.eligible ? "Eligible for planning only" : `Held: ${entry.hold_reason}`}</p>
          <p class="note">Revision {entry.revision}; {entry.actor}; {entry.reason}</p>
        </li>)}
      </ul>}
      <form onSubmit={submit}>
        <label>Local channel <input class="input" required maxLength={64}
          pattern="local-[a-z0-9]+(-[a-z0-9]+)*" placeholder="local-reviewed"
          value={channel} onInput={event => setChannel(event.currentTarget.value)} /></label>
        <p class="note">Lowercase letters, numbers and single hyphens after local-; 64 characters maximum.</p>
        <label>Imported RELEASE member <select class="input" required value={releaseId}
          onChange={event => setReleaseId(event.currentTarget.value)}>
          <option value="">Select an independently imported release</option>
          {state.available_releases.map(value => <option key={value.release_id}>{value.release_id}</option>)}
        </select></label>
        {release && <p class="note mono">Exact Release digest: {release.release_digest}</p>}
        {state.available_releases.length === 0 && <p class="note">No current RELEASE member is eligible. Review source membership, recall and trust.</p>}
        <label>Curation reason <input class="input" required minLength={3} maxLength={500}
          value={reason} onInput={event => setReason(event.currentTarget.value)} /></label>
        <label>Type <span class="mono">{target}</span> to confirm
          <input class="input" required autoComplete="off" value={confirmation}
            onInput={event => setConfirmation(event.currentTarget.value)} /></label>
        <button class="btn primary" type="submit"
          disabled={busy || !!error || !release || !channel || state.accepted_sha256 !== acceptedDigest || confirmation !== target || reason.trim().length < 3}>
          {busy ? "Recording local membership..." : "Add reviewed local member"}
        </button>
      </form>
    </>}
  </section>;
}
