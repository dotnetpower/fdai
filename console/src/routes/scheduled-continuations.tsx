import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import {
  AsyncBoundary,
  DataTable,
  EmptyState,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import {
  decodeUserContext,
  fetchUserContext,
  type ScheduledContinuationPayload,
} from "../user-context-client";

interface ContinuationResponse {
  readonly continuations: readonly ScheduledContinuationPayload[];
}

export function ScheduledContinuationsRoute({ client: _client }: { readonly client: ReadApiClient }) {
  const [state, setState] = useState<AsyncState<ContinuationResponse>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    fetchUserContext()
      .then((context) => {
        if (!cancelled) setState({
          status: "ready",
          data: { continuations: context.scheduled_continuations },
        });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({
          status: "error",
          message: error instanceof Error ? error.message : String(error),
        });
      });
    return () => { cancelled = true; };
  }, []);
  return <div class="stack"><PageHeader title={t("route.scheduledContinuations")} subtitle={t("nav.panelSub.scheduledContinuations")} /><AsyncBoundary state={state} resourceLabel="scheduled continuations">{(data) => <ContinuationBody data={data} />}</AsyncBoundary></div>;
}

export function decodeScheduledContinuations(value: unknown): ContinuationResponse {
  return { continuations: decodeUserContext(value).scheduled_continuations };
}

const columns: readonly Column<ScheduledContinuationPayload>[] = [
  { key: "result", header: "Scheduled result", render: (item) => <div><strong>{item.result_summary.split("\n", 1)[0]}</strong><small>{item.run_id}</small></div> },
  { key: "state", header: "State", render: (item) => <StatusPill kind={item.state === "active" ? "success" : "neutral"} label={item.state} /> },
  { key: "scope", header: "Scope", render: (item) => <code>{item.scope_ref}</code> },
  { key: "window", header: "Observation window", render: (item) => `${item.observation_started_at} - ${item.observation_ended_at}` },
  { key: "origin", header: "Conversation origin", render: (item) => `${item.origin.channel_kind}:${item.origin.conversation_ref}${item.origin.thread_ref ? `:${item.origin.thread_ref}` : ""}` },
  { key: "evidence", header: "Evidence", render: (item) => item.evidence_refs.length },
  { key: "digest", header: "Result digest", render: (item) => <code>{item.result_digest.slice(0, 12)}</code> },
  { key: "expiry", header: "Expires", render: (item) => item.expires_at },
];

function ContinuationBody({ data }: { readonly data: ContinuationResponse }) {
  usePublishViewContext(
    () => ({
      routeId: "scheduled-continuations",
      routeLabel: "Scheduled continuations",
      purpose: "Read-only anchors linking exact scheduled runs and evidence to authorized conversations.",
      glossary: composeGlossary([], [{ term: "scheduled continuation", plain: "a scoped conversation anchor for one exact scheduled result", tech: "ScheduledConversationAnchor" }]),
      headline: `${data.continuations.filter((item) => item.state === "active").length} active anchors`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "anchor_count", value: data.continuations.length, group: "continuity" },
        { key: "mutation_controls", value: false, group: "safety" },
      ],
      records: { continuations: data.continuations.map((item) => ({ ...item })) },
    }),
    [data],
  );
  return <div class="stack"><div class="governance-readonly-banner"><strong>Conversation anchors only.</strong><span>Opening or expiring an anchor requires an authenticated operator command.</span></div><DataTable rows={data.continuations} columns={columns} keyOf={(item) => item.anchor_id} empty={<EmptyState title="No continuable scheduled results" />} /></div>;
}
