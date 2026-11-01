import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
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
import { formatConsoleTimestamp } from "../time-format";
import { presentationLabel, t } from "./i18n/evidence";
import {
  decodeUserContext,
  fetchUserContext,
  type ScheduledContinuationPayload,
  UserContextRequestError,
} from "../user-context-client";
import type { ConsoleDataMode } from "../console-data-mode";
import { OPERATIONS_SAMPLE_CONTINUATIONS } from "./operations.sample";

interface ContinuationResponse {
  readonly continuations: readonly ScheduledContinuationPayload[];
}

export function ScheduledContinuationsRoute({
  client,
  dataMode,
}: {
  readonly client: OperatorApiClient;
  readonly dataMode: ConsoleDataMode;
}) {
  const [state, setState] = useState<AsyncState<ContinuationResponse>>({ status: "loading" });
  useEffect(() => {
    let cancelled = false;
    if (dataMode === "sample") {
      setState({
        status: "ready",
        data: { continuations: OPERATIONS_SAMPLE_CONTINUATIONS },
      });
      return () => {
        cancelled = true;
      };
    }
    setState({ status: "loading" });
    fetchUserContext()
      .then((context) => ({ continuations: context.scheduled_continuations }))
      .catch(async (primaryError: unknown) => {
        try {
          return decodeScheduledContinuations(await client.panel<unknown>("/me/context"));
        } catch {
          throw primaryError;
        }
      })
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({
          status: error instanceof UserContextRequestError && error.status === 503
            ? "unavailable"
            : "error",
          message: error instanceof Error ? error.message : String(error),
        });
      });
    return () => { cancelled = true; };
  }, [client, dataMode]);
  return <div class="stack"><PageHeader title={t("route.scheduledContinuations")} subtitle={t("nav.panelSub.scheduledContinuations")} /><AsyncBoundary state={state} resourceLabel={t("evidence.continuations.resource")}>{(data) => <ContinuationBody data={data} />}</AsyncBoundary></div>;
}

export function decodeScheduledContinuations(value: unknown): ContinuationResponse {
  return { continuations: decodeUserContext(value).scheduled_continuations };
}

export function scheduledContinuationColumns(): readonly Column<ScheduledContinuationPayload>[] {
  return [
    { key: "result", header: t("evidence.continuations.column.result"), render: (item) => <div><strong>{item.result_summary.split("\n", 1)[0]}</strong><small>{item.run_id}</small></div> },
    { key: "state", header: t("evidence.continuations.column.state"), render: (item) => <StatusPill kind={item.state === "active" ? "success" : "neutral"} label={presentationLabel("status", item.state)} /> },
    { key: "scope", header: t("evidence.continuations.column.scope"), render: (item) => <code>{item.scope_ref}</code> },
    { key: "window", header: t("evidence.continuations.column.window"), render: (item) => `${formatConsoleTimestamp(item.observation_started_at)} - ${formatConsoleTimestamp(item.observation_ended_at)}` },
    { key: "origin", header: t("evidence.continuations.column.origin"), render: (item) => `${item.origin.channel_kind}:${item.origin.conversation_ref}${item.origin.thread_ref ? `:${item.origin.thread_ref}` : ""}` },
    { key: "evidence", header: t("evidence.continuations.column.evidence"), render: (item) => item.evidence_refs.length },
    { key: "digest", header: t("evidence.continuations.column.digest"), render: (item) => <code>{item.result_digest.slice(0, 12)}</code> },
    { key: "expiry", header: t("evidence.continuations.column.expiry"), render: (item) => formatConsoleTimestamp(item.expires_at) },
  ];
}

function ContinuationBody({ data }: { readonly data: ContinuationResponse }) {
  const columns = scheduledContinuationColumns();
  usePublishViewContext(
    () => ({
      routeId: "scheduled-continuations",
      routeLabel: t("route.scheduledContinuations"),
      purpose: t("evidence.continuations.viewPurpose"),
      glossary: composeGlossary([], [{ term: t("evidence.continuations.glossaryTerm"), plain: t("evidence.continuations.glossaryPlain"), tech: "ScheduledConversationAnchor" }]),
      headline: t("evidence.continuations.headline", {
        count: data.continuations.filter((item) => item.state === "active").length,
      }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "anchor_count", value: data.continuations.length, group: "continuity" },
        { key: "mutation_controls", value: false, group: "safety" },
      ],
      records: { continuations: data.continuations.map((item) => ({ ...item })) },
    }),
    [data],
  );
  return <div class="stack"><div class="governance-readonly-banner"><strong>{t("evidence.continuations.bannerTitle")}</strong><span>{t("evidence.continuations.bannerBody")}</span></div><DataTable rows={data.continuations} columns={columns} keyOf={(item) => item.anchor_id} empty={<EmptyState title={t("evidence.continuations.empty")} />} /></div>;
}
