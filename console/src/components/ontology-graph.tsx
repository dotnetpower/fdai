/**
 * OntologyGraph - 2D force-directed ontology renderer.
 *
 * Powered by ``force-graph`` (HTML5 canvas + d3-force). 2D was chosen
 * over 3D because a small structural ontology (13 nodes / 10 edges)
 * reads better on a flat plane - no occlusion, no perspective
 * foreshortening of labels, no camera fatigue.
 *
 * Behaviour:
 * - Physics settles the graph automatically. Drag any node to reposition.
 * - Hover a node → its neighbours brighten, unrelated edges fade,
 *   directional particles animate along the involved links.
 * - Click a node → pins it as the focus and pans/zooms so it's centred.
 * - Right column: focus card with description, properties, in/out edges.
 *
 * SRP: presentation-only. Data comes from the parent
 * (``/ontology/graph`` fetch); this component owns the canvas lifecycle
 * and interaction state, nothing else.
 *
 * Lazy load: ``force-graph`` is dynamic-imported so the console main
 * bundle stays small; the runtime only lands when this route opens.
 */

import { useEffect, useMemo, useRef, useState } from "preact/hooks";

export interface OntologyNode {
  readonly name: string;
  readonly key: string;
  readonly property_count: number;
  readonly properties: readonly string[];
  readonly description: string | null;
}

export interface OntologyEdge {
  readonly name: string;
  readonly from_type: string;
  readonly to_type: string;
  readonly cardinality: string;
  readonly is_transitive: boolean;
  readonly is_causal: boolean;
  readonly temporal_order: boolean;
  readonly description: string | null;
}

interface Props {
  readonly nodes: readonly OntologyNode[];
  readonly edges: readonly OntologyEdge[];
}

// ---------------------------------------------------------------------------
// Semantic clustering + colour palette
// ---------------------------------------------------------------------------

type Cluster = "sensor" | "brain" | "action" | "target" | "record" | "other";

interface ClusterMeta {
  readonly id: Cluster;
  readonly label: string;
  readonly hex: string;
}

// Deep, saturated jewel tones - reads as "glass over anodized metal"
// rather than the washed-out pastels that made cards feel disabled.
const CLUSTERS: Readonly<Record<Cluster, ClusterMeta>> = {
  sensor: { id: "sensor", label: "Sensors", hex: "#0e9bad" },
  brain: { id: "brain", label: "Knowledge", hex: "#3b82f6" },
  action: { id: "action", label: "Decisions", hex: "#e07b39" },
  target: { id: "target", label: "Targets", hex: "#16a34a" },
  record: { id: "record", label: "Records", hex: "#8b5cf6" },
  other: { id: "other", label: "Other", hex: "#64748b" },
};

function clusterOf(name: string): Cluster {
  if (/^(Signal|SecurityEvent|Metric|Event)$/i.test(name)) return "sensor";
  if (/^(Rule|Agent|RuleCandidate|Conversation)$/i.test(name)) return "brain";
  if (/^(Finding|Action|HandoffEscalation|Issue|Verdict|Decision)$/i.test(name))
    return "action";
  if (/^(Resource|Cluster|Deployment|Service|Subscription)$/i.test(name))
    return "target";
  if (/^(ChangeSummary|AuditEntry|Report|Trace|Bitemporal|Snapshot)$/i.test(name))
    return "record";
  return "other";
}

function shortCard(c: string): string {
  const s = c.toLowerCase();
  if (s.includes("many_to_many")) return "*..*";
  if (s.includes("one_to_many")) return "1..*";
  if (s.includes("many_to_one")) return "*..1";
  if (s.includes("one_to_one")) return "1..1";
  return c;
}

// ---------------------------------------------------------------------------
// force-graph node / link shapes
// ---------------------------------------------------------------------------

interface GraphNodeDatum {
  id: string;
  name: string;
  cluster: Cluster;
  color: string;
  propertyCount: number;
  outCount: number;
  inCount: number;
  degree: number;
  properties: readonly string[];
  /** first-N outgoing links, formatted like "applies_to → Resource" */
  outgoingLines: readonly string[];
  /** first-N incoming links, formatted like "Rule → applies_to" */
  incomingLines: readonly string[];
  description: string | null;
  key: string;
  /** cached card width (px), stable across frames */
  _w?: number;
  /** cached card height (px) - varies per node based on content */
  _h?: number;
  /** depth layer - "front" is fully rendered, "back" is scaled and
   *  faded so it feels one plane behind the front cards. */
  layer: "front" | "back";
  /** true when this node has at least one self-reference. Self-refs
   *  render as a small `↷` badge on the card instead of a full
   *  3D loop link - see drawNodeChip. */
  hasSelfRef: boolean;
  x?: number;
  y?: number;
  z?: number;
}

interface GraphLinkDatum {
  source: string | GraphNodeDatum;
  target: string | GraphNodeDatum;
  label: string;
  color: string;
  isCausal: boolean;
  /** row index of this link inside the source card's outgoing list. */
  outgoingIndex: number;
  /** row index of this link inside the target card's incoming list. */
  incomingIndex: number;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function OntologyGraph({ nodes, edges }: Props) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const instanceRef = useRef<any>(null);
  const hoverIdRef = useRef<string | null>(null);
  // Focus ref mirrors pinnedNode for the imperative update paths
  // (line particles, sprite opacity). It is always the "sticky"
  // click-selected node; hover is layered on top of this.
  const focusIdRef = useRef<string | null>(null);
  const [pinnedNode, setPinnedNode] = useState<string | null>(null);
  const [hoverNode, setHoverNode] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const focusName = pinnedNode ?? initialFocus(nodes, edges);

  const neighbourhoods = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const n of nodes) map.set(n.name, new Set([n.name]));
    for (const e of edges) {
      map.get(e.from_type)?.add(e.to_type);
      map.get(e.to_type)?.add(e.from_type);
    }
    return map;
  }, [nodes, edges]);

  const graphData = useMemo(() => {
    // Pre-collect outgoing/incoming lists per node - and track a
    // (source, target, linkName) -> row-index map so links can later
    // anchor to the ROW where their name appears on the card.
    const outMap = new Map<string, string[]>();
    const inMap = new Map<string, string[]>();
    // Keys: "<src>|<name>|<tgt>" -> row index in the source's
    // outgoingLines / target's incomingLines. Self-refs stay in the
    // outgoing/incoming lists so they can be visibly connected by a
    // real 3D loop line rather than an isolated `↷` badge.
    const outIndex = new Map<string, number>();
    const inIndex = new Map<string, number>();
    const selfRefIds = new Set<string>();
    for (const e of edges) {
      if (e.from_type === e.to_type) selfRefIds.add(e.from_type);
      const out = outMap.get(e.from_type) ?? [];
      const oIdx = out.length;
      out.push(`${e.name} → ${e.to_type}`);
      outMap.set(e.from_type, out);
      outIndex.set(`${e.from_type}|${e.name}|${e.to_type}`, oIdx);

      const inn = inMap.get(e.to_type) ?? [];
      const iIdx = inn.length;
      inn.push(`${e.from_type} → ${e.name}`);
      inMap.set(e.to_type, inn);
      inIndex.set(`${e.from_type}|${e.name}|${e.to_type}`, iIdx);
    }
    // Compute a front/back layer split so the graph acquires a real
    // z-axis: the top 5 most-connected nodes stay on the FRONT plane
    // at full size; the remaining 8 recede to a BACK plane farther
    // from the camera and slightly smaller.
    const FRONT_LAYER_COUNT = 5;
    const rankedForLayer = nodes
      .map((n) => ({
        name: n.name,
        deg: (outMap.get(n.name)?.length ?? 0) + (inMap.get(n.name)?.length ?? 0),
      }))
      .sort((a, b) => b.deg - a.deg);
    const frontIds = new Set(
      rankedForLayer.slice(0, FRONT_LAYER_COUNT).map((r) => r.name),
    );

    const gnodes: GraphNodeDatum[] = nodes.map((n) => {
      const c = clusterOf(n.name);
      const outs = outMap.get(n.name) ?? [];
      const ins = inMap.get(n.name) ?? [];
      // Per-node card dimensions so cards can be short or tall.
      const h = cardHeightFor(n.property_count, outs.length, ins.length);
      return {
        id: n.name,
        name: n.name,
        cluster: c,
        color: CLUSTERS[c].hex,
        propertyCount: n.property_count,
        outCount: outs.length,
        inCount: ins.length,
        degree: outs.length + ins.length,
        properties: n.properties,
        outgoingLines: outs,
        incomingLines: ins,
        description: n.description,
        key: n.key,
        _w: CARD_W,
        _h: h,
        layer: frontIds.has(n.name) ? "front" : "back",
        hasSelfRef: selfRefIds.has(n.name),
      } as GraphNodeDatum;
    });
    // Sort so BACK-layer nodes come first in the array (for depth-order
    // sanity if anything ever falls back to painter's algorithm).
    gnodes.sort((a, b) => {
      if (a.layer === b.layer) return 0;
      return a.layer === "back" ? -1 : 1;
    });
    // Build every link INCLUDING self-loops. Self-loops route with a
    // special curve (arcs outside the card's right edge) so they
    // visibly connect the outgoing text row to the incoming text row
    // on the same card - see updateLinkEndpoints.
    const glinks: GraphLinkDatum[] = [];
    for (const e of edges) {
      const c = clusterOf(e.from_type);
      const key = `${e.from_type}|${e.name}|${e.to_type}`;
      glinks.push({
        source: e.from_type,
        target: e.to_type,
        label: `${e.name} ${shortCard(e.cardinality)}`,
        color: CLUSTERS[c].hex,
        isCausal: e.is_causal,
        outgoingIndex: outIndex.get(key) ?? 0,
        incomingIndex: inIndex.get(key) ?? 0,
      });
    }
    return { nodes: gnodes, links: glinks };
  }, [nodes, edges]);

  // Mount 3D graph on first render.
  useEffect(() => {
    if (typeof window === "undefined") return;
    let cancelled = false;
    const mount = mountRef.current;
    if (!mount) return;

    (async () => {
      let ForceGraph3D: any;
      let THREE: any;
      try {
        const [fgMod, threeMod] = await Promise.all([
          import("3d-force-graph"),
          import("three"),
        ]);
        ForceGraph3D = fgMod.default ?? fgMod;
        THREE = threeMod;
      } catch (err) {
        if (!cancelled) {
          setIsLoading(false);
          setLoadError(err instanceof Error ? err.message : String(err));
        }
        return;
      }
      if (cancelled || !mountRef.current) return;

      const theme = document.documentElement.getAttribute("data-theme");
      const isDark = theme === "dark";
      const bgColor = isDark ? "#0f1115" : "#f4f6fa";
      const labelColor = isDark ? "#e6e8ee" : "#1c1e24";
      const mutedColor = isDark ? "#a4abb8" : "#575d69";

      const width = mount.clientWidth || 720;
      const height = 820;

      // ---------------------------------------------------------------
      // Sprite factory: render each card to an offscreen canvas at
      // hi-DPI so text stays crisp, then wrap it in a THREE.Sprite so
      // the card ALWAYS faces the camera (billboard). Sprites keep
      // the cards flat 2D even as the scene rotates in 3D.
      // ---------------------------------------------------------------
      const cardSpriteCache = new Map<string, any>();
      const emptyNbhd = new Map<string, Set<string>>();

      // Paint a card's canvas texture. Extracted so the click-focus
      // logic can re-paint the same canvas with a CSS-style blur
      // filter applied when the node is currently unfocused - the
      // blur pushes unrelated cards visually further away and lets
      // the focused subgraph read cleanly.
      function paintCardCanvas(
        node: GraphNodeDatum,
        canvas: HTMLCanvasElement,
        ctx: CanvasRenderingContext2D,
        dpr: number,
        cw: number,
        ch: number,
        blurred: boolean,
      ): void {
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.scale(dpr, dpr);
        // 2D canvas filter - browser applies a real Gaussian blur.
        ctx.filter = blurred ? "blur(2.5px)" : "none";
        const savedX = (node as any).x;
        const savedY = (node as any).y;
        const savedLayer = node.layer;
        (node as any).x = cw / 2;
        (node as any).y = ch / 2;
        (node as any).layer = "front";
        drawNodeChip(ctx, node, 1, {
          labelColor,
          mutedColor,
          isDark,
          hoverId: null,
          neighbourhood: emptyNbhd,
        });
        (node as any).x = savedX;
        (node as any).y = savedY;
        (node as any).layer = savedLayer;
        ctx.filter = "none";
      }

      function makeCardSprite(node: GraphNodeDatum): any {
        const cached = cardSpriteCache.get(node.id);
        if (cached) return cached;
        // dpr=3 renders text 3x internal resolution so it stays crisp
        // at the 3D camera distance without upscale blur.
        const dpr = 3;
        const cw = nodeW(node);
        const ch = nodeH(node);
        const c = document.createElement("canvas");
        c.width = cw * dpr;
        c.height = ch * dpr;
        const ctx = c.getContext("2d");
        if (!ctx) return null;
        paintCardCanvas(node, c, ctx, dpr, cw, ch, false);

        const tex = new THREE.CanvasTexture(c);
        tex.minFilter = THREE.LinearFilter;
        tex.magFilter = THREE.LinearFilter;
        tex.needsUpdate = true;
        // Front-layer cards WRITE depth (they occlude any link arc
        // that dips behind them) and render AFTER lines so they sit
        // on top. Back-layer cards do the OPPOSITE: they don't write
        // depth and render BEFORE lines, so any link touching a back
        // card visibly runs OVER that card - the user asked for the
        // back plane to look like it sits behind the link ribbon.
        const isBackNode = node.layer === "back";
        const mat = new THREE.SpriteMaterial({
          map: tex,
          transparent: true,
          // Fully opaque so front cards read as solid glass panels
          // instead of the washed-out translucent look. Depth recede
          // for back cards is carried by their smaller sprite scale.
          opacity: 1,
          depthWrite: !isBackNode,
          depthTest: true,
          alphaTest: 0.05,
        });
        const sprite = new THREE.Sprite(mat);
        sprite.renderOrder = isBackNode ? 0 : 2;
        const spriteScale = nodeSpriteScale(node);
        sprite.scale.set(cw * spriteScale, ch * spriteScale, 1);
        sprite.userData.baseScaleX = cw * spriteScale;
        sprite.userData.baseScaleY = ch * spriteScale;
        // Store what paintCardCanvas needs so we can re-paint the
        // texture in-place when focus changes (no sprite recreate).
        sprite.userData.paintCtx = ctx;
        sprite.userData.paintCanvas = c;
        sprite.userData.paintDpr = dpr;
        sprite.userData.paintW = cw;
        sprite.userData.paintH = ch;
        sprite.userData.paintNode = node;
        sprite.userData.paintTex = tex;
        sprite.userData.currentlyBlurred = false;
        cardSpriteCache.set(node.id, sprite);
        return sprite;
      }

      // ---------------------------------------------------------------
      // Click focus: applies the sticky selection state uniformly.
      //   focused node + its neighbours -> full opacity, pulled forward
      //                                    on the z-axis to layer 1
      //   everything else                -> dimmed opacity, pushed back
      //                                    on the z-axis, and blurred
      //                                    via a real canvas Gaussian
      //                                    so the focus subgraph reads
      //                                    cleanly.
      // Hover no longer affects visuals - only click drives focus. The
      // hover state is still used for the pointer cursor.
      // ---------------------------------------------------------------
      const SPRITE_BASE_OPACITY = 0.85;
      const SPRITE_FOCUS_OPACITY = 1.0;
      const SPRITE_DIM_OPACITY = 0.30;
      const FOCUS_Z = 60;    // pulled forward to (roughly) the front layer
      const DIM_Z = -260;    // pushed way back so the subgraph pops out
      function applyClickFocus(): void {
        const focusId = focusIdRef.current;
        const nbrs = focusId ? neighbourhoods.get(focusId) : null;
        cardSpriteCache.forEach((sprite, nodeId) => {
          if (!sprite || !sprite.material) return;
          const isInSet =
            !focusId || nodeId === focusId || (nbrs?.has(nodeId) ?? false);
          // Opacity.
          sprite.material.opacity = focusId
            ? (isInSet ? SPRITE_FOCUS_OPACITY : SPRITE_DIM_OPACITY)
            : SPRITE_BASE_OPACITY;
          // Blur: only unfocused-subgraph cards get blurred. Re-paint
          // the same canvas so we do NOT recreate the texture object.
          const wantBlur = !!focusId && !isInSet;
          if (sprite.userData.currentlyBlurred !== wantBlur) {
            paintCardCanvas(
              sprite.userData.paintNode,
              sprite.userData.paintCanvas,
              sprite.userData.paintCtx,
              sprite.userData.paintDpr,
              sprite.userData.paintW,
              sprite.userData.paintH,
              wantBlur,
            );
            sprite.userData.paintTex.needsUpdate = true;
            sprite.userData.currentlyBlurred = wantBlur;
          }
          // Z position animation.
          const node = (graphData.nodes as any[]).find((n) => n.id === nodeId);
          if (node) {
            const orig = originalZ.get(nodeId) ?? 0;
            let target = orig;
            if (focusId) target = isInSet ? FOCUS_Z : DIM_Z;
            animateNodeZ(node, target);
            // Sprite-scale animation: focused cards unify at
            // FRONT_SPRITE_SCALE (layer 1 size) so they visually
            // sit on the same plane; unfocused cards return to
            // their natural layer scale.
            const targetScale = focusId && isInSet
              ? FRONT_SPRITE_SCALE
              : baseSpriteScale(node);
            animateNodeSpriteScale(node, targetScale);
          }
        });
      }

      // ---------------------------------------------------------------
      // Pin every node in a 4x4 grid on the XY plane, then push
      // back-layer nodes to a farther Z. That gives real depth in the
      // scene rather than a fake 2D drop-shadow.
      //
      // Spacing is wide enough (240 units) to accommodate the tallest
      // front-layer card that now shows every property + every link.
      // Cards are ≤ ~280 px which at 0.55 sprite scale = ~154 world
      // units tall - a 240 unit row leaves 86 units of breathing room.
      // ---------------------------------------------------------------
      const cols = 4;
      const rows = 4;
      const spacingX = 175;
      const spacingY = 235;
      const spiralOrder: readonly [number, number][] = [
        [1, 1], [2, 1], [1, 2], [2, 2],
        [0, 1], [3, 1], [0, 2], [3, 2],
        [1, 0], [2, 0], [1, 3], [2, 3],
        [0, 0], [3, 0], [0, 3], [3, 3],
      ];
      const sortedByDegree = [...(graphData.nodes as any[])].sort(
        (a, b) => (b.degree ?? 0) - (a.degree ?? 0),
      );
      // originalZ per node so the click-focus can restore positions
      // when the user clicks the background or hits Reset.
      const originalZ = new Map<string, number>();
      sortedByDegree.forEach((n, i) => {
        const slot = spiralOrder[i] ?? [0, 0];
        const col = slot[0];
        const row = slot[1];
        const x = (col - 1.5) * spacingX;
        const y = -(row - 1.5) * spacingY;
        // Small per-node Z jitter so cards on the same layer are not
        // all at IDENTICAL z. Adds parallax when the camera pans -
        // sells the "cards floating in space" feel.
        const zJitter = ((n.name.charCodeAt(0) * 7 + n.name.length * 11) % 40) - 20;
        const z = (n.layer === "front" ? 40 : -140) + zJitter;
        n.x = x; n.y = y; n.z = z;
        n.fx = x; n.fy = y; n.fz = z;
        originalZ.set(n.id, z);
      });

      // ---------------------------------------------------------------
      // Z animation: smoothly slide a node to a target z. Used by
      // applyClickFocus so the connected subgraph animates forward
      // and unrelated cards recede on click.
      // ---------------------------------------------------------------
      const activeZAnims = new Map<string, number>();
      function animateNodeZ(node: any, targetZ: number, duration = 520): void {
        const startZ = node.z ?? targetZ;
        if (Math.abs(startZ - targetZ) < 0.5) {
          node.z = targetZ; node.fz = targetZ;
          return;
        }
        const start = performance.now();
        const prev = activeZAnims.get(node.id);
        if (prev !== undefined) cancelAnimationFrame(prev);
        function tick() {
          const now = performance.now();
          const t = Math.min(1, (now - start) / duration);
          // Ease-out cubic - fast start, gentle finish.
          const e = 1 - Math.pow(1 - t, 3);
          const z = startZ + (targetZ - startZ) * e;
          node.z = z;
          node.fz = z;
          const sprite = cardSpriteCache.get(node.id);
          if (sprite) sprite.position.z = z;
          if (t < 1) {
            activeZAnims.set(node.id, requestAnimationFrame(tick));
          } else {
            activeZAnims.delete(node.id);
          }
        }
        activeZAnims.set(node.id, requestAnimationFrame(tick));
      }

      // ---------------------------------------------------------------
      // Sprite-scale animation: smoothly resize a card's sprite to
      // a target sprite-scale factor. Focused cards animate up to
      // FRONT_SPRITE_SCALE (unifying visual size with layer 1);
      // unfocused ones return to their natural layer-based scale.
      // The scale is also mirrored into ``node._currentSpriteScale``
      // so ``nodeSpriteScale()`` and every link anchor helper track
      // the live sprite size as the animation plays out.
      // ---------------------------------------------------------------
      const activeScaleAnims = new Map<string, number>();
      function animateNodeSpriteScale(
        node: any,
        targetScale: number,
        duration = 520,
      ): void {
        const start = performance.now();
        const startScale =
          typeof node._currentSpriteScale === "number"
            ? node._currentSpriteScale
            : baseSpriteScale(node);
        if (Math.abs(startScale - targetScale) < 0.002) {
          node._currentSpriteScale = targetScale;
          return;
        }
        const sprite = cardSpriteCache.get(node.id);
        const cw = sprite?.userData?.paintW ?? nodeW(node);
        const ch = sprite?.userData?.paintH ?? nodeH(node);
        const prev = activeScaleAnims.get(node.id);
        if (prev !== undefined) cancelAnimationFrame(prev);
        function tick() {
          const now = performance.now();
          const t = Math.min(1, (now - start) / duration);
          const e = 1 - Math.pow(1 - t, 3);
          const s = startScale + (targetScale - startScale) * e;
          node._currentSpriteScale = s;
          if (sprite) sprite.scale.set(cw * s, ch * s, 1);
          if (t < 1) {
            activeScaleAnims.set(node.id, requestAnimationFrame(tick));
          } else {
            activeScaleAnims.delete(node.id);
          }
        }
        activeScaleAnims.set(node.id, requestAnimationFrame(tick));
      }

      // ---------------------------------------------------------------
      // Create the 3D graph. Links are drawn with a fully custom
      // THREE object per link so their endpoints can land on the
      // EXACT text row where the link name is written on each card,
      // AND the line body arcs BEHIND the front card plane so it
      // never crosses over card text.
      // ---------------------------------------------------------------
      // Number of vertices along each bezier line (higher = smoother
      // curve; 32 reads as a smooth arc without heavy geometry).
      const LINK_SEGMENTS = 32;

      function updateLinkEndpoints(groupObj: any, link: any): void {
        const src = link.source;
        const tgt = link.target;
        if (typeof src !== "object" || typeof tgt !== "object") return;
        if (src.x === undefined || tgt.x === undefined) return;

        const isSelfLoop = src.id === tgt.id;

        const s = anchorForOutgoing(src, link.outgoingIndex ?? 0);
        // Both anchors are on the LEFT edge (source and target) so
        // links visibly emanate from the text rows that name them.
        const e = anchorForIncoming(tgt, link.incomingIndex ?? 0);

        // Deterministic per-link phase from the row indices so re-renders
        // produce the same offsets (no jitter between frames).
        const phase = ((link.outgoingIndex ?? 0) * 37 + (link.incomingIndex ?? 0) * 53) % 100 / 100;

        let midX: number;
        let midYAdj: number;
        let midZ: number;

        if (isSelfLoop) {
          // Both endpoints sit on the card's LEFT edge (same policy
          // as every other link), so the loop arcs OUT to the LEFT
          // of the card and comes back. Each loop uses a UNIQUE bulge
          // + vertical stagger keyed on outgoingIndex so N self-refs
          // on the same card fan out into N clearly-separated arcs
          // instead of piling up on top of one another.
          const scale = nodeSpriteScale(src);
          const cardLeft = (src.x ?? 0) - (nodeW(src) * scale) / 2;
          const loopIdx = link.outgoingIndex ?? 0;
          const bulge = 50 + loopIdx * 32;
          midX = cardLeft - bulge;
          // Stagger midY progressively so subsequent loops sit above
          // or below their siblings, not overlapping horizontally.
          midYAdj = (s.y + e.y) / 2 + (loopIdx - 1) * 14;
          // Loops sit slightly IN FRONT of the card plane so they
          // are not occluded by the card body.
          midZ = (src.z ?? 0) + 20;
        } else {
          // Regular link: midpoint offset in -Z (away from camera /
          // behind the front card plane) so the line arcs BEHIND
          // the cards rather than crossing over them. Each link
          // also gets a small per-link phase offset in Z and Y so
          // parallel-ish links don't stack on top of each other.
          const midXBase = (s.x + e.x) / 2;
          const midYBase = (s.y + e.y) / 2;
          const segLen = Math.hypot(e.x - s.x, e.y - s.y, e.z - s.z);
          const zBow = Math.min(180, 50 + segLen * 0.22) * (0.85 + phase * 0.30);
          midX = midXBase;
          midYAdj = midYBase + (phase - 0.5) * 16;
          midZ = Math.min(s.z, e.z) - zBow;
        }

        const line = groupObj.userData.line;
        if (line && line.geometry) {
          const positions = line.geometry.attributes.position.array as Float32Array;
          // Sample the quadratic bezier B(t) = (1-t)^2*P0 + 2(1-t)t*P1 + t^2*P2
          for (let i = 0; i < LINK_SEGMENTS; i++) {
            const t = i / (LINK_SEGMENTS - 1);
            const u = 1 - t;
            const x = u * u * s.x + 2 * u * t * midX + t * t * e.x;
            const y = u * u * s.y + 2 * u * t * midYAdj + t * t * e.y;
            const z = u * u * s.z + 2 * u * t * midZ + t * t * e.z;
            positions[i * 3] = x;
            positions[i * 3 + 1] = y;
            positions[i * 3 + 2] = z;
          }
          line.geometry.attributes.position.needsUpdate = true;
          line.geometry.computeBoundingSphere();
          // Dashed materials need line-distance attributes recomputed
          // whenever vertex positions change.
          if (groupObj.userData.isSelfLoop) {
            (line as any).computeLineDistances?.();
          }
        }

        // Focus-based emphasis: click-driven only. Links touching the
        // pinned focus stay bright + get particle flow, everything
        // else is HIDDEN outright so the focused subgraph reads on a
        // clean plate. (Previously unrelated links were drawn at
        // opacity 0.08 which still visibly cluttered the scene.)
        const focusId = focusIdRef.current;
        const anyFocus = focusId !== null;
        const involved =
          anyFocus && (src.id === focusId || tgt.id === focusId);
        const cone = groupObj.userData.cone;
        const baseOpacity = groupObj.userData.isSelfLoop
          ? (isDark ? 0.9 : 0.85)
          : (isDark ? 0.5 : 0.4);
        const hotOpacity = 1;
        // Belt-and-suspenders hide: set the group AND every child
        // AND drive material opacity to 0 AND shrink the group to
        // a point. Any one of these should hide the link; combined
        // they defeat whatever pass keeps 3d-force-graph's line
        // remnants visible after focus.
        const hideThisLink = anyFocus && !involved;
        groupObj.visible = !hideThisLink;
        // scale.set(0) collapses the group to a single point so even
        // if some render path ignores `.visible`, the geometry has
        // zero area and never paints pixels.
        if (hideThisLink) groupObj.scale.set(0, 0, 0);
        else groupObj.scale.set(1, 1, 1);
        if (line) {
          line.visible = !hideThisLink;
          if (line.material) {
            line.material.opacity = hideThisLink
              ? 0
              : involved ? hotOpacity : baseOpacity;
            line.material.transparent = true;
            line.material.needsUpdate = true;
          }
        }
        if (cone) {
          cone.visible = !hideThisLink;
          if (cone.material) {
            cone.material.opacity = hideThisLink
              ? 0
              : involved ? 1 : (isDark ? 0.85 : 0.75);
            cone.material.transparent = true;
            cone.material.needsUpdate = true;
          }
        }

        // Arrowhead: place it at the target anchor, oriented along
        // the bezier tangent at t=1 (which is 2*(end - mid) for a
        // quadratic bezier). That way the cone flows naturally into
        // the target card even for tightly-curved arcs.
        if (cone) {
          const tx = 2 * (e.x - midX);
          const ty = 2 * (e.y - midYAdj);
          const tz = 2 * (e.z - midZ);
          const tlen = Math.sqrt(tx * tx + ty * ty + tz * tz) || 1;
          const dir = new THREE.Vector3(tx / tlen, ty / tlen, tz / tlen);
          const backDist = 3;
          cone.position.set(
            e.x - dir.x * backDist,
            e.y - dir.y * backDist,
            e.z - dir.z * backDist,
          );
          const up = new THREE.Vector3(0, 1, 0);
          const quat = new THREE.Quaternion().setFromUnitVectors(up, dir);
          cone.setRotationFromQuaternion(quat);
        }

        // Flowing particles along the bezier: only visible for links
        // touching the currently-focused node, otherwise hidden. Their
        // t-parameter is derived from wall-clock time so the flow is
        // continuous even though nodes are pinned.
        const particles = groupObj.userData.particles as any[] | undefined;
        if (particles && particles.length) {
          if (involved) {
            const nowSec = performance.now() * 0.001;
            const speed = 0.35; // full traversal per ~1/speed seconds
            const count = particles.length;
            for (let i = 0; i < count; i++) {
              const p = particles[i];
              // Phase-offset per particle so they space out along
              // the curve rather than stacking.
              const tp = ((nowSec * speed) + i / count) % 1;
              const up_ = 1 - tp;
              const px = up_ * up_ * s.x + 2 * up_ * tp * midX + tp * tp * e.x;
              const py = up_ * up_ * s.y + 2 * up_ * tp * midYAdj + tp * tp * e.y;
              const pz = up_ * up_ * s.z + 2 * up_ * tp * midZ + tp * tp * e.z;
              p.position.set(px, py, pz);
              p.visible = true;
              if (p.material) p.material.opacity = 0.95;
            }
          } else {
            for (const p of particles) p.visible = false;
          }
        }
      }

      const Graph = ForceGraph3D()(mount)
        .backgroundColor(bgColor)
        .width(width)
        .height(height)
        .graphData(graphData)
        .cooldownTicks(0) // static positions; no visible physics dance
        .nodeThreeObject((n: any) => makeCardSprite(n as GraphNodeDatum))
        .nodeThreeObjectExtend(false)
        .linkThreeObject((link: any) => {
          const group = new THREE.Group();
          // Sample-point line for the bezier arc.
          const lineGeo = new THREE.BufferGeometry();
          lineGeo.setAttribute(
            "position",
            new THREE.BufferAttribute(new Float32Array(LINK_SEGMENTS * 3), 3),
          );
          // Self-loops render as a slightly thicker dashed line so
          // they read as "this card references itself" even when
          // the loop crosses the same space as other links.
          const isSelfLoop = link.source === link.target ||
            (typeof link.source === "object" && typeof link.target === "object" && link.source.id === link.target.id);
          const lineMat = isSelfLoop
            ? new THREE.LineDashedMaterial({
                color: link.color,
                transparent: true,
                opacity: isDark ? 0.9 : 0.85,
                dashSize: 4,
                gapSize: 3,
                depthWrite: false,
                depthTest: true,
              })
            : new THREE.LineBasicMaterial({
                color: link.color,
                transparent: true,
                // Softer opacity so many crossing arcs do not dominate
                // the scene. Hovered links get boosted below.
                opacity: isDark ? 0.5 : 0.4,
                depthWrite: false,
                depthTest: true,
              });
          const line = new THREE.Line(lineGeo, lineMat);
          if (isSelfLoop) line.computeLineDistances?.();
          line.renderOrder = 1; // below sprites (renderOrder 2)
          group.add(line);
          // Cone arrowhead - slightly larger for self-loops so the
          // loop direction reads.
          const coneRadius = isSelfLoop ? 3.2 : 2.6;
          const coneHeight = isSelfLoop ? 8 : 6.5;
          const coneGeo = new THREE.ConeGeometry(coneRadius, coneHeight, 12);
          const coneMat = new THREE.MeshBasicMaterial({
            color: link.color,
            transparent: true,
            opacity: isDark ? 0.9 : 0.85,
            depthWrite: false,
            depthTest: true,
          });
          const cone = new THREE.Mesh(coneGeo, coneMat);
          cone.renderOrder = 1;
          group.add(cone);
          // Custom flowing particles - four small emissive spheres
          // that sample points along the bezier curve every frame.
          // Hidden by default; updateLinkEndpoints turns them on for
          // links touching the currently-focused node.
          const PARTICLE_COUNT = 5;
          // Bigger radius so the flow reads at the current camera
          // distance without the dots vanishing into the arc.
          const particleGeo = new THREE.SphereGeometry(4.5, 12, 10);
          const particles: any[] = [];
          for (let i = 0; i < PARTICLE_COUNT; i++) {
            const pMat = new THREE.MeshBasicMaterial({
              color: link.color,
              transparent: true,
              opacity: 1.0,
              // Particles must render ON TOP of every card + arc, no
              // matter which z plane they happen to be at along the
              // bezier - otherwise they visibly disappear whenever
              // the flow passes behind a card body.
              depthWrite: false,
              depthTest: false,
              blending: THREE.AdditiveBlending,
            });
            const p = new THREE.Mesh(particleGeo, pMat);
            p.visible = false;
            p.renderOrder = 5;
            group.add(p);
            particles.push(p);
          }
          group.userData.line = line;
          group.userData.cone = cone;
          group.userData.isSelfLoop = isSelfLoop;
          group.userData.particles = particles;
          // Do a first placement immediately so the link is visible
          // even before force-graph runs its first tick.
          updateLinkEndpoints(group, link);
          return group;
        })
        .linkThreeObjectExtend(false)
        // Update endpoints every frame (nodes are pinned so this is
        // cheap - just re-writes vertex positions per link).
        .linkPositionUpdate((groupObj: any, _pos: any, link: any) => {
          updateLinkEndpoints(groupObj, link);
          return true;
        })
        // Default arrows are disabled - the cone in our custom group
        // is the ONLY arrow.
        .linkDirectionalArrowLength(0)
        // Built-in directional particles are disabled - they draw
        // straight-line paths between raw node centres and can't
        // follow our custom bezier curves. We spawn our own particle
        // meshes on each linkThreeObject group and sample the bezier
        // per-frame in updateLinkEndpoints so the flow ACTUALLY
        // rides the curve.
        .linkDirectionalParticles(() => 0)
        // Link visibility accessor: 3d-force-graph re-evaluates this
        // on every render, so it is the reliable way to hide the
        // "wrong" links when a focus is pinned. We also mirror the
        // change onto group.visible in updateLinkEndpoints for the
        // rAF-driven animation frames.
        .linkVisibility((l: any) => {
          const focusId = focusIdRef.current;
          if (!focusId) return true;
          return isInvolved(l, focusId);
        })
        .enableNodeDrag(true)
        .onNodeHover((n: any) => {
          // Hover is intentionally passive - the pointer cursor is
          // the only feedback so the user does not confuse hover
          // with a real selection. Click is what commits focus.
          document.body.style.cursor = n ? "pointer" : "default";
        })
        .onNodeClick((n: any) => {
          // Sticky click focus: pin the node, pull its subgraph
          // forward on the z-axis, dim + blur everything else.
          setPinnedNode(n.id);
          focusIdRef.current = n.id;
          applyClickFocus();
          refreshLinkParticles();
        })
        .onBackgroundClick(() => {
          setPinnedNode(null);
          focusIdRef.current = null;
          applyClickFocus();
          refreshLinkParticles();
        })
        .onNodeDragEnd((n: any) => {
          n.fx = n.x; n.fy = n.y; n.fz = n.z;
        });

      // ---------------------------------------------------------------
      // refreshLinkParticles rewires 3d-force-graph's linkVisibility
      // accessor. Setting an accessor to a fresh function is the
      // canonical way to force 3d-force-graph to re-evaluate visibility
      // on every link the next time it renders (its internal cache
      // keys off the accessor reference identity). We also nudge the
      // renderer/simulation so the change is applied immediately.
      // ---------------------------------------------------------------
      function refreshLinkParticles(): void {
        // Update 3d-force-graph's linkVisibility accessor. Setting it
        // to a new function reference makes force-graph re-evaluate
        // link visibility on the next tick / render.
        try {
          Graph.linkVisibility((l: any) => {
            const focusId = focusIdRef.current;
            if (!focusId) return true;
            return isInvolved(l, focusId);
          });
        } catch {
          /* ignore */
        }
        // Walk every rendered link right now and force its visibility
        // state to match. This is the reliable path when force-graph
        // has already paused its animation loop (cooldownTicks(0)):
        //   - .visible flag stops the traversal in the renderer
        //   - .scale.set(0,0,0) collapses geometry to a single point
        //     so even a rogue render path draws nothing
        //   - opacity 0 on materials as a third safety net
        const data = Graph.graphData?.();
        const links = data?.links;
        if (links && Array.isArray(links)) {
          for (const link of links) {
            const grp = (link as any).__threeObj;
            if (!grp) continue;
            const focusId = focusIdRef.current;
            const involved = !focusId || isInvolved(link, focusId);
            grp.visible = involved;
            grp.scale.set(involved ? 1 : 0, involved ? 1 : 0, involved ? 1 : 0);
          }
        }
        try {
          Graph.resumeAnimation?.();
        } catch {
          /* ignore */
        }
        try {
          const r = Graph.renderer?.();
          const s = Graph.scene?.();
          const c = Graph.camera?.();
          if (r && s && c) r.render(s, c);
        } catch {
          /* ignore */
        }
      }

      // ---------------------------------------------------------------
      // Scene decorations: floor grid, back-wall grid, atmospheric
      // fog, and ambient lighting. Fog gives real perspective depth -
      // objects farther from the camera fade toward the background
      // colour so back-layer cards feel truly "far".
      // ---------------------------------------------------------------
      const scene = Graph.scene();

      // Exponential fog. Density 0.0007 tuned so back-layer cards
      // visibly recede without their text becoming unreadable.
      scene.fog = new THREE.FogExp2(bgColor, 0.0007);

      const floorMajor = isDark ? 0x4f9df5 : 0x5a80c0;
      const floorMinor = isDark ? 0x2a3040 : 0xc8d0e0;
      const floor = new THREE.GridHelper(1400, 28, floorMajor, floorMinor);
      floor.position.y = -260;
      (floor.material as any).transparent = true;
      (floor.material as any).opacity = isDark ? 0.35 : 0.30;
      scene.add(floor);

      // Back wall grid, rotated 90deg so it sits vertically far
      // behind the back-layer cards. Reinforces the z-depth.
      const wall = new THREE.GridHelper(1400, 20, floorMajor, floorMinor);
      wall.rotation.x = Math.PI / 2;
      wall.position.z = -320;
      (wall.material as any).transparent = true;
      (wall.material as any).opacity = isDark ? 0.20 : 0.16;
      scene.add(wall);

      const ambient = new THREE.AmbientLight(0xffffff, 0.85);
      scene.add(ambient);
      const dir = new THREE.DirectionalLight(0xffffff, 0.35);
      dir.position.set(120, 200, 220);
      scene.add(dir);

      // ---------------------------------------------------------------
      // Camera + controls: fixed front view (rotate disabled), so the
      // cards always face the viewer square-on. Users can still zoom
      // and pan the scene. The camera sits far enough back that both
      // depth planes are comfortably visible.
      // ---------------------------------------------------------------
      // ---------------------------------------------------------------
      // Camera + controls: OrbitControls handles pan (LEFT drag) and
      // zoom (wheel). Rotation is a custom middle-mouse handler that
      // rotates around the world Y axis ONLY - OrbitControls' native
      // rotation covers both axes even when polar is clamped, so we
      // bypass it entirely to guarantee horizontal-only spin.
      // ---------------------------------------------------------------
      const INITIAL_CAM: [number, number, number] = [0, 10, 780];
      Graph.cameraPosition(
        { x: INITIAL_CAM[0], y: INITIAL_CAM[1], z: INITIAL_CAM[2] },
        { x: 0, y: 0, z: 0 },
        0,
      );
      let mouseDragCleanup: (() => void) | null = null;
      try {
        const ctrls: any = Graph.controls?.();
        if (ctrls) {
          // OrbitControls rotation is fully disabled - our custom
          // handler below owns middle-click rotation and enforces
          // horizontal-only motion.
          ctrls.enableRotate = false;
          ctrls.zoomSpeed = 0.35;
          ctrls.panSpeed = 0.3;
          if ((THREE as any).MOUSE) {
            ctrls.mouseButtons = {
              LEFT: (THREE as any).MOUSE.PAN,
              MIDDLE: -1, // OrbitControls sees no button here
              RIGHT: (THREE as any).MOUSE.PAN,
            };
          }
          ctrls.update?.();
        }

        // Custom middle-mouse drag = azimuth-only rotation.
        // We rotate the camera position around the current
        // OrbitControls target using a plain Y-axis rotation matrix.
        // Camera Y stays fixed, so pitch never changes.
        let midActive = false;
        let lastX = 0;
        const cam = Graph.camera?.();
        const target = ctrls?.target;
        const onMouseDown = (ev: MouseEvent) => {
          if (ev.button !== 1) return; // middle only
          midActive = true;
          lastX = ev.clientX;
          ev.preventDefault();
        };
        const onMouseMove = (ev: MouseEvent) => {
          if (!midActive || !cam || !target) return;
          const dx = ev.clientX - lastX;
          lastX = ev.clientX;
          // Sensitivity chosen so a full drag across the canvas
          // rotates roughly a quarter turn.
          const angle = -dx * 0.006;
          const cos = Math.cos(angle);
          const sin = Math.sin(angle);
          const ox = cam.position.x - target.x;
          const oz = cam.position.z - target.z;
          const nx = ox * cos - oz * sin;
          const nz = ox * sin + oz * cos;
          cam.position.x = target.x + nx;
          cam.position.z = target.z + nz;
          // Y stays untouched - guarantees no pitch change.
          cam.lookAt(target);
          ctrls?.update?.();
        };
        const onMouseUp = (ev: MouseEvent) => {
          if (ev.button === 1) midActive = false;
        };
        mount.addEventListener("mousedown", onMouseDown);
        window.addEventListener("mousemove", onMouseMove);
        window.addEventListener("mouseup", onMouseUp);
        // Prevent the browser scroll cursor on middle click.
        const onAuxDown = (ev: MouseEvent) => {
          if (ev.button === 1) ev.preventDefault();
        };
        mount.addEventListener("auxclick", onAuxDown);
        mouseDragCleanup = () => {
          mount.removeEventListener("mousedown", onMouseDown);
          window.removeEventListener("mousemove", onMouseMove);
          window.removeEventListener("mouseup", onMouseUp);
          mount.removeEventListener("auxclick", onAuxDown);
        };
      } catch {
        /* ignore */
      }
      // Stash the cleanup on the Graph so the effect teardown finds it.
      (Graph as any).__customDrag = mouseDragCleanup;

      // ---------------------------------------------------------------
      // Reset helper: exposed on Graph so the top-right reset button
      // can bring the scene back to its initial state.
      // ---------------------------------------------------------------
      function resetView(): void {
        try {
          Graph.cameraPosition(
            { x: INITIAL_CAM[0], y: INITIAL_CAM[1], z: INITIAL_CAM[2] },
            { x: 0, y: 0, z: 0 },
            600,
          );
        } catch {
          /* ignore */
        }
        // Clear BOTH hover and pin state - hover may have been set on
        // a card that the user was over when they clicked reset.
        hoverIdRef.current = null;
        focusIdRef.current = null;
        setPinnedNode(null);
        setHoverNode(null);
        applyClickFocus();
        refreshLinkParticles();
      }
      (Graph as any).__resetView = resetView;

      instanceRef.current = Graph;
      setIsLoading(false);

      // Resize with container.
      const ro = new ResizeObserver(() => {
        if (!mountRef.current || !instanceRef.current) return;
        instanceRef.current
          .width(mountRef.current.clientWidth || 720)
          .height(height);
      });
      ro.observe(mount);
      (Graph as any).__ro = ro;

      // ---------------------------------------------------------------
      // Frame loop for the flowing particles + link geometry. When a
      // focus is active, particles need per-frame position updates AND
      // a fresh render call (3d-force-graph pauses its internal loop
      // once physics cools, so the WebGL renderer will not redraw the
      // moving particles otherwise). ``settlingFrames`` keeps the loop
      // alive for a beat after focus clears so the return animation
      // still shows.
      // ---------------------------------------------------------------
      let animFrameId = 0;
      const renderer3d = Graph.renderer?.();
      const sceneRef = Graph.scene?.();
      const cameraRef = Graph.camera?.();
      function animateFrame() {
        // Always sync every link's visibility + endpoint state from
        // the current focus, so a stale "hidden" state cannot linger
        // after focus clears and vice versa. Physics is pinned so
        // this is cheap - just a per-link update + one render.
        const data = Graph.graphData?.();
        const links = data?.links;
        if (links && Array.isArray(links)) {
          for (const link of links) {
            const grp = (link as any).__threeObj;
            if (grp) updateLinkEndpoints(grp, link);
          }
        }
        if (renderer3d && sceneRef && cameraRef) {
          renderer3d.render(sceneRef, cameraRef);
        }
        animFrameId = requestAnimationFrame(animateFrame);
      }
      animFrameId = requestAnimationFrame(animateFrame);
      (Graph as any).__animFrame = () => cancelAnimationFrame(animFrameId);
    })();

    return () => {
      cancelled = true;
      const fg = instanceRef.current;
      if (fg) {
        try {
          (fg as any).__ro?.disconnect();
          (fg as any).__customDrag?.();
          (fg as any).__animFrame?.();
          fg.pauseAnimation?.();
          fg._destructor?.();
        } catch {
          /* ignore */
        }
        instanceRef.current = null;
      }
      if (mount) mount.innerHTML = "";
      document.body.style.cursor = "default";
    };
  }, [graphData]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleReset = () => {
    const fg = instanceRef.current;
    if (fg && typeof (fg as any).__resetView === "function") {
      (fg as any).__resetView();
    }
  };

  return (
    <div class="ontology-orbit">
      <div class="ontology-orbit-canvas-wrap">
        <div ref={mountRef} class="ontology-webgl-mount" />
        {isLoading ? (
          <div class="ontology-webgl-overlay">
            <span class="state-spinner" aria-hidden="true" />
            <span class="muted">Loading 3D graph...</span>
          </div>
        ) : null}
        {loadError ? (
          <div class="ontology-webgl-overlay ontology-webgl-error">
            <span>3D renderer failed to load: {loadError}</span>
          </div>
        ) : null}
        {!isLoading && !loadError ? (
          <button
            type="button"
            class="ontology-orbit-reset"
            onClick={handleReset}
            aria-label="Reset view"
            title="Reset view (clear focus + recenter camera)"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <path d="M3 12a9 9 0 0 1 15.5-6.36" />
              <path d="M21 4v6h-6" />
              <path d="M21 12a9 9 0 0 1-15.5 6.36" />
              <path d="M3 20v-6h6" />
            </svg>
            <span>Reset</span>
          </button>
        ) : null}
        <div class="ontology-orbit-legend" aria-hidden="true">
          {Object.values(CLUSTERS)
            .filter(
              (c) =>
                c.id !== "other" ||
                nodes.some((n) => clusterOf(n.name) === "other"),
            )
            .map((c) => (
              <span key={c.id} class="ontology-orbit-legend-item">
                <span
                  class="ontology-orbit-legend-dot"
                  style={`background: ${c.hex};`}
                />
                {c.label}
              </span>
            ))}
          <span class="ontology-orbit-legend-note">
            drag to pan · middle-click drag to rotate · scroll to zoom · click a card to focus
          </span>
        </div>
      </div>

      <FocusCard
        name={focusName}
        nodes={nodes}
        edges={edges}
        neighbourhood={neighbourhoods.get(focusName) ?? new Set()}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Canvas drawing helpers
// ---------------------------------------------------------------------------

function isInvolved(link: any, hoverId: string | null): boolean {
  if (hoverId === null) return false;
  const src = typeof link.source === "string" ? link.source : link.source.id;
  const tgt = typeof link.target === "string" ? link.target : link.target.id;
  return src === hoverId || tgt === hoverId;
}

// Card sizing: width is fixed for a tidy grid feel; height is
// *computed per node* from how many items each section previews.
// Typography and geometry are tuned so text reads clearly at the
// 3D camera distance without needing the viewer to zoom in.
const CARD_W = 180;
const HEADER_H = 28;
const BODY_PAD_Y = 8;
const SECTION_LABEL_H = 16; // "P 5 properties" line
const SECTION_PAD = 4;      // trailing gap after each section
const ROW_H = 14;           // per preview item line
// Long lists are capped to keep cards from towering over the scene
// and, on click focus, from overlapping their vertical neighbours
// once the sprite scale animates to layer 1. Overflow rows show up
// as a compact "+N more" line and any link that would have anchored
// beyond the cap collapses onto that line.
const MAX_ITEMS_PER_SECTION = 4;

function cardHeightFor(propCount: number, outCount: number, inCount: number): number {
  const sectionH = (items: number) => {
    const shown = Math.min(items, MAX_ITEMS_PER_SECTION);
    const overflow = items - shown;
    const rows = Math.max(1, shown + (overflow > 0 ? 1 : 0));
    return SECTION_LABEL_H + rows * ROW_H + SECTION_PAD;
  };
  return (
    HEADER_H + BODY_PAD_Y +
    sectionH(propCount) + sectionH(outCount) + sectionH(inCount) +
    BODY_PAD_Y
  );
}

function nodeW(n: any): number {
  return (n?._w ?? CARD_W) as number;
}
function nodeH(n: any): number {
  const h = n?._h;
  return (typeof h === "number" && h > 0 ? h : 140) as number;
}

// Back-layer cards are drawn at this scale so they visually recede.
// The value picks a size ratio subtle enough to still read text but
// clear enough that the depth is obvious at a glance.
const BACK_LAYER_SCALE = 0.78;
const BACK_LAYER_ALPHA = 0.78;

function nodeScale(n: any): number {
  return n?.layer === "back" ? BACK_LAYER_SCALE : 1;
}
/** Effective on-screen half-width (accounts for layer scale). */
function nodeHalfW(n: any): number {
  return (nodeW(n) * nodeScale(n)) / 2;
}
/** Effective on-screen half-height (accounts for layer scale). */
function nodeHalfH(n: any): number {
  return (nodeH(n) * nodeScale(n)) / 2;
}

// 3D sprite scale per node. Front cards render slightly larger than
// back cards so the depth planes read at a glance even without
// perspective. Kept as a single source of truth so the link anchor
// math and the sprite factory always agree.
//
// On click, focused cards animate their scale up to FRONT_SPRITE_SCALE
// (matching layer 1) - the animation stores the current scale on
// ``node._currentSpriteScale`` so this getter, and therefore every
// anchor helper, immediately reflects the new size.
const FRONT_SPRITE_SCALE = 0.78;
const BACK_SPRITE_SCALE = 0.62;
function baseSpriteScale(n: any): number {
  return n?.layer === "back" ? BACK_SPRITE_SCALE : FRONT_SPRITE_SCALE;
}
function nodeSpriteScale(n: any): number {
  const overridden = n?._currentSpriteScale;
  if (typeof overridden === "number" && overridden > 0) return overridden;
  return baseSpriteScale(n);
}

/**
 * Y-offset from a card's centre to the vertical middle of a specific
 * body row, in world units (already includes the sprite scale).
 *
 * The row layout inside a card is:
 *   HEADER_H
 *   BODY_PAD_Y
 *   [Properties label + propRows * ROW_H + SECTION_PAD]
 *   [Outgoing   label + outRows  * ROW_H + SECTION_PAD]
 *   [Incoming   label + inRows   * ROW_H + SECTION_PAD]
 *   BODY_PAD_Y
 *
 * We walk that layout to find the target row and return
 * ``(h/2 - yFromTop) * scale``. Up is positive.
 */
function rowYOffset(
  node: any,
  section: "out" | "in",
  rowIdx: number,
): number {
  const h = nodeH(node);
  const scale = nodeSpriteScale(node);
  const propRows = Math.max(1, (node.properties?.length ?? 0));
  const outRows = Math.max(1, node.outCount ?? 0);
  // Overflow rows collapse onto the "+N more" line at position
  // MAX_ITEMS_PER_SECTION. To avoid every overflow link stacking on
  // exactly the same y (which produces the bundled "hot spot" the
  // user reported), each overflow index gets a small per-index Y
  // stagger so multiple hidden links spread out visibly across the
  // "+N more" line's vertical footprint.
  const isOverflow = rowIdx >= MAX_ITEMS_PER_SECTION;
  const clampedIdx = Math.min(rowIdx, MAX_ITEMS_PER_SECTION);
  const clampedPropRows =
    Math.min(propRows, MAX_ITEMS_PER_SECTION) +
    (propRows > MAX_ITEMS_PER_SECTION ? 1 : 0);
  const clampedOutRows =
    Math.min(outRows, MAX_ITEMS_PER_SECTION) +
    (outRows > MAX_ITEMS_PER_SECTION ? 1 : 0);
  let yFromTop = HEADER_H + BODY_PAD_Y;
  // Properties block precedes both outgoing and incoming.
  yFromTop += SECTION_LABEL_H + clampedPropRows * ROW_H + SECTION_PAD;
  if (section === "in") {
    yFromTop += SECTION_LABEL_H + clampedOutRows * ROW_H + SECTION_PAD;
  }
  yFromTop += SECTION_LABEL_H + clampedIdx * ROW_H + ROW_H / 2;
  // Overflow stagger: spread each overflow index by ~6 px in Y so
  // multiple hidden links visibly fan out below the "+N more" line
  // instead of all bundling onto the exact same anchor point.
  if (isOverflow) {
    const overflowOrder = rowIdx - MAX_ITEMS_PER_SECTION;
    yFromTop += (overflowOrder - 1) * 6;
  }
  return (h / 2 - yFromTop) * scale;
}

/**
 * World-space anchor point for the start of an outgoing link.
 * Placed at the LEFT edge of the source card so ALL link endpoints
 * (outgoing + incoming) live on the same side of every card - that
 * way the arrows visibly sprout from the text rows that name them,
 * consistent across the whole graph.
 */
function anchorForOutgoing(node: any, outIndex: number): { x: number; y: number; z: number } {
  const scale = nodeSpriteScale(node);
  const xOff = -(nodeW(node) * scale) / 2;
  const yOff = rowYOffset(node, "out", outIndex);
  return {
    x: (node.x ?? 0) + xOff,
    y: (node.y ?? 0) + yOff,
    z: node.z ?? 0,
  };
}

/**
 * World-space anchor point for the end of an incoming link.
 * Placed at the LEFT edge of the target card so it matches the
 * source anchor policy above.
 */
function anchorForIncoming(
  node: any,
  inIndex: number,
): { x: number; y: number; z: number } {
  const scale = nodeSpriteScale(node);
  const xOff = -(nodeW(node) * scale) / 2;
  const yOff = rowYOffset(node, "in", inIndex);
  return {
    x: (node.x ?? 0) + xOff,
    y: (node.y ?? 0) + yOff,
    z: node.z ?? 0,
  };
}

function truncateText(
  ctx: CanvasRenderingContext2D,
  text: string,
  maxWidth: number,
): string {
  if (ctx.measureText(text).width <= maxWidth) return text;
  const ellipsis = "…";
  let lo = 0;
  let hi = text.length;
  while (lo < hi) {
    const mid = Math.floor((lo + hi + 1) / 2);
    const candidate = text.slice(0, mid) + ellipsis;
    if (ctx.measureText(candidate).width <= maxWidth) lo = mid;
    else hi = mid - 1;
  }
  return text.slice(0, lo) + ellipsis;
}

function drawNodeChip(
  ctx: CanvasRenderingContext2D,
  node: GraphNodeDatum,
  _globalScale: number,
  opts: {
    readonly labelColor: string;
    readonly mutedColor: string;
    readonly isDark: boolean;
    readonly hoverId: string | null;
    readonly neighbourhood: ReadonlyMap<string, Set<string>>;
  },
) {
  // Card dims come from the node datum so each card can be a
  // different height depending on how much content it carries.
  const w = nodeW(node);
  const h = nodeH(node);
  const cx = node.x ?? 0;
  const cy = node.y ?? 0;

  // Back-layer cards are scaled around their own centre. We apply
  // the transform once here so the rest of the draw code stays in
  // "virgin" coordinates and does not need to know about depth.
  const isBack = node.layer === "back";
  ctx.save();
  if (isBack) {
    ctx.translate(cx, cy);
    ctx.scale(BACK_LAYER_SCALE, BACK_LAYER_SCALE);
    ctx.translate(-cx, -cy);
  }

  const x = cx - w / 2;
  const y = cy - h / 2;

  const isHover = opts.hoverId === node.id;
  const inNbhd =
    opts.hoverId !== null &&
    opts.neighbourhood.get(opts.hoverId)?.has(node.id);
  const dimmed = opts.hoverId !== null && !inNbhd && !isHover;
  const isOrphan = node.degree === 0;

  // Base opacity chains: dim > back-layer > full.
  ctx.globalAlpha = dimmed ? 0.24 : isBack ? BACK_LAYER_ALPHA : 1;

  // Card background: near-opaque panel colour so the card reads as a
  // real UI card, not a ghost. A subtle node-colour tint sits on top
  // to preserve semantic colour, and a coloured header strip on top
  // of that gives strong hierarchy.
  if (isHover) {
    ctx.shadowColor = node.color;
    ctx.shadowBlur = 16;
  } else if (!isBack) {
    // Front cards get a soft drop-shadow so they visually pop above
    // the back plane. Back cards intentionally get no shadow.
    ctx.shadowColor = opts.isDark ? "rgba(0,0,0,0.60)" : "rgba(30,40,60,0.22)";
    ctx.shadowBlur = 12;
    ctx.shadowOffsetY = 4;
  }
  // 1) Panel fill - a vertical gradient gives the card a brushed
  //    glass / stainless sheen instead of a flat pastel wash.
  const panel = ctx.createLinearGradient(0, y, 0, y + h);
  if (opts.isDark) {
    panel.addColorStop(0, "#2b323d");
    panel.addColorStop(0.5, "#212734");
    panel.addColorStop(1, "#161b24");
  } else {
    panel.addColorStop(0, "#ffffff");
    panel.addColorStop(0.5, "#f2f5f9");
    panel.addColorStop(1, "#e6eaf1");
  }
  ctx.fillStyle = panel;
  roundedRect(ctx, x, y, w, h, 12);
  ctx.fill();
  ctx.shadowBlur = 0;
  ctx.shadowOffsetY = 0;
  // 2) Colour tint overlay - deeper than before so the semantic hue
  //    reads clearly and the card no longer looks disabled.
  ctx.fillStyle = withAlpha(node.color, opts.isDark ? 0.22 : 0.13);
  roundedRect(ctx, x, y, w, h, 12);
  ctx.fill();
  // 3) Glass top-highlight - a faint bright line just inside the top
  //    edge sells the reflective glass surface.
  ctx.save();
  roundedRect(ctx, x, y, w, h, 12);
  ctx.clip();
  ctx.strokeStyle = opts.isDark
    ? "rgba(255,255,255,0.16)"
    : "rgba(255,255,255,0.9)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x + 3, y + 1.5);
  ctx.lineTo(x + w - 3, y + 1.5);
  ctx.stroke();
  ctx.restore();

  // Border - strong metallic edge so cards separate cleanly against
  // the link ribbon behind them.
  ctx.lineWidth = isHover ? 2.6 : isBack ? 1.4 : 1.8;
  ctx.strokeStyle = isBack
    ? withAlpha(node.color, 0.85)
    : withAlpha(node.color, opts.isDark ? 1 : 0.95);
  if (isOrphan) ctx.setLineDash([3, 3]);
  roundedRect(ctx, x, y, w, h, 12);
  ctx.stroke();
  ctx.setLineDash([]);

  // Header strip - a saturated colour gradient so the type name reads
  // instantly and the card gains a strong top-down hierarchy.
  const headerH = HEADER_H;
  const header = ctx.createLinearGradient(0, y, 0, y + headerH);
  header.addColorStop(0, withAlpha(node.color, opts.isDark ? 0.98 : 0.95));
  header.addColorStop(1, withAlpha(node.color, opts.isDark ? 0.72 : 0.74));
  ctx.fillStyle = header;
  roundedRectTop(ctx, x, y, w, headerH, 12);
  ctx.fill();

  // Header title. White on the saturated header strip for maximum
  // contrast, with a soft shadow so it stays legible on any hue.
  ctx.font =
    "700 14px 'Segoe UI', system-ui, -apple-system, Roboto, 'Helvetica Neue', sans-serif";
  ctx.fillStyle = "#ffffff";
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  ctx.save();
  ctx.shadowColor = "rgba(0,0,0,0.35)";
  ctx.shadowBlur = 2;
  ctx.shadowOffsetY = 0.5;
  const titleMax = w - 20;
  ctx.fillText(truncateText(ctx, node.name, titleMax), x + 10, y + headerH / 2);
  ctx.restore();

  // Body sections (properties / outgoing / incoming). Items over
  // MAX_ITEMS_PER_SECTION collapse into a single "+N more" line so
  // cards never grow taller than the grid row spacing.
  const bodyPadX = 9;
  const rowLabelFont =
    "600 11px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
  const rowItemFont =
    "500 12px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace";
  const contentMax = w - bodyPadX * 2;

  const sections: readonly [string, string, readonly string[]][] = [
    ["P", `${node.propertyCount} properties`, node.properties],
    ["↑", `${node.outCount} outgoing`, node.outgoingLines],
    ["↓", `${node.inCount} incoming`, node.incomingLines],
  ];

  // Cursor walks down the card so variable section heights stack cleanly.
  let cursorY = y + headerH + BODY_PAD_Y;
  sections.forEach(([icon, header, items], sectionIdx) => {
    // Divider between sections: a subtle dashed line running across
    // the card so property / outgoing / incoming rows read as clearly
    // grouped blocks and the eye can jump to the row a link anchors to.
    if (sectionIdx > 0) {
      const dividerY = cursorY - Math.floor(SECTION_PAD / 2);
      ctx.save();
      ctx.strokeStyle = opts.isDark
        ? withAlpha(node.color, 0.35)
        : withAlpha(node.color, 0.25);
      ctx.lineWidth = 0.8;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(x + bodyPadX, dividerY);
      ctx.lineTo(x + w - bodyPadX, dividerY);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();
    }
    // Row header: coloured icon + count label.
    ctx.font = rowLabelFont;
    ctx.fillStyle = node.color;
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText(icon, x + bodyPadX, cursorY);
    ctx.fillStyle = opts.mutedColor;
    ctx.fillText(header, x + bodyPadX + 14, cursorY);

    // Row items: shown up to MAX_ITEMS_PER_SECTION, then a "+N more"
    // hint. Truncated horizontally to fit card width.
    ctx.font = rowItemFont;
    ctx.fillStyle = opts.labelColor;
    let lineY = cursorY + SECTION_LABEL_H;
    if (items.length === 0) {
      ctx.fillStyle = opts.mutedColor;
      ctx.fillText(icon === "P" ? "no properties" : "-", x + bodyPadX, lineY);
      lineY += ROW_H;
    } else {
      const shown = items.slice(0, MAX_ITEMS_PER_SECTION);
      for (const raw of shown) {
        const line = truncateText(ctx, raw, contentMax);
        ctx.fillText(line, x + bodyPadX, lineY);
        lineY += ROW_H;
      }
      const overflow = items.length - shown.length;
      if (overflow > 0) {
        ctx.fillStyle = opts.mutedColor;
        ctx.font = rowLabelFont;
        ctx.fillText(`+${overflow} more`, x + bodyPadX, lineY);
        ctx.font = rowItemFont;
        lineY += ROW_H;
      }
    }
    // Advance cursor by this section's reserved height (matches cardHeightFor()).
    const shownRows = Math.min(items.length, MAX_ITEMS_PER_SECTION);
    const overflowRow = items.length > MAX_ITEMS_PER_SECTION ? 1 : 0;
    const reservedRows = Math.max(1, shownRows + overflowRow);
    cursorY += SECTION_LABEL_H + reservedRows * ROW_H + SECTION_PAD;
  });

  ctx.restore();
}

function roundedRectTop(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) {
  const rr = Math.min(r, w / 2, h);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.lineTo(x + w - rr, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + rr);
  ctx.lineTo(x + w, y + h);
  ctx.lineTo(x, y + h);
  ctx.lineTo(x, y + rr);
  ctx.quadraticCurveTo(x, y, x + rr, y);
  ctx.closePath();
}

function drawLinkLabel(
  ctx: CanvasRenderingContext2D,
  link: any,
  globalScale: number,
  opts: { readonly labelColor: string; readonly isDark: boolean },
) {
  const src = link.source;
  const tgt = link.target;
  if (typeof src === "string" || typeof tgt === "string") return;
  if (src.x === undefined || tgt.x === undefined) return;
  const inv = 1 / Math.max(0.6, globalScale);
  const midX = (src.x + tgt.x) / 2;
  const midY = (src.y + tgt.y) / 2;
  const fontSize = 10 * inv;
  ctx.font = `600 ${fontSize}px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`;
  const label = link.label as string;
  const textW = ctx.measureText(label).width;
  const padX = 6 * inv;
  const w = textW + padX * 2;
  const h = fontSize + 6 * inv;
  const x = midX - w / 2;
  const y = midY - h / 2;
  ctx.fillStyle = opts.isDark ? "rgba(23,26,33,0.9)" : "rgba(255,255,255,0.94)";
  ctx.strokeStyle = link.color;
  ctx.lineWidth = 1 * inv;
  roundedRect(ctx, x, y, w, h, 6 * inv);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = opts.labelColor;
  ctx.textBaseline = "middle";
  ctx.textAlign = "center";
  ctx.fillText(label, midX, midY + 0.5);
}

/**
 * Compute the intersection of a segment from ``(cx, cy)`` to ``(x, y)``
 * with the axis-aligned rectangle centred at ``(cx, cy)`` with half
 * extents ``hw`` × ``hh``. Returns the point on the rectangle border
 * along the same line, so an edge that would otherwise pass through
 * the card stops at its border instead.
 */
function rectBorderPoint(
  cx: number,
  cy: number,
  x: number,
  y: number,
  hw: number,
  hh: number,
): { x: number; y: number } {
  const dx = x - cx;
  const dy = y - cy;
  if (dx === 0 && dy === 0) return { x, y };
  // Parametric: find the smallest t in (0, 1] such that
  // |cx + t*dx - cx| = hw OR |cy + t*dy - cy| = hh.
  const tx = dx === 0 ? Infinity : Math.abs(hw / dx);
  const ty = dy === 0 ? Infinity : Math.abs(hh / dy);
  const t = Math.min(tx, ty);
  return { x: cx + dx * t, y: cy + dy * t };
}

/**
 * Draw a link that starts on the source card border, curves outward
 * from the canvas centre, and ends with an arrow tip on the target
 * card border. Text labels only appear for the hovered node's links
 * so the canvas does not become a wall of pill-labels.
 */
function drawRectEdgeLink(
  ctx: CanvasRenderingContext2D,
  link: any,
  globalScale: number,
  opts: {
    readonly labelColor: string;
    readonly isDark: boolean;
    readonly hoverId: string | null;
  },
) {
  const src = link.source;
  const tgt = link.target;
  if (typeof src === "string" || typeof tgt === "string") return;
  if (src.x === undefined || tgt.x === undefined) return;
  // Per-node half-extents that already account for the back-layer
  // scale, so the arrow tip lands on the visible card edge.
  const hwSrc = nodeHalfW(src) + 4;
  const hhSrc = nodeHalfH(src) + 4;
  const hwTgt = nodeHalfW(tgt) + 4;
  const hhTgt = nodeHalfH(tgt) + 4;

  const involved =
    opts.hoverId !== null &&
    (src.id === opts.hoverId || tgt.id === opts.hoverId);
  const dim = opts.hoverId !== null && !involved;

  // Self-loop: draw a small arc above the card.
  if (src.id === tgt.id) {
    ctx.save();
    ctx.globalAlpha = dim ? 0.15 : 0.9;
    ctx.strokeStyle = involved ? "var(--accent, #4f9df5)" : link.color;
    ctx.lineWidth = involved ? 2.2 : 1.4;
    ctx.setLineDash(link.isCausal ? [] : [4, 4]);
    const cx = src.x;
    const cy = src.y;
    const rTop = cy - hhSrc;
    ctx.beginPath();
    ctx.moveTo(cx - 12, rTop);
    ctx.bezierCurveTo(cx - 12, rTop - 40, cx + 12, rTop - 40, cx + 12, rTop);
    ctx.stroke();
    ctx.setLineDash([]);
    // Arrow tip at the right side of the return leg.
    drawArrowHead(ctx, cx + 12, rTop, Math.PI / 2, involved ? 8 : 6);
    ctx.restore();
    return;
  }

  // Endpoint on each rectangle border along the line between centres.
  // Add a small curvature offset perpendicular to the segment so
  // parallel edges (multi-graph case) don't stack.
  const sx = src.x;
  const sy = src.y;
  const tx = tgt.x;
  const ty = tgt.y;
  const dx = tx - sx;
  const dy = ty - sy;
  const dist = Math.hypot(dx, dy) || 1;
  const nx = -dy / dist;
  const ny = dx / dist;
  const curveAmount = 12 + Math.min(28, dist * 0.05);
  const mx = (sx + tx) / 2 + nx * curveAmount;
  const my = (sy + ty) / 2 + ny * curveAmount;

  const start = rectBorderPoint(sx, sy, mx, my, hwSrc, hhSrc);
  const end = rectBorderPoint(tx, ty, mx, my, hwTgt, hhTgt);

  ctx.save();
  ctx.globalAlpha = dim ? 0.12 : 1;
  ctx.strokeStyle = involved ? "var(--accent, #4f9df5)" : link.color;
  ctx.lineWidth = involved ? 2.2 : 1.2;
  ctx.setLineDash(link.isCausal ? [] : [4, 4]);
  ctx.beginPath();
  ctx.moveTo(start.x, start.y);
  ctx.quadraticCurveTo(mx, my, end.x, end.y);
  ctx.stroke();
  ctx.setLineDash([]);

  // Arrow head at the target-border point, pointing along the
  // tangent of the curve at t=1 (derivative of the quadratic bezier).
  const tanX = end.x - mx;
  const tanY = end.y - my;
  const tanAngle = Math.atan2(tanY, tanX);
  drawArrowHead(ctx, end.x, end.y, tanAngle, involved ? 9 : 7);

  ctx.restore();

  // Show the link label on the hovered node's edges.
  if (involved) {
    const inv = 1 / Math.max(0.6, globalScale);
    const fontSize = 10.5 * inv;
    ctx.font = `600 ${fontSize}px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`;
    const label = link.label as string;
    const textW = ctx.measureText(label).width;
    const padX = 6 * inv;
    const w = textW + padX * 2;
    const h = fontSize + 6 * inv;
    // Anchor label at the bezier midpoint (t=0.5).
    const lx = 0.25 * sx + 0.5 * mx + 0.25 * tx;
    const ly = 0.25 * sy + 0.5 * my + 0.25 * ty;
    ctx.fillStyle = opts.isDark ? "rgba(23,26,33,0.94)" : "rgba(255,255,255,0.96)";
    ctx.strokeStyle = link.color;
    ctx.lineWidth = 1;
    roundedRect(ctx, lx - w / 2, ly - h / 2, w, h, 6);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = opts.labelColor;
    ctx.textBaseline = "middle";
    ctx.textAlign = "center";
    ctx.fillText(label, lx, ly + 0.5);
  }
}

function drawArrowHead(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  angle: number,
  size: number,
) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(angle);
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(-size, -size * 0.5);
  ctx.lineTo(-size, size * 0.5);
  ctx.closePath();
  ctx.fillStyle = ctx.strokeStyle;
  ctx.fill();
  ctx.restore();
}

/**
 * Draw a subtle one-point-perspective floor grid onto the grid
 * underlay canvas.
 *
 * The grid is drawn in **screen coordinates** (origin at top-left,
 * (width, height) at bottom-right). The vanishing point sits above
 * the visible area so radial lines converge outside the canvas and
 * horizontal lines look like a floor receding into the distance.
 */
function drawPerspectiveGrid(
  ctx: CanvasRenderingContext2D,
  opts: {
    readonly width: number;
    readonly height: number;
    readonly isDark: boolean;
    readonly globalScale: number;
  },
) {
  const { width: w, height: h, isDark } = opts;

  // Screen rectangle to fill with the grid.
  const left = 0;
  const top = 0;
  const right = w;
  const bottom = h;

  // Vanishing point sits ABOVE the canvas top edge so all radial
  // lines converge outside the visible rectangle - the grid feels
  // like a floor extending past the horizon.
  const vpX = w / 2;
  const vpY = top - h * 0.05;

  // Colours: two intensities so major grid lines pop more than the
  // fine grid. Kept subtle (max ~14% alpha) so they never fight the
  // cards for attention.
  const majorColor = isDark
    ? "rgba(180, 200, 230, 0.16)"
    : "rgba(80, 110, 160, 0.13)";
  const minorColor = isDark
    ? "rgba(150, 170, 200, 0.08)"
    : "rgba(80, 110, 160, 0.06)";

  ctx.save();
  ctx.lineWidth = 0.7;

  // Horizontal grid lines: perspective compression via a power curve,
  // so lines are dense near the horizon and sparse near the viewer.
  // rows = 12 gives a clear "floor tile" feel without being noisy.
  const rows = 12;
  const bandTop = top + h * 0.03; // start just below the visible top
  for (let i = 1; i <= rows; i++) {
    const t = i / rows;
    // Power > 1 pushes lines toward the horizon (small t values map
    // very close to vpY / top edge).
    const y = bandTop + (bottom - bandTop) * Math.pow(t, 2.0);
    ctx.strokeStyle = i % 4 === 0 ? majorColor : minorColor;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
  }

  // Radial grid lines: fan out from vanishing point down to the
  // bottom edge, extending slightly past the canvas horizontally so
  // no line stops abruptly at the edge.
  const cols = 14;
  const bottomL = left - w * 0.35;
  const bottomR = right + w * 0.35;
  for (let i = 0; i <= cols; i++) {
    const t = i / cols;
    const bx = bottomL + (bottomR - bottomL) * t;
    ctx.strokeStyle = i % 4 === 0 ? majorColor : minorColor;
    ctx.beginPath();
    ctx.moveTo(bx, bottom);
    ctx.lineTo(vpX, vpY);
    ctx.stroke();
  }

  // Horizon line - a slightly darker stripe along the top-most
  // horizontal line, so the eye reads a clear "far edge" of the
  // floor. This anchors the back-layer cards to a real horizon.
  const horizonY = bandTop + (bottom - bandTop) * Math.pow(1 / rows, 2.0);
  ctx.strokeStyle = isDark
    ? "rgba(200, 220, 255, 0.24)"
    : "rgba(60, 90, 140, 0.22)";
  ctx.lineWidth = 1.1;
  ctx.beginPath();
  ctx.moveTo(left, horizonY);
  ctx.lineTo(right, horizonY);
  ctx.stroke();

  // Soft floor gradient: darker at the horizon, fading toward the
  // viewer. Reinforces the "receding into distance" cue without
  // adding hard lines.
  const grad = ctx.createLinearGradient(0, horizonY, 0, bottom);
  if (isDark) {
    grad.addColorStop(0, "rgba(80, 110, 160, 0.18)");
    grad.addColorStop(1, "rgba(80, 110, 160, 0)");
  } else {
    grad.addColorStop(0, "rgba(120, 140, 190, 0.11)");
    grad.addColorStop(1, "rgba(120, 140, 190, 0)");
  }
  ctx.fillStyle = grad;
  ctx.fillRect(left, horizonY, w, bottom - horizonY);

  ctx.restore();
}

/** Seeded PRNG so the initial node scatter is deterministic across
 *  reloads. Mulberry32 - tiny (32-bit state), good enough for jitter. */
function mulberry32(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function roundedRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  w: number,
  h: number,
  r: number,
) {
  const rr = Math.min(r, w / 2, h / 2);
  ctx.beginPath();
  ctx.moveTo(x + rr, y);
  ctx.arcTo(x + w, y, x + w, y + h, rr);
  ctx.arcTo(x + w, y + h, x, y + h, rr);
  ctx.arcTo(x, y + h, x, y, rr);
  ctx.arcTo(x, y, x + w, y, rr);
  ctx.closePath();
}

function withAlpha(hex: string, alpha: number): string {
  if (!hex.startsWith("#") || hex.length !== 7) return hex;
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function initialFocus(
  nodes: readonly OntologyNode[],
  edges: readonly OntologyEdge[],
): string {
  const deg = new Map<string, number>();
  for (const n of nodes) deg.set(n.name, 0);
  for (const e of edges) {
    deg.set(e.from_type, (deg.get(e.from_type) ?? 0) + 1);
    deg.set(e.to_type, (deg.get(e.to_type) ?? 0) + 1);
  }
  let best = nodes[0]?.name ?? "";
  let bestDeg = -1;
  for (const [name, d] of deg) {
    if (d > bestDeg) {
      bestDeg = d;
      best = name;
    }
  }
  return best;
}

// ---------------------------------------------------------------------------
// FocusCard - right column
// ---------------------------------------------------------------------------

function FocusCard({
  name,
  nodes,
  edges,
  neighbourhood,
}: {
  readonly name: string;
  readonly nodes: readonly OntologyNode[];
  readonly edges: readonly OntologyEdge[];
  readonly neighbourhood: ReadonlySet<string>;
}) {
  const node = nodes.find((n) => n.name === name);
  if (!node) return null;
  const outgoing = edges.filter((e) => e.from_type === name);
  const incoming = edges.filter((e) => e.to_type === name);
  return (
    <aside class="ontology-focus" aria-live="polite">
      <header class="ontology-focus-head">
        <span class="ontology-focus-name">{node.name}</span>
        <span class="ontology-focus-key muted">key: {node.key}</span>
      </header>
      {node.description ? (
        <p class="ontology-focus-desc muted">{node.description}</p>
      ) : null}
      {node.properties.length > 0 ? (
        <section>
          <h4 class="ontology-focus-h">
            Properties ({node.properties.length})
          </h4>
          <ul class="ontology-focus-list">
            {node.properties.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {outgoing.length > 0 ? (
        <section>
          <h4 class="ontology-focus-h">Outgoing ({outgoing.length})</h4>
          <ul class="ontology-focus-list">
            {outgoing.map((e, i) => (
              <li key={i}>
                <code>{e.name}</code>{" "}
                <span class="muted">
                  {shortCard(e.cardinality)} → {e.to_type}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {incoming.length > 0 ? (
        <section>
          <h4 class="ontology-focus-h">Incoming ({incoming.length})</h4>
          <ul class="ontology-focus-list">
            {incoming.map((e, i) => (
              <li key={i}>
                <span class="muted">
                  {e.from_type} {shortCard(e.cardinality)} →
                </span>{" "}
                <code>{e.name}</code>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      <div class="ontology-focus-neighbours">
        {neighbourhood.size - 1} direct neighbour(s)
      </div>
    </aside>
  );
}
