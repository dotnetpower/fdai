import { useEffect, useRef, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import { EvidenceRefresh } from "../components/evidence-refresh";
import { AsyncBoundary, KpiCard, KpiGrid, StatusPill, type AsyncState } from "../components/ui";
import type { ConsoleDataMode } from "../console-data-mode";
import { usePublishViewContext } from "../deck/context";
import { composeGlossary, TERMS } from "../deck/glossary";
import { currentRoute, routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { environmentUxText } from "./environment-deployment.i18n";
import { decodeRuntimeSettings, type RuntimeSettingsView } from "./settings-runtime.model";

export interface VersionHistoryEntry {
  readonly time: string;
  readonly change: string;
  readonly result: "succeeded" | "rolled_back";
}

export interface InstallationVersionProjection {
  readonly currentRelease: string;
  readonly channel: string;
  readonly managedBy: string;
  readonly connectionLabel: string;
  readonly nextChangeNote: string;
  readonly revision: number;
  readonly updatedAt: string | null;
  readonly history: readonly VersionHistoryEntry[];
  readonly sample: boolean;
}

const SAMPLE_VERSION_PROJECTION: InstallationVersionProjection = {
  currentRelease: "1.5.1",
  channel: "RELEASE",
  managedBy: "Lifecycle Hub (cell-7f3a)",
  connectionLabel: "Connected",
  nextChangeNote:
    "No upgrade is scheduled. This installation runs the newest Release on its channel.",
  revision: 42,
  updatedAt: "2026-10-12T02:34:00Z",
  history: [
    { time: "2026-10-12T02:34:00Z", change: "1.4.3 -> 1.5.1", result: "succeeded" },
    { time: "2026-10-03T02:12:00Z", change: "Configuration rev 41 -> 42", result: "succeeded" },
    { time: "2026-09-21T03:05:00Z", change: "1.4.2 -> 1.4.3", result: "succeeded" },
    { time: "2026-09-20T02:40:00Z", change: "1.4.1 -> 1.4.2", result: "rolled_back" },
  ],
  sample: true,
};

export function projectLiveVersionFromRuntimeSettings(
  settings: RuntimeSettingsView,
): InstallationVersionProjection {
  return {
    currentRelease: environmentUxText("versionUnboundRelease"),
    channel: settings.runtime.environment.toUpperCase(),
    managedBy: environmentUxText("versionManagedByRuntime"),
    connectionLabel: settings.runtime.stateStoreDurable
      ? environmentUxText("versionDurableState")
      : environmentUxText("versionEphemeralState"),
    nextChangeNote: environmentUxText("versionNextChangeLive"),
    revision: settings.revision,
    updatedAt: settings.updatedAt,
    history: settings.updatedAt
      ? [
          {
            time: settings.updatedAt,
            change: `Runtime policy revision ${settings.revision}`,
            result: "succeeded",
          },
        ]
      : [],
    sample: false,
  };
}

export function EnvironmentDeploymentVersion({
  client,
  dataMode,
}: {
  readonly client: OperatorApiClient;
  readonly dataMode: ConsoleDataMode;
}) {
  const [state, setState] = useState<AsyncState<InstallationVersionProjection>>({
    status: "loading",
  });
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const generation = useRef(0);

  const load = async () => {
    const request = ++generation.current;
    const isSample = dataMode === "sample" || currentRoute().search.get("data") === "sample";
    if (isSample) {
      const nowIso = new Date().toISOString();
      setCheckedAt(nowIso);
      setState({ status: "ready", data: SAMPLE_VERSION_PROJECTION });
      return;
    }
    setState({ status: "loading" });
    try {
      const settings = decodeRuntimeSettings(await client.panel<unknown>("/runtime/settings"));
      if (request === generation.current) {
        setCheckedAt(new Date().toISOString());
        setState({ status: "ready", data: projectLiveVersionFromRuntimeSettings(settings) });
      }
    } catch (reason) {
      if (request === generation.current) {
        setState(
          isOptionalOperatorApiUnavailable(reason)
            ? { status: "unavailable", message: environmentUxText("versionUnavailable") }
            : {
                status: "error",
                message: `${environmentUxText("versionSourceError")} ${
                  reason instanceof Error ? reason.message : String(reason)
                }`,
              },
        );
      }
    }
  };

  useEffect(() => {
    void load();
    return () => {
      generation.current += 1;
    };
  }, [client, dataMode]);

  usePublishViewContext(
    () =>
      state.status !== "ready"
        ? null
        : {
            routeId: "environment-version",
            routeLabel: environmentUxText("versionTab"),
            purpose: environmentUxText("versionBoundaryCallout"),
            headline: `${state.data.currentRelease} (${state.data.channel})`,
            capturedAt: checkedAt ?? new Date().toISOString(),
            glossary: composeGlossary([TERMS.mode]),
            facts: [
              { key: "current_release", value: state.data.currentRelease, group: "version" },
              { key: "channel", value: state.data.channel, group: "version" },
              { key: "execution_authority", value: false, group: "version" },
            ],
            records: {
              history: state.data.history.map((entry) => ({
                time: entry.time,
                change: entry.change,
                result: entry.result,
              })),
            },
          },
    [state, checkedAt],
  );

  const versionHref = routeHref("settings-environment", {
    segments: ["version"],
    params: { data: dataMode === "sample" ? "sample" : null },
  });

  return (
    <div class="stack environment-version">
      <header class="environment-deployment-section-header">
        <div>
          <h2>{environmentUxText("versionTitle")}</h2>
          <p>{environmentUxText("versionSubtitle")}</p>
        </div>
        <EvidenceRefresh loading={state.status === "loading"} onRefresh={() => void load()} />
      </header>
      <p class="muted">
        {checkedAt
          ? environmentUxText("lastFetched", { time: formatConsoleTimestamp(checkedAt) })
          : environmentUxText("notFetched")}
      </p>
      <AsyncBoundary state={state} resourceLabel={environmentUxText("versionTitle")}>
        {(projection) => (
          <>
            {projection.sample ? (
              <div class="state-block" role="note">
                {environmentUxText("versionSampleNote")}
              </div>
            ) : null}
            <KpiGrid>
              <KpiCard
                evidenceState="measured"
                href={`${versionHref}#environment-version-history`}
                label={environmentUxText("currentReleaseLabel")}
                value={projection.currentRelease}
              />
              <KpiCard
                evidenceState="measured"
                href={`${versionHref}#environment-version-next`}
                label={environmentUxText("channelLabel")}
                value={projection.channel}
              />
              <KpiCard
                evidenceState="measured"
                href={`${versionHref}#environment-version-next`}
                label={environmentUxText("managedByLabel")}
                value={projection.managedBy}
              />
              <KpiCard
                evidenceState="measured"
                href={`${versionHref}#environment-version-history`}
                label={environmentUxText("hubConnectionLabel")}
                value={projection.connectionLabel}
              />
            </KpiGrid>

            <div class="environment-version-grid">
              <section
                id="environment-version-history"
                class="settings-section"
                aria-label={environmentUxText("versionHistoryTitle")}
              >
                <h3>{environmentUxText("versionHistoryTitle")}</h3>
                {projection.history.length === 0 ? (
                  <p class="muted">{environmentUxText("versionHistoryEmpty")}</p>
                ) : (
                  <div class="table-scroll" tabIndex={0} role="region" aria-label={environmentUxText("versionHistoryTitle")}>
                    <table class="data-table">
                      <thead>
                        <tr>
                          <th>{environmentUxText("versionTimeCol")}</th>
                          <th>{environmentUxText("versionChangeCol")}</th>
                          <th>{environmentUxText("versionResultCol")}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {projection.history.map((item) => (
                          <tr key={`${item.time}-${item.change}`}>
                            <td>{formatConsoleTimestamp(item.time)}</td>
                            <td>{item.change}</td>
                            <td>
                              <StatusPill
                                kind={item.result === "succeeded" ? "success" : "danger"}
                                label={
                                  item.result === "succeeded"
                                    ? environmentUxText("versionResultSucceeded")
                                    : environmentUxText("versionResultRolledBack")
                                }
                              />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>

              <section
                id="environment-version-next"
                class="settings-section"
                aria-label={environmentUxText("versionNextChangeTitle")}
              >
                <h3>{environmentUxText("versionNextChangeTitle")}</h3>
                <p class="muted">{projection.nextChangeNote}</p>
                <div class="state-block" role="note">
                  {environmentUxText("versionBoundaryCallout")}
                </div>
              </section>
            </div>
          </>
        )}
      </AsyncBoundary>
    </div>
  );
}
