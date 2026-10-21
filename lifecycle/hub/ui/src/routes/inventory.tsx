import { hubApi } from "../api";
import { AsyncBoundary } from "../components/async-boundary";
import { Link } from "../components/link";
import { formatTimestamp } from "../format";
import { useAsync } from "../hooks/use-async";
import { installationPath } from "../router";

function InventoryHeader({ title, reload, loading }: {
  title: string; reload: () => void; loading: boolean;
}) {
  return <div class="m-head">
    <h1>{title}</h1>
    <button type="button" class="btn" disabled={loading} onClick={reload}>Refresh</button>
  </div>;
}

export function ReleasesPage() {
  const inventory = useAsync(() => hubApi.listReleases(), []);
  return <div class="inventory-page">
    <InventoryHeader title="Available releases" reload={inventory.reload}
      loading={inventory.status === "loading"} />
    <div class="callout">
      <strong>Accepted catalog metadata only</strong>
      <p>Reads the already imported catalog and rechecks its pin, signature and expiry.
        This does not import, publish or apply anything. Catalog membership does not prove
        artifact availability, installation eligibility or readiness to deploy.</p>
    </div>
    <AsyncBoundary state={inventory}>
      {({ releases }) => releases.length === 0
        ? <p class="empty">The verified catalog contains no releases.</p>
        : releases.map(release => <section class="catalog-panel" key={release.release_id}
          aria-label={`Release ${release.release_id}`}>
          <h2 class="panel-title">Release {release.release_id}</h2>
          <dl class="catalog-trust">
            <dt>Channels</dt><dd>{release.channels.join(", ") || "No channel membership"}</dd>
            <dt>Manifest digest</dt><dd class="mono inventory-value">{release.digest}</dd>
            <dt>Source commit</dt><dd class="mono inventory-value">{release.source_commit}</dd>
            <dt>Platform</dt><dd>{release.platform_tag}</dd>
            <dt>Schema target</dt><dd>{release.schema_target ?? "Not declared"}</dd>
            <dt>Tolerated schema</dt><dd>{release.schema_range
              ? `${release.schema_range.minimum} to ${release.schema_range.maximum}`
              : "Not declared"}</dd>
          </dl>
          <details>
            <summary>Inspect component images and recall notices for {release.release_id}</summary>
            <div class="table-scroll"><table class="t">
              <caption>Image digests for {release.release_id}</caption>
              <thead><tr><th>Section</th><th>Component</th><th>Image digest</th></tr></thead>
              <tbody>{release.images.map(image => <tr key={`${image.section}/${image.component}`}>
                <td>{image.section}</td><td>{image.component}</td>
                <td class="mono inventory-value">{image.image_digest}</td>
              </tr>)}</tbody>
            </table></div>
            <p class="note">Release recall notices are historical facts, not an eligibility decision.
              The planner also checks capability recalls and installation constraints.</p>
            {release.recall_notices.length === 0
              ? <p class="note">No release-scoped recall notices in this catalog.</p>
              : <ul>{release.recall_notices.map(notice => <li key={notice.sequence}>
                Sequence {notice.sequence}: {notice.action}
                <div class="mono inventory-value">{notice.notice_digest}</div>
              </li>)}</ul>}
          </details>
        </section>)}
    </AsyncBoundary>
  </div>;
}

export function ConfigurationsPage() {
  const inventory = useAsync(() => hubApi.listConfigurations(), []);
  return <div class="inventory-page">
    <InventoryHeader title="Configuration packages" reload={inventory.reload}
      loading={inventory.status === "loading"} />
    <div class="callout">
      <strong>Stored configuration revisions, not verified signed packages</strong>
      <p>These revisions may originate from enrollment. Independent package signature provenance
        is not recorded. This view cannot establish signed-input readiness.
        Configuration values, sealed identifiers and signatures are not exposed.</p>
    </div>
    <AsyncBoundary state={inventory} layout="table">
      {({ configurations }) => configurations.length === 0
        ? <p class="empty">No configuration revisions stored.</p>
        : <div class="table-scroll"><table class="t">
          <caption>Stored configuration revision metadata</caption>
          <thead><tr><th>Digest</th><th>Stored at</th><th>Schema keys</th>
            <th>Override blocks</th><th>Referenced by</th><th>Package signature</th></tr></thead>
          <tbody>{configurations.map(configuration => <tr key={configuration.digest}>
            <td class="mono inventory-value">{configuration.digest}</td>
            <td>{formatTimestamp(configuration.imported_at)}</td>
            <td>{configuration.schema_key_count}</td><td>{configuration.override_count}</td>
            <td>{configuration.installation_ids.length === 0 ? "No current references"
              : <ul>{configuration.installation_ids.map(id => <li key={id}>
                <Link href={installationPath(id)}>{id}</Link>
              </li>)}</ul>}</td>
            <td>Not recorded</td>
          </tr>)}</tbody>
        </table></div>}
    </AsyncBoundary>
  </div>;
}
