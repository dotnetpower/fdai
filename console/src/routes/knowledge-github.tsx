import { useEffect, useRef, useState } from "preact/hooks";
import type { KnowledgeGithubChange } from "../api";
import { OperatorApiError } from "../api";
import { AsyncBoundary, PageHeader, StatusPill, type AsyncState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary, TERMS } from "../deck/glossary";
import type { PanelProps } from "../panels";
import { routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { decodeGithubSources, githubConnectionInputValid, githubConnectionOwner, type GithubSources } from "./knowledge-github.model";
import { knowledgeText as text } from "./knowledge-sources.i18n";
import type { IamSelfStatus } from "./settings-iam.model";
import "./knowledge-github.css";

type GithubWorkspaceData = GithubSources & { readonly principal: IamSelfStatus | null };

export function KnowledgeGithubRoute(props: PanelProps) {
  return <GithubWorkspace {...props} key={props.auth.account?.homeAccountId ?? "anonymous"} />;
}

function GithubWorkspace({ client, auth, dataMode }: PanelProps) {
  const [snapshot, setSnapshot] = useState<{ client: typeof client; state: AsyncState<GithubWorkspaceData> }>({
    client, state: { status: "loading" },
  });
  const view: AsyncState<GithubWorkspaceData> = snapshot.client === client ? snapshot.state : { status: "loading" };
  const setView = (state: AsyncState<GithubWorkspaceData>) => setSnapshot({ client, state });
  const [alias, setAlias] = useState("");
  const [location, setLocation] = useState("");
  const [reference, setReference] = useState<"public" | "deployment-github-app">("public");
  const [feedback, setFeedback] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const generation = useRef(0);
  const pending = useRef(false);
  const identity = auth.account?.homeAccountId ?? "";
  const subjectId = auth.account?.localAccountId;
  const data = view.status === "ready" ? view.data : null;
  const owner = dataMode === "live" && githubConnectionOwner(data?.principal ?? null, subjectId);

  const refresh = async () => {
    if (pending.current) return;
    const current = ++generation.current;
    setView({ status: "loading" });
    try {
      const [result, principal] = await Promise.all([
        client.panel("/knowledge/github/sources").then(decodeGithubSources),
        dataMode === "live" && subjectId ? client.iamSelf() : Promise.resolve(null),
      ]);
      if (current !== generation.current) return;
      setView({ status: "ready", data: { ...result, principal } });
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
  }, [client, identity, subjectId, dataMode]);

  usePublishViewContext(() => ({
    routeId: "github", routeLabel: "GitHub",
    purpose: text("githubPurpose"), glossary: composeGlossary([TERMS.humanRbac]),
    headline: text("githubBoundary"), capturedAt: new Date().toISOString(),
    facts: [{ key: "projection_state", value: view.status, group: "knowledge-source" }],
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
  return <div class="stack knowledge-route knowledge-github-route cs-workspace-route">
    <PageHeader title="GitHub" subtitle={text("githubPurpose")} />
    <div class="governance-readonly-banner">
      <strong>GitHub</strong>
      <span>{text("githubBoundary")}</span>
    </div>
    <nav class="knowledge-connector-actions" aria-label={text("connectorActions")}>
      <button type="button" class="btn secondary" disabled={busy || view.status === "loading"} onClick={() => void refresh()}>{text("githubRefresh")}</button>
      <a href={routeHref("settings-integrations")}>{text("openIntegrationSettings")}</a>
      <a href={routeHref("code-security")}>{text("githubScanSettings")}</a>
    </nav>
    {view.status === "unavailable" ? (
      <section class="knowledge-connector-state" aria-labelledby="knowledge-connector-title">
        <h3 id="knowledge-connector-title">
          {text("connectorUnavailableTitle", { provider: "GitHub" })}
        </h3>
        <p>{text("connectorUnavailableBody", { provider: "GitHub" })}</p>
      </section>
    ) : null}
    <AsyncBoundary state={view} resourceLabel={text("sourcesTitle")}>
      {(result) => <section class="cs-workspace-split has-selection" aria-label={text("sourcesTitle")}>
        <div class="cs-workspace-main">
          {result.gaps.length > 0 && <p role="status">{text("githubGaps")}</p>}
          {result.sources.length === 0 && <p>{text("githubEmpty")}</p>}
          <ul class="knowledge-github-sources">
            {result.sources.map((row) => <li class="cs-inspector-pane" key={row.repository_alias}>
              <header class="cs-inspector-head">
                <div>
                  <span class="cs-inspector-kicker">{row.location}</span>
                  <h3>{row.repository_alias}</h3>
                  <p>{text(row.enabled ? "githubScanEnabled" : "githubScanDisabled")}</p>
                </div>
                <StatusPill kind={row.knowledge_source?.knowledge_read_enabled ? "success" : "neutral"} label={text(row.knowledge_source?.knowledge_read_enabled ? "githubVerified" : "githubDisconnected")} />
              </header>
              {row.knowledge_source && <dl class="cs-facts-grid">
                <div><dt>{text("githubObserved")}</dt><dd>{formatConsoleTimestamp(row.knowledge_source.observed_at)}</dd></div>
                <div><dt>{text("githubCommit")}</dt><dd><code>{row.knowledge_source.observed_commit}</code></dd></div>
                <div><dt>{text("githubReadmeDigest")}</dt><dd><code>{row.knowledge_source.readme_digest}</code></dd></div>
              </dl>}
              {owner && row.knowledge_source?.knowledge_read_enabled && <button type="button" class="btn secondary" disabled={busy || needsRefresh}
                onClick={() => void submit({ action: "disconnect", repository_alias: row.repository_alias, expected_revision: row.revision })}>
                {text("githubDisconnect")}
              </button>}
            </li>)}
          </ul>
        </div>
        <aside class="cs-inspector-pane" aria-label={text("githubConnect")}>
          {owner ? <form class="knowledge-github-form" onSubmit={(event) => {
            event.preventDefault();
            if (valid) void submit({ action: "connect", repository_alias: alias.trim(), location: location.trim(),
              credential_reference: reference, expected_revision: selected?.revision ?? 0 });
          }}>
            <h3>{text("githubConnect")}</h3>
            <label>{text("githubAlias")}<input class="form-input" value={alias} disabled={busy || needsRefresh}
              onInput={(event) => setAlias(event.currentTarget.value)} /></label>
            <label>{text("githubLocation")}<input class="form-input" value={location} placeholder="owner/repository" disabled={busy || needsRefresh}
              onInput={(event) => setLocation(event.currentTarget.value)} /></label>
            <label>{text("githubCredential")}<select class="form-input" value={reference} disabled={busy || needsRefresh}
              onChange={(event) => setReference(event.currentTarget.value as typeof reference)}>
              <option value="public">{text("githubPublic")}</option>
              <option value="deployment-github-app">{text("githubApp")}</option>
            </select></label>
            <p class="muted small">{text("githubCredentialHint")}</p>
            <button class="btn primary" type="submit" disabled={!valid || busy || needsRefresh}>{text("githubConnect")}</button>
          </form> : <p>{text("githubOwnerOnly")}</p>}
        </aside>
      </section>}
    </AsyncBoundary>
    {feedback && <p role="status">{feedback}</p>}
  </div>;
}
