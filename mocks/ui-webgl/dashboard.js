// AIOpsPilot — full-WebGL operator console (read-only mock).
// KPIs, trust-tier split, HIL queue, shadow results, and an audit log — all rendered in WebGL.
// Card shapes/shadows use canvas textures; all text uses SDF glyphs (troika-three-text) for crisp
// type. Wheel to scroll, click to replay. English-only, customer-agnostic, synthetic values.

import * as THREE from "three";
import { Text } from "troika-three-text";

// ---------------------------------------------------------------------------
// Palette
// ---------------------------------------------------------------------------
const COLOR = {
  steel: 0x44688e, navy: 0x3e4c59, sage: 0x5e8259,
  terracotta: 0xbc7449, teal: 0x4f847e, plum: 0x7b6c9c,
  dustyRed: 0xac5a5a, card: 0xffffff, hairline: 0xe3e1de,
  shade: 0xf1eeea, text: 0x2c333a, soft: 0x6b7178,
};
const hex = (n) => "#" + (n >>> 0).toString(16).padStart(6, "0").slice(-6);
const FRUSTUM = 10;
const FADE = 0.5;
const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// ---------------------------------------------------------------------------
// Renderer / scene / camera
// ---------------------------------------------------------------------------
const canvas = document.getElementById("scene");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setClearColor(0x000000, 0);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
const MAX_ANISO = renderer.capabilities.getMaxAnisotropy();

const scene = new THREE.Scene();
const world = new THREE.Group();        // parallax
const content = new THREE.Group();      // scrollable content
world.add(content);
scene.add(world);

let aspect = window.innerWidth / window.innerHeight;
const camera = new THREE.OrthographicCamera(
  (-FRUSTUM * aspect) / 2, (FRUSTUM * aspect) / 2, FRUSTUM / 2, -FRUSTUM / 2, 0.1, 100
);
camera.position.z = 10;

const fadeGroups = []; // { group, formStart }
const allTexts = [];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function crisp(tex) {
  tex.minFilter = THREE.LinearFilter; tex.magFilter = THREE.LinearFilter;
  tex.generateMipmaps = false; tex.anisotropy = MAX_ANISO; tex.needsUpdate = true;
  return tex;
}
function roundRectPath(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
const S = 300;
// A card background (white rounded rect + soft shadow + border), optional top accent bar.
function cardBg(w, h, accent) {
  const PAD = 0.45;
  const wU = w + PAD, hU = h + PAD;
  const W = Math.round(wU * S), H = Math.round(hU * S);
  const cv = document.createElement("canvas"); cv.width = W; cv.height = H;
  const ctx = cv.getContext("2d");
  const pad = (PAD / 2) * S, rw = W - pad * 2, rh = H - pad * 2, rad = 0.13 * S;
  ctx.save();
  ctx.shadowColor = "rgba(46,54,64,0.10)"; ctx.shadowBlur = 0.11 * S; ctx.shadowOffsetY = 0.045 * S;
  ctx.fillStyle = hex(COLOR.card); roundRectPath(ctx, pad, pad, rw, rh, rad); ctx.fill();
  ctx.restore();
  ctx.strokeStyle = hex(COLOR.hairline); ctx.lineWidth = Math.max(1, 0.007 * S);
  roundRectPath(ctx, pad, pad, rw, rh, rad); ctx.stroke();
  if (accent !== undefined) {
    ctx.fillStyle = hex(accent);
    roundRectPath(ctx, pad + 0.14 * S, pad + 0.14 * S, 0.26 * S, 0.035 * S, 0.018 * S); ctx.fill();
  }
  const mesh = new THREE.Mesh(
    new THREE.PlaneGeometry(wU, hU),
    new THREE.MeshBasicMaterial({ map: crisp(new THREE.CanvasTexture(cv)), transparent: true, depthWrite: false, depthTest: false, opacity: 0 })
  );
  mesh.renderOrder = 0;
  return mesh;
}
function addText(parent, str, x, y, size, color, anchorX = "left") {
  const t = new Text();
  t.text = str; t.fontSize = size; t.color = color;
  t.anchorX = anchorX; t.anchorY = "middle";
  t.position.set(x, y, 0.03); t.sdfGlyphSize = 64; t.renderOrder = 2; t.sync();
  parent.add(t); allTexts.push(t);
  return t;
}
function addRect(parent, x, y, w, h, color, z = 0.02, radius = 0) {
  const mesh = new THREE.Mesh(
    new THREE.PlaneGeometry(w, h),
    new THREE.MeshBasicMaterial({ color, transparent: true, depthWrite: false, depthTest: false, opacity: 0 })
  );
  mesh.position.set(x, y, z);
  mesh.renderOrder = 1;
  parent.add(mesh);
  return mesh;
}
function addDot(parent, x, y, r, color, z = 0.03) {
  const mesh = new THREE.Mesh(
    new THREE.CircleGeometry(r, 24),
    new THREE.MeshBasicMaterial({ color, transparent: true, depthWrite: false, depthTest: false, opacity: 0 })
  );
  mesh.position.set(x, y, z);
  mesh.renderOrder = 1;
  parent.add(mesh);
  return mesh;
}
function meter(parent, x, y, w, frac, color) {
  addRect(parent, x, y, w, 0.09, COLOR.shade, 0.02); // track (centered origin)
  const fill = addRect(parent, x - w / 2 + (w * frac) / 2, y, Math.max(0.001, w * frac), 0.09, color, 0.04);
  fill.renderOrder = 2; // always above its track
  return fill;
}
// a section group placed at (x,y) with a fade-in stagger
function section(x, y, formStart, build) {
  const g = new THREE.Group();
  g.position.set(x, y, 0);
  build(g);
  content.add(g);
  fadeGroups.push({ group: g, formStart });
  return g;
}
const SEV = { critical: COLOR.dustyRed, high: COLOR.terracotta, medium: COLOR.steel, low: COLOR.soft };
const TIERC = { T0: COLOR.sage, T1: COLOR.teal, T2: COLOR.plum };

// ---------------------------------------------------------------------------
// Layout — stacked top→down; wheel scrolls `content`
// ---------------------------------------------------------------------------
// Header
section(0, 4.05, 0.0, (g) => {
  addText(g, "Control-plane status", -4.4, 0.16, 0.34, COLOR.text, "left");
  addText(g, "read-only console · shadow mode", -4.4, -0.30, 0.17, COLOR.soft, "left");
  const st = [["core healthy", COLOR.sage], ["bus draining", COLOR.sage], ["HIL: 2 pending", COLOR.terracotta], ["scale: idle", 0xC4C1BD]];
  let x = 0.2;
  for (const [label, col] of st) {
    addDot(g, x, 0.0, 0.05, col);
    const t = addText(g, label, x + 0.12, 0.0, 0.15, COLOR.soft, "left");
    x += 0.12 + label.length * 0.083 + 0.28;
  }
});

// KPI row
const kpis = [
  { v: "88%", l: "Auto-resolved", a: COLOR.steel },
  { v: "42s", l: "MTTR (median)", a: COLOR.teal },
  { v: "6.9%", l: "Reached T2", a: COLOR.plum },
  { v: "0.2%", l: "Rollback rate", a: COLOR.terracotta },
];
const kpiCX = [-3.45, -1.15, 1.15, 3.45];
kpis.forEach((k, i) => {
  section(kpiCX[i], 2.55, 0.08 + i * 0.05, (g) => {
    g.add(cardBg(2.1, 1.5, k.a));
    addText(g, k.v, -0.86, 0.24, 0.40, COLOR.text, "left");
    addText(g, k.l, -0.86, -0.34, 0.155, COLOR.soft, "left");
  });
});

// Trust-tier split (left) + HIL queue (right)
section(-2.35, 0.35, 0.28, (g) => {
  g.add(cardBg(4.3, 2.4));
  addText(g, "Trust tiers", -1.9, 0.86, 0.20, COLOR.text, "left");
  const rows = [["T0", 0.76], ["T1", 0.17], ["T2", 0.07]];
  rows.forEach(([name, frac], i) => {
    const y = 0.36 - i * 0.52;
    addText(g, name, -1.9, y, 0.16, TIERC[name], "left");
    meter(g, 0.2, y, 2.6, frac, TIERC[name]);
    addText(g, Math.round(frac * 100) + "%", 1.95, y, 0.15, COLOR.soft, "left");
  });
});
section(2.35, 0.35, 0.34, (g) => {
  g.add(cardBg(4.3, 2.4));
  addText(g, "HIL queue", -1.9, 0.86, 0.20, COLOR.text, "left");
  const rows = [
    ["Enable PITR on database", "critical", "8m"],
    ["Prod autoscale floor", "high", "21m"],
    ["Firewall reconcile", "medium", "—"],
  ];
  rows.forEach(([label, sev, wait], i) => {
    const y = 0.38 - i * 0.52;
    addDot(g, -1.86, y, 0.055, SEV[sev]);
    addText(g, label, -1.72, y, 0.155, COLOR.text, "left");
    addText(g, wait, 1.9, y, 0.14, COLOR.soft, "right");
    if (i < rows.length - 1) addRect(g, 0, y - 0.26, 3.8, 0.008, COLOR.hairline, 0.015);
  });
});

// Shadow results (3 cards)
const shadow = [
  { tag: "accuracy", val: "98.6%", frac: 0.986, c: COLOR.sage },
  { tag: "policy escapes", val: "0", frac: 0.02, c: COLOR.steel },
  { tag: "disagreement", val: "3.4%", frac: 0.34, c: COLOR.terracotta },
];
const shCX = [-3.0, 0.0, 3.0];
shadow.forEach((s, i) => {
  section(shCX[i], -2.35, 0.42 + i * 0.05, (g) => {
    g.add(cardBg(2.7, 1.4));
    addText(g, s.tag, -1.12, 0.42, 0.15, s.c, "left");
    addText(g, s.val, 1.12, 0.42, 0.24, COLOR.text, "right");
    meter(g, 0, -0.06, 2.1, s.frac, s.c);
    addText(g, "7-day shadow window", -1.12, -0.42, 0.13, COLOR.soft, "left");
  });
});

// Audit log (wide)
section(0, -4.7, 0.5, (g) => {
  g.add(cardBg(9.1, 2.7));
  addText(g, "Audit log", -4.3, 1.02, 0.20, COLOR.text, "left");
  addText(g, "append-only", 4.3, 1.02, 0.14, COLOR.soft, "right");
  const rows = [
    ["09:15:04Z", "evt-0001", "T0", "remediation-pr opened", "shadow"],
    ["09:14:52Z", "evt-0002", "T1", "reused learned action", "enforce"],
    ["09:14:31Z", "evt-0003", "T2", "abstain → HIL", "n/a"],
    ["09:13:58Z", "evt-0004", "T0", "no-op (compliant)", "shadow"],
  ];
  rows.forEach((r, i) => {
    const y = 0.5 - i * 0.42;
    addText(g, r[0], -4.3, y, 0.14, COLOR.soft, "left");
    addText(g, r[1], -2.75, y, 0.14, COLOR.text, "left");
    addText(g, r[2], -1.35, y, 0.14, TIERC[r[2]], "left");
    addText(g, r[3], -0.75, y, 0.14, COLOR.text, "left");
    addText(g, r[4], 4.3, y, 0.14, r[4] === "enforce" ? COLOR.steel : COLOR.soft, "right");
    if (i < rows.length - 1) addRect(g, 0, y - 0.21, 8.6, 0.008, COLOR.hairline, 0.015);
  });
});

// Hint
section(0, -6.15, 0.6, (g) => {
  addText(g, "scroll to explore · click to replay", 0, 0, 0.15, COLOR.soft, "center");
});

// ---------------------------------------------------------------------------
// Interaction: wheel scroll, replay, parallax, resize
// ---------------------------------------------------------------------------
const MAX_SCROLL = 3.0;
let scrollTarget = 0, scroll = 0;
window.addEventListener("wheel", (e) => {
  scrollTarget = THREE.MathUtils.clamp(scrollTarget + e.deltaY * 0.0022, 0, MAX_SCROLL);
}, { passive: true });

const pointer = new THREE.Vector2(0, 0);
window.addEventListener("pointermove", (e) => {
  pointer.x = (e.clientX / window.innerWidth) * 2 - 1;
  pointer.y = -(e.clientY / window.innerHeight) * 2 + 1;
  // translation parallax only (no rotation) so transparent draw order never flips
  world.position.x = pointer.x * 0.12;
  world.position.y = pointer.y * 0.08;
});
window.addEventListener("pointerdown", () => { startTime = clock.getElapsedTime(); });

function onResize() {
  aspect = window.innerWidth / window.innerHeight;
  camera.left = (-FRUSTUM * aspect) / 2; camera.right = (FRUSTUM * aspect) / 2;
  camera.top = FRUSTUM / 2; camera.bottom = -FRUSTUM / 2;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
}
window.addEventListener("resize", onResize);
onResize();

const loadingEl = document.getElementById("loading");
setTimeout(() => loadingEl.classList.add("hidden"), 300);

// ---------------------------------------------------------------------------
// Loop
// ---------------------------------------------------------------------------
const clock = new THREE.Clock();
let startTime = 0;
function setOpacity(g, p) {
  g.traverse((o) => { if (o.material && o !== g) { o.material.transparent = true; o.material.depthWrite = false; o.material.depthTest = false; o.material.opacity = p; } });
}
function animate() {
  requestAnimationFrame(animate);
  const t = clock.getElapsedTime() - startTime;
  scroll += (scrollTarget - scroll) * 0.12;
  content.position.y = scroll;

  for (const { group, formStart } of fadeGroups) {
    const p = prefersReduced ? 1 : THREE.MathUtils.smoothstep(t, formStart, formStart + FADE);
    setOpacity(group, p);
  }
  renderer.render(scene, camera);
}
animate();
