import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import type { HilQueueItem } from "../types";
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
import { TERMS, agentTerm, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";

interface Props {
  readonly client: ReadApiClient;
}

export function HilQueueRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<readonly HilQueueItem[]>>({
    status: "loading",
  });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const page = await client.listHilQueue({ limit: 100 });
        if (!cancelled) setState({ status: "ready", data: page.items });
      } catch (err) {
        if (!cancelled) {
          setState({
            status: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client]);

  return (
    <div class="stack">
      <PageHeader
        title={t("route.hilQueue")}
        subtitle={
          <>
            High-risk actions waiting for a human approver. Approvals flow through
            the ChatOps channel (Teams / Adaptive Cards) - the console never
            exposes an approval button (see docs/roadmap/user-rbac-and-identity.md § 7).
          </>
        }
        actions={
          <StatusPill kind="neutral" label="read-only" />
        }
      />
      <AsyncBoundary state={state} resourceLabel="HIL queue">
        {(items) => <HilBody items={items} />}
      </AsyncBoundary>
    </div>
  );
}

function HilBody({ items }: { readonly items: readonly HilQueueItem[] }) {
  usePublishViewContext(
    () => ({
      routeId: "hil-queue",
      routeLabel: "HIL queue",
      purpose:
        "High-risk actions the risk gate parked for a human approver instead of " +
        "auto-executing. Read-only: approvals happen in Teams/ChatOps cards, " +
        "never a console button, and never self-approval. Each item shows the " +
        "recorded reason it needs a human.",
      glossary: composeGlossary([
        TERMS.hil,
        TERMS.actionKind,
        TERMS.gateDecision,
        TERMS.correlationId,
      ]),
      headline: items.length === 0
        ? "No pending HIL items"
        : `${items.length} item(s) waiting for a human approver`,
      capturedAt: new Date().toISOString(),
      facts: [{ key: "pending", value: items.length, group: "queue" }],
      records: {
        items: items.map((i) => ({
          action_kind: i.action_kind,
          reason: i.reason,
          requested_at: i.requested_at,
          idempotency_key: i.idempotency_key,
          correlation_id: i.correlation_id,
        })),
      },
    }),
    [items],
  );

  if (items.length === 0) {
    return (
      <EmptyState
        title="No pending HIL items."
        body="All autonomous decisions are within the risk gate's auto envelope right now."
      />
    );
  }

  const columns: readonly Column<HilQueueItem>[] = [
    {
      key: "kind",
      header: "Action kind",
      render: (i) => <StatusPill kind="hil" label={i.action_kind} />,
    },
    { key: "reason", header: "Reason", render: (i) => i.reason },
    { key: "at", header: "Requested at", render: (i) => i.requested_at, cellClass: "mono" },
    { key: "idem", header: "Idempotency key", render: (i) => i.idempotency_key, cellClass: "mono" },
    {
      key: "corr",
      header: "Correlation id",
      render: (i) => i.correlation_id ?? <span class="muted">-</span>,
      cellClass: "mono",
    },
  ];

  return (
    <DataTable
      columns={columns}
      rows={items}
      keyOf={(i) => i.idempotency_key}
    />
  );
}
