import { useEffect, useRef, useState } from "preact/hooks";
import { requestDeploymentRequests, type DeploymentRequestPage } from "./api";

const SUBSCRIPTION = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}";
const LIMIT = 25;

export function nextRequestOffset(page: DeploymentRequestPage): number | null {
  return page.has_more ? page.offset + page.limit : null;
}

export function DeploymentRequests() {
  const [draft, setDraft] = useState("");
  const [filter, setFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [page, setPage] = useState<DeploymentRequestPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const generation = useRef(0);
  useEffect(() => {
    const current = ++generation.current;
    setLoading(true); setPage(null); setError("");
    void requestDeploymentRequests(filter, offset, LIMIT).then((result) => {
      if (generation.current === current) setPage(result);
    }).catch(() => {
      if (generation.current === current) setError("Deployment requests unavailable. Check operator access, then refresh requests.");
    }).finally(() => {
      if (generation.current === current) setLoading(false);
    });
    return () => { generation.current++; };
  }, [filter, offset, refresh]);
  return <>
    <div class="page-head"><div><p class="eyebrow">Clone deployment intake</p><h1>Deployment requests</h1>
      <p>Subscriptions that self-reported a deployment request, newest first.</p></div>
      <button disabled={loading} onClick={() => { setOffset(0); setRefresh((value) => value + 1); }}>Refresh requests</button>
    </div>
    <p class="warning">Self-reported / ownership unverified. A request is not verified subscription ownership, approval, or a successful deployment.</p>
    <form class="request-filter" onSubmit={(event) => {
      event.preventDefault(); setFilter(draft); setOffset(0); setRefresh((value) => value + 1);
    }}>
      <label>Subscription ID<input value={draft} maxLength={36} pattern={SUBSCRIPTION}
        placeholder="Canonical lowercase UUID" autoComplete="off"
        onInput={(event) => setDraft(event.currentTarget.value)} /></label>
      <button disabled={loading}>Filter requests</button>
      <button type="button" disabled={loading || (!draft && !filter)}
        onClick={() => { setDraft(""); setFilter(""); setOffset(0); }}>Clear filter</button>
    </form>
    {filter && <p>Filtered subscription: <code class="request-subscription">{filter}</code></p>}
    {loading && <p role="status" class="empty">Loading deployment requests...</p>}
    {error && <p role="alert" class="error">{error}</p>}
    {page && <>
      {!page.requests.length ? <p class="empty">No deployment requests match this view.</p>
        : <div class="request-table" role="region" aria-label="Deployment request records" tabIndex={0}>
          <table>
            <caption>Self-reported requests / requested only / ownership unverified</caption>
            <thead><tr><th scope="col">Recorded (UTC)</th><th scope="col">Subscription</th>
              <th scope="col">Release / channel</th><th scope="col">Region</th><th scope="col">Request evidence</th></tr></thead>
            <tbody>{page.requests.map((record) => <tr key={record.request_id}>
              <td><time dateTime={record.recorded_at}>{new Date(record.recorded_at).toISOString().replace("T", " ").replace("Z", "")}</time>
                <small>Requested / self-reported</small></td>
              <td><code>{record.subscription_id}</code><small>Ownership unverified</small></td>
              <td><a href={`#/releases/${encodeURIComponent(record.release_id)}`}>{record.release_id}</a><small>{record.channel}</small></td>
              <td>{record.region}</td>
              <td><details><summary>Metadata</summary><dl>
                <dt>Request id</dt><dd><code class="digest">{record.request_id}</code></dd>
                <dt>Source commit</dt><dd><code class="digest">{record.source_commit}</code></dd>
                <dt>Catalog digest</dt><dd><code class="digest">{record.catalog_digest}</code></dd>
              </dl></details></td>
            </tr>)}</tbody>
          </table>
        </div>}
      <div class="request-pagination" aria-label="Deployment request pagination">
        <button disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>Previous</button>
        <span role="status">{page.requests.length ? `${offset + 1} - ${offset + page.requests.length}` : "0"} requests in this view</span>
        <button disabled={loading || nextRequestOffset(page) === null} onClick={() => {
          const next = nextRequestOffset(page);
          if (next !== null) setOffset(next);
        }}>Next</button>
      </div>
    </>}
  </>;
}
