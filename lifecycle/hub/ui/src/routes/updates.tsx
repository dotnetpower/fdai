import { useState } from "preact/hooks";
import {
  hubApi, type IntegrityState, type UpdateCandidate, type UpdateCheckRecord, type UpdateStatus,
} from "../api";
import { AsyncBoundary } from "../components/async-boundary";
import { Badge } from "../components/badge";
import { Link } from "../components/link";
import { formatRelative, formatTimestamp } from "../format";
import { useAsync } from "../hooks/use-async";
import {
  canApply, describeActionError, describeDetail, describeIntegrity, describePlanOutcome,
  describeSchedule, describeVersions, hasUrgentRecall, isTimestampExpired, outcomeBadge, shortDigest,
  summarizeChange,
} from "../update-status";

type Notice = { kind: "error" | "info"; message: string };

function Digest({ sha256 }: { sha256: string }) {
  return <span class="mono" title={sha256}>{shortDigest(sha256)}</span>;
}

function Expiry({ iso }: { iso: string }) {
  return <>{formatRelative(iso)} ({formatTimestamp(iso)})</>;
}

function Integrity({ state }: { state: IntegrityState }) {
  const last = state.last;
  const view = last ? describeIntegrity(last) : null;
  // A persisted expiry is judged now, so an old check cannot make stale metadata look fresh.
  const staleNow = isTimestampExpired(state) && view?.badge.variant === "ok";
  const badge = staleNow
    ? { label: "Timestamp expired", variant: "warn" as const }
    : view?.badge ?? { label: "Not checked yet", variant: "mute" as const };
  const lines = staleNow
    ? ["The signed timestamp has expired. Only recall roll-off Plans are issued until fresh metadata arrives."]
    : view && view.badge.variant !== "ok" ? view.lines : [];
  return <>
    <Badge variant={badge.variant}>{badge.label}</Badge>
    <p class="note">{describeVersions(state)}.
      {state.timestamp_expires_at
        ? <> Timestamp expires <Expiry iso={state.timestamp_expires_at} />.</> : null}</p>
    {lines.map(line => <p class="note" key={line}>{line}</p>)}
  </>;
}

function CheckSummary({ record }: { record: UpdateCheckRecord }) {
  const badge = outcomeBadge(record.outcome);
  // The candidate panel below lists the reasons, so the summary does not repeat them.
  const lines = record.outcome === "review_required" && record.candidate
    ? ["A new catalog is waiting for your review."]
    : describeDetail(record.outcome, record.detail);
  const integrity = record.outcome === "failed" && record.integrity && !record.integrity.verified
    ? describeIntegrity(record.integrity).lines : [];
  return <>
    <span>{formatTimestamp(record.checked_at)} <Badge variant={badge.variant}>{badge.label}</Badge></span>
    {lines.length === 1
      ? <p class="note">{lines[0]}</p>
      : <ul class="update-list">{lines.map(line => <li key={line}>{line}</li>)}</ul>}
    {integrity.map(line => <p class="note" key={line}>{line}</p>)}
  </>;
}

function Summary({ status }: { status: UpdateStatus }) {
  const { accepted, last_check: check, authorization } = status;
  return <section class="kv update-kv" aria-label="Update status">
    <div>
      <div class="k">Accepted catalog</div>
      <div class="v small">{accepted
        ? <>Revision {accepted.revision}, <Digest sha256={accepted.sha256} />, {accepted.release_count}{" "}
          {accepted.release_count === 1 ? "release" : "releases"}<br />
          Expires <Expiry iso={accepted.expires_at} /></>
        : "No catalog accepted yet"}</div>
    </div>
    <div>
      <div class="k">Last check</div>
      <div class="v small">{check ? <CheckSummary record={check} /> : "No check has run yet"}</div>
    </div>
    {status.integrity && <div>
      <div class="k">Catalog integrity</div>
      <div class="v small"><Integrity state={status.integrity} /></div>
    </div>}
    {status.mode === "auto" && <div>
      <div class="k">Standing authorization</div>
      <div class="v small">{authorization
        ? <>{authorization.authorized_by}, expires <Expiry iso={authorization.expires_at} />{" "}
          <Badge variant={authorization.valid ? "ok" : "fail"}>{authorization.valid ? "Valid" : "Expired"}</Badge></>
        : <Badge variant="warn">Missing</Badge>}</div>
    </div>}
  </section>;
}

function ChangeSummary({ candidate }: { candidate: UpdateCandidate }) {
  const sections = summarizeChange(candidate.change);
  if (sections.length === 0) {
    return <p class="note">No release or channel differences from the accepted catalog.</p>;
  }
  return <dl class="update-change">
    {sections.map(section => <div key={section.label}>
      <dt>{section.label}</dt>
      <dd><ul class="update-list">{section.items.map(item => <li key={item}>{item}</li>)}</ul></dd>
    </div>)}
  </dl>;
}

function CandidatePanel({ record, busy, onApply }: {
  record: UpdateCheckRecord; busy: boolean; onApply: (candidate: UpdateCandidate) => void;
}) {
  const candidate = record.candidate!;
  const reasons = describeDetail(record.outcome, record.detail);
  return <section class="catalog-panel" aria-label="Candidate catalog">
    <h2 class="panel-title">Candidate catalog
      <Badge variant={candidate.signature_verified ? "ok" : "fail"}>
        {candidate.signature_verified ? "Signature verified" : "Signature not verified"}
      </Badge></h2>
    {hasUrgentRecall(candidate.change) && <div class="banner fail" role="alert">
      <strong>Urgent: this catalog adds recalls</strong>
      <span>{candidate.change.new_recalls.length === 1
        ? "A release or capability has been recalled."
        : `${candidate.change.new_recalls.length} recalls have been added.`} Review them below.</span>
    </div>}
    <dl class="catalog-trust">
      <dt>Revision</dt><dd>{candidate.revision}</dd>
      <dt>Digest</dt><dd><Digest sha256={candidate.sha256} /></dd>
      <dt>Expires</dt><dd><Expiry iso={candidate.expires_at} /></dd>
      <dt>Signature verified</dt><dd>{candidate.signature_verified
        ? `Yes${candidate.key_id ? ` (key ${candidate.key_id})` : ""}` : "No"}</dd>
    </dl>
    {candidate.integrity && <CandidateIntegrity candidate={candidate} />}
    <h3 class="update-subtitle">Why a review is needed</h3>
    <ul class="update-list">{reasons.map(line => <li key={line}>{line}</li>)}</ul>
    <h3 class="update-subtitle">What changes</h3>
    <ChangeSummary candidate={candidate} />
    {canApply(record)
      ? <div class="acts">
        <button type="button" class="btn primary" disabled={busy} onClick={() => onApply(candidate)}>
          Review and apply
        </button>
      </div>
      : candidate.signature_verified
        ? <p class="note" role="note">This candidate cannot be applied now because the vendor's signed
          timestamp has expired. Only recall changes are accepted until fresh metadata arrives.</p>
        : <p class="note" role="note">This candidate cannot be applied here because its signature could not be
          verified. For an unsigned or offline export, use the{" "}
          <Link href="/catalog">Catalog import</Link> page.</p>}
  </section>;
}

function CandidateIntegrity({ candidate }: { candidate: UpdateCandidate }) {
  const integrity = candidate.integrity!;
  const view = describeIntegrity(integrity);
  return <>
    {(integrity.expired || integrity.root_rotation) && <div class="banner" role="alert">
      <strong>{view.badge.label}</strong>
      <span>{view.lines[0]}</span>
    </div>}
    <dl class="catalog-trust" aria-label="Catalog roles">
      <dt>Catalog roles</dt><dd><Badge variant={view.badge.variant}>{view.badge.label}</Badge></dd>
      <dt>Root</dt><dd>{integrity.root ? `v${integrity.root.version}` : "None"}
        {integrity.root_rotation ? ` (was v${integrity.previous_root_version})` : ""}</dd>
      <dt>Snapshot</dt><dd>{integrity.snapshot ? `v${integrity.snapshot.version}` : "None"}</dd>
      <dt>Timestamp</dt><dd>{integrity.timestamp
        ? <>v{integrity.timestamp.version}, expires <Expiry iso={integrity.timestamp.expires_at} /></>
        : "None"}</dd>
    </dl>
  </>;
}

function PlanResults({ record }: { record: UpdateCheckRecord }) {
  return <section class="catalog-panel" aria-label="Plan results">
    <h2 class="panel-title">Plans after adoption</h2>
    {record.plans.length === 0
      ? <p class="note">No installation produced a Plan result.</p>
      : <div class="table-scroll"><table class="t">
        <caption>Plan result per installation</caption>
        <thead><tr><th>Installation</th><th>Outcome</th></tr></thead>
        <tbody>{record.plans.map(plan => <tr key={plan.installation_id}>
          <td>{plan.installation_id}</td>
          <td>{describePlanOutcome(plan.outcome)}{plan.reason ? ` (${plan.reason})` : ""}</td>
        </tr>)}</tbody>
      </table></div>}
    <p class="note">Issuing a Plan never applies it. Each installation applies a Plan only inside its
      own maintenance window and constraints.</p>
  </section>;
}

function Events({ status }: { status: UpdateStatus }) {
  return <section aria-label="Recent update events">
    <h2 class="panel-title">Recent events</h2>
    {status.events.length === 0
      ? <p class="empty">No update events recorded yet.</p>
      : <div class="table-scroll"><table class="t">
        <caption>Recent update events, newest first</caption>
        <thead><tr><th>Time</th><th>Action</th><th>Actor</th><th>Revision</th><th>Digest</th></tr></thead>
        <tbody>{status.events.map(event => <tr key={`${event.recorded_at}/${event.action}/${event.sha256}`}>
          <td>{formatTimestamp(event.recorded_at)}</td><td>{event.action}</td><td>{event.actor}</td>
          <td>{event.revision}</td><td><Digest sha256={event.sha256} /></td>
        </tr>)}</tbody>
      </table></div>}
  </section>;
}

export function UpdatesPage() {
  const status = useAsync(() => hubApi.getUpdateStatus(), []);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [adopted, setAdopted] = useState<UpdateCheckRecord | null>(null);

  async function run(action: () => Promise<UpdateCheckRecord>) {
    if (busy) return;
    setBusy(true);
    setNotice(null);
    setAdopted(null);
    try {
      const record = await action();
      if (record.outcome === "adopted") setAdopted(record);
    } catch (error) {
      setNotice({ kind: "error", message: describeActionError(error).message });
    } finally {
      setBusy(false);
      status.reload();
    }
  }

  const loading = status.status === "loading";
  const sentence = status.status === "ready" ? describeSchedule(status.data) : "";
  return <div class="catalog-page updates-page">
    <div class="m-head">
      <div>
        <h1>Updates</h1>
        <p class="sub">{sentence || "Keeps the Hub on the latest vendor Release."}</p>
      </div>
      <div class="acts">
        <button type="button" class="btn primary" disabled={loading || busy}
          aria-busy={busy}
          onClick={() => void run(() => hubApi.checkForUpdates())}>
          Check now
        </button>
      </div>
    </div>
    {notice && <p class={`banner ${notice.kind === "error" ? "fail" : ""}`}
      role={notice.kind === "error" ? "alert" : "status"}>{notice.message}</p>}
    {adopted && <div class="banner" role="status">
      <strong>The new catalog was adopted.</strong>
      <span>{adopted.candidate ? `Revision ${adopted.candidate.revision} is now the accepted catalog.`
        : "It is now the accepted catalog."}</span>
    </div>}
    <AsyncBoundary state={status}>
      {(data) => {
        const record = data.last_check;
        const plansRecord = adopted ?? (record?.outcome === "adopted" ? record : null);
        return <>
          <Summary status={data} />
          {record?.outcome === "review_required" && record.candidate &&
            <CandidatePanel record={record} busy={busy}
              onApply={candidate => void run(() => hubApi.applyUpdate(candidate.revision, candidate.sha256))} />}
          {plansRecord && <PlanResults record={plansRecord} />}
          <Events status={data} />
        </>;
      }}
    </AsyncBoundary>
  </div>;
}
