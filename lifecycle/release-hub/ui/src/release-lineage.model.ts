import {
  blockedReleaseCapabilities,
  extractReleaseStencil,
  nextPromotionTransition,
  parseReleaseManifest,
  type Catalog,
  type Release,
} from "./api";
import {
  BADGE_HEIGHT, CARD_HEIGHT, CARD_WIDTH, COL_GAP, PAD_X, PAD_Y, ROW_GAP,
} from "./release-lineage.geometry";
export {
  BADGE_HEIGHT, buildConnectorGeometry, CARD_HEIGHT, CARD_WIDTH, COL_GAP, PAD_X, PAD_Y, ROW_GAP,
} from "./release-lineage.geometry";

export type LineageNodeStatus = "complete" | "running" | "recalled" | "pending";

export type LineageNode = {
  id: string;
  title: string;
  titleKo?: string;
  subtitle: string;
  badgeText: string;
  badgeTextKo: string;
  status: LineageNodeStatus;
  icon: "init" | "branch" | "cloud" | "shield";
  stencilId: string;
  stageLabel: string;
  commitShort: string;
  col: number;
  row: number;
  x: number;
  y: number;
  parentIds?: string[];
  actionableHint?: { en: string; ko: string } | null;
  release?: Release;
};

export type LineageSummary = {
  total: number;
  complete: number;
  running: number;
  recalled: number;
  editionTracks: string[];
  recallLifts: number;
};

export type LineageEdge = {
  id: string;
  fromId: string;
  toId: string;
  kind: "semver" | "stencil-track" | "branch" | "recall-lift" | "stage";
  active: boolean;
  startX: number;
  startY: number;
  endX: number;
  endY: number;
};

export type LineageGraph = {
  nodes: LineageNode[];
  edges: LineageEdge[];
  width: number;
  height: number;
};

export function parseSemVerTuple(version: string): [number, number, number, string] {
  const withoutBuild = version.trim().replace(/^v/i, "").split("+", 1)[0] ?? "";
  const match = /^(\d+)\.(\d+)\.(\d+)(?:-(.+))?$/.exec(withoutBuild);
  if (!match) return [0, 0, 0, withoutBuild];
  return [
    Number.parseInt(match[1]!, 10),
    Number.parseInt(match[2]!, 10),
    Number.parseInt(match[3]!, 10),
    match[4] ?? "",
  ];
}

function comparePreRelease(aPre: string, bPre: string): number {
  if (!aPre && !bPre) return 0;
  if (!aPre && bPre) return 1;
  if (aPre && !bPre) return -1;
  const aParts = aPre.split(".");
  const bParts = bPre.split(".");
  const len = Math.max(aParts.length, bParts.length);
  for (let i = 0; i < len; i++) {
    const aSeg = aParts[i];
    const bSeg = bParts[i];
    if (aSeg === undefined) return -1;
    if (bSeg === undefined) return 1;
    if (aSeg === bSeg) continue;
    const aNum = /^\d+$/.test(aSeg) ? Number.parseInt(aSeg, 10) : null;
    const bNum = /^\d+$/.test(bSeg) ? Number.parseInt(bSeg, 10) : null;
    if (aNum !== null && bNum !== null) return aNum - bNum;
    if (aNum !== null) return -1;
    if (bNum !== null) return 1;
    return aSeg.localeCompare(bSeg);
  }
  return 0;
}

export function compareSemVer(a: string, b: string): number {
  const [aMaj, aMin, aPat, aPre] = parseSemVerTuple(a);
  const [bMaj, bMin, bPat, bPre] = parseSemVerTuple(b);
  if (aMaj !== bMaj) return aMaj - bMaj;
  if (aMin !== bMin) return aMin - bMin;
  if (aPat !== bPat) return aPat - bPat;
  return comparePreRelease(aPre, bPre);
}

export function nextSuggestedSemVer(
  releases: readonly Pick<Release, "id">[],
  bump: "patch" | "minor" | "major" = "patch",
): string {
  if (releases.length === 0) {
    return "0.5.0";
  }
  const existingIds = new Set(releases.map((r) => r.id.trim().replace(/^v/i, "")));
  const sorted = [...releases].sort((a, b) => compareSemVer(a.id, b.id));
  const latest = sorted[sorted.length - 1]!;
  let [maj, min, pat, pre] = parseSemVerTuple(latest.id);
  if (bump === "major") {
    maj += 1;
    min = 0;
    pat = 0;
  } else if (bump === "minor") {
    min += 1;
    pat = 0;
  } else if (maj === 0 && min < 5) {
    maj = 0;
    min = 5;
    pat = 0;
  } else if (pre) {
    // Promoting a pre-release (e.g. 0.5.1-rc.1) suggests the stable patch 0.5.1 first
  } else {
    pat += 1;
  }
  let candidate = `${maj}.${min}.${pat}`;
  while (existingIds.has(candidate)) {
    pat += 1;
    candidate = `${maj}.${min}.${pat}`;
  }
  return candidate;
}

export function resolveReleaseNodeStatus(
  release: Release,
  catalog: Catalog,
  activeReleaseId?: string | null,
): LineageNodeStatus {
  if (activeReleaseId && release.id === activeReleaseId) return "running";
  let blocked = false;
  try {
    const manifest = parseReleaseManifest(release.manifest);
    blocked = blockedReleaseCapabilities(manifest, catalog.events).length > 0;
  } catch {
    blocked = false;
  }
  if (release.state === "recalled" || blocked) return "recalled";
  if (release.channels.includes("RELEASE")) return "complete";
  if (
    release.state === "draft" ||
    release.channels.includes("DEV") ||
    release.channels.includes("RELEASE_CANDIDATE")
  ) {
    return "running";
  }
  return "pending";
}

function layoutGraphNodes(
  rawNodes: Omit<LineageNode, "x" | "y">[],
  rawEdges: Omit<LineageEdge, "startX" | "startY" | "endX" | "endY">[],
): LineageGraph {
  const nodeMap = new Map(rawNodes.map((n) => [n.id, n]));
  const maxCol = rawNodes.reduce((acc, n) => Math.max(acc, n.col), 0);
  const maxRow = rawNodes.reduce((acc, n) => Math.max(acc, n.row), 0);
  const nodes: LineageNode[] = rawNodes.map((n) => ({
    ...n,
    x: PAD_X + n.col * (CARD_WIDTH + COL_GAP),
    y: PAD_Y + n.row * (CARD_HEIGHT + BADGE_HEIGHT + ROW_GAP),
  }));
  const positionedMap = new Map(nodes.map((n) => [n.id, n]));
  const edges: LineageEdge[] = [];
  for (const e of rawEdges) {
    const from = positionedMap.get(e.fromId);
    const to = positionedMap.get(e.toId);
    if (!from || !to || nodeMap.get(e.fromId) === undefined) continue;
    edges.push({
      ...e,
      startX: from.x + CARD_WIDTH,
      startY: from.y + BADGE_HEIGHT + CARD_HEIGHT / 2,
      endX: to.x,
      endY: to.y + BADGE_HEIGHT + CARD_HEIGHT / 2,
    });
  }
  const width = Math.max(
    220,
    PAD_X * 2 + (maxCol + 1) * CARD_WIDTH + Math.max(0, maxCol) * COL_GAP,
  );
  const height = Math.max(
    134,
    PAD_Y * 2 + (maxRow + 1) * (CARD_HEIGHT + BADGE_HEIGHT) + Math.max(0, maxRow) * ROW_GAP,
  );
  return { nodes, edges, width, height };
}

export function computeLineageSummary(graph: LineageGraph): LineageSummary {
  let complete = 0;
  let running = 0;
  let recalled = 0;
  const tracks = new Set<string>();
  for (const n of graph.nodes) {
    if (n.status === "complete") complete += 1;
    else if (n.status === "running") running += 1;
    else if (n.status === "recalled") recalled += 1;
    if (n.stencilId) tracks.add(n.stencilId);
  }
  const recallLifts = graph.edges.filter((e) => e.kind === "recall-lift").length;
  return {
    total: graph.nodes.length,
    complete,
    running,
    recalled,
    editionTracks: [...tracks],
    recallLifts,
  };
}

export function buildReleaseLineageGraph(
  catalog: Catalog,
  options?: {
    activeReleaseId?: string | null | undefined;
    buildingDraft?: { id: string; stencilId: string; label?: string | undefined } | null | undefined;
  },
): LineageGraph {
  const sorted = [...catalog.releases].sort((a, b) => compareSemVer(a.id, b.id));
  const rawNodes: Omit<LineageNode, "x" | "y">[] = [];
  const rawEdges: Omit<LineageEdge, "startX" | "startY" | "endX" | "endY">[] = [];

  const liftMap = new Map<string, string>();
  for (const ev of catalog.events) {
    if (ev.action === "lift_capability" && ev.channel) {
      liftMap.set(ev.release_id, ev.channel);
    }
  }

  const trackLastId = new Map<string, string>();
  const colById = new Map<string, number>();
  const rowById = new Map<string, number>();
  const rowOccupiedAtCol = new Map<number, Set<number>>();
  const declaredCapsByNodeId = new Map<string, Set<string>>();

  const reserveRow = (col: number, preferredRow: number): number => {
    const used = rowOccupiedAtCol.get(col) ?? new Set<number>();
    let r = Math.max(0, preferredRow);
    while (used.has(r)) r += 1;
    used.add(r);
    rowOccupiedAtCol.set(col, used);
    return r;
  };

  for (let idx = 0; idx < sorted.length; idx++) {
    const rel = sorted[idx]!;
    let manifest: Record<string, unknown> = {};
    let blockedCaps: string[] = [];
    try {
      manifest = parseReleaseManifest(rel.manifest);
      blockedCaps = blockedReleaseCapabilities(manifest, catalog.events);
    } catch {
      manifest = {};
    }
    const st = extractReleaseStencil(manifest);
    const stencilId = st?.stencil_id ?? "standard-sre";
    const declaredCaps = new Set<string>(
      manifest.capability_maximums && typeof manifest.capability_maximums === "object"
        ? Object.keys(manifest.capability_maximums as Record<string, unknown>)
        : [],
    );
    if (st) {
      declaredCaps.add(`stencil:${st.stencil_id}`);
      for (const w of st.enabled_workloads ?? []) declaredCaps.add(w);
      for (const l of st.enabled_loops ?? []) declaredCaps.add(l);
    }
    declaredCapsByNodeId.set(rel.id, declaredCaps);

    const commitRaw = typeof manifest.source_commit === "string" ? manifest.source_commit : rel.digest;
    const commitShort = commitRaw.slice(0, 7);
    const status = resolveReleaseNodeStatus(
      rel,
      catalog,
      options?.activeReleaseId,
    );

    const inProd = rel.channels.includes("RELEASE");
    const inRc = rel.channels.includes("RELEASE_CANDIDATE");
    const inDev = rel.channels.includes("DEV");
    const customCount = rel.channels.filter((c) => c.startsWith("custom-")).length;
    const baseStage =
      rel.state === "recalled"
        ? "RECALLED"
        : inProd
          ? "RELEASE"
          : inRc
            ? "RC"
            : inDev
              ? "DEV"
              : "DRAFT";
    const stageLabel = customCount > 0 && baseStage !== "RECALLED" ? `${baseStage}+${customCount}` : baseStage;

    const parentIds = new Set<string>();
    const prevSameTrack = trackLastId.get(stencilId);
    if (prevSameTrack && prevSameTrack !== rel.id) {
      parentIds.add(prevSameTrack);
    } else if (idx > 0) {
      parentIds.add(sorted[idx - 1]!.id);
    }

    let col = 0;
    if (parentIds.size > 0) {
      const maxParentCol = Math.max(...[...parentIds].map((pid) => colById.get(pid) ?? 0));
      col = maxParentCol + 1;
    }

    const trackOrderHint =
      stencilId === "lite-observe-alert" ? 0 : stencilId === "standard-sre" ? 0 : 1;
    const preferredRow =
      prevSameTrack && rowById.has(prevSameTrack)
        ? rowById.get(prevSameTrack)!
        : col === 0
          ? 0
          : trackOrderHint;
    const row = reserveRow(col, preferredRow);
    colById.set(rel.id, col);
    rowById.set(rel.id, row);
    trackLastId.set(stencilId, rel.id);

    for (const pid of parentIds) {
      const kind = pid === prevSameTrack ? "stencil-track" : "semver";
      rawEdges.push({
        id: `edge-${pid}-${rel.id}`,
        fromId: pid,
        toId: rel.id,
        kind,
        active: status === "running" || status === "complete",
      });
    }

    const workloadsCount = st?.enabled_workloads.length ?? 3;
    const menusCount = st?.enabled_panel_ids.length ?? 32;
    const isActivelyMutating = Boolean(options?.activeReleaseId && options.activeReleaseId === rel.id);
    const badgeInfo =
      status === "complete"
        ? { en: `Complete · ${stageLabel}`, ko: `운영 승격 완료 · ${stageLabel}` }
        : status === "running"
          ? isActivelyMutating
            ? { en: `Updating · ${stageLabel}`, ko: `처리 중 · ${stageLabel}` }
            : {
                en: rel.state === "draft" ? "Draft · Unsigned" : `Staged · ${stageLabel}`,
                ko: rel.state === "draft" ? "초안 · 미서명" : `${stageLabel} 발행됨 (승격 대기)`,
              }
          : status === "recalled"
            ? rel.state === "recalled"
              ? { en: "Recalled · Release", ko: "긴급 회수됨" }
              : { en: `Blocked · ${blockedCaps[0] ?? "Cap"}`, ko: `기능 리콜 차단` }
            : { en: stageLabel, ko: stageLabel };

    rawNodes.push({
      id: rel.id,
      title: `v${rel.id} · ${stencilId}`,
      subtitle: `git ${commitShort} · ${workloadsCount}w/${menusCount}m`,
      badgeText: badgeInfo.en,
      badgeTextKo: badgeInfo.ko,
      status,
      icon: idx === 0 ? "init" : inProd ? "cloud" : "branch",
      stencilId,
      stageLabel,
      commitShort,
      col,
      row,
      parentIds: [...parentIds],
      release: rel,
    });
  }

  for (const [capId, liftingId] of liftMap.entries()) {
    const targetNode = rawNodes.find((n) => n.id === liftingId);
    if (!targetNode) continue;
    const candidates = rawNodes.filter((n) => n.col < targetNode.col);
    const exactCapMatch = candidates
      .slice()
      .reverse()
      .find(
        (n) =>
          n.status === "recalled" &&
          (declaredCapsByNodeId.get(n.id)?.has(capId) ?? false),
      );
    const fallbackRecalled = candidates
      .slice()
      .reverse()
      .find((n) => n.status === "recalled");
    const sourceNode = exactCapMatch ?? fallbackRecalled;
    if (sourceNode) {
      const edgeId = `edge-lift-${sourceNode.id}-${targetNode.id}`;
      if (!rawEdges.some((e) => e.id === edgeId)) {
        rawEdges.push({
          id: edgeId,
          fromId: sourceNode.id,
          toId: targetNode.id,
          kind: "recall-lift",
          active: true,
        });
      }
    }
  }

  if (options?.buildingDraft && !rawNodes.some((n) => n.id === options.buildingDraft!.id)) {
    const draft = options.buildingDraft;
    const lastNode = rawNodes[rawNodes.length - 1];
    const col = lastNode ? lastNode.col + 1 : 0;
    const row = reserveRow(col, lastNode?.row ?? 0);
    rawNodes.push({
      id: draft.id,
      title: `v${draft.id} · ${draft.stencilId}`,
      subtitle: draft.label || "stencil-compose · building manifest",
      badgeText: "Running · Building",
      badgeTextKo: "빌드 중 · 매니페스트 생성",
      status: "running",
      icon: "branch",
      stencilId: draft.stencilId,
      stageLabel: "BUILDING",
      commitShort: "pending",
      col,
      row,
    });
    if (lastNode) {
      rawEdges.push({
        id: `edge-${lastNode.id}-${draft.id}`,
        fromId: lastNode.id,
        toId: draft.id,
        kind: "semver",
        active: true,
      });
    }
  }

  return layoutGraphNodes(rawNodes, rawEdges);
}

export function buildReleaseStagePipeline(
  release: Release,
  catalog: Catalog,
): LineageGraph {
  let manifest: Record<string, unknown> = {};
  let blockedCaps: string[] = [];
  try {
    manifest = parseReleaseManifest(release.manifest);
    blockedCaps = blockedReleaseCapabilities(manifest, catalog.events);
  } catch {
    manifest = {};
  }
  const st = extractReleaseStencil(manifest);
  const stencilId = st?.stencil_id ?? "standard-sre";
  const commitShort = (
    typeof manifest.source_commit === "string" ? manifest.source_commit : release.digest
  ).slice(0, 8);
  const inDev = release.channels.includes("DEV");
  const inRc = release.channels.includes("RELEASE_CANDIDATE");
  const inProd = release.channels.includes("RELEASE");
  const recalled = release.state === "recalled";
  const capBlocked = blockedCaps.length > 0;
  const transition = nextPromotionTransition(release);

  const stageSpecs: {
    id: string;
    title: string;
    titleKo: string;
    subtitle: string;
    icon: LineageNode["icon"];
    done: boolean;
    running: boolean;
    blocked?: boolean;
    actionableHint?: { en: string; ko: string } | null;
  }[] = [
    {
      id: "initialize-stencil",
      title: "1. Stencil Blueprint",
      titleKo: "1. 스텐실 구성",
      subtitle: `${stencilId} · ${st ? `${st.enabled_workloads.length}w/${st.enabled_panel_ids.length}m` : "full-stack"}`,
      icon: "init",
      done: st !== null,
      running: false,
      actionableHint: { en: "Open Stencil Builder", ko: "스텐실 빌더 열기" },
    },
    {
      id: "clone-codebase",
      title: "2. Source & Digest",
      titleKo: "2. 소스·다이제스트",
      subtitle: `git · ${commitShort}`,
      icon: "branch",
      done: true,
      running: false,
      actionableHint: { en: "Inspect Release details", ko: "릴리스 상세 열기" },
    },
    {
      id: "build-sign-dev",
      title: "3. DEV Ring",
      titleKo: "3. DEV 서명·발행",
      subtitle: `ed25519 · ${inDev ? "DEV member" : "awaiting DEV sign"}`,
      icon: "shield",
      done: inDev && !recalled,
      running: !recalled && release.state === "draft",
      blocked: recalled,
      actionableHint:
        !recalled && release.state === "draft"
          ? { en: "Click to sign & publish DEV", ko: "클릭하여 DEV 서명·발행" }
          : null,
    },
    {
      id: "promote-rc-canary",
      title: "4. RC Canary",
      titleKo: "4. RC 카나리",
      subtitle: `apollo-gate · ${inRc ? "RC member" : capBlocked && inDev && !inRc ? `blocked (${blockedCaps[0]})` : "canary soak"}`,
      icon: "branch",
      done: inRc && !recalled,
      running: !recalled && !capBlocked && transition?.targetChannel === "RELEASE_CANDIDATE",
      blocked: capBlocked && inDev && !inRc,
      actionableHint:
        !recalled && !capBlocked && transition?.targetChannel === "RELEASE_CANDIDATE"
          ? { en: "Click to promote to RC", ko: "클릭하여 RC 승격" }
          : null,
    },
    {
      id: "release-production",
      title: "5. Production RELEASE",
      titleKo: "5. 운영 RELEASE",
      subtitle: `hub-catalog · ${inProd ? `RELEASE v${release.id}` : capBlocked && inRc && !inProd ? `blocked (${blockedCaps[0]})` : "production ring"}`,
      icon: "cloud",
      done: inProd && !recalled,
      running: !recalled && !capBlocked && transition?.targetChannel === "RELEASE",
      blocked: capBlocked && inRc && !inProd,
      actionableHint:
        !recalled && !capBlocked && transition?.targetChannel === "RELEASE"
          ? { en: "Click to promote to RELEASE", ko: "클릭하여 운영 RELEASE 승격" }
          : null,
    },
  ];

  const rawNodes: Omit<LineageNode, "x" | "y">[] = stageSpecs.map((spec, idx) => {
    const status: LineageNodeStatus =
      spec.blocked || (recalled && idx <= 2)
        ? "recalled"
        : spec.running
          ? "running"
          : spec.done
            ? "complete"
            : "pending";
    const badgeInfo =
      status === "complete"
        ? idx < 2 ? { en: "Recorded", ko: "정보 있음" } : { en: "Channel recorded", ko: "소속 기록" }
        : status === "running"
          ? { en: "Review next stage", ko: "다음 단계 검토" }
          : status === "recalled"
            ? spec.blocked && !recalled
              ? { en: "Blocked · Recall", ko: "기능 리콜 차단" }
              : { en: "Recalled", ko: "Recalled · 회수됨" }
            : idx < 2 ? { en: "Not declared", ko: "선언 없음" } : { en: "No membership", ko: "소속 없음" };
    return {
      id: spec.id,
      title: spec.title,
      titleKo: spec.titleKo,
      subtitle: spec.subtitle,
      badgeText: badgeInfo.en,
      badgeTextKo: badgeInfo.ko,
      status,
      icon: spec.icon,
      stencilId,
      stageLabel: spec.id,
      commitShort,
      col: idx,
      row: 0,
      actionableHint: spec.actionableHint ?? null,
    };
  });

  const rawEdges: Omit<LineageEdge, "startX" | "startY" | "endX" | "endY">[] = [];
  for (let i = 0; i < rawNodes.length - 1; i++) {
    const curr = rawNodes[i]!;
    const next = rawNodes[i + 1]!;
    rawEdges.push({
      id: `stage-edge-${curr.id}-${next.id}`,
      fromId: curr.id,
      toId: next.id,
      kind: "stage",
      active: curr.status === "complete" || curr.status === "running",
    });
  }

  void catalog;
  return layoutGraphNodes(rawNodes, rawEdges);
}

export function buildReleaseTopologyGraph(
  release: Release,
  catalog: Catalog,
): LineageGraph {
  const base = buildReleaseStagePipeline(release, catalog);
  let manifest: Record<string, unknown> = {};
  try {
    manifest = parseReleaseManifest(release.manifest);
  } catch {
    manifest = {};
  }
  const st = extractReleaseStencil(manifest);
  const components =
    manifest.components && typeof manifest.components === "object"
      ? (manifest.components as Record<string, Record<string, unknown>>)
      : {};
  const componentEntries = Object.entries(components);
  const workloads =
    componentEntries.length > 0
      ? componentEntries.map(([name, info]) => ({
          name,
          digest:
            typeof info?.image_digest === "string"
              ? info.image_digest.replace(/^sha256:/, "").slice(0, 12)
              : null,
          kind: name === "pgvector" || name === "clamav" ? "sidecar" : "workload",
        }))
      : (st?.enabled_workloads ?? []).map((name) => ({
          name,
          digest: null,
          kind: "workload",
        }));

  const recalled = release.state === "recalled";
  const inDev = release.channels.includes("DEV");
  const inRc = release.channels.includes("RELEASE_CANDIDATE");
  const inProd = release.channels.includes("RELEASE");
  const workloadStage = inProd ? "RELEASE" : inRc ? "RC" : inDev ? "DEV" : "DRAFT";
  const workloadStatus: LineageNodeStatus = recalled
    ? "recalled"
    : inDev || inRc || inProd
      ? "complete"
      : "pending";

  const rawNodes: Omit<LineageNode, "x" | "y">[] = base.nodes.map((node) => ({
    id: node.id,
    title: node.title,
    ...(node.titleKo ? { titleKo: node.titleKo } : {}),
    subtitle: node.subtitle,
    badgeText: node.badgeText,
    badgeTextKo: node.badgeTextKo,
    status: node.status,
    icon: node.icon,
    stencilId: node.stencilId,
    stageLabel: node.stageLabel,
    commitShort: node.commitShort,
    col: node.col,
    row: node.row,
    ...(node.actionableHint !== undefined ? { actionableHint: node.actionableHint } : {}),
  }));

  const rawEdges: Omit<LineageEdge, "startX" | "startY" | "endX" | "endY">[] = base.edges.map(
    (edge) => ({
      id: edge.id,
      fromId: edge.fromId,
      toId: edge.toId,
      kind: edge.kind,
      active: edge.active,
    }),
  );

  workloads.slice(0, 3).forEach((item, index) => {
    const nodeId = `workload-${item.name}`;
    const col = Math.min(4, index + 2);
    rawNodes.push({
      id: nodeId,
      title: item.name,
      titleKo: item.name,
      subtitle: `${item.kind}${item.digest ? ` · sha256:${item.digest}` : " · digest not declared"}`,
      badgeText: `Declared · ${workloadStage}`,
      badgeTextKo: `선언됨 · ${workloadStage}`,
      status: workloadStatus,
      icon: item.kind === "sidecar" ? "shield" : "cloud",
      stencilId: base.nodes[0]?.stencilId ?? "standard-sre",
      stageLabel: item.kind.toUpperCase(),
      commitShort: item.digest ?? "",
      col,
      row: 1,
      actionableHint: null,
    });
    rawEdges.push({
      id: `edge-workload-${item.name}`,
      fromId: index === 0 ? "clone-codebase" : `workload-${workloads[index - 1]!.name}`,
      toId: nodeId,
      kind: "branch",
      active: workloadStatus === "complete",
    });
  });

  return layoutGraphNodes(rawNodes, rawEdges);
}
