import {
  blockedReleaseCapabilities,
  extractReleaseStencil,
  nextPromotionTransition,
  parseReleaseManifest,
  type Catalog,
  type Release,
} from "./api";

export type LineageNodeStatus = "complete" | "running" | "recalled" | "pending";

export type LineageNode = {
  id: string;
  title: string;
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
  release?: Release;
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

export const CARD_WIDTH = 166;
export const CARD_HEIGHT = 82;
export const BADGE_HEIGHT = 24;
export const COL_GAP = 46;
export const ROW_GAP = 24;
export const PAD_X = 12;
export const PAD_Y = 14;

export function buildConnectorGeometry(edge: {
  startX: number;
  startY: number;
  endX: number;
  endY: number;
}): {
  portCx: number;
  portCy: number;
  pathD: string;
  arrowD: string;
} {
  const portCx = edge.startX + 3.5;
  const portCy = edge.startY;
  const lineStartX = portCx + 3.5;
  const sy = edge.startY;
  const arrowTipX = edge.endX - 2.5;
  const ey = edge.endY;
  const lineEndX = arrowTipX - 0.5;
  const arrowD = `M ${arrowTipX - 6.5} ${ey - 4.2} L ${arrowTipX} ${ey} L ${arrowTipX - 6.5} ${ey + 4.2}`;

  if (Math.abs(ey - sy) < 1) {
    return {
      portCx,
      portCy,
      pathD: `M ${lineStartX} ${sy} L ${lineEndX} ${ey}`,
      arrowD,
    };
  }

  const dir = ey > sy ? 1 : -1;
  const midX = Math.round(lineStartX + (lineEndX - lineStartX) * 0.44);
  const r = Math.max(
    2,
    Math.min(
      8,
      Math.abs(ey - sy) / 2,
      Math.abs(midX - lineStartX) - 2,
      Math.abs(lineEndX - 7 - midX) - 2,
    ),
  );
  const pathD = [
    `M ${lineStartX} ${sy}`,
    `L ${midX - r} ${sy}`,
    `Q ${midX} ${sy} ${midX} ${sy + dir * r}`,
    `L ${midX} ${ey - dir * r}`,
    `Q ${midX} ${ey} ${midX + r} ${ey}`,
    `L ${lineEndX} ${ey}`,
  ].join(" ");

  return {
    portCx,
    portCy,
    pathD,
    arrowD,
  };
}

export function parseSemVerTuple(version: string): [number, number, number, string] {
  const cleaned = version.trim().replace(/^v/i, "");
  const match = /^(\d+)\.(\d+)\.(\d+)(?:-(.+))?$/.exec(cleaned);
  if (!match) return [0, 0, 0, cleaned];
  return [
    Number.parseInt(match[1]!, 10),
    Number.parseInt(match[2]!, 10),
    Number.parseInt(match[3]!, 10),
    match[4] ?? "",
  ];
}

export function compareSemVer(a: string, b: string): number {
  const [aMaj, aMin, aPat, aPre] = parseSemVerTuple(a);
  const [bMaj, bMin, bPat, bPre] = parseSemVerTuple(b);
  if (aMaj !== bMaj) return aMaj - bMaj;
  if (aMin !== bMin) return aMin - bMin;
  if (aPat !== bPat) return aPat - bPat;
  if (!aPre && bPre) return 1;
  if (aPre && !bPre) return -1;
  return aPre.localeCompare(bPre);
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
  const width = PAD_X * 2 + (maxCol + 1) * CARD_WIDTH + Math.max(0, maxCol) * COL_GAP;
  const height =
    PAD_Y * 2 + (maxRow + 1) * (CARD_HEIGHT + BADGE_HEIGHT) + Math.max(0, maxRow) * ROW_GAP;
  return { nodes, edges, width, height };
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
    try {
      manifest = parseReleaseManifest(rel.manifest);
    } catch {
      manifest = {};
    }
    const st = extractReleaseStencil(manifest);
    const stencilId = st?.stencil_id ?? "standard-sre";
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
    const stageLabel =
      rel.state === "recalled"
        ? "RECALLED"
        : inProd
          ? "RELEASE"
          : inRc
            ? "RC"
            : inDev
              ? "DEV"
              : "DRAFT";

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

    const preferredRow =
      prevSameTrack && rowById.has(prevSameTrack) ? rowById.get(prevSameTrack)! : 0;
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
    const badgeInfo =
      status === "complete"
        ? { en: `Complete · ${stageLabel}`, ko: `승격 완료 · ${stageLabel}` }
        : status === "running"
          ? {
              en: rel.state === "draft" ? "Building · Draft" : `Running · ${stageLabel}`,
              ko: rel.state === "draft" ? "빌드/서명 대기 · 초안" : `검증 진행 중 · ${stageLabel}`,
            }
          : status === "recalled"
            ? { en: "Recalled · Blocked", ko: "긴급 회수됨" }
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
      release: rel,
    });
  }

  for (const [, liftingId] of liftMap.entries()) {
    const targetNode = rawNodes.find((n) => n.id === liftingId);
    const recalledNode = rawNodes.find(
      (n) => n.status === "recalled" && n.col < (targetNode?.col ?? 0),
    );
    if (targetNode && recalledNode) {
      const edgeId = `edge-lift-${recalledNode.id}-${targetNode.id}`;
      if (!rawEdges.some((e) => e.id === edgeId)) {
        rawEdges.push({
          id: edgeId,
          fromId: recalledNode.id,
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
  try {
    manifest = parseReleaseManifest(release.manifest);
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
  const transition = nextPromotionTransition(release);

  const stageSpecs: {
    id: string;
    title: string;
    subtitle: string;
    icon: LineageNode["icon"];
    done: boolean;
    running: boolean;
  }[] = [
    {
      id: "initialize-stencil",
      title: "initialize-stencil",
      subtitle: `${stencilId} · ${st ? `${st.enabled_workloads.length}w/${st.enabled_panel_ids.length}m` : "full-stack"}`,
      icon: "init",
      done: true,
      running: false,
    },
    {
      id: "clone-codebase",
      title: "clone-codebase",
      subtitle: `git · ${commitShort}`,
      icon: "branch",
      done: true,
      running: false,
    },
    {
      id: "build-sign-dev",
      title: "build-sign-dev",
      subtitle: `ed25519 · ${inDev ? "DEV ring verified" : "awaiting DEV sign"}`,
      icon: "shield",
      done: inDev && !recalled,
      running: !recalled && release.state === "draft",
    },
    {
      id: "promote-rc-canary",
      title: "promote-rc-canary",
      subtitle: `apollo-gate · ${inRc ? "RELEASE_CANDIDATE" : "canary soak"}`,
      icon: "branch",
      done: inRc && !recalled,
      running: !recalled && transition?.targetChannel === "RELEASE_CANDIDATE",
    },
    {
      id: "release-production",
      title: "release-production",
      subtitle: `hub-catalog · ${inProd ? `RELEASE v${release.id}` : "production ring"}`,
      icon: "cloud",
      done: inProd && !recalled,
      running: !recalled && transition?.targetChannel === "RELEASE",
    },
  ];

  const rawNodes: Omit<LineageNode, "x" | "y">[] = stageSpecs.map((spec, idx) => {
    const status: LineageNodeStatus = recalled
      ? idx <= 2
        ? "recalled"
        : "pending"
      : spec.running
        ? "running"
        : spec.done
          ? "complete"
          : "pending";
    const badgeInfo =
      status === "complete"
        ? { en: "Complete", ko: "Complete · 완료" }
        : status === "running"
          ? { en: "Running", ko: "Running · 진행 중" }
          : status === "recalled"
            ? { en: "Recalled", ko: "Recalled · 회수됨" }
            : { en: "Pending", ko: "대기 중" };
    return {
      id: spec.id,
      title: spec.title,
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
