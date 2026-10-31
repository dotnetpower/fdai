import { useCallback, useEffect, useMemo, useRef, useState } from "preact/hooks";

import type { OperatorApiClient } from "../api";
import {
  KpiCard,
  KpiGrid,
  PageHeader,
  StatusPill,
  UnavailableState,
  type PillKind,
} from "../components/ui";
import { loadConfig } from "../config";
import type { ConsoleDataMode } from "../console-data-mode";
import { useLiveStream, type LiveConnectionStatus } from "../hooks/use-live-stream";
import { routeHref } from "../router";
import {
  decodeGpuObservation,
  gpuDeviceViews,
  gpuSampleObservations,
  mergeGpuObservation,
  type GpuObservation,
} from "./gpu-monitoring.model";
import {
  formatPercent,
  GpuAction,
  GpuCharts,
  GpuFindings,
  GpuInventory,
  GpuMetrics,
  GpuPipeline,
  GpuProvenance,
  GpuSelectedHeader,
  memoryPercent,
} from "./gpu-monitoring.view";
import { gpuMonitoringText } from "./i18n/gpu-monitoring";
import "./gpu-monitoring.css";

interface Props {
  readonly client: OperatorApiClient;
  readonly dataMode: ConsoleDataMode;
}

export function gpuLiveStreamHref(dataMode: ConsoleDataMode): string {
  return routeHref("live", {
    params: { data: dataMode === "sample" ? "sample" : null },
  });
}

export function GpuMonitoringRoute({ client, dataMode }: Props) {
  const [now, setNow] = useState(Date.now());
  const [observations, setObservations] = useState<readonly GpuObservation[]>(
    () => dataMode === "sample" ? gpuSampleObservations(Date.now()) : [],
  );
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const modeRef = useRef<ConsoleDataMode>(dataMode);
  modeRef.current = dataMode;
  const ingest = useCallback((event: Parameters<typeof decodeGpuObservation>[0]) => {
    if (modeRef.current !== "live") return;
    const observation = decodeGpuObservation(event);
    if (observation !== null) {
      setObservations((current) =>
        modeRef.current === "live" ? mergeGpuObservation(current, observation) : current
      );
    }
  }, []);
  const url = useMemo(() => {
    const config = loadConfig();
    const base = config.operatorApiBaseUrl ||
      (typeof window !== "undefined" ? window.location.origin : "");
    return `${base.replace(/\/$/, "")}/live/stream`;
  }, []);
  const stream = useLiveStream({
    url,
    enabled: dataMode === "live",
    getAuthorizationHeader: client.authorizationHeader,
    onEvent: ingest,
  });
  useEffect(() => {
    setObservations(dataMode === "sample" ? gpuSampleObservations(Date.now()) : []);
    setSelectedKey(null);
    setNow(Date.now());
  }, [dataMode]);
  useEffect(() => {
    if (dataMode !== "live") return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 15_000);
    return () => window.clearInterval(timer);
  }, [dataMode]);
  const devices = useMemo(
    () => gpuDeviceViews(observations, now),
    [now, observations],
  );
  const selected = devices.find((device) => device.key === selectedKey) ??
    devices[0] ??
    null;
  useEffect(() => {
    if (selected !== null && selected.key !== selectedKey) setSelectedKey(selected.key);
  }, [selected, selectedKey]);
  const latest = selected?.latest ?? null;
  const openFindings = devices.filter((device) =>
    device.latest?.finding?.status === "open"
  ).length;
  const modeLabel = dataMode === "sample" ? gpuMonitoringText("sample") : gpuMonitoringText("live");
  return (
    <div class="stack gpu-monitoring-route">
      <PageHeader
        title={gpuMonitoringText("title")}
        subtitle={gpuMonitoringText("subtitle")}
        actions={(
          <div class="gpu-monitoring-mode">
            <StatusPill
              kind={dataMode === "sample" ? "info" : streamTone(stream.status)}
              label={modeLabel}
            />
            <a class="btn btn-secondary" href={gpuLiveStreamHref(dataMode)}>{gpuMonitoringText("openLive")}</a>
          </div>
        )}
      />
      <div class="governance-readonly-banner">
        <strong>{gpuMonitoringText("readonlyTitle")}</strong>
        <span>{gpuMonitoringText("readonlyBody")}</span>
      </div>
      {dataMode === "live" && devices.length === 0 ? (
        <UnavailableState message={gpuMonitoringText("unavailable")} evidenceState="not-connected" />
      ) : selected !== null && latest !== null ? (
        <>
          <KpiGrid>
            <KpiCard
              href="#gpu-inventory"
              label={gpuMonitoringText("kpi.devices")}
              value={devices.length}
              hint={gpuMonitoringText("kpi.devicesHint")}
            />
            <KpiCard
              href="#gpu-load"
              label={gpuMonitoringText("kpi.utilization")}
              value={formatPercent(latest.utilizationPct)}
              hint={gpuMonitoringText("kpi.utilizationHint")}
              tone={latest.utilizationPct >= 95 ? "warning" : "default"}
            />
            <KpiCard
              href="#gpu-load"
              label={gpuMonitoringText("kpi.memory")}
              value={formatPercent(memoryPercent(latest))}
              hint={gpuMonitoringText("kpi.memoryHint")}
              tone={memoryPercent(latest) >= 95 ? "warning" : "default"}
            />
            <KpiCard
              href="#gpu-findings"
              label={gpuMonitoringText("kpi.findings")}
              value={openFindings}
              hint={gpuMonitoringText("kpi.findingsHint")}
              tone={openFindings > 0 ? "warning" : "positive"}
            />
          </KpiGrid>
          <div class="gpu-monitoring-workspace">
            <GpuInventory
              devices={devices}
              selectedKey={selected.key}
              onSelect={setSelectedKey}
            />
            <section class="stack gpu-monitoring-detail" aria-label={gpuMonitoringText("title")}>
              <GpuSelectedHeader device={selected} dataMode={dataMode} />
              <GpuCharts device={selected} />
              <GpuMetrics observation={latest} />
              <GpuFindings findings={selected.findings} />
              <GpuPipeline observation={latest} />
              <GpuAction action={selected.action} />
              <GpuProvenance
                device={selected}
                correlationId={latest.correlationId}
                dataMode={dataMode}
              />
            </section>
          </div>
        </>
      ) : (
        <UnavailableState message={gpuMonitoringText("unavailable")} evidenceState="not-measured" />
      )}
    </div>
  );
}

function streamTone(status: LiveConnectionStatus): PillKind {
  return status === "open" ? "success" : status === "connecting" ? "info" : "warning";
}
