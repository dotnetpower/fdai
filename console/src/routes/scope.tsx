import { architectureHref } from "../components/architecture-map.model";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable, type ReadApiClient } from "../api";
import type {
  EffectiveScope,
  ScopeAxis,
  ScopeAxisName,
  ScopeEntry,
  ScopeEntryState,
} from "../types";
import {
  AsyncBoundary,
  DataTable,
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
  type PillKind,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { routeHref } from "../router";
import { t } from "./i18n/evidence";

/**
 * Scope view. Read-only projection of the effective monitoring and
 * automated-action scope (which subscriptions / resource groups FDAI
    {
      key: "topology",
      header: "Topology",
      render: (item) => (
        <a href={architectureHref(undefined, item.resource_group ?? item.subscription)}>
          Open scope
        </a>
      ),
    },
 * observes and may act on), plus the hard RG-scoped executor IAM
 * boundary. Authoring a scope change never writes from the console: the
 * builder generates a policy-as-code artifact the operator submits as a
 * remediation / config PR (GitOps). No mutating back-channel.
 */

interface Props {
  readonly client: ReadApiClient;
}

export function includedScopeEntryCount(entries: readonly ScopeEntry[]): number {
  return entries.filter((entry) => entry.state === "included").length;
}

export function ScopeRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<EffectiveScope | null>>({ status: "loading" });

  useEffect(() => {
    let live = true;
    setState({ status: "loading" });
    void client.scope().then(
      (data) => {
        if (live) setState({ status: "ready", data });
      },
      (error: unknown) => {
        if (!live) return;
        // A deployment that does not wire a scope source returns 404 -
        // render "not served here" rather than a hard error.
        if (isOptionalReadApiUnavailable(error)) {
          setState({ status: "ready", data: null });
          return;
        }
        setState({
          status: "error",
          message: error instanceof Error ? error.message : String(error),
        });
      },
    );
    return () => {
      live = false;
    };
  }, [client]);

  return (
    <div class="stack governance-route scope-route">
      <PageHeader title={t("route.scope")} subtitle={t("scope.subtitle")} />
      <AsyncBoundary state={state} resourceLabel={t("route.scope")}>
        {(data) =>
          data === null ? (
            <p class="muted">{t("scope.notServed")}</p>
          ) : (
            <ScopeBody data={data} />
          )
        }
      </AsyncBoundary>
    </div>
  );
}

function ScopeBody({ data }: { readonly data: EffectiveScope }) {
  const org = useMemo(() => deriveOrg(data), [data]);
  const monitoringCount = includedScopeEntryCount(data.monitoring.entries);
  const actionCount = includedScopeEntryCount(data.action.entries);

  usePublishViewContext(
    () => ({
      routeId: "scope",
      routeLabel: t("route.scope"),
      purpose: t("scope.viewPurpose"),
      glossary: composeGlossary([TERMS.mode, TERMS.gateDecision]),
      headline: t("scope.viewHeadline", {
        monitoring: monitoringCount,
        action: actionCount,
      }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "monitoring_entries", value: monitoringCount, group: "scope" },
        { key: "action_entries", value: actionCount, group: "scope" },
        {
          key: "executor_resource_groups",
          value: data.executor_boundary.resource_groups.length,
          group: "scope",
        },
      ],
      records: {
        monitoring: data.monitoring.entries.map((e) => ({ ...e })),
        action: data.action.entries.map((e) => ({ ...e })),
      },
    }),
    [actionCount, data, monitoringCount],
  );

  return (
    <div class="stack governance-scope">
      <div class="governance-readonly-banner">
        <strong>{t("evidence.scope.bannerTitle")}</strong>
        <span>{t("evidence.scope.bannerBody")}</span>
      </div>
      <KpiGrid>
        <KpiCard href={`${routeHref("scope")}#scope-axis-monitoring`} label={t("evidence.scope.monitoringResources")} value={monitoringCount} hint={t("evidence.scope.monitoringHint")} />
        <KpiCard href={`${routeHref("scope")}#scope-axis-action`} label={t("evidence.scope.actionResources")} value={actionCount} hint={t("evidence.scope.actionHint")} />
        <KpiCard
          href={`${routeHref("scope")}#scope-executor-boundary`}
          label={t("evidence.scope.executorGroups")}
          value={data.executor_boundary.resource_groups.length}
          tone={data.executor_boundary.resource_groups.length > 0 ? "warning" : "default"}
          hint={t("evidence.scope.executorHint")}
        />
      </KpiGrid>
      <div class="scope-axis-grid">
        <ScopeAxisTable axis={data.monitoring} />
        <ScopeAxisTable axis={data.action} />
      </div>
      <ExecutorBoundaryCard boundary={data.executor_boundary} />
      <ScopeBuilder org={org} />
    </div>
  );
}

function ScopeAxisTable({ axis }: { readonly axis: ScopeAxis }) {
  const columns: readonly Column<ScopeEntry>[] = [
    {
      key: "state",
      header: t("scope.column.state"),
      render: (item) => (
        <StatusPill kind={statePill(item.state)} label={t(`scope.state.${item.state}`)} />
      ),
    },
    {
      key: "level",
      header: t("scope.column.level"),
      render: (item) => t(`scope.level.${item.level}`),
    },
    {
      key: "subscription",
      header: t("scope.column.subscription"),
      render: (item) => <span class="mono small">{item.subscription}</span>,
      cellClass: "mono",
    },
    {
      key: "resource_group",
      header: t("scope.column.resourceGroup"),
      render: (item) => <span class="mono small">{item.resource_group ?? t("scope.allRgs")}</span>,
    },
  ];
  return (
    <section id={`scope-axis-${axis.axis}`} class="stack-section scope-axis-section">
      <h3 class="section-title">{t(`scope.axis.${axis.axis}`)}</h3>
      <p class="muted footnote">{t(`scope.axisHint.${axis.axis}`)}</p>
      <DataTable
        columns={columns}
        rows={axis.entries}
        keyOf={(item) => `${item.address}:${item.state}`}
        empty={t("scope.emptyAxis")}
      />
    </section>
  );
}

function ExecutorBoundaryCard({
  boundary,
}: {
  readonly boundary: EffectiveScope["executor_boundary"];
}) {
  return (
    <section id="scope-executor-boundary" class="stack-section scope-executor-section">
      <h3 class="section-title">{t("scope.executor")}</h3>
      <p class="muted footnote">{t("scope.executorHint")}</p>
      <KpiGrid>
        <KpiCard
          href={`${routeHref("scope")}#scope-executor-boundary`}
          label={t("scope.executorResourceGroups")}
          value={boundary.resource_groups.length === 0 ? t("scope.none") : boundary.resource_groups.length}
        />
      </KpiGrid>
      {boundary.resource_groups.length > 0 ? (
        <div class="scope-boundary-links">
          {boundary.resource_groups.map((resourceGroup) => (
            <a key={resourceGroup} class="mono small" href={architectureHref(undefined, resourceGroup)}>
              {resourceGroup}
            </a>
          ))}
        </div>
      ) : null}
      {boundary.note ? <p class="muted footnote">{boundary.note}</p> : null}
    </section>
  );
}

interface DraftEntry {
  readonly id: number;
  readonly axis: ScopeAxisName;
  readonly state: ScopeEntryState;
  readonly subscription: string;
  readonly resourceGroup: string;
}

type CopyState = "idle" | "copied" | "failed";

export async function copyScopeArtifact(
  clipboard: Pick<Clipboard, "writeText"> | undefined,
  artifact: string,
): Promise<Exclude<CopyState, "idle">> {
  if (!clipboard) return "failed";
  try {
    await clipboard.writeText(artifact);
    return "copied";
  } catch {
    return "failed";
  }
}

function ScopeBuilder({ org }: { readonly org: string }) {
  const [axis, setAxis] = useState<ScopeAxisName>("action");
  const [entryState, setEntryState] = useState<ScopeEntryState>("included");
  const [subscription, setSubscription] = useState("");
  const [resourceGroup, setResourceGroup] = useState("");
  const [drafts, setDrafts] = useState<readonly DraftEntry[]>([]);
  const [copyState, setCopyState] = useState<CopyState>("idle");
  const nextId = useRef(1);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (copyTimer.current !== null) clearTimeout(copyTimer.current);
    },
    [],
  );

  function addDraft(e: Event): void {
    e.preventDefault();
    if (!subscription.trim()) return;
    setDrafts((current) => [
      ...current,
      {
        id: nextId.current++,
        axis,
        state: entryState,
        subscription: subscription.trim(),
        resourceGroup: resourceGroup.trim(),
      },
    ]);
    setSubscription("");
    setResourceGroup("");
  }

  function removeDraft(id: number): void {
    setDrafts((current) => current.filter((d) => d.id !== id));
  }

  const artifact = useMemo(() => renderArtifact(org, drafts), [org, drafts]);

  async function copyArtifact(): Promise<void> {
    const result = await copyScopeArtifact(navigator.clipboard, artifact);
    setCopyState(result);
    if (copyTimer.current !== null) clearTimeout(copyTimer.current);
    if (result === "copied") {
      copyTimer.current = setTimeout(() => setCopyState("idle"), 2000);
    }
  }

  return (
    <section class="stack-section scope-builder-section">
      <div class="governance-readonly-banner">
        <strong>{t("evidence.scope.artifactBannerTitle")}</strong>
        <span>{t("evidence.scope.artifactBannerBody")}</span>
      </div>
      <h3 class="section-title">{t("scope.builder")}</h3>
      <p class="muted footnote">{t("scope.builderHint")}</p>
      <form class="form-grid inline" onSubmit={addDraft}>
        <label>
          {t("scope.builderAxis")}
          <select value={axis} onChange={(e) => setAxis((e.target as HTMLSelectElement).value as ScopeAxisName)}>
            <option value="monitoring">{t("scope.axis.monitoring")}</option>
            <option value="action">{t("scope.axis.action")}</option>
          </select>
        </label>
        <label>
          {t("scope.builderState")}
          <select
            value={entryState}
            onChange={(e) => setEntryState((e.target as HTMLSelectElement).value as ScopeEntryState)}
          >
            <option value="included">{t("scope.state.included")}</option>
            <option value="excluded">{t("scope.state.excluded")}</option>
          </select>
        </label>
        <label>
          {t("scope.column.subscription")}
          <input
            type="text"
            value={subscription}
            onInput={(e) => setSubscription((e.target as HTMLInputElement).value)}
            required
          />
        </label>
        <label>
          {t("scope.builderResourceGroupOptional")}
          <input
            type="text"
            value={resourceGroup}
            onInput={(e) => setResourceGroup((e.target as HTMLInputElement).value)}
          />
        </label>
        <button type="submit" class="btn primary" disabled={!subscription.trim()}>
          {t("scope.builderAdd")}
        </button>
      </form>

      {drafts.length === 0 ? (
        <p class="muted">{t("scope.builderEmpty")}</p>
      ) : (
        <div class="stack">
          <DataTable
            columns={draftColumns(removeDraft)}
            rows={drafts}
            keyOf={(item) => item.id}
            empty={t("scope.builderEmpty")}
          />
          <h4 class="section-title">{t("scope.artifact")}</h4>
          <p class="muted footnote">{t("scope.artifactHint")}</p>
          <pre class="mono small entry-json">{artifact}</pre>
          <button type="button" class="btn" onClick={() => void copyArtifact()}>
            {copyState === "copied"
              ? t("scope.copied")
              : copyState === "failed"
                ? t("scope.copyFailed")
                : t("scope.copy")}
          </button>
          {copyState === "failed" ? (
            <p class="state-error-text" role="alert">{t("scope.copyFailedHint")}</p>
          ) : null}
        </div>
      )}
    </section>
  );
}

function draftColumns(onRemove: (id: number) => void): readonly Column<DraftEntry>[] {
  return [
    { key: "axis", header: t("scope.column.axis"), render: (item) => t(`scope.axis.${item.axis}`) },
    {
      key: "state",
      header: t("scope.column.state"),
      render: (item) => (
        <StatusPill kind={statePill(item.state)} label={t(`scope.state.${item.state}`)} />
      ),
    },
    {
      key: "subscription",
      header: t("scope.column.subscription"),
      render: (item) => <span class="mono small">{item.subscription}</span>,
    },
    {
      key: "resource_group",
      header: t("scope.column.resourceGroup"),
      render: (item) => (
        <span class="mono small">{item.resourceGroup || t("scope.allRgs")}</span>
      ),
    },
    {
      key: "remove",
      header: "",
      render: (item) => (
        <button type="button" class="btn" onClick={() => onRemove(item.id)}>
          {t("scope.builderRemove")}
        </button>
      ),
    },
  ];
}

/** Compose the policy-as-code scope artifact from the draft entries. The
 * console never applies this; the operator commits it as a PR. */
function renderArtifact(org: string, drafts: readonly DraftEntry[]): string {
  const axes: ScopeAxisName[] = ["monitoring", "action"];
  const lines: string[] = [
    `# ${t("evidence.scope.artifactCommentTitle")}`,
    `# ${t("evidence.scope.artifactCommentSource")}`,
  ];
  for (const axisName of axes) {
    const forAxis = drafts.filter((d) => d.axis === axisName);
    if (forAxis.length === 0) continue;
    const includes = forAxis.filter((d) => d.state === "included").map((d) => address(org, d));
    const excludes = forAxis.filter((d) => d.state === "excluded").map((d) => address(org, d));
    lines.push(`${axisName}:`);
    lines.push("  binding:");
    lines.push("    includes:");
    for (const addr of includes) lines.push(`      - ${addr}`);
    if (includes.length === 0) lines.push("      []");
    lines.push("    excludes:");
    for (const addr of excludes) lines.push(`      - ${addr}`);
    if (excludes.length === 0) lines.push("      []");
  }
  return lines.join("\n");
}

function address(org: string, draft: DraftEntry): string {
  const segments = [org, draft.subscription];
  if (draft.resourceGroup) segments.push(draft.resourceGroup);
  return `scope://${segments.join("/")}`;
}

function deriveOrg(data: EffectiveScope): string {
  const first =
    data.monitoring.entries[0]?.address ?? data.action.entries[0]?.address ?? null;
  if (first && first.startsWith("scope://")) {
    const segment = first.slice("scope://".length).split("/")[0];
    if (segment) return segment;
  }
  return "example-org";
}

function statePill(state: ScopeEntryState): PillKind {
  return state === "included" ? "success" : "danger";
}
