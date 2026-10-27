import { useEffect, useRef, useState } from "preact/hooks";
import { catalogChangeObserved, catalogRecovery, isCustomChannel, releaseStateIndex, releaseTitle, requestCatalog, type Action, type Catalog, type Change, type Release } from "./api";
import { DeploymentRequests } from "./deployment-requests";
import { ReleaseWorkspace } from "./release-workspace";

const TITLES = { register: "Register release", publish: "Publish to DEV", contribute: "Add to channel", recall: "Recall release", renew: "Renew catalog freshness" };
type Pending = { action: Action; release: Release | null };
type ConfirmationState = {
  action: Action;
  busy: boolean;
  channel: string;
  channelConfirmation: string;
  confirmation: string;
  customChannel: boolean;
  reason: string;
  target: string;
};
const time = (value: string) => new Date(value).toISOString().replace("T", " ").replace(".000Z", " UTC");
const locationRoute = () => decodeURI(location.hash.slice(1) || "/releases");

export function isConfirmationDisabled(state: ConfirmationState): boolean {
  return state.busy
    || state.confirmation !== state.target
    || !state.target
    || state.reason.trim().length < 3
    || (state.action === "contribute"
      && state.customChannel
      && state.channelConfirmation !== state.channel);
}

function Confirm({ pending, catalog, close, done, failed }: {
  pending: Pending; catalog: Catalog; close: () => void; done: (id: string, change: Change) => Promise<void>;
  failed: (failure: unknown) => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [id, setId] = useState(pending.release?.id ?? "");
  const [confirmation, setConfirmation] = useState("");
  const [reason, setReason] = useState("");
  const [manifest, setManifest] = useState("");
  const [label, setLabel] = useState("");
  const [channel, setChannel] = useState(
    Object.keys(catalog.channels).find((name) => !pending.release?.channels.includes(name)) ?? "",
  );
  const [channelConfirmation, setChannelConfirmation] = useState("");
  const customChannel = isCustomChannel(channel);
  const action = pending.action;
  const target = action === "renew" ? `renew ${catalog.revision}` : id;
  useEffect(() => {
    const previous = document.activeElement;
    dialog.current?.showModal();
    return () => {
      dialog.current?.close();
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, []);
  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      const change: Change = {
        revision: catalog.revision, confirmation, reason,
        ...(action === "register" ? { label, manifest } : {}),
        ...(action === "contribute" ? { channel, ...(customChannel ? { channel_confirmation: channelConfirmation } : {}) } : {}),
      };
      await requestCatalog(action === "renew" ? "/v1/catalog/renew" : `/v1/releases/${encodeURIComponent(id)}/${action}`, change);
      await done(id, change);
    } catch (failure) {
      await failed(failure);
    } finally { setBusy(false); }
  }
  return <dialog ref={dialog} aria-labelledby="confirm-title" onCancel={(event) => {
    event.preventDefault(); if (!busy) close();
  }}>
    <form onSubmit={submit}>
      <header><h2 id="confirm-title">{TITLES[action]}</h2><p>Development validation only. No registry publication or installation changes.</p></header>
      {action === "register" && <>
        <label>Release id (SemVer)<input required value={id} onInput={(e) => setId(e.currentTarget.value)} placeholder="1.0.0" /></label>
        <label>Release label (optional)<input maxLength={160} value={label} onInput={(e) => setLabel(e.currentTarget.value)} /></label>
        <label>Lifecycle release manifest<textarea required rows={7} spellcheck={false} value={manifest} onInput={(e) => setManifest(e.currentTarget.value)} /></label>
        <p>Metadata validation only. Artifact files and registry availability are not checked.</p>
      </>}
      {pending.release && <p><strong>{releaseTitle(pending.release)}</strong><code class="digest">{pending.release.digest}</code></p>}
      {action === "publish" && <p>Sign the exact manifest with the development key and add it to DEV. This does not establish production trust.</p>}
      {action === "contribute" && <>
        <label>Destination channel<input required list="contribution-channels" maxLength={64} pattern="DEV|RELEASE_CANDIDATE|RELEASE|custom-[a-z0-9]+(-[a-z0-9]+)*" aria-describedby="channel-help" value={channel} onInput={(e) => setChannel(e.currentTarget.value)} /></label>
        <datalist id="contribution-channels">
          {Object.keys(catalog.channels).filter((c) => !pending.release?.channels.includes(c)).map((c) => <option key={c} value={c} />)}
        </datalist>
        <p id="channel-help">Choose an existing channel or enter custom-name, using lowercase letters, numbers and single hyphens (64 characters maximum). The first reviewed contribution creates its membership.</p>
        {customChannel && <label class="channel-confirmation">Type {channel} to confirm destination<input required maxLength={64} autoComplete="off" value={channelConfirmation} onInput={(e) => setChannelConfirmation(e.currentTarget.value)} /></label>}
        <p>Manual eligibility curation does not run the existing server-side promotion evaluator. Use the supported promotion pipeline for gated advancement.</p>
      </>}
      {action === "recall" && <p class="warning">Withdraw eligibility in every channel. Recall is irreversible here. Running installations and issued Plans do not change automatically.</p>}
      {action === "renew" && <p class="warning">Review the current releases, channels and recalls before confirming. Publish a new revision with 24-hour freshness; manifests, signatures and eligibility stay unchanged. Customers must separately approve the new exact export pin and import it. This does not restore their accepted catalogs automatically.</p>}
      <label>Reason<textarea required minLength={3} maxLength={500} rows={2} value={reason} onInput={(e) => setReason(e.currentTarget.value)} /></label>
      <label>Type {target || "the Release id"} to confirm<input required autoComplete="off" value={confirmation} onInput={(e) => setConfirmation(e.currentTarget.value)} /></label>
      <p>Catalog revision {catalog.revision}. A concurrent change requires refresh and review.</p>
      <footer><button type="button" disabled={busy} onClick={close}>Cancel</button>
        <button class={action === "recall" ? "danger" : "primary"} disabled={isConfirmationDisabled({
          action, busy, channel, channelConfirmation, confirmation, customChannel, reason, target,
        })}>
          {busy ? "Saving..." : `Confirm ${TITLES[action].toLowerCase()}`}
        </button></footer>
    </form>
  </dialog>;
}

function Status({ release }: { release: Release }) {
  return <span class={`status ${release.state}`}>{release.state === "draft" ? "Draft / unsigned" : release.state === "recalled" ? "Recalled" : "Development published"}</span>;
}

function Activity({ catalog, releaseId }: { catalog: Catalog; releaseId?: string }) {
  const events = catalog.events.filter((event) => !releaseId || event.release_id === releaseId);
  return events.length ? <ol class="activity">{events.map((event) => <li key={event.revision}>
    <div><strong>{event.action}{event.channel ? ` / ${event.channel}` : ""}</strong>{event.action === "renew"
      ? <a href="#/trust">Catalog freshness</a>
      : <a href={`#/releases/${event.release_id}`}>Release {event.release_id}</a>}</div>
    <p>{event.reason}</p><small>Revision {event.revision} / {time(event.occurred_at)} / {event.actor === "local-operator" ? "local operator (unauthenticated)" : event.actor ? `operator: ${event.actor}` : "Operator attribution unavailable"}</small>
  </li>)}</ol> : <p class="empty">No recorded activity.</p>;
}

function Channels({ catalog }: { catalog: Catalog }) {
  const states = releaseStateIndex(catalog.releases);
  return <>
    <div class="page-head"><div><p class="eyebrow">Eligibility curation</p><h1>Channels</h1><p>Manual contributions only. Promotion gate results are not exposed in this workspace.</p></div></div>
    <div class="channel-grid">{Object.entries(catalog.channels).map(([channel, members]) => <section class="channel" key={channel}><h2>{channel}</h2><p>{members.length} memberships (including recalled releases)</p>
      {members.map((id) => <p key={id}><a href={`#/releases/${id}`}>Release {id}</a> {states.get(id) === "recalled" ? " / Recalled" : ""}</p>)}
      {!members.length && <p>No releases added.</p>}
    </section>)}</div><p>Channel membership is eligibility, not permission to deploy. Installation constraints remain authoritative.</p>
  </>;
}

export function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [route, setRoute] = useState(locationRoute);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<Pending | null>(null);
  const [notice, setNotice] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const heading = useRef<HTMLElement>(null);
  async function refresh() {
    setLoading(true);
    try { const current = await requestCatalog(); setCatalog(current); setError(""); return current; }
    catch (failure) { setError(catalogRecovery(failure)); return null; }
    finally { setLoading(false); }
  }
  useEffect(() => {
    void refresh();
    const changed = () => { setRoute(locationRoute()); setNotice(""); heading.current?.focus(); };
    addEventListener("hashchange", changed);
    return () => removeEventListener("hashchange", changed);
  }, []);
  const releaseId = route.startsWith("/releases/") ? route.slice(10) : null;
  const release = catalog?.releases.find((r) => r.id === releaseId);
  const active = route.startsWith("/releases") ? "/releases" : route;
  const disabled = loading || !!error;
  return <div class="app">
    <a class="skip" href="#main" onClick={(event) => { event.preventDefault(); heading.current?.focus(); }}>Skip to content</a>
    <nav class="side" aria-label="Release Hub">
      <div class="brand"><img src="/brand/fdai-logo.png" alt="FDAI" /><span>Release Hub<small>Vendor workspace</small></span></div>
      {[["/releases", "Releases"], ["/channels", "Channels"], ["/deployment-requests", "Deployment requests"], ["/activity", "Activity"], ["/trust", "Catalog trust"]].map(([path, title]) =>
        <a key={path} class={active === path ? "nav-link current" : "nav-link"} href={`#${path}`} aria-current={active === path ? "page" : undefined}>{title}</a>)}
      <div class="side-note"><strong>Development validation</strong><p>No production trust root or deployment authority.</p></div>
    </nav>
    <main id="main" class="main" ref={heading} tabIndex={-1}>
      <div class="workspace-bar"><span>Vendor / FDAI</span><button disabled={loading} onClick={() => { setNotice(""); void refresh(); }}>{loading ? "Loading..." : "Refresh catalog"}</button></div>
      <p class="boundary">Development signatures only. Images remain external; nothing is deployed.</p>
      {error && <p class="error" role="alert">Catalog unavailable: {error} {catalog ? "Previously loaded data is shown; mutations are disabled." : "Use Refresh catalog to retry."}</p>}
      {notice && <p role={uncertain ? "alert" : "status"} class={error || uncertain ? "warning" : "success"}>{notice}</p>}
      {route === "/deployment-requests" && <DeploymentRequests />}
      {!catalog && !error && <p role="status" class="empty">Loading release catalog...</p>}
      {catalog && <>
        {catalog.expired && <p class="warning">Catalog export expired at {time(catalog.expires_at)}. Consumers will reject it. Review the releases, channels and recalls, then use <a href="#/trust">Catalog trust</a> to explicitly renew freshness. Refresh catalog is read-only.</p>}
        {release ? <ReleaseWorkspace release={release} catalog={catalog} disabled={disabled} act={(action, r) => setPending({ action, release: r })} activity={<Activity catalog={catalog} releaseId={release.id} />} />
          : releaseId ? <><h1>Release unavailable</h1><p>No release matches {releaseId}.</p><a href="#/releases">Back to releases</a></>
          : route === "/releases" ? <>
            <div class="page-head"><div><p class="eyebrow">Release catalog</p><h1>Releases</h1><p>Publish once. Curate eligibility. Keep the evidence in view.</p></div><button class="primary" disabled={disabled} onClick={() => setPending({ action: "register", release: null })}>Register release</button></div>
            <div class="summary"><strong>{catalog.releases.length} releases</strong><span>Revision {catalog.revision}</span><span>Updated {time(catalog.updated_at)}</span></div>
            {catalog.releases.length === 0 ? <section class="empty"><h2>No releases yet</h2><p>Register a signed application package or a legacy runtime manifest to begin. No sample releases are seeded.</p></section>
              : <div class="release-list">{catalog.releases.map((r) => <a key={r.id} href={`#/releases/${r.id}`} class="release-row"><div><strong>{releaseTitle(r)}</strong><p>{r.label || "No label"}</p></div><Status release={r} /><span>{r.channels.join(" / ") || "No channel"}</span><span class="row-next" aria-hidden="true">View details</span></a>)}</div>}
          </>           : route === "/deployment-requests" ? null
          : route === "/channels" ? <Channels catalog={catalog} />
          : route === "/activity" ? <><h1>Activity</h1><p>Transactional publication changes, newest first. Development attribution is not a production audit guarantee.</p><Activity catalog={catalog} /></>
          : route === "/trust" ? <>
            <h1>Catalog trust</h1><p>Verify exact export bytes and every published manifest before Lifecycle planning.</p>
            <section><h2>Development verification boundary</h2><p>Release signatures are verified against the active development key on every read. Channels and recalls are development metadata, not signed production catalog roles.</p>
              <dl><dt>Key id</dt><dd><code>{catalog.key_id}</code></dd><dt>Revision</dt><dd>{catalog.revision}</dd><dt>Export expiry</dt><dd>{time(catalog.expires_at)}</dd><dt>Export SHA-256 pin</dt><dd><code class="digest">{catalog.export_sha256 || "Refresh to obtain the current pin."}</code></dd></dl>
              <a href="/v1/catalog/export" target="_blank" rel="noreferrer">Open local JSON export (new tab)</a>
              <p>Obtain the pin and public key independently. Retain the accepted revision floor. Every new export revision, including freshness renewal, needs a separately approved pin and explicit customer import.</p>
            </section><section><h2>Renew development freshness</h2>
              <p>After reviewing the releases, channels and recalls, extend freshness by 24 hours from publication without changing their content. This creates an attributed catalog event and a new export pin; it does not update customer Hubs or deploy anything.</p>
              <button disabled={disabled} onClick={() => setPending({ action: "renew", release: null })}>Renew catalog freshness</button>
            </section><section><h2>Not available in this build</h2><p>Production signing, key rotation, production contributor governance, TUF freshness, automatic sync, registry mirroring and upgrade bundle import.</p></section>
          </> : <><h1>Page not found</h1><a href="#/releases">Back to releases</a></>}
      </>}
      {pending && catalog && <Confirm pending={pending} catalog={catalog} close={() => setPending(null)} done={async (id, change) => {
        const renewed = pending.action === "renew";
        setUncertain(false);
        setPending(null); location.hash = renewed ? "/trust" : `/releases/${id}`; const readBack = await refresh();
        const observed = readBack && catalogChangeObserved(readBack, pending.action, id, change);
        setUncertain(!observed);
        setNotice(observed
          ? renewed
            ? "Freshness renewal recorded and read back. Customers still need separate pin approval and import; no deployment was performed."
            : "Catalog change recorded and read back; no deployment was performed."
          : "The API accepted the request, but the exact attributed change is not confirmed by catalog readback. Review activity and refresh before another action.");
        if (renewed) heading.current?.focus();
      }} failed={async (failure) => {
        setPending(null);
        setUncertain(true);
        setNotice(`Write outcome unconfirmed. ${catalogRecovery(failure)} Reading authoritative catalog state; no write will be replayed.`);
        const readBack = await refresh();
        setNotice(`Write outcome unconfirmed. ${catalogRecovery(failure)} ${readBack
          ? "Current catalog read back. Review membership and activity before opening a new confirmation."
          : "Catalog readback failed. Mutations remain disabled until a successful refresh."}`);
        heading.current?.focus();
      }} />}
    </main>
  </div>;
}
