import { useState } from "preact/hooks";
import { hubApi, HubApiError } from "../api";
import { AsyncBoundary } from "../components/async-boundary";
import { Link } from "../components/link";
import { formatTimestamp } from "../format";
import { useAsync } from "../hooks/use-async";
import { enrollmentPath, enrollmentsPath, navigate } from "../router";

export function EnrollmentsPage({ selectedId }: { selectedId: string | null }) {
  return selectedId === null ? (
    <EnrollmentsList />
  ) : (
    <EnrollmentDetail installationId={selectedId} />
  );
}

function EnrollmentsList() {
  const pending = useAsync(() => hubApi.listPendingEnrollments(), []);

  return (
    <>
      <div class="crumb">Enrollment requests</div>
      <div class="m-head">
        <div>
          <h1>Enrollment requests</h1>
          <div class="sub">Awaiting a customer approver's decision</div>
        </div>
      </div>
      <AsyncBoundary state={pending}>
        {({ enrollments }) =>
          enrollments.length === 0 ? (
            <p class="empty">No enrollment request is waiting.</p>
          ) : (
            <table class="t">
              <thead>
                <tr>
                  <th>Installation</th>
                  <th>Requested</th>
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
                    <td class="mono">{request.channel}</td>
                    <td>{request.entities.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        }
      </AsyncBoundary>
    </>
  );
}

function EnrollmentDetail({ installationId }: { installationId: string }) {
  const pending = useAsync(() => hubApi.getPendingEnrollment(installationId), [installationId]);
  const [approver, setApprover] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function decide(action: (approver: string) => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action(approver);
      navigate(enrollmentsPath());
    } catch (cause) {
      setError(cause instanceof HubApiError ? cause.reasonCode : "Something went wrong.");
    } finally {
      setBusy(false);
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
                Requested {formatTimestamp(request.requested_at)} · key{" "}
                {request.installation_key_id}
              </div>
            </div>
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
            <div class="panel-title">
              Discovered Entities <span class="hint">All start unmanaged after acceptance</span>
            </div>
            <table class="t">
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
                    <td>{entity.release_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section aria-label="Decision">
            <div class="panel-title">Decision</div>
            <div class="form-row">
              <label class="lbl" for="approver">
                Approver
              </label>
              <input
                id="approver"
                class="input"
                value={approver}
                placeholder="name or email"
                onInput={(event) => setApprover((event.target as HTMLInputElement).value)}
              />
            </div>
            <div class="form-row">
              <label class="lbl" for="reason">
                Rejection reason
              </label>
              <input
                id="reason"
                class="input"
                value={reason}
                placeholder="a reason code, e.g. unknown_key"
                onInput={(event) => setReason((event.target as HTMLInputElement).value)}
              />
            </div>
            {error && <p class="note">{error}</p>}
            <div class="acts">
              <button
                type="button"
                class="btn"
                disabled={busy || approver.length === 0 || reason.length === 0}
                onClick={() =>
                  decide((who) => hubApi.rejectEnrollment(installationId, who, reason))
                }
              >
                Reject
              </button>
              <button
                type="button"
                class="btn primary"
                disabled={busy || approver.length === 0}
                onClick={() =>
                  decide((who) =>
                    hubApi.approveEnrollment(installationId, who, request.installation_key_id),
                  )
                }
              >
                Accept enrollment
              </button>
            </div>
          </section>
        </>
      )}
    </AsyncBoundary>
  );
}
