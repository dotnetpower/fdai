// AIOpsPilot — UI Cells mock.
//
// A WebGL2 view of a hierarchical tree (WAF pillars / topology / severity)
// rendered as weighted Voronoi cells filling the viewport.  On cold start
// the tree is present but empty; a simulated discovery stream (SSE with a
// JSONL replay fallback) fills each cell like a building from the base up.
//
// This is a mock. See README.md for scope.

// ---------------------------------------------------------------------------
// Config

const CFG = {
  // Hex layout radius in layout units.  The clip is a regular flat-top
  // hexagon centred at the origin; a view radius equal to this fits the
  // hex vertically edge-to-edge on the shorter viewport side.
  hexRadius: 500,
  seed: 20260704,
  voronoi: {
    root: { convergenceRatio: 0.01, maxIterationCount: 80,  minWeightRatio: 0.01 },
    deep: { convergenceRatio: 0.05, maxIterationCount: 26,  minWeightRatio: 0.01 },
  },
  zoom: {
    factor: 1.0011,
    minRatio: 0.02,        // view.radius / hexRadius floor
    maxRatio: 1.0,
    ease: 0.14,
  },
  building: {
    // One isometric building per top-level (depth === 1) cell during
    // discovery/evaluation — it fills from the base to visualize that
    // cell's aggregate progress.  Sizes are in screen pixels.
    minPx: 40,
    maxPx: 260,
    aspectHeight: 1.35,    // building height vs footprint width
    depthRatio: 0.38,      // isometric depth as a fraction of width
    sizeFactor: 0.75,      // fraction of inscribed diameter used as width
  },
  backdrop: {
    // Phyllotaxis decorative cells that sit OUTSIDE the hex — a soft
    // organic border that fades in as the view zooms out.
    count: 460,
    innerScale: 1.06,      // seed spiral inner radius as multiple of hexRadius
    outerScale: 2.6,       // spiral outer radius as multiple of hexRadius
    tint: [90, 180, 220],  // cool cyan tint that blends with the palette accent
    tintMix: 0.55,
    baseAlpha: 0.10,
  },
  overlay: {
    labelMinPx: 34,        // shorter cell side must exceed this to draw a label
    labelPadPx: 12,        // padding inside cell for label fit
  },
};

// ---------------------------------------------------------------------------
// Utilities

function lerp(a, b, t) { return a + (b - a) * t; }
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
function smoothstep(a, b, x) {
  const t = clamp((x - a) / (b - a), 0, 1);
  return t * t * (3 - 2 * t);
}

// Deterministic Lehmer LCG PRNG so layouts are stable across reloads.
function makePRNG(seed) {
  let s = (seed >>> 0) || 1;
  return function () {
    s = Math.imul(s, 48271) >>> 0;
    return (s & 0x7fffffff) / 0x7fffffff;
  };
}

function polygonCentroid(poly) {
  let x = 0, y = 0, a = 0;
  const n = poly.length;
  for (let i = 0; i < n; i++) {
    const [x0, y0] = poly[i];
    const [x1, y1] = poly[(i + 1) % n];
    const cross = x0 * y1 - x1 * y0;
    a += cross;
    x += (x0 + x1) * cross;
    y += (y0 + y1) * cross;
  }
  a *= 0.5;
  if (Math.abs(a) < 1e-9) {
    // Fallback: average of vertices
    let sx = 0, sy = 0;
    for (const p of poly) { sx += p[0]; sy += p[1]; }
    return [sx / n, sy / n];
  }
  return [x / (6 * a), y / (6 * a)];
}

function polygonMaxRadius(poly, cx, cy) {
  let r = 0;
  for (const [x, y] of poly) {
    const d = Math.hypot(x - cx, y - cy);
    if (d > r) r = d;
  }
  return r;
}

function hexPoints(cx, cy, r, rot = 0) {
  const pts = [];
  for (let i = 0; i < 6; i++) {
    const a = rot + i * (Math.PI / 3);
    pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
  }
  return pts;
}

function pointInPolygon(x, y, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const xi = poly[i][0], yi = poly[i][1];
    const xj = poly[j][0], yj = poly[j][1];
    const intersect = ((yi > y) !== (yj > y)) &&
      (x < ((xj - xi) * (y - yi)) / ((yj - yi) || 1e-9) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

// Squared distance from (px, py) to the line segment (x1,y1)-(x2,y2).
function segmentDistanceSq(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1, dy = y2 - y1;
  const lenSq = dx * dx + dy * dy;
  let t = lenSq > 0 ? ((px - x1) * dx + (py - y1) * dy) / lenSq : 0;
  t = clamp(t, 0, 1);
  const qx = x1 + t * dx, qy = y1 + t * dy;
  const ex = px - qx, ey = py - qy;
  return ex * ex + ey * ey;
}

// Signed distance from a point to a polygon: positive if inside, negative
// otherwise.  Magnitude is Euclidean distance to the nearest edge.
function signedPolygonDistance(x, y, poly) {
  let minSq = Infinity;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const dSq = segmentDistanceSq(x, y, poly[i][0], poly[i][1], poly[j][0], poly[j][1]);
    if (dSq < minSq) minSq = dSq;
  }
  const d = Math.sqrt(minSq);
  return pointInPolygon(x, y, poly) ? d : -d;
}

// Pole of inaccessibility (aka polylabel):
// find the point inside the polygon that is farthest from any edge.
// Uses a quadtree-style search over a bounding-box grid.  Returns
// { pos: [x, y], radius: <distance to nearest edge> }.
function polylabel(poly, precisionMul = 0.001) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const [x, y] of poly) {
    if (x < minX) minX = x; if (y < minY) minY = y;
    if (x > maxX) maxX = x; if (y > maxY) maxY = y;
  }
  const w = maxX - minX, h = maxY - minY;
  if (w <= 0 || h <= 0) return { pos: [minX, minY], radius: 0 };
  // Use the shorter side as the initial cell size for coverage;
  // for very elongated polygons this seeds enough cells along the
  // long axis to find the true pole rather than a local optimum.
  const cellSize = Math.min(w, h);
  const precision = Math.max(1e-6, cellSize * precisionMul);

  const evalCell = (cx, cy, half) => {
    const d = signedPolygonDistance(cx, cy, poly);
    return { x: cx, y: cy, half, d, max: d + half * Math.SQRT2 };
  };

  // Priority queue as array, sorted descending by max potential.
  const queue = [];
  const push = (c) => {
    // Binary-search insert to keep sorted.
    let lo = 0, hi = queue.length;
    while (lo < hi) {
      const m = (lo + hi) >>> 1;
      if (queue[m].max > c.max) lo = m + 1; else hi = m;
    }
    queue.splice(lo, 0, c);
  };

  // Seed grid — one cell per cellSize × cellSize square covers the
  // bbox with enough spacing that the priority-queue refinement below
  // can find the global optimum in a bounded number of iterations.
  for (let x = minX; x < maxX; x += cellSize) {
    for (let y = minY; y < maxY; y += cellSize) {
      push(evalCell(x + cellSize / 2, y + cellSize / 2, cellSize / 2));
    }
  }

  // Initial best: bbox centre + area centroid.
  let best = evalCell(minX + w / 2, minY + h / 2, 0);
  const [ccx, ccy] = polygonCentroid(poly);
  const centroidCell = evalCell(ccx, ccy, 0);
  if (centroidCell.d > best.d) best = centroidCell;

  let iter = 0;
  while (queue.length && iter++ < 2000) {
    const cell = queue.shift();
    if (cell.d > best.d) best = cell;
    if (cell.max - best.d <= precision) continue;
    const nh = cell.half / 2;
    push(evalCell(cell.x - nh, cell.y - nh, nh));
    push(evalCell(cell.x + nh, cell.y - nh, nh));
    push(evalCell(cell.x - nh, cell.y + nh, nh));
    push(evalCell(cell.x + nh, cell.y + nh, nh));
  }
  return { pos: [best.x, best.y], radius: Math.max(best.d, 0) };
}

// ---------------------------------------------------------------------------
// Palettes

let PALETTES = null;
let currentPaletteName = null;
let currentPalette = null;

async function loadPalettes() {
  const res = await fetch('data/palettes.json');
  PALETTES = await res.json();
  const stored = localStorage.getItem('ui-cells.palette');
  currentPaletteName = (stored && PALETTES.palettes[stored]) ? stored : PALETTES.default;
  currentPalette = PALETTES.palettes[currentPaletteName];
}

function paletteRGB(g, node) {
  const p = currentPalette;
  if (!p) return [200, 200, 200];
  if (p.mode === 'layered') {
    // Depth-based colour — every cell at the same depth shares one
    // shade, and children switch to a distinct shade as the view zooms
    // in.  Uses node.depth as the layer index.
    const layers = p.layers || [];
    if (!layers.length) return p.fallback || [140, 140, 155];
    const depth = node && node.depth != null ? node.depth : 0;
    const idx = Math.min(Math.max(depth, 0), layers.length - 1);
    return layers[idx].slice();
  }
  if (p.mode === 'categorical') {
    // Category driven by pillar id if available, else fallback
    const key = node && node.data ? (node.data.pillarId || node.data.pillar) : null;
    const cats = p.categories || {};
    return cats[key] || p.fallback || [140, 140, 155];
  }
  // Gradient
  const stops = p.stops || [];
  if (!stops.length) return [200, 200, 200];
  const gg = clamp(g, 0, 1);
  for (let i = 0; i < stops.length - 1; i++) {
    const s0 = stops[i], s1 = stops[i + 1];
    if (gg >= s0.t && gg <= s1.t) {
      const t = (gg - s0.t) / ((s1.t - s0.t) || 1);
      return [
        Math.round(lerp(s0.rgb[0], s1.rgb[0], t)),
        Math.round(lerp(s0.rgb[1], s1.rgb[1], t)),
        Math.round(lerp(s0.rgb[2], s1.rgb[2], t)),
      ];
    }
  }
  return stops[stops.length - 1].rgb.slice();
}

function pendingRGB() {
  return (currentPalette && currentPalette.pending) || [120, 120, 130];
}

function severityRGB(sev) {
  return (PALETTES && PALETTES.severity && PALETTES.severity[sev]) || [140, 140, 155];
}

function applyAccentToCSS() {
  const accent = (currentPalette && currentPalette.accent) || '#ffb347';
  const [r, g, b] = hexToRgbF(accent).map(v => Math.round(v * 255));
  document.documentElement.style.setProperty('--accent', accent);
  document.documentElement.style.setProperty(
    '--panel-border',
    `rgba(${r}, ${g}, ${b}, 0.35)`
  );
}

function populatePaletteSelector() {
  const sel = document.getElementById('palette-select');
  sel.innerHTML = '';
  for (const [id, p] of Object.entries(PALETTES.palettes)) {
    const opt = document.createElement('option');
    opt.value = id;
    opt.textContent = p.label;
    if (id === currentPaletteName) opt.selected = true;
    sel.appendChild(opt);
  }
  sel.addEventListener('change', () => {
    currentPaletteName = sel.value;
    currentPalette = PALETTES.palettes[currentPaletteName];
    localStorage.setItem('ui-cells.palette', currentPaletteName);
    applyAccentToCSS();
    if (state.tree) refreshColors();
    state.meshDirty = true;
  });
}

// ---------------------------------------------------------------------------
// Data / tree builders

const state = {
  skeleton: null,
  findings: [],           // { rule, resource, severity, pillar, category }
  resources: new Map(),   // id -> { ...meta, discovered, permitted, fillLevel, gCache }
  viewMode: 'pillar',
  tree: null,             // d3.hierarchy root, with polygons + centroids
  phase: 'idle',
  phaseLabel: '',
  meshDirty: true,
  viewCurrent: { x: 0, y: 0, r: CFG.hexRadius },
  viewTarget:  { x: 0, y: 0, r: CFG.hexRadius },
  backdrop: null,         // cached decorative outside cells
  focus: null,
};

async function loadSkeleton() {
  const res = await fetch('data/skeleton.json');
  state.skeleton = await res.json();
  // Seed a resource map so we can track fillLevel per resource cell
  for (const s of state.skeleton.topology.subscriptions) {
    for (const rg of s.resourceGroups) {
      for (const r of rg.resources) {
        state.resources.set(r.id, {
          ...r, sub: s.id, subLabel: s.label,
          rg: rg.id, rgLabel: rg.label,
          discovered: false, permitted: false,
          fillLevel: 0, gCache: 0,
        });
      }
    }
  }
  document.getElementById('cnt-subs').textContent = state.skeleton.topology.subscriptions.length.toString();
}

function severityOf(rule) {
  return (state.skeleton.severities.find(s => s.id === rule.severity)) || { riskScore: 0.4, weight: 0.5 };
}

function findingsForRule(ruleId) {
  return state.findings.filter(f => f.rule === ruleId);
}

function findingsForResource(resId) {
  return state.findings.filter(f => f.resource === resId);
}

function ruleFillLevel(rule, applicable) {
  // In pillar view: how many applicable resources have been evaluated for
  // this rule? Approximated as findings_count / applicable_count, capped.
  if (!applicable.length) return 0.15;
  const fired = findingsForRule(rule.id).length;
  return clamp(fired / applicable.length, 0, 1);
}

function ruleRisk(rule) {
  // g in [0,1], higher = more risk.
  const fs = findingsForRule(rule.id);
  if (!fs.length) return 0.05;
  let maxRisk = 0;
  for (const f of fs) {
    const s = state.skeleton.severities.find(x => x.id === f.severity);
    if (s && s.riskScore > maxRisk) maxRisk = s.riskScore;
  }
  return maxRisk;
}

function resourceRisk(resId) {
  const fs = findingsForResource(resId);
  if (!fs.length) return 0.03;
  let maxRisk = 0;
  for (const f of fs) {
    const s = state.skeleton.severities.find(x => x.id === f.severity);
    if (s && s.riskScore > maxRisk) maxRisk = s.riskScore;
  }
  return maxRisk;
}

function resourcesTargetedBy(rule) {
  const targets = new Set(rule.targets || ['any']);
  const out = [];
  for (const r of state.resources.values()) {
    if (targets.has('any') || targets.has(r.target)) out.push(r);
  }
  return out;
}

function buildPillarTree() {
  const sk = state.skeleton;
  const root = { id: 'root', label: 'AIOpsPilot', kind: 'root', children: [] };
  for (const p of sk.pillars) {
    const pNode = { id: p.id, label: p.label, kind: 'pillar', pillarId: p.id, children: [] };
    for (const c of p.categories) {
      const cNode = { id: `${p.id}/${c.id}`, label: c.label, kind: 'category',
                      pillarId: p.id, categoryId: c.id, children: [] };
      const rules = sk.rules.filter(r => r.pillar === p.id && r.category === c.id);
      for (const rule of rules) {
        const applicable = resourcesTargetedBy(rule);
        const sev = severityOf(rule);
        const findings = findingsForRule(rule.id).length;
        const w = sev.weight * (1 + findings * 0.5);
        cNode.children.push({
          id: rule.id, label: rule.label, kind: 'rule',
          pillarId: p.id, categoryId: c.id, severity: rule.severity,
          rule, applicable, findings,
          _value: w,
          _fillLevel: ruleFillLevel(rule, applicable),
          _g: ruleRisk(rule),
        });
      }
      if (cNode.children.length) pNode.children.push(cNode);
    }
    if (pNode.children.length) root.children.push(pNode);
  }
  return root;
}

function buildTopologyTree() {
  const sk = state.skeleton;
  const root = { id: 'root', label: 'AIOpsPilot', kind: 'root', children: [] };
  for (const s of sk.topology.subscriptions) {
    const sNode = { id: s.id, label: s.label, kind: 'subscription', subId: s.id, children: [] };
    for (const rg of s.resourceGroups) {
      const rgNode = { id: rg.id, label: rg.label, kind: 'resourceGroup', subId: s.id, children: [] };
      for (const r of rg.resources) {
        const rec = state.resources.get(r.id);
        rgNode.children.push({
          id: r.id, label: r.label, kind: 'resource',
          subId: s.id, rgId: rg.id,
          resource: rec,
          _value: 1 + findingsForResource(r.id).length * 0.6,
          _fillLevel: rec && rec.discovered ? 1 : (rec && rec.permitted ? 0.25 : 0.05),
          _g: resourceRisk(r.id),
        });
      }
      sNode.children.push(rgNode);
    }
    root.children.push(sNode);
  }
  return root;
}

function buildSeverityTree() {
  const sk = state.skeleton;
  const root = { id: 'root', label: 'AIOpsPilot', kind: 'root', children: [] };
  // Bucket findings by severity → pillar → rule.  Rules with no findings
  // fall into an "unfired" info-severity bucket so the tree stays populated.
  const buckets = new Map(); // sev -> pillar -> rule -> count
  for (const rule of sk.rules) {
    const fs = findingsForRule(rule.id);
    if (!fs.length) {
      const sev = 'info';
      if (!buckets.has(sev)) buckets.set(sev, new Map());
      const byP = buckets.get(sev);
      if (!byP.has(rule.pillar)) byP.set(rule.pillar, new Map());
      byP.get(rule.pillar).set(rule.id, { rule, count: 0 });
    } else {
      for (const f of fs) {
        const sev = f.severity;
        if (!buckets.has(sev)) buckets.set(sev, new Map());
        const byP = buckets.get(sev);
        if (!byP.has(rule.pillar)) byP.set(rule.pillar, new Map());
        const byR = byP.get(rule.pillar);
        const prev = byR.get(rule.id);
        byR.set(rule.id, { rule, count: (prev ? prev.count : 0) + 1 });
      }
    }
  }
  const sevOrder = ['critical', 'high', 'medium', 'low', 'info'];
  for (const sev of sevOrder) {
    const byP = buckets.get(sev);
    if (!byP) continue;
    const s = sk.severities.find(x => x.id === sev) || { riskScore: 0.3 };
    const sevNode = {
      id: `sev-${sev}`, label: sev.charAt(0).toUpperCase() + sev.slice(1),
      kind: 'severity', severity: sev, children: [],
    };
    for (const [pid, byR] of byP.entries()) {
      const pNode = { id: `sev-${sev}/${pid}`, label: pid, kind: 'pillar',
                      pillarId: pid, severity: sev, children: [] };
      for (const [rid, rec] of byR.entries()) {
        pNode.children.push({
          id: `sev-${sev}/${pid}/${rid}`, label: rec.rule.label, kind: 'rule',
          pillarId: pid, severity: sev,
          _value: 0.5 + rec.count,
          _fillLevel: rec.count > 0 ? 1 : 0.2,
          _g: s.riskScore,
        });
      }
      if (pNode.children.length) sevNode.children.push(pNode);
    }
    if (sevNode.children.length) root.children.push(sevNode);
  }
  return root;
}

function buildTreeForView(view) {
  if (view === 'topology') return buildTopologyTree();
  if (view === 'severity') return buildSeverityTree();
  return buildPillarTree();
}

// ---------------------------------------------------------------------------
// Layout — weighted Voronoi treemap inside a flat-top hex clip.

function runLayout(rootData) {
  const hex = hexPoints(0, 0, CFG.hexRadius);
  const prng = makePRNG(CFG.seed);
  const rootH = d3.hierarchy(rootData).sum(d => d._value || 1);
  const cfg = CFG.voronoi.root;
  const treemap = d3.voronoiTreemap()
    .clip(hex)
    .convergenceRatio(cfg.convergenceRatio)
    .maxIterationCount(cfg.maxIterationCount)
    .minWeightRatio(cfg.minWeightRatio)
    .prng(prng);
  treemap(rootH);

  // Cache per-node geometry:
  //   _c        centroid (used for hit-tests and framing zoom)
  //   _r        max radius from centroid (framing zoom)
  //   _ext      axis-aligned distances from the LABEL anchor to the
  //             polygon edge, in layout units
  //   _labelPos label anchor = pole of inaccessibility (the point
  //             INSIDE the polygon that is farthest from any edge).
  //             This is the "most visually central" point for a
  //             polygon and beats both centroid and bbox centre for
  //             asymmetric shapes.  See mapbox/polylabel.
  //   _halfW,   symmetric half-widths from the label anchor.  Using
  //   _halfH    min(right, left) / min(up, down) guarantees the label
  //             rectangle stays inside the convex cell along the axis
  //             lines through the anchor.
  rootH.each(n => {
    const poly = n.polygon;
    if (poly && poly.length) {
      const c = polygonCentroid(poly);
      n._c = c;
      n._r = polygonMaxRadius(poly, c[0], c[1]);
      const pl = polylabel(poly);
      const anchor = pointInPolygon(pl.pos[0], pl.pos[1], poly) ? pl.pos : c;
      n._labelPos = anchor;
      const ext = axisExtentsFromInside(anchor[0], anchor[1], poly);
      n._ext = ext;
      n._halfW = Math.min(ext.right, ext.left);
      n._halfH = Math.min(ext.up,    ext.down);
    } else {
      n._c = [0, 0];
      n._r = 0;
      n._labelPos = [0, 0];
      n._ext = { right: 0, left: 0, up: 0, down: 0 };
      n._halfW = 0;
      n._halfH = 0;
    }
  });
  return rootH;
}

// Distance from an interior point (cx, cy) to the polygon edge along
// each of the four axis directions.  In layout space +y is "up" (screen
// y flip happens later).  Voronoi cells are convex, so a ray from an
// interior point crosses exactly one edge per direction.
function axisExtentsFromInside(cx, cy, poly) {
  const dirs = [[1, 0], [-1, 0], [0, 1], [0, -1]];
  const keys = ['right', 'left', 'up', 'down'];
  const out = { right: 0, left: 0, up: 0, down: 0 };
  for (let k = 0; k < 4; k++) {
    const dx = dirs[k][0], dy = dirs[k][1];
    let best = Infinity;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const x1 = poly[j][0], y1 = poly[j][1];
      const x2 = poly[i][0], y2 = poly[i][1];
      const ex = x2 - x1, ey = y2 - y1;
      const det = ex * dy - ey * dx;   // (dx, dy) × edge
      if (Math.abs(det) < 1e-9) continue;
      const t = ((y1 - cy) * ex - (x1 - cx) * ey) / det;
      const u = (dx * (y1 - cy) - dy * (x1 - cx)) / det;
      if (t > 0 && u >= 0 && u <= 1 && t < best) best = t;
    }
    out[keys[k]] = Number.isFinite(best) ? best : 0;
  }
  return out;
}

// Extract flat array of nodes with polygons, sorted by depth ascending
function walkNodes(root) {
  const nodes = [];
  root.each(n => { if (n.polygon && n.polygon.length >= 3) nodes.push(n); });
  return nodes;
}

// ---------------------------------------------------------------------------
// WebGL2 renderer

let gl = null;
const glState = {
  prog: null, progLight: null,
  fillVao: null, fillBuf: null, fillCount: 0,
  rimVao: null,  rimBuf: null,  rimCount: 0,
  lightVao: null,
  loc: {},
  lightLoc: {},
};

const VS_FILL = `#version 300 es
precision highp float;
in vec2 a_pos;
in vec3 a_color;
in vec3 a_meta;    // (depth, mode, baseAlpha)
uniform vec2 u_center;
uniform float u_scale;
uniform vec2 u_res;
uniform float u_viewRatio;
out vec3 v_color;
out float v_alpha;
out float v_mode;
out vec2 v_world;

float revealOf(float depth, float vr){
  // Root (0) and depth-1 cells are always visible.  Deeper cells
  // reveal as we zoom in (viewRatio shrinks).  Each depth has
  // (begin, end) thresholds in viewRatio: reveal starts at begin
  // and completes at end (end < begin).
  if (depth < 1.5) return 1.0;
  vec2 w;
  if      (depth < 2.5) w = vec2(0.70, 0.42);
  else if (depth < 3.5) w = vec2(0.30, 0.12);
  else                  w = vec2(0.10, 0.04);
  float t = clamp((vr - w.x) / (w.y - w.x), 0.0, 1.0);
  return t*t*(3.0 - 2.0*t);
}

void main(){
  vec2 p = (a_pos - u_center) * u_scale;
  // Both WebGL NDC and the 2D overlay treat "layout +y" as UP; without
  // this convention the overlay labels (drawn with layout +y = up) end
  // up mirrored from the WebGL cells.  Use +p.y (no flip) so the two
  // stay in sync.
  vec2 ndc = vec2(p.x * 2.0 / u_res.x, p.y * 2.0 / u_res.y);
  gl_Position = vec4(ndc, 0.0, 1.0);
  float depth = a_meta.x;
  float mode  = a_meta.y;
  float baseAlpha = a_meta.z;
  float a;
  if (mode >= 1.5) {
    // Decorative backdrop cells outside the hex — fade IN as we zoom
    // out (viewRatio grows) and fade OUT as we zoom in.
    float t = smoothstep(0.35, 0.95, u_viewRatio);
    a = t * baseAlpha;
  } else {
    float rr = revealOf(depth, u_viewRatio);
    float rrNext = revealOf(depth + 1.0, u_viewRatio);
    // Non-leaf cells fade as their children fade in.
    a = rr * (1.0 - rrNext * 0.85) * baseAlpha;
  }
  v_color = a_color;
  v_alpha = a;
  v_mode = mode;
  v_world = a_pos;
}
`;

const FS_FILL = `#version 300 es
precision highp float;
in vec3 v_color;
in float v_alpha;
in float v_mode;
in vec2 v_world;
uniform float u_hexRadius;
out vec4 outColor;

// Flat-top regular-hex containment test.
bool insideHex(vec2 p, float R){
  vec2 q = abs(p);
  float apo = R * 0.86602540;                   // R * sqrt(3) / 2
  return (q.y <= apo) && (q.x + q.y * 0.57735026 <= R);
}

void main(){
  // Decorative backdrop cells must not draw inside the hex; the primary
  // tree cells own that area.  Discard bleeding fragments cleanly.
  if (v_mode >= 1.5 && insideHex(v_world, u_hexRadius)) discard;
  outColor = vec4(v_color * v_alpha, v_alpha);
}
`;

const VS_LIGHT = `#version 300 es
precision highp float;
in vec2 a_pos;
out vec2 v_uv;
void main(){
  v_uv = a_pos * 0.5 + 0.5;
  gl_Position = vec4(a_pos, 0.0, 1.0);
}
`;

const FS_LIGHT = `#version 300 es
precision highp float;
in vec2 v_uv;
uniform float u_time;
uniform vec3 u_accent;
out vec4 outColor;

float glow(vec2 uv, vec2 c, float r, float s){
  float d = distance(uv, c);
  return exp(-pow(d / r, 2.0)) * s;
}

void main(){
  vec2 uv = v_uv;
  // Sci-fi ambient — a lifted mid-navy gradient (no near-black corners
  // so the frame doesn't feel oppressive), with subtle cool glows and
  // a faint square grid.
  vec3 top = vec3(0.18, 0.23, 0.36);
  vec3 bot = vec3(0.12, 0.16, 0.26);
  vec3 col = mix(bot, top, uv.y);

  float t = u_time * 0.08;
  col += glow(uv, vec2(0.25 + 0.03*sin(t*0.9), 0.75 + 0.02*cos(t*0.7)), 0.55, 0.10) * vec3(0.30, 0.90, 1.00);
  col += glow(uv, vec2(0.78 + 0.03*cos(t*0.8), 0.30 + 0.03*sin(t*0.9)), 0.50, 0.09) * vec3(0.85, 0.45, 1.00);
  col += glow(uv, vec2(0.55 + 0.02*sin(t*1.1), 0.20 + 0.02*cos(t*0.85)), 0.40, 0.06) * u_accent;

  // Faint grid — thin cyan lines, fading near the centre of the screen.
  vec2 g = abs(fract(uv * 42.0) - 0.5);
  float line = 1.0 - smoothstep(0.005, 0.02, min(g.x, g.y));
  float fade = smoothstep(0.20, 0.85, distance(uv, vec2(0.5, 0.5)));
  col += line * 0.045 * fade * vec3(0.40, 0.88, 1.00);

  outColor = vec4(col, 1.0);
}
`;

function compileShader(gl, type, src) {
  const sh = gl.createShader(type);
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    const info = gl.getShaderInfoLog(sh);
    console.error('Shader compile failed:', info, '\n', src);
    gl.deleteShader(sh);
    throw new Error('Shader compile failed: ' + info);
  }
  return sh;
}

function linkProgram(gl, vsSrc, fsSrc) {
  const vs = compileShader(gl, gl.VERTEX_SHADER, vsSrc);
  const fs = compileShader(gl, gl.FRAGMENT_SHADER, fsSrc);
  const prog = gl.createProgram();
  gl.attachShader(prog, vs);
  gl.attachShader(prog, fs);
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
    const info = gl.getProgramInfoLog(prog);
    console.error('Program link failed:', info);
    throw new Error('Program link failed: ' + info);
  }
  return prog;
}

function initGL() {
  const canvas = document.getElementById('gl');
  const ctx = canvas.getContext('webgl2', { antialias: true, premultipliedAlpha: true });
  if (!ctx) throw new Error('WebGL2 not available');
  gl = ctx;

  glState.prog = linkProgram(gl, VS_FILL, FS_FILL);
  glState.progLight = linkProgram(gl, VS_LIGHT, FS_LIGHT);

  glState.loc.a_pos     = gl.getAttribLocation(glState.prog, 'a_pos');
  glState.loc.a_color   = gl.getAttribLocation(glState.prog, 'a_color');
  glState.loc.a_meta    = gl.getAttribLocation(glState.prog, 'a_meta');
  glState.loc.u_center  = gl.getUniformLocation(glState.prog, 'u_center');
  glState.loc.u_scale   = gl.getUniformLocation(glState.prog, 'u_scale');
  glState.loc.u_res     = gl.getUniformLocation(glState.prog, 'u_res');
  glState.loc.u_viewRatio = gl.getUniformLocation(glState.prog, 'u_viewRatio');
  glState.loc.u_hexRadius = gl.getUniformLocation(glState.prog, 'u_hexRadius');

  glState.lightLoc.a_pos    = gl.getAttribLocation(glState.progLight, 'a_pos');
  glState.lightLoc.u_time   = gl.getUniformLocation(glState.progLight, 'u_time');
  glState.lightLoc.u_accent = gl.getUniformLocation(glState.progLight, 'u_accent');

  // Full-screen triangle for the ambient light program
  glState.lightVao = gl.createVertexArray();
  gl.bindVertexArray(glState.lightVao);
  const lb = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, lb);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
    -1, -1,  3, -1,  -1, 3,
  ]), gl.STATIC_DRAW);
  gl.enableVertexAttribArray(glState.lightLoc.a_pos);
  gl.vertexAttribPointer(glState.lightLoc.a_pos, 2, gl.FLOAT, false, 0, 0);
  gl.bindVertexArray(null);

  glState.fillVao = gl.createVertexArray();
  glState.fillBuf = gl.createBuffer();
  glState.rimVao  = gl.createVertexArray();
  glState.rimBuf  = gl.createBuffer();

  // Vertex layout: 2 (pos) + 3 (color) + 3 (meta) = 8 floats per vertex
  const stride = 8 * 4;

  gl.bindVertexArray(glState.fillVao);
  gl.bindBuffer(gl.ARRAY_BUFFER, glState.fillBuf);
  gl.enableVertexAttribArray(glState.loc.a_pos);
  gl.vertexAttribPointer(glState.loc.a_pos, 2, gl.FLOAT, false, stride, 0);
  gl.enableVertexAttribArray(glState.loc.a_color);
  gl.vertexAttribPointer(glState.loc.a_color, 3, gl.FLOAT, false, stride, 2 * 4);
  gl.enableVertexAttribArray(glState.loc.a_meta);
  gl.vertexAttribPointer(glState.loc.a_meta, 3, gl.FLOAT, false, stride, 5 * 4);
  gl.bindVertexArray(null);

  gl.bindVertexArray(glState.rimVao);
  gl.bindBuffer(gl.ARRAY_BUFFER, glState.rimBuf);
  gl.enableVertexAttribArray(glState.loc.a_pos);
  gl.vertexAttribPointer(glState.loc.a_pos, 2, gl.FLOAT, false, stride, 0);
  gl.enableVertexAttribArray(glState.loc.a_color);
  gl.vertexAttribPointer(glState.loc.a_color, 3, gl.FLOAT, false, stride, 2 * 4);
  gl.enableVertexAttribArray(glState.loc.a_meta);
  gl.vertexAttribPointer(glState.loc.a_meta, 3, gl.FLOAT, false, stride, 5 * 4);
  gl.bindVertexArray(null);

  gl.enable(gl.BLEND);
  gl.blendFuncSeparate(gl.ONE, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
}

function nodeColorRGB(n) {
  const data = n.data;
  const isBranch = !!(n.children && n.children.length);
  // Pending state: no data yet → neutral pending gray
  const pending = state.phase === 'idle' || state.phase === 'auth' || state.phase === 'permission';
  const rec = data.resource;
  const isUndiscovered = data.kind === 'resource' && rec && !rec.discovered;
  if (pending || isUndiscovered) {
    return pendingRGB();
  }
  // Layered palette: colour depends only on tree depth so every cell
  // at the same layer shares one shade (paletteRGB reads n.depth).
  if (currentPalette && currentPalette.mode === 'layered') {
    return paletteRGB(0, n);
  }
  let g = data._g || 0;
  if (isBranch) {
    // Branches take the max g of their descendants for a "hot spot" read
    let m = 0;
    n.each(child => { if (child !== n && (child.data._g || 0) > m) m = child.data._g || 0; });
    g = m;
  }
  return paletteRGB(g, n);
}

function nodeFillLevel(n) {
  if (n.data._fillLevel != null) return n.data._fillLevel;
  if (n.children && n.children.length) {
    let s = 0, c = 0;
    for (const ch of n.children) { s += nodeFillLevel(ch); c += 1; }
    return c ? s / c : 0;
  }
  return 0;
}

function nodeBaseAlpha(n) {
  // Fills are translucent so the dark bg reads through — the bright
  // rim (drawn separately) does the heavy lifting for cell identity.
  if (n.depth === 0) return 0.06;
  return 0.42;
}

// Generate decorative Voronoi cells OUTSIDE the hex, seeded by a
// golden-angle phyllotaxis spiral.  Cached on state.backdrop and
// rebuilt only when the palette changes (colors baked into VBO).
function generateBackdrop() {
  if (typeof d3.Delaunay !== 'function') return [];
  const N = CFG.backdrop.count;
  const inner = CFG.hexRadius * CFG.backdrop.innerScale;
  const outer = CFG.hexRadius * CFG.backdrop.outerScale;
  const golden = Math.PI * (3 - Math.sqrt(5));
  const points = [];
  for (let i = 0; i < N; i++) {
    const t = (i + 0.5) / N;
    const r = inner + (outer - inner) * Math.sqrt(t);
    const a = i * golden;
    points.push([r * Math.cos(a), r * Math.sin(a)]);
  }
  const b = outer * 1.5;
  const delaunay = d3.Delaunay.from(points);
  const voronoi = delaunay.voronoi([-b, -b, b, b]);
  const hex = hexPoints(0, 0, CFG.hexRadius);
  const cells = [];
  for (let i = 0; i < points.length; i++) {
    const [sx, sy] = points[i];
    // Skip seeds inside the hex; those cells are handled by the primary
    // tree layout.
    if (pointInPolygon(sx, sy, hex)) continue;
    const poly = voronoi.cellPolygon(i);
    if (!poly || poly.length < 3) continue;
    cells.push({ seed: points[i], polygon: poly });
  }
  return cells;
}

function buildMesh() {
  if (!state.tree) return;
  const nodes = walkNodes(state.tree);

  // Fills: per polygon, a triangle fan (center + rim vertices).
  // Center vertex has higher alpha; rim vertices have lower — gives a
  // radial "membrane" gradient without a texture.
  const fillArr = [];
  const rimArr = [];

  // Decorative backdrop cells (outside the hex).  They render at mode 2
  // so the vertex shader fades them IN as the view zooms out.
  const bd = state.backdrop || (state.backdrop = generateBackdrop());
  if (bd && bd.length) {
    // Base color is the palette's tint with a slight blend toward its accent.
    const [tr, tg, tb] = CFG.backdrop.tint;
    const accent = (currentPalette && currentPalette.accent) || '#ffb347';
    const [ar, ag, ab] = hexToRgbF(accent).map(v => Math.round(v * 255));
    const mix = 1 - CFG.backdrop.tintMix;
    const r0 = ((tr * (1 - mix) + ar * mix) / 255);
    const g0 = ((tg * (1 - mix) + ag * mix) / 255);
    const b0 = ((tb * (1 - mix) + ab * mix) / 255);
    const rimR = clamp(r0 * 1.25, 0, 1);
    const rimG = clamp(g0 * 1.25, 0, 1);
    const rimB = clamp(b0 * 1.25, 0, 1);
    const baseA = CFG.backdrop.baseAlpha;

    for (const cell of bd) {
      const poly = cell.polygon;
      // d3-delaunay closes the polygon (last point == first) — skip it.
      const len = poly[poly.length - 1][0] === poly[0][0] &&
                  poly[poly.length - 1][1] === poly[0][1]
        ? poly.length - 1 : poly.length;
      if (len < 3) continue;
      const [cx, cy] = cell.seed;
      for (let i = 0; i < len; i++) {
        const j = (i + 1) % len;
        fillArr.push(cx, cy,             r0, g0, b0, 0, 2, baseA);
        fillArr.push(poly[i][0], poly[i][1], r0, g0, b0, 0, 2, baseA * 0.4);
        fillArr.push(poly[j][0], poly[j][1], r0, g0, b0, 0, 2, baseA * 0.4);
      }
      for (let i = 0; i < len; i++) {
        const j = (i + 1) % len;
        rimArr.push(poly[i][0], poly[i][1], rimR, rimG, rimB, 0, 2, baseA * 1.6);
        rimArr.push(poly[j][0], poly[j][1], rimR, rimG, rimB, 0, 2, baseA * 1.6);
      }
    }
  }

  for (const n of nodes) {
    const poly = n.polygon;
    if (!poly || poly.length < 3) continue;
    const [cx, cy] = n._c;
    const rgb = nodeColorRGB(n);
    const r = rgb[0] / 255, g = rgb[1] / 255, b = rgb[2] / 255;
    const depth = n.depth;
    const isLeaf = !n.children || n.children.length === 0;
    const mode = isLeaf ? 1 : 0;
    const centerAlpha = nodeBaseAlpha(n);
    const rimAlpha = centerAlpha * 0.78;

    // Fan
    for (let i = 0; i < poly.length; i++) {
      const j = (i + 1) % poly.length;
      // Triangle: center, poly[i], poly[j]
      fillArr.push(cx, cy, r, g, b, depth, mode, centerAlpha);
      fillArr.push(poly[i][0], poly[i][1], r, g, b, depth, mode, rimAlpha);
      fillArr.push(poly[j][0], poly[j][1], r, g, b, depth, mode, rimAlpha);
    }

    // Rim: bright line loop along the polygon edge, colour boosted so
    // it reads as a glowing seam against the dark sci-fi background.
    const rimR = Math.min(1, r * 1.35 + 0.10);
    const rimG = Math.min(1, g * 1.35 + 0.10);
    const rimB = Math.min(1, b * 1.35 + 0.10);
    const rimBase = 0.95;
    for (let i = 0; i < poly.length; i++) {
      const j = (i + 1) % poly.length;
      rimArr.push(poly[i][0], poly[i][1], rimR, rimG, rimB, depth, mode, rimBase);
      rimArr.push(poly[j][0], poly[j][1], rimR, rimG, rimB, depth, mode, rimBase);
    }
  }

  const fills = new Float32Array(fillArr);
  const rims = new Float32Array(rimArr);
  gl.bindBuffer(gl.ARRAY_BUFFER, glState.fillBuf);
  gl.bufferData(gl.ARRAY_BUFFER, fills, gl.DYNAMIC_DRAW);
  glState.fillCount = fills.length / 8;

  gl.bindBuffer(gl.ARRAY_BUFFER, glState.rimBuf);
  gl.bufferData(gl.ARRAY_BUFFER, rims, gl.DYNAMIC_DRAW);
  glState.rimCount = rims.length / 8;

  state.meshDirty = false;
}

function refreshColors() {
  // Rebuild the mesh — color and fillLevel changes are baked into the VBO.
  // For a mock with a few hundred cells this is cheap; for 10k+ we would
  // separate a color-only fast path.
  state.meshDirty = true;
}

// ---------------------------------------------------------------------------
// 2D overlay — labels and discovery-phase isometric buildings.

const overlayState = {
  canvas: null, ctx: null,
  dpr: 1,
};

function initOverlay() {
  overlayState.canvas = document.getElementById('overlay');
  overlayState.ctx = overlayState.canvas.getContext('2d');
}

function toScreen(x, y, view, w, h) {
  const scale = Math.min(w, h) / (view.r * 2);
  return [
    (x - view.x) * scale + w / 2,
    -(y - view.y) * scale + h / 2,   // flip y for screen space
  ];
}

function screenSize(size, view, w, h) {
  return size * (Math.min(w, h) / (view.r * 2));
}

function drawIsometricBuilding(ctx, cx, cy, w, h, fillLevel, rgb, alpha) {
  // Simple isometric block with a fill bar climbing from the base.
  const dx = w * CFG.building.depthRatio;
  const dy = -w * CFG.building.depthRatio * 0.5;
  const halfW = w / 2;
  const baseY = cy + halfW * 0.25;   // sit slightly below centroid
  const topY  = baseY - h;

  const colStroke = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${clamp(alpha * 0.9, 0, 1)})`;
  const colFill   = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${clamp(alpha * 0.35, 0, 1)})`;
  const colGhost  = `rgba(255, 255, 255, ${clamp(alpha * 0.10, 0, 1)})`;

  const fY = baseY - h * clamp(fillLevel, 0, 1);

  // Filled portion of front face (up to fillLevel)
  ctx.fillStyle = colFill;
  ctx.fillRect(cx - halfW, fY, w, baseY - fY);
  // Filled portion of right face
  ctx.beginPath();
  ctx.moveTo(cx + halfW, fY);
  ctx.lineTo(cx + halfW + dx, fY + dy);
  ctx.lineTo(cx + halfW + dx, baseY + dy);
  ctx.lineTo(cx + halfW, baseY);
  ctx.closePath();
  ctx.fillStyle = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${clamp(alpha * 0.22, 0, 1)})`;
  ctx.fill();

  // Full outline (ghost frame)
  ctx.lineWidth = 1;
  ctx.strokeStyle = colStroke;
  ctx.fillStyle = colGhost;
  // Front face
  ctx.beginPath();
  ctx.rect(cx - halfW, topY, w, h);
  ctx.fill();
  ctx.stroke();
  // Right face
  ctx.beginPath();
  ctx.moveTo(cx + halfW, topY);
  ctx.lineTo(cx + halfW + dx, topY + dy);
  ctx.lineTo(cx + halfW + dx, baseY + dy);
  ctx.lineTo(cx + halfW, baseY);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  // Top face
  ctx.beginPath();
  ctx.moveTo(cx - halfW, topY);
  ctx.lineTo(cx + halfW, topY);
  ctx.lineTo(cx + halfW + dx, topY + dy);
  ctx.lineTo(cx - halfW + dx, topY + dy);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
}

// 1.0 when the cell is fully in view at its depth, 0 when hidden.
// Mirrors revealOf() in the shader.  vr shrinks as we zoom in.
function overlayReveal(depth, vr) {
  if (depth <= 1) return 1.0;
  let begin, end;
  if      (depth === 2) { begin = 0.70; end = 0.42; }
  else if (depth === 3) { begin = 0.30; end = 0.12; }
  else                  { begin = 0.10; end = 0.04; }
  const t = clamp((vr - begin) / (end - begin), 0, 1);
  return t * t * (3 - 2 * t);
}

// Word-wrap `text` into up to `maxLines` lines that fit within `maxWidth`
// at the current font.  Returns an array of line strings.
function wrapText(ctx, text, maxWidth, maxLines) {
  if (!text) return [];
  const words = text.split(/\s+/);
  const lines = [];
  let cur = '';
  for (const w of words) {
    const trial = cur ? cur + ' ' + w : w;
    if (ctx.measureText(trial).width <= maxWidth) {
      cur = trial;
    } else {
      if (cur) lines.push(cur);
      cur = w;
      if (lines.length >= maxLines - 1) {
        // Truncate remaining words into the last line, adding ellipsis if it overflows.
        break;
      }
    }
  }
  if (cur) lines.push(cur);
  // If we broke out early, dump remaining words into the last line and ellipsize.
  const consumed = lines.reduce((n, ln) => n + ln.split(/\s+/).length, 0);
  if (consumed < words.length && lines.length) {
    const rest = words.slice(consumed).join(' ');
    let last = lines[lines.length - 1] + ' ' + rest;
    while (last.length > 3 && ctx.measureText(last + '…').width > maxWidth) {
      last = last.slice(0, -1);
    }
    lines[lines.length - 1] = last + '…';
  }
  return lines;
}

// Choose a font size (px) that fits `text` in `maxWidth` × `maxHeight`
// using at most `maxLines` lines.  Returns { size, lines }.
function fitLabel(ctx, text, maxWidth, maxHeight, maxLines, fontMin, fontMax) {
  let lo = fontMin, hi = fontMax;
  let best = { size: fontMin, lines: [text] };
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    ctx.font = `600 ${mid}px -apple-system, "Segoe UI", "Noto Sans KR", sans-serif`;
    const lines = wrapText(ctx, text, maxWidth, maxLines);
    const lineH = mid * 1.15;
    const blockH = lines.length * lineH;
    const fits = lines.length > 0 &&
      lines.every(ln => ctx.measureText(ln).width <= maxWidth) &&
      blockH <= maxHeight;
    if (fits) {
      best = { size: mid, lines };
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return best;
}

function drawOverlay(w, h) {
  const ctx = overlayState.ctx;
  const dpr = window.devicePixelRatio || 1;
  overlayState.canvas.width  = Math.floor(w * dpr);
  overlayState.canvas.height = Math.floor(h * dpr);
  overlayState.canvas.style.width  = w + 'px';
  overlayState.canvas.style.height = h + 'px';
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  if (!state.tree) return;

  const view = state.viewCurrent;
  const vr = view.r / CFG.hexRadius;

  const nodes = walkNodes(state.tree);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';

  // Labels — anchored at the cell's axis-based visual centre (not the
  // area-mass centroid), sized to the min-extent box guaranteed to fit
  // inside the convex cell.  Parent labels crossfade OUT as children
  // fade IN so we never render two layers at the same cell.
  const scale = Math.min(w, h) / (view.r * 2);
  for (const n of nodes) {
    if (n.depth === 0) continue;

    const [sx, sy] = toScreen(n._labelPos[0], n._labelPos[1], view, w, h);
    const maxR = screenSize(n._r, view, w, h);
    if (sx < -maxR - 20 || sy < -maxR - 20 || sx > w + maxR + 20 || sy > h + maxR + 20) continue;

    const depth = n.depth;
    const reveal = overlayReveal(depth, vr);
    if (reveal <= 0.02) continue;
    // Fade this label OUT as the next-depth labels fade IN.
    const nextReveal = overlayReveal(depth + 1, vr);
    const crossfade = 1 - nextReveal * 0.95;
    const effReveal = reveal * crossfade;
    if (effReveal <= 0.02) continue;

    const halfWpx = (n._halfW || 0) * scale;
    const halfHpx = (n._halfH || 0) * scale;
    const pad = CFG.overlay.labelPadPx;
    const maxWidth  = Math.max(0, halfWpx * 2 - pad);
    const maxHeight = Math.max(0, halfHpx * 2 - pad);
    if (Math.min(maxWidth, maxHeight) < CFG.overlay.labelMinPx) continue;

    const maxLines = maxHeight > 40 && depth <= 2 ? 2 : 1;
    const fontMax = depth === 1 ? 30 : depth === 2 ? 22 : 15;
    const fitted = fitLabel(ctx, n.data.label || '', maxWidth, maxHeight,
                            maxLines, 10, fontMax);
    if (!fitted.lines.length || fitted.size < 10) continue;

    const alpha = clamp(effReveal, 0, 1);
    // Pale cyan text with a soft accent glow — evokes a HUD readout.
    ctx.shadowColor = 'rgba(77, 208, 225, 0.55)';
    ctx.shadowBlur = Math.min(18, fitted.size * 0.7);
    ctx.font = `600 ${fitted.size}px -apple-system, "Segoe UI", "Noto Sans KR", sans-serif`;
    ctx.fillStyle = `rgba(220, 234, 246, ${alpha})`;
    const lineH = fitted.size * 1.15;
    const totalH = fitted.lines.length * lineH;
    const startY = sy - totalH / 2 + lineH / 2;
    for (let i = 0; i < fitted.lines.length; i++) {
      ctx.fillText(fitted.lines[i], sx, startY + i * lineH);
    }
    ctx.shadowBlur = 0;
  }
}

// ---------------------------------------------------------------------------
// State machine + discovery stream

const phaseNames = {
  idle:       'Idle',
  auth:       'Authenticating',
  permission: 'Permission check',
  discovery:  'Discovery',
  evaluation: 'Evaluation',
  ready:      'Ready',
  error:      'Error',
};

function setPhase(phase, label) {
  state.phase = phase;
  state.phaseLabel = label || phaseNames[phase] || phase;
  const phaseName = document.getElementById('phase-name');
  const phaseLabel = document.getElementById('phase-label');
  const bar = document.getElementById('phase-bar');
  phaseName.textContent = (phaseNames[phase] || phase).toUpperCase();
  phaseLabel.textContent = state.phaseLabel;
  const pct = {
    idle: 0, auth: 15, permission: 30, discovery: 55, evaluation: 85, ready: 100, error: 100,
  }[phase] || 0;
  bar.style.width = pct + '%';

  if (phase === 'ready') {
    // Swap progress card for focus card
    document.getElementById('hud-progress').classList.add('hidden');
    document.getElementById('hud-focus').classList.remove('hidden');
    updateFocusCard(state.tree);
  } else {
    document.getElementById('hud-progress').classList.remove('hidden');
    document.getElementById('hud-focus').classList.add('hidden');
  }
}

function onPermit(payload) {
  const sub = state.skeleton.topology.subscriptions.find(s => s.id === payload.subscription);
  if (!sub) return;
  for (const rg of sub.resourceGroups) {
    for (const r of rg.resources) {
      const rec = state.resources.get(r.id);
      if (rec) { rec.permitted = payload.granted !== false; rec.fillLevel = Math.max(rec.fillLevel, 0.2); }
    }
  }
  refreshColors();
}

function onResource(payload) {
  const rec = state.resources.get(payload.resource);
  if (!rec) return;
  rec.discovered = true;
  rec.fillLevel = 1;
  updateResourceCounts();
  // Rebuild is expensive; do it lazily on a timer instead
  scheduleTreeRebuild();
}

function onFinding(payload) {
  state.findings.push(payload);
  updateFindingCounts();
  scheduleTreeRebuild();
}

let treeRebuildTimer = null;
function scheduleTreeRebuild() {
  if (treeRebuildTimer) return;
  treeRebuildTimer = setTimeout(() => {
    treeRebuildTimer = null;
    rebuildTree();
  }, 120);
}

function updateResourceCounts() {
  let discovered = 0;
  for (const r of state.resources.values()) if (r.discovered) discovered++;
  document.getElementById('cnt-resources').textContent = discovered.toString();
}

function updateFindingCounts() {
  document.getElementById('cnt-findings').textContent = state.findings.length.toString();
}

function rebuildTree() {
  const data = buildTreeForView(state.viewMode);
  state.tree = runLayout(data);
  state.meshDirty = true;
  if (state.phase === 'ready') updateFocusCard(state.tree);
}

function applyEvent(type, payload) {
  if (type === 'phase') {
    setPhase(payload.phase, payload.label);
    if (payload.phase === 'ready') {
      // Final rebuild for any missed events
      rebuildTree();
    }
  } else if (type === 'permit') {
    onPermit(payload);
  } else if (type === 'resource') {
    onResource(payload);
  } else if (type === 'finding') {
    onFinding(payload);
  } else if (type === 'progress') {
    // Ambient tick — nudge fillLevels for cells that haven't advanced.
    // Ignored for the mock since findings drive fillLevel already.
  } else if (type === 'done') {
    if (state.phase !== 'ready') setPhase('ready');
  }
}

let currentStreamAbort = null;

function connectSSE() {
  return new Promise((resolve) => {
    if (typeof window.EventSource === 'undefined' || !location.protocol.startsWith('http')) {
      resolve(false);
      return;
    }
    const es = new EventSource('/events');
    let opened = false;
    const eventTypes = ['phase', 'permit', 'resource', 'finding', 'progress', 'done', 'hello'];
    for (const t of eventTypes) {
      es.addEventListener(t, (e) => {
        opened = true;
        try {
          const payload = JSON.parse(e.data);
          if (t === 'hello') return;
          applyEvent(t, payload);
          if (t === 'done') es.close();
        } catch (err) { console.warn('event parse fail', err); }
      });
    }
    es.onerror = () => {
      if (!opened) { es.close(); resolve(false); }
    };
    es.onopen = () => { opened = true; resolve(true); };
    currentStreamAbort = () => es.close();
    // Give it a beat to open, then resolve either way
    setTimeout(() => resolve(opened), 500);
  });
}

async function replayJSONL() {
  const res = await fetch('data/discovery-stream.jsonl');
  const text = await res.text();
  const events = text.split('\n').filter(Boolean).map(l => JSON.parse(l));
  events.sort((a, b) => a.at - b.at);
  const start = performance.now();
  let cancelled = false;
  currentStreamAbort = () => { cancelled = true; };
  for (const e of events) {
    if (cancelled) break;
    const elapsed = performance.now() - start;
    const wait = e.at - elapsed;
    if (wait > 0) await new Promise(r => setTimeout(r, wait));
    applyEvent(e.type, e.payload || {});
  }
}

async function startDiscovery() {
  // Reset state
  if (currentStreamAbort) { currentStreamAbort(); currentStreamAbort = null; }
  state.findings = [];
  for (const r of state.resources.values()) {
    r.discovered = false; r.permitted = false; r.fillLevel = 0;
  }
  updateResourceCounts();
  updateFindingCounts();
  rebuildTree();
  setPhase('idle', 'Waiting');

  const sseOk = await connectSSE();
  if (!sseOk) await replayJSONL();
}

// Fast-forward: fetch the recorded discovery stream and apply every
// event synchronously, then jump to the ready state.  Used at boot to
// avoid a 30-second animated replay when the caller only wants the
// final view.
async function bootstrapReadyState() {
  try {
    const res = await fetch('data/discovery-stream.jsonl');
    const text = await res.text();
    const events = text.split('\n').filter(Boolean).map(l => JSON.parse(l));
    events.sort((a, b) => a.at - b.at);
    for (const e of events) applyEvent(e.type, e.payload || {});
  } catch (err) {
    console.warn('bootstrapReadyState: failed to load recorded stream', err);
  }
  // Cancel any debounced rebuild that got scheduled by applyEvent so we
  // don't get a second layout pass 120ms later.
  if (treeRebuildTimer) { clearTimeout(treeRebuildTimer); treeRebuildTimer = null; }
  if (state.phase !== 'ready') setPhase('ready', 'Ready');
  rebuildTree();
}

// ---------------------------------------------------------------------------
// Interactions

const interact = {
  dragging: false,
  moved: false,
  lastX: 0, lastY: 0,
};

function pixelToLayout(px, py, view, w, h) {
  const scale = Math.min(w, h) / (view.r * 2);
  return [
    (px - w / 2) / scale + view.x,
    -(py - h / 2) / scale + view.y,
  ];
}

function setupInteractions() {
  const stage = document.getElementById('stage');

  stage.addEventListener('wheel', (e) => {
    e.preventDefault();
    const w = window.innerWidth, h = window.innerHeight;
    const view = state.viewTarget;
    // Layout point under the cursor before we change zoom
    const [lx, ly] = pixelToLayout(e.clientX, e.clientY, view, w, h);
    const factor = Math.pow(CFG.zoom.factor, e.deltaY);
    const newR = clamp(view.r * factor,
                       CFG.hexRadius * CFG.zoom.minRatio,
                       CFG.hexRadius * CFG.zoom.maxRatio);
    view.r = newR;
    // After the zoom change, shift the view so (lx, ly) sits under the
    // cursor again.  Screen-to-layout mapping is:
    //   layout.x = (px - w/2) / scale + view.x
    //   layout.y = -(py - h/2) / scale + view.y   (y flipped)
    const scaleNew = Math.min(w, h) / (view.r * 2);
    view.x = lx - (e.clientX - w / 2) / scaleNew;
    view.y = ly + (e.clientY - h / 2) / scaleNew;
  }, { passive: false });

  stage.addEventListener('pointerdown', (e) => {
    if (e.target.closest('#hud-controls') || e.target.closest('#hud-focus') || e.target.closest('#hud-progress')) return;
    interact.dragging = true;
    interact.moved = false;
    interact.lastX = e.clientX;
    interact.lastY = e.clientY;
    document.body.style.cursor = 'grabbing';
    stage.setPointerCapture(e.pointerId);
  });

  stage.addEventListener('pointermove', (e) => {
    if (!interact.dragging) return;
    const dx = e.clientX - interact.lastX;
    const dy = e.clientY - interact.lastY;
    interact.lastX = e.clientX;
    interact.lastY = e.clientY;
    if (Math.abs(dx) + Math.abs(dy) > 2) interact.moved = true;
    const w = window.innerWidth, h = window.innerHeight;
    const scale = Math.min(w, h) / (state.viewTarget.r * 2);
    state.viewTarget.x -= dx / scale;
    state.viewTarget.y += dy / scale;
  });

  stage.addEventListener('pointerup', (e) => {
    if (!interact.dragging) return;
    interact.dragging = false;
    document.body.style.cursor = 'default';
    if (!interact.moved) {
      handleClick(e.clientX, e.clientY);
    }
  });

  stage.addEventListener('pointercancel', () => {
    interact.dragging = false;
    document.body.style.cursor = 'default';
  });

  document.getElementById('view-select').addEventListener('change', (e) => {
    state.viewMode = e.target.value;
    rebuildTree();
  });

  // Replay button is hidden by default (progress animation intentionally
  // disabled).  Kept in the DOM so tests / debug can enable it again.
  const replayBtn = document.getElementById('replay-btn');
  if (replayBtn) {
    replayBtn.classList.add('hidden');
    replayBtn.addEventListener('click', () => { startDiscovery(); });
  }
}

function handleClick(px, py) {
  if (!state.tree) return;
  const w = window.innerWidth, h = window.innerHeight;
  const [lx, ly] = pixelToLayout(px, py, state.viewCurrent, w, h);
  // Deepest polygon hit
  let hit = null;
  state.tree.each(n => {
    if (n.depth === 0) return;
    if (n.polygon && pointInPolygon(lx, ly, n.polygon)) {
      if (!hit || n.depth > hit.depth) hit = n;
    }
  });
  if (hit) setFocus(hit);
}

function setFocus(node) {
  state.focus = node;
  const margin = 1.15;
  const targetR = Math.max(node._r * margin, CFG.hexRadius * CFG.zoom.minRatio);
  state.viewTarget.x = node._c[0];
  state.viewTarget.y = node._c[1];
  state.viewTarget.r = clamp(targetR, CFG.hexRadius * CFG.zoom.minRatio, CFG.hexRadius * CFG.zoom.maxRatio);
  updateFocusCard(node);
}

function updateFocusCard(node) {
  if (!node) return;
  document.getElementById('hud-focus').classList.remove('hidden');
  const label = node.data.label || 'root';
  const kind = node.data.kind || 'node';
  let subtitle = kind;
  if (node.data.pillarId) subtitle += ` · pillar: ${node.data.pillarId}`;
  if (node.data.severity) subtitle += ` · severity: ${node.data.severity}`;
  document.getElementById('focus-title').textContent = label;
  document.getElementById('focus-subtitle').textContent = subtitle;
  let desc = '';
  if (kind === 'rule') {
    const f = findingsForRule(node.data.id);
    desc = f.length
      ? `${f.length} finding${f.length > 1 ? 's' : ''} across ${new Set(f.map(x => x.resource)).size} resource${f.length > 1 ? 's' : ''}.`
      : 'No findings recorded in this run.';
  } else if (kind === 'resource') {
    const f = findingsForResource(node.data.id);
    desc = f.length
      ? `${f.length} finding${f.length > 1 ? 's' : ''} against this resource.`
      : 'No findings recorded in this run.';
  } else {
    desc = `${node.leaves().length} leaf cell${node.leaves().length !== 1 ? 's' : ''} under this node.`;
  }
  document.getElementById('focus-desc').textContent = desc;
  const g = node.data._g || (node.children ? (Math.max(...node.leaves().map(l => l.data._g || 0))) : 0);
  document.getElementById('focus-risk').textContent = g.toFixed(2);
  document.getElementById('focus-children').textContent = node.children ? node.children.length : 0;
  document.getElementById('focus-depth').textContent = node.depth;
}

// ---------------------------------------------------------------------------
// Main loop

function resizeGL() {
  const canvas = document.getElementById('gl');
  const dpr = window.devicePixelRatio || 1;
  const w = window.innerWidth, h = window.innerHeight;
  canvas.width = Math.floor(w * dpr);
  canvas.height = Math.floor(h * dpr);
  canvas.style.width = w + 'px';
  canvas.style.height = h + 'px';
  gl.viewport(0, 0, canvas.width, canvas.height);
}

function frame(tMs) {
  const w = window.innerWidth, h = window.innerHeight;
  const dpr = window.devicePixelRatio || 1;
  const canvas = document.getElementById('gl');
  if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
    resizeGL();
  }

  // Ease view toward target
  state.viewCurrent.x = lerp(state.viewCurrent.x, state.viewTarget.x, CFG.zoom.ease);
  state.viewCurrent.y = lerp(state.viewCurrent.y, state.viewTarget.y, CFG.zoom.ease);
  state.viewCurrent.r = lerp(state.viewCurrent.r, state.viewTarget.r, CFG.zoom.ease);

  if (state.meshDirty && state.tree) buildMesh();

  const bgW = canvas.width, bgH = canvas.height;

  // Light program (opaque clear)
  gl.disable(gl.BLEND);
  gl.useProgram(glState.progLight);
  gl.bindVertexArray(glState.lightVao);
  gl.uniform1f(glState.lightLoc.u_time, tMs / 1000);
  const accent = (currentPalette && currentPalette.accent) || '#ffb347';
  const [ar, ag, ab] = hexToRgbF(accent);
  gl.uniform3f(glState.lightLoc.u_accent, ar, ag, ab);
  gl.drawArrays(gl.TRIANGLES, 0, 3);
  gl.enable(gl.BLEND);

  // Cell program
  if (state.tree && glState.fillCount > 0) {
    gl.useProgram(glState.prog);
    const w2 = canvas.width, h2 = canvas.height;
    const scale = Math.min(w2, h2) / (state.viewCurrent.r * 2);
    gl.uniform2f(glState.loc.u_center, state.viewCurrent.x, state.viewCurrent.y);
    gl.uniform1f(glState.loc.u_scale, scale);
    gl.uniform2f(glState.loc.u_res, w2, h2);
    gl.uniform1f(glState.loc.u_viewRatio, state.viewCurrent.r / CFG.hexRadius);
    gl.uniform1f(glState.loc.u_hexRadius, CFG.hexRadius);
    gl.bindVertexArray(glState.fillVao);
    gl.drawArrays(gl.TRIANGLES, 0, glState.fillCount);
    if (glState.rimCount > 0) {
      gl.bindVertexArray(glState.rimVao);
      gl.drawArrays(gl.LINES, 0, glState.rimCount);
    }
  }

  drawOverlay(w, h);

  requestAnimationFrame(frame);
}

function hexToRgbF(hex) {
  const h = hex.replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map(c => c + c).join('') : h, 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

// ---------------------------------------------------------------------------
// Boot

async function main() {
  try {
    await loadPalettes();
    populatePaletteSelector();
    applyAccentToCSS();
    await loadSkeleton();
    initOverlay();
    initGL();
    resizeGL();
    rebuildTree();
    setupInteractions();
    document.getElementById('loading').classList.add('hidden');
    requestAnimationFrame(frame);
    // Boot directly to the READY state — no progress-animation replay.
    // The recorded discovery stream still populates findings so cells
    // have realistic colours, but every event is applied synchronously.
    await bootstrapReadyState();
    // Expose for debugging.
    window.__cells = { state, CFG };
  } catch (err) {
    console.error(err);
    document.getElementById('loading').textContent = 'Failed to start: ' + err.message;
  }
}

main();
