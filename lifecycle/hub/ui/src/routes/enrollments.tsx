import { useEffect, useState } from "preact/hooks";
import { hubApi, HubApiError, type BindableInstallation } from "../api";
import { effectiveSelection, isSelectable, optionLabel } from "../bindable-installations";
import { enrollmentRequester } from "../enrollment-requester";
import { AsyncBoundary } from "../components/async-boundary";
import { Link } from "../components/link";
import { formatTimestamp } from "../format";
import { useAsync } from "../hooks/use-async";
import { enrollmentPath, enrollmentsPath, navigate } from "../router";

export function EnrollmentsPage({ selectedId }: { selectedId: string | null }) {
  return selectedId === null ? (
    <EnrollmentsList />
  ) : (
    <EnrollmentDetail key={selectedId} installationId={selectedId} />
  );
}

function EnrollmentsList() {
  const pending = useAsync(() => hubApi.listPendingEnrollments(), []);

  return (
    <>
      <div class="m-head">
        <h1>Enrollment requests</h1>
        <div class="acts">
          <button type="button" class="btn" onClick={pending.reload} disabled={pending.status === "loading"}>Refresh</button>
        </div>
      </div>
      <EnrollmentRequestForm onSubmitted={pending.reload} />
      <AsyncBoundary state={pending} layout="table">
        {({ enrollments }) =>
          enrollments.length === 0 ? (
            <p class="empty">No enrollment requests pending.</p>
          ) : (
            <div class="table-scroll"><table class="t">
              <thead>
                <tr>
                  <th>Installation</th>
                  <th>Requested</th>
                  <th>Requested by</th>
                  <th>Channel</th>
                  <th>Entities</th>
                </tr>
              </thead>
              <tbody>
                {enrollments.map((request) => (
                  <tr key={request.installation_id}>
                    <td>
                      <Link href={enrollmentPath(request.installation_id)}>
                        {request.installation_id}
                      </Link>
                    </td>
                    <td>{formatTimestamp(request.requested_at)}</td>
                    <td>{enrollmentRequester(request).fromAgent ? "Installation Agent" : "Operator or file"}</td>
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
        ? `${cause.message}. Refresh before retrying. Check the installation binding and request freshness.`
        : `${cause instanceof Error ? cause.message : "Submission could not be confirmed."} Refresh before retrying.`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form class="catalog-panel" onSubmit={event => {
      event.preventDefault();
      void submit();
    }}>
      <h2 class="panel-title">Submit a signed enrollment request</h2>
      <p class="note">Remote development only. The installation must already be bound to its Agent identity.
        Upload a request signed within five minutes, never a private key. Submission does not approve
        enrollment, manage Entities, or apply a Plan.</p>
      <p class="note">Create the file with `fdai-lifecycle-hub sign-enrollment` inside the installation
        boundary; it prints the key id to compare at approval. An installation whose Agent can reach this
        Hub may instead run `fdai-lifecycle-agent enroll`: the Agent submits the pending request itself and
        it appears in the list below.</p>
      {bindable === undefined && <p class="note" role="status">Loading bound installations...</p>}
      {bindable && <>
        <label>Installation
          <select class="input" aria-label="Installation" disabled={busy} value={selected} onChange={event => {
            setInstallationId(event.currentTarget.value);
            setSubmitted(false);
            setError("");
          }}>
            {selected === "" && <option value="" disabled>No installation can take a new request</option>}
            {bindable.map(item => <option key={item.installation_id} value={item.installation_id}
              disabled={!isSelectable(item)}>{optionLabel(item)}</option>)}
          </select>
        </label>
        {selected === "" && <p class="note">Every bound installation already has a pending request or is
          enrolled.</p>}
      </>}
      {bindable === null && <label>Installation ID
        <input class="input" required pattern="[a-z][a-z0-9-]{0,62}" maxLength={63}
          disabled={busy} value={installationId} onInput={event => {
            setInstallationId(event.currentTarget.value);
            setSubmitted(false);
            setError("");
          }} />
      </label>}
      <label>Signed request JSON
        <input class="input" required type="file" accept=".json,application/json" disabled={busy}
          onChange={event => {
            setFile(event.currentTarget.files?.[0] ?? null);
            setSubmitted(false);
            setError("");
          }} />
      </label>
      <button class="btn primary" type="submit" disabled={busy || !file || submitted || !selected}>
        {busy ? "Submitting request..." : "Submit request"}
      </button>
      {error && <p class="banner fail" role="alert">{error}</p>}
      {submitted && <p class="banner" role="status">Request submitted as pending. Verify the installation
        key ID independently before approving enrollment.</p>}
    </form>
  );
}

function EnrollmentDetail({ installationId }: { installationId: string }) {
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
      setError(cause instanceof HubApiError ? cause.message : "Could not confirm the decision. Refresh the request before trying again.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <AsyncBoundary state={pending}>
      {(request) => (
        <>
          <div class="crumb">
            <Link href={enrollmentsPath()}>Enrollment requests</Link> ›{" "}
            {request.installation_id}
          </div>
          <div class="m-head">
            <div>
              <h1>{request.installation_id}</h1>
              <div class="sub">
                {enrollmentRequester(request).label} · {formatTimestamp(request.requested_at)}
              </div>
            </div>
          </div>

          <div class="callout">
            <strong>Verify the installation before accepting</strong>
            <p>Verify <code>{request.installation_key_id}</code> against the key id you obtained
              outside this screen (for example, from the installation's own enrollment output)
              before accepting. Do not accept solely because this screen shows a key id.</p>
            {enrollmentRequester(request).fromAgent && (
              <p>The installation Agent can propose this request but cannot accept or reject it.
                Your decision is still required.</p>
            )}
          </div>

          <div class="kv">
            <div>
              <div class="k">Channel</div>
              <div class="v small mono">{request.channel}</div>
            </div>
            <div>
              <div class="k">Version range</div>
              <div class="v small mono">{request.version_range}</div>
            </div>
            <div>
              <div class="k">Region</div>
              <div class="v small">{request.region}</div>
            </div>
            <div>
              <div class="k">Schema revision</div>
              <div class="v small">{request.schema_revision}</div>
            </div>
          </div>

          <section aria-label="Discovered Entities">
            <h2 class="panel-title">
              Discovered Entities <span class="hint">All start unmanaged after acceptance</span>
            </h2>
            <div class="table-scroll"><table class="t">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Kind</th>
                  <th>Reported release</th>
                </tr>
              </thead>
              <tbody>
                {request.entities.map((entity) => (
                  <tr key={entity.entity_id}>
                    <td>{entity.entity_id}</td>
                    <td>{entity.kind}</td>
                    <td>{entity.release_id ?? "Not reported"}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          </section>

          <section aria-label="Decision">
            <h2 class="panel-title">Enrollment decision</h2>
            <p class="note">Accepting enrolls this installation; it does not manage its Entities or deploy a release.</p>
            <fieldset disabled={busy !== null} class="decision-fields">
              <div class="form-row">
                <label class="lbl" for="approver">
                  Approver
                </label>
                <input
                  id="approver"
                  class="input"
                  value={approver}
                  required
                  placeholder="name or email"
                  onInput={(event) => setApprover(event.currentTarget.value)}
                />
              </div>
              <div class="form-row">
                <label class="lbl" for="key-id">
                  Verified key id
                </label>
                <input
                  id="key-id"
                  class="input"
                  value={keyId}
                  aria-describedby="key-help"
                  placeholder="the key id you verified out of band"
                  onInput={(event) => setKeyId(event.currentTarget.value)}
                />
              </div>
              <p class="note" id="key-help">Required only to accept. Use the independently verified key id.</p>
              <div class="form-row">
                <label class="lbl" for="reason">
                  Rejection reason
                </label>
                <input
                  id="reason"
                  class="input"
                  value={reason}
                  placeholder="a reason code, e.g. unknown_key"
                  aria-describedby="rejection-help"
                  onInput={(event) => setReason(event.currentTarget.value)}
                />
              </div>
              <p class="note" id="rejection-help">Required only to reject. The installation ID remains reserved after rejection.</p>
            </fieldset>
            {error && <p class="banner fail" role="alert">{error}</p>}
            <div role="status" class="note">{busy === "accept" ? "Accepting enrollment..." : busy === "reject" ? "Rejecting enrollment..." : ""}</div>
            <div class="acts">
              <button
                type="button"
                class="btn"
                disabled={busy !== null || approver.trim().length === 0 || reason.trim().length === 0}
                onClick={() =>
                  decide("reject", (who) => hubApi.rejectEnrollment(installationId, who, reason.trim()))
                }
              >
                {busy === "reject" && <span class="spinner" aria-hidden="true" />}
                Reject
              </button>
              <button
                type="button"
                class="btn primary"
                disabled={busy !== null || approver.trim().length === 0 || keyId.trim().length === 0}
                onClick={() =>
                  decide("accept", (who) => hubApi.approveEnrollment(installationId, who, keyId.trim()))
                }
              >
                {busy === "accept" && <span class="spinner" aria-hidden="true" />}
                Accept enrollment
              </button>
            </div>
          </section>
        </>
      )}
    </AsyncBoundary>
  );
}
