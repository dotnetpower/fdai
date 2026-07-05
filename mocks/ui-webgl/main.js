// AIOpsPilot — full-WebGL card UI. Cards fade in cleanly (no particles).
// Text is rendered with SDF glyphs (troika-three-text) so it stays crisp at any scale;
// card backgrounds/shadows use a canvas texture. English-only, customer-agnostic, synthetic.

import * as THREE from "three";
import { Text } from "troika-three-text";

// ---------------------------------------------------------------------------
// Palette (Calm Slate)
// ---------------------------------------------------------------------------
const COLOR = {
  steel: 0x44688e, navy: 0x3e4c59, sage: 0x5e8259,
  terracotta: 0xbc7449, teal: 0x4f847e, plum: 0x7b6c9c,
  card: 0xffffff, hairline: 0xe3e1de, text: 0x2c333a, soft: 0x6b7178,
};
const hex = (n) => "#" + (n >>> 0).toString(16).padStart(6, "0").slice(-6);

const FRUSTUM = 10;
const FADE = 0.55;
const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// ---------------------------------------------------------------------------
// Layout (world units, origin centered, y in [-5,5])
// ---------------------------------------------------------------------------
const cards = [
  { id: 0, cx: -3.6, cy: 1.5, w: 2.15, h: 1.9, color: COLOR.steel, order: 0.05,
    kind: "kpi", value: "87.4%", label: "Auto-resolution" },
  { id: 1, cx: -1.2, cy: 1.5, w: 2.15, h: 1.9, color: COLOR.teal, order: 0.13,
    kind: "kpi", value: "42s", label: "MTTR (median)" },
  { id: 2, cx: 1.2, cy: 1.5, w: 2.15, h: 1.9, color: COLOR.terracotta, order: 0.21,
    kind: "kpi", value: "3.1", label: "Human touch / 100" },
  { id: 3, cx: 3.6, cy: 1.5, w: 2.15, h: 1.9, color: COLOR.sage, order: 0.29,
    kind: "kpi", value: "$0.06", label: "Cost / incident" },
  { id: 4, cx: 0, cy: -1.75, w: 8.5, h: 2.7, color: COLOR.navy, order: 0.40,
    kind: "panel", value: "Control-plane status", label: "T0 76%   ·   T1 17%   ·   T2 7%   ·   shadow mode" },
];

// ---------------------------------------------------------------------------
// Renderer / scene / camera
// ---------------------------------------------------------------------------
const canvas = document.getElementById("scene");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setClearColor(0x000000, 0);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
const MAX_ANISO = renderer.capabilities.getMaxAnisotropy();

const scene = new THREE.Scene();
const group = new THREE.Group();
scene.add(group);

let aspect = window.innerWidth / window.innerHeight;
const camera = new THREE.OrthographicCamera(
  (-FRUSTUM * aspect) / 2, (FRUSTUM * aspect) / 2, FRUSTUM / 2, -FRUSTUM / 2, 0.1, 100
);
camera.position.z = 10;

function crisp(tex) {
  tex.minFilter = THREE.LinearFilter;
  tex.magFilter = THREE.LinearFilter;
  tex.generateMipmaps = false;
  tex.anisotropy = MAX_ANISO;
  tex.needsUpdate = true;
  return tex;
}

// ---------------------------------------------------------------------------
// Card background texture (shape only — shadow, rounded rect, border, accent bar)
// ---------------------------------------------------------------------------
function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
const S = 300;
function makeCardBg(c) {
  const PADW = 0.5;
  const wUnits = c.w + PADW, hUnits = c.h + PADW;
  const W = Math.round(wUnits * S), H = Math.round(hUnits * S);
  const cv = document.createElement("canvas");
  cv.width = W; cv.height = H;
  const ctx = cv.getContext("2d");
  const pad = (PADW / 2) * S;
  const rw = W - pad * 2, rh = H - pad * 2, rad = 0.14 * S;

  ctx.save();
  ctx.shadowColor = "rgba(46,54,64,0.12)";
  ctx.shadowBlur = 0.12 * S; ctx.shadowOffsetY = 0.05 * S;
  ctx.fillStyle = hex(COLOR.card);
  roundRect(ctx, pad, pad, rw, rh, rad); ctx.fill();
  ctx.restore();
  ctx.strokeStyle = hex(COLOR.hairline); ctx.lineWidth = Math.max(1, 0.008 * S);
  roundRect(ctx, pad, pad, rw, rh, rad); ctx.stroke();

  if (c.kind === "kpi") {
    ctx.fillStyle = hex(c.color);
    roundRect(ctx, pad + 0.16 * S, pad + 0.17 * S, 0.30 * S, 0.04 * S, 0.02 * S); ctx.fill();
  }
  return { tex: crisp(new THREE.CanvasTexture(cv)), wUnits, hUnits };
}

// ---------------------------------------------------------------------------
// Build cards: one THREE.Group per card (bg plane + SDF text), fade + hover together
// ---------------------------------------------------------------------------
const cardGroups = [];
const allTexts = [];

function makeText(str, x, y, size, color, anchorX) {
  const t = new Text();
  t.text = str;
  t.fontSize = size;
  t.color = color;
  t.anchorX = anchorX;
  t.anchorY = "middle";
  t.position.set(x, y, 0.02);
  t.letterSpacing = 0.0;
  t.sdfGlyphSize = 64;
  t.renderOrder = 2;
  t.sync();
  allTexts.push(t);
  return t;
}

for (const c of cards) {
  const g = new THREE.Group();
  g.position.set(c.cx, c.cy, 0.2);
  g.userData = { cardId: c.id, formStart: c.order, baseZ: 0.2, baseY: c.cy };

  const { tex, wUnits, hUnits } = makeCardBg(c);
  const bg = new THREE.Mesh(
    new THREE.PlaneGeometry(wUnits, hUnits),
    new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, depthTest: false, opacity: 0 })
  );
  bg.renderOrder = 0;
  g.add(bg);

  const left = -c.w / 2 + 0.18;
  if (c.kind === "kpi") {
    g.add(makeText(c.value, left, 0.12, 0.42, COLOR.text, "left"));
    g.add(makeText(c.label, left, -0.52, 0.17, COLOR.soft, "left"));
  } else {
    g.add(makeText(c.value, -c.w / 2 + 0.32, 0.55, 0.34, COLOR.text, "left"));
    g.add(makeText(c.label, -c.w / 2 + 0.33, -0.05, 0.20, COLOR.soft, "left"));
  }

  group.add(g);
  cardGroups.push(g);
}

// Title + hint groups
function makeTextGroup(cx, cy, formStart, build) {
  const g = new THREE.Group();
  g.position.set(cx, cy, 0.3);
  g.userData = { cardId: -1, formStart, baseZ: 0.3, baseY: cy };
  build(g);
  group.add(g);
  cardGroups.push(g);
}
makeTextGroup(0, 4.0, 0.0, (g) => {
  g.add(makeText("AIOpsPilot", 0, 0.18, 0.52, COLOR.text, "center"));
  g.add(makeText("autonomous cloud operations", 0, -0.42, 0.17, COLOR.soft, "center"));
});
makeTextGroup(0, -3.75, 0.7, (g) => {
  g.add(makeText("click to replay", 0, 0, 0.16, COLOR.soft, "center"));
});

// ---------------------------------------------------------------------------
// Hover focus + interaction
// ---------------------------------------------------------------------------
const hitPlanes = [];
for (const c of cards) {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(c.w, c.h), new THREE.MeshBasicMaterial({ visible: false }));
  m.position.set(c.cx, c.cy, 0); m.userData.cardId = c.id; group.add(m); hitPlanes.push(m);
}
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2(-10, -10);
let hovered = -1;

window.addEventListener("pointermove", (e) => {
  pointer.x = (e.clientX / window.innerWidth) * 2 - 1;
  pointer.y = -(e.clientY / window.innerHeight) * 2 + 1;
  // translation parallax only (no rotation) so transparent draw order never flips
  group.position.x = pointer.x * 0.1;
  group.position.y = pointer.y * 0.07;
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
// Loop — set opacity on every material in each card group (bg + SDF text)
// ---------------------------------------------------------------------------
const clock = new THREE.Clock();
let startTime = 0;
function setGroupOpacity(g, p) {
  g.traverse((o) => {
    if (o.material && o.material.visible !== false && o !== g) {
      o.material.transparent = true;
      o.material.depthWrite = false;
      o.material.depthTest = false;
      o.material.opacity = p;
    }
  });
}
function animate() {
  requestAnimationFrame(animate);
  const t = clock.getElapsedTime() - startTime;

  raycaster.setFromCamera(pointer, camera);
  const hits = raycaster.intersectObjects(hitPlanes, false);
  hovered = hits.length ? hits[0].object.userData.cardId : -1;

  for (const g of cardGroups) {
    const fs = g.userData.formStart;
    const p = prefersReduced ? 1 : THREE.MathUtils.smoothstep(t, fs, fs + FADE);
    setGroupOpacity(g, p);
    const focused = g.userData.cardId === hovered && hovered !== -1;
    g.position.z += (g.userData.baseZ + (focused ? 0.3 : 0) - g.position.z) * 0.15;
    const s = focused ? 1.03 : 1;
    g.scale.x += (s - g.scale.x) * 0.15;
    g.scale.y += (s - g.scale.y) * 0.15;
  }

  renderer.render(scene, camera);
}
animate();
