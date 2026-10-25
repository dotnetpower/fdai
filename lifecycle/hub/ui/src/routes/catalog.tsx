import { useEffect, useState } from "preact/hooks";
import { request } from "../api";
import { LocalChannelsPanel } from "./local-channels";

type Trust = {
  approved_revision: number; approved_sha256: string | null;
  minimum_revision: number; accepted_sha256: string | null; imported: boolean; mode: string;
};

export function CatalogPage() {
  const [trust, setTrust] = useState<Trust | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState("");
  const [digest, setDigest] = useState("");
  const [reason, setReason] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [installation, setInstallation] = useState("");
  const [outcome, setOutcome] = useState("");
  useEffect(() => {
    void request<Trust>("/v1/catalog/trust").then(setTrust).catch(() => {
      setError("Catalog import is unavailable. It requires the explicit remote development profile.");
    });
  }, []);

  async function act(path: string, body: object) {
    setBusy(true); setError(""); setOutcome("");
    try {
      const result = await request<Trust & { outcome?: string }>(path, {
        method: "POST", body: JSON.stringify(body),
      });
      if (result.outcome) setOutcome(result.outcome);
      else setTrust(result);
    } catch {
      setError("Request rejected. Review the approved pin, expiry, revision, and installation constraints.");
    } finally { setBusy(false); }
  }

  return <div class="catalog-page">
    <div class="m-head"><div>
      <h1>Release Catalog import</h1>
      <p class="sub">For unsigned or offline exports: approve trust, import once, then compute a Plan.
        Signed vendor catalogs are kept current on the Updates page.</p>
    </div><span class="badge warn">Development only</span></div>
    <div class="callout"><strong>Independent approval is required</strong>
    <p>Obtain the exact export digest and revision through your separately approved trust channel.
      Do not copy a digest supplied by the download response as proof of trust.</p>
    <p>No registry artifact or installation execution is verified here.</p></div>
    {error && <p class="banner fail" role="alert">{error}</p>}
    {!trust && !error && <section class="skeleton" role="status" aria-busy="true" aria-label="Loading catalog trust" />}
    {trust && <>
      <dl class="catalog-trust">
        <dt>Accepted revision floor</dt><dd>{trust.minimum_revision}</dd>
        <dt>Accepted digest</dt><dd style={{ overflowWrap: "anywhere" }}>{trust.accepted_sha256 ?? "No catalog imported"}</dd>
        <dt>Approved revision</dt><dd>{trust.approved_revision}</dd>
        <dt>Approved digest</dt><dd style={{ overflowWrap: "anywhere" }}>{trust.approved_sha256 ?? "Not approved"}</dd>
      </dl>
      <form class="catalog-panel" onSubmit={(event) => {
        event.preventDefault();
        void act("/v1/catalog/trust/approve", {
          revision: Number(revision), sha256: digest, reason, confirmation,
        });
      }}>
        <h2 class="panel-title">1. Approve independently reviewed pin</h2>
        <label>Revision <input class="input" required type="number" min="0" step="1" value={revision}
          onInput={(e) => setRevision(e.currentTarget.value)} /></label>
        <label>SHA-256 <input class="input mono" required pattern="[0-9a-f]{64}" value={digest}
          onInput={(e) => setDigest(e.currentTarget.value)} /></label>
        <label>Approval reason <input class="input" required minLength={3} maxLength={500} value={reason}
          onInput={(e) => setReason(e.currentTarget.value)} /></label>
        <label>Type approve, revision and digest separated by spaces
          <input class="input mono" required value={confirmation} onInput={(e) => setConfirmation(e.currentTarget.value)} /></label>
        <button class="btn primary" disabled={busy} type="submit">Approve exact pin</button>
      </form>
      <section class="catalog-panel">
        <h2 class="panel-title">2. Bounded outbound import</h2>
        <p class="note">One configured HTTPS source, one request, no redirects, no polling.</p>
        <button class="btn" disabled={busy || !trust.approved_sha256}
          onClick={() => void act("/v1/catalog/import", {})}>Import approved catalog</button>
      </section>
      {trust.imported && trust.accepted_sha256 && <LocalChannelsPanel acceptedDigest={trust.accepted_sha256} />}
      <form class="catalog-panel" onSubmit={(event) => {
        event.preventDefault();
        void act(`/v1/installations/${encodeURIComponent(installation)}/recompute`, {});
      }}>
        <h2 class="panel-title">3. Compute a Lifecycle Plan</h2>
        <p class="note">Uses the persisted catalog and existing installation constraints. This does not apply a Plan.</p>
        <label>Installation ID <input class="input" required value={installation}
          onInput={(e) => setInstallation(e.currentTarget.value)} /></label>
        <button class="btn" disabled={busy || !trust.imported}>Compute Plan</button>
      </form>
      {outcome && <p class="banner" role="status">Planner outcome: {outcome}</p>}
    </>}
  </div>;
}
