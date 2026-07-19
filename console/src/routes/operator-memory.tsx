import { useEffect, useRef, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable, type ReadApiClient } from "../api";
import {
  AsyncBoundary,
  DataTable,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
} from "../components/ui";
import { t } from "../i18n";
import {
  decodeOperatorMemory,
    nextOperatorMemoryExpiryDelay,
    operatorMemoryDisplayState,
  type MemoryCompactionReviewItem,
  type OperatorMemoryReviewItem,
  type OperatorMemoryReviewView,
} from "./operator-memory.model";

export function OperatorMemoryRoute({ client }: { readonly client: ReadApiClient }) {
  const [scopeKind, setScopeKind] = useState("");
  const [scopeRef, setScopeRef] = useState("");
  const [state, setState] = useState<AsyncState<OperatorMemoryReviewView>>({
    status: "loading",
  });
  const generation = useRef(0);

  const load = async (): Promise<void> => {
    const request = ++generation.current;
    setState({ status: "loading" });
    try {
      const payload = await client.panel<unknown>("/operator-memory", {
        limit: "100",
        ...(scopeKind ? { scope_kind: scopeKind } : {}),
        ...(scopeRef.trim() ? { scope_ref: scopeRef.trim() } : {}),
      });
      if (request === generation.current) {
        setState({ status: "ready", data: decodeOperatorMemory(payload) });
      }
    } catch (error) {
      if (request === generation.current) {
        setState(isOptionalReadApiUnavailable(error)
          ? { status: "unavailable", message: t("settings.operatorMemory.unavailable") }
          : { status: "error", message: error instanceof Error ? error.message : String(error) });
      }
    }
  };

  useEffect(() => {
    void load();
    return () => { generation.current += 1; };
  }, [client]);

  return (
    <div class="stack operator-memory-route">
      <PageHeader
        title={t("route.operatorMemory")}
        subtitle={t("settings.operatorMemory.subtitle")}
      />
      <form class="scheduler-runs-filter" onSubmit={(event) => { event.preventDefault(); void load(); }}>
        <label>
          <span>{t("settings.operatorMemory.scopeKind")}</span>
          <select value={scopeKind} onChange={(event) => setScopeKind(event.currentTarget.value)}>
            <option value="">{t("settings.operatorMemory.allScopes")}</option>
            <option value="resource-group">resource-group</option>
            <option value="resource">resource</option>
          </select>
        </label>
        <label>
          <span>{t("settings.operatorMemory.scopeRef")}</span>
          <input value={scopeRef} onInput={(event) => setScopeRef(event.currentTarget.value)} />
        </label>
        <button type="submit" class="btn">{t("settings.operatorMemory.filter")}</button>
      </form>
      <AsyncBoundary state={state} resourceLabel={t("settings.operatorMemory.resourceLabel")}>
        {(view) => <OperatorMemoryBody view={view} />}
      </AsyncBoundary>
    </div>
  );
}

function OperatorMemoryBody({ view }: { readonly view: OperatorMemoryReviewView }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const delay = nextOperatorMemoryExpiryDelay(view.items, now);
    if (delay === null) return undefined;
    const timer = window.setTimeout(() => setNow(Date.now()), delay);
    return () => window.clearTimeout(timer);
  }, [now, view.items]);
  return (
    <div class="stack">
      <section class="stack-section">
        <h3>{t("settings.operatorMemory.compactions")}</h3>
        <DataTable
          columns={compactionColumns()}
          rows={view.compactions}
          keyOf={(item) => item.candidateId}
          empty={t("settings.operatorMemory.noCompactions")}
        />
      </section>
      <section class="stack-section">
        <h3>{t("settings.operatorMemory.entries")}</h3>
        <DataTable
          columns={columns(now)}
          rows={view.items}
          keyOf={(item) => item.id}
          empty={t("settings.operatorMemory.empty")}
        />
      </section>
    </div>
  );
}

function compactionColumns(): readonly Column<MemoryCompactionReviewItem>[] {
  return [
    {
      key: "candidate",
      header: t("settings.operatorMemory.candidate"),
      render: (item) => <span><strong>{item.category}</strong><small>{item.body}</small></span>,
    },
    {
      key: "sources",
      header: t("settings.operatorMemory.sources"),
      render: (item) => item.sourceRefs.join(", "),
    },
    {
      key: "review",
      header: t("settings.operatorMemory.review"),
      render: (item) => <span><strong>{item.proposedByAgent}</strong><small>{item.reviewedBy ?? "-"}</small></span>,
    },
    {
      key: "state",
      header: t("settings.operatorMemory.state"),
      render: (item) => <StatusPill kind="neutral" label={item.state} />,
    },
  ];
}

function columns(now: number): readonly Column<OperatorMemoryReviewItem>[] {
  return [
    {
      key: "memory",
      header: t("settings.operatorMemory.memory"),
      render: (item) => <span><strong>{item.category}</strong><small>{item.body}</small></span>,
    },
    {
      key: "scope",
      header: t("settings.operatorMemory.scope"),
      render: (item) => <span><strong>{item.scopeKind}</strong><small>{item.scopeRef}</small></span>,
    },
    {
      key: "provenance",
      header: t("settings.operatorMemory.provenance"),
      render: (item) => <span><strong>{item.sourceEvent}</strong><small>{item.sourceRef}</small></span>,
    },
    {
      key: "approval",
      header: t("settings.operatorMemory.approval"),
      render: (item) => <span><strong>{item.author}</strong><small>{item.approvedBy}</small></span>,
    },
    {
      key: "state",
      header: t("settings.operatorMemory.state"),
      render: (item) => {
        const state = operatorMemoryDisplayState(item, now);
        return (
          <StatusPill
            kind={state === "active" ? "success" : state === "expired" ? "warning" : "neutral"}
            label={state}
          />
        );
      },
    },
  ];
}
