import { useEffect, useRef, useState } from "preact/hooks";
import type { KnowledgeGithubChange } from "../api";
import { OperatorApiError } from "../api";
import { AsyncBoundary, PageHeader, StatusPill, type AsyncState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary, TERMS } from "../deck/glossary";
import type { PanelProps } from "../panels";
import { routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { decodeGithubSources, githubConnectionInputValid, type GithubSources } from "./knowledge-github.model";
import { knowledgeText as text } from "./knowledge-sources.i18n";
import "./knowledge-github.css";

export function KnowledgeGithubRoute(props: PanelProps) {
  return <GithubWorkspace {...props} key={props.auth.account?.homeAccountId ?? "anonymous"} />;
}

function GithubWorkspace({ client, auth, dataMode }: PanelProps) {
  const [snapshot, setSnapshot] = useState<{ client: typeof client; state: AsyncState<GithubSources> }>({
    client, state: { status: "loading" },
  });
  const view: AsyncState<GithubSources> = snapshot.client === client ? snapshot.state : { status: "loading" };
  const setView = (state: AsyncState<GithubSources>) => setSnapshot({ client, state });
  const [alias, setAlias] = useState("");
  const [location, setLocation] = useState("");
  const [reference, setReference] = useState<"public" | "deployment-github-app">("public");
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const generation = useRef(0);
  const pending = useRef(false);
  const identity = auth.account?.homeAccountId ?? "";
  const roles = auth.account?.idTokenClaims?.roles;
  const owner = Array.isArray(roles) && roles.includes("Owner") && dataMode === "live";
  const data = view.status === "ready" ? view.data : null;

  const refresh = async () => {
    if (pending.current) return;
    const current = ++generation.current;
    setView({ status: "loading" });
    try {
      const result = decodeGithubSources(await client.panel("/knowledge/github/sources"));
      if (current !== generation.current) return;
      setView({ status: "ready", data: result });
      setNeedsRefresh(false);
    } catch {
      if (current === generation.current) setView({ status: "unavailable", message: text("githubUnavailable") });
    }
  };
  useEffect(() => {
    pending.current = false;
    setBusy(false);
    setFeedback(null);
    setAlias("");
    setLocation("");
    setNeedsRefresh(false);
    void refresh();
    return () => { generation.current += 1; };
  }, [client, identity]);

  usePublishViewContext(() => ({
    routeId: "github", routeLabel: "GitHub",
    purpose: text("githubPurpose"), glossary: composeGlossary([TERMS.humanRbac]),
    headline: text("githubBoundary"), capturedAt: new Date().toISOString(),
    facts: [{ key: "connection_state", value: view.status, group: "knowledge-source" }],
    records: { sources: data?.sources.map((row) => ({
      repository_alias: row.repository_alias, knowledge_read_enabled: row.knowledge_source?.knowledge_read_enabled ?? false,
      scan_enabled: row.enabled, indexed: false,
    })) ?? [] },
  }), [view, data]);

  const submit = async (body: KnowledgeGithubChange) => {
    if (!owner || pending.current || needsRefresh || view.status !== "ready") return;
    pending.current = true;
    setBusy(true);
    const current = generation.current;
    setFeedback(null);
    try {
      await client.changeKnowledgeGithubSource(body, `knowledge-github:${crypto.randomUUID()}`);
      if (current === generation.current) setFeedback(text("githubQueued"));
    } catch (error) {
      if (current === generation.current) setFeedback(text(
        error instanceof OperatorApiError && error.status === 403 ? "githubForbidden" : "githubFailed",
      ));
    } finally {
      if (current === generation.current) {
        pending.current = false;
        setBusy(false);
        setNeedsRefresh(true);
      }
    }
  };
  const selected = data?.sources.find((row) => row.repository_alias === alias.trim());
  const valid = githubConnectionInputValid(alias.trim(), location.trim());
  return <div class="stack knowledge-route knowledge-github-route">
    <PageHeader title="GitHub" subtitle={text("githubPurpose")} />
    <p>{text("githubBoundary")}</p>
    <nav class="knowledge-connector-actions" aria-label={text("connectorActions")}>
      <button class="btn" disabled={busy || view.status === "loading"} onClick={() => void refresh()}>{text("githubRefresh")}</button>
      <a href={routeHref("settings-integrations")}>{text("openIntegrationSettings")}</a>
      <a href={routeHref("code-security")}>{text("githubScanSettings")}</a>
    </nav>
    <AsyncBoundary state={view} resourceLabel={text("sourcesTitle")}>
      {(result) => <section class="stack" aria-label={text("sourcesTitle")}>
        {result.gaps.length > 0 && <p role="status">{text("githubGaps")}</p>}
        {result.sources.length === 0 && <p>{text("githubEmpty")}</p>}
        <ul class="knowledge-github-sources">
          {result.sources.map((row) => <li key={row.repository_alias}>
            <h3>{row.repository_alias}</h3><p>{row.location}</p>
            <StatusPill kind="neutral" label={text(row.knowledge_source?.knowledge_read_enabled ? "githubVerified" : "githubDisconnected")} />
            <p>{text(row.enabled ? "githubScanEnabled" : "githubScanDisabled")}</p>
            {row.knowledge_source && <dl>
              <dt>{text("githubObserved")}</dt><dd>{formatConsoleTimestamp(row.knowledge_source.observed_at)}</dd>
              <dt>{text("githubCommit")}</dt><dd><code>{row.knowledge_source.observed_commit}</code></dd>
              <dt>{text("githubReadmeDigest")}</dt><dd><code>{row.knowledge_source.readme_digest}</code></dd>
            </dl>}
            {owner && row.knowledge_source?.knowledge_read_enabled && <button class="btn" disabled={busy || needsRefresh}
              onClick={() => void submit({ action: "disconnect", repository_alias: row.repository_alias, expected_revision: row.revision })}>
              {text("githubDisconnect")}
            </button>}
          </li>)}
        </ul>
        {owner ? <form class="knowledge-github-form" onSubmit={(event) => {
          event.preventDefault();
          if (valid) void submit({ action: "connect", repository_alias: alias.trim(), location: location.trim(),
            credential_reference: reference, expected_revision: selected?.revision ?? 0 });
        }}>
          <h3>{text("githubConnect")}</h3>
          <label>{text("githubAlias")}<input value={alias} disabled={busy || needsRefresh}
            onInput={(event) => setAlias(event.currentTarget.value)} /></label>
          <label>{text("githubLocation")}<input value={location} placeholder="owner/repository" disabled={busy || needsRefresh}
            onInput={(event) => setLocation(event.currentTarget.value)} /></label>
          <label>{text("githubCredential")}<select value={reference} disabled={busy || needsRefresh}
            onChange={(event) => setReference(event.currentTarget.value as typeof reference)}>
            <option value="public">{text("githubPublic")}</option>
            <option value="deployment-github-app">{text("githubApp")}</option>
          </select></label>
          <p>{text("githubCredentialHint")}</p>
          <button class="btn" type="submit" disabled={!valid || busy || needsRefresh}>{text("githubConnect")}</button>
        </form> : <p>{text("githubOwnerOnly")}</p>}
      </section>}
    </AsyncBoundary>
    {feedback && <p role="status">{feedback}</p>}
  </div>;
}
