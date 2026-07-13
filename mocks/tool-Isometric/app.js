import {
  CATALOG, CATEGORIES, FILTERS, RESOURCE_FOOTPRINT, WORLD, categoryFor, createInitialScene,
  findRegionAt, serializeScene,
} from "./model.js?v=10";
import { AtlasRenderer } from "./renderer.js?v=10";

const canvas = document.getElementById("scene");
const stage = document.getElementById("stage");
const renderer = new AtlasRenderer(canvas);
let scene = createInitialScene();
let nextId = 1;
let pointerMode = null;
let activeResource = null;
let dragGroup = [];
let dragStartWorld = null;
let dragSceneStart = null;
let mapScaleStart = null;
let lastPointer = { x: 0, y: 0 };
let moved = false;
let paletteDragType = null;
let history = [];
let future = [];
let toastTimer = null;
let editMode = true;
let clipboard = [];

function draw() {
  renderer.render(scene);
  updateCompass();
  document.getElementById("zoomLevel").textContent =
    `${Math.round((renderer.camera.scale / renderer.fitScale) * 100)}%`;
}

function snapshot() {
  history.push(JSON.stringify(scene));
  if (history.length > 40) history.shift();
  future = [];
  syncHistoryButtons();
}

function restore(serialized) {
  scene = JSON.parse(serialized);
  renderer.selectedIds.clear();
  updateSelectionUI();
  buildLayerFilters();
  draw();
}

function undo() {
  if (!editMode || !history.length) return;
  future.push(JSON.stringify(scene));
  restore(history.pop());
  syncHistoryButtons();
}

function redo() {
  if (!editMode || !future.length) return;
  history.push(JSON.stringify(scene));
  restore(future.pop());
  syncHistoryButtons();
}

function syncHistoryButtons() {
  document.getElementById("undoBtn").disabled = !editMode || history.length === 0;
  document.getElementById("redoBtn").disabled = !editMode || future.length === 0;
}

function pointFromEvent(event) {
  const rect = canvas.getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}

function snap(value) {
  return Math.round(value / WORLD.grid) * WORLD.grid;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function resourceBoundary(resource) {
  return scene.regions.find((region) => region.id === resource.parentId)
    ?? scene.regions.find((region) => region.kind === "subscription")
    ?? { x: 0, y: 0, w: WORLD.width, h: WORLD.height };
}

function resourceLimits(resource) {
  const boundary = resourceBoundary(resource);
  const insetX = RESOURCE_FOOTPRINT.width / 2 + .06;
  const insetY = RESOURCE_FOOTPRINT.depth / 2 + .06;
  return {
    minX: boundary.x + insetX,
    maxX: boundary.x + boundary.w - insetX,
    minY: boundary.y + insetY,
    maxY: boundary.y + boundary.h - insetY,
  };
}

function resourcesOverlap(first, second) {
  return Math.abs(first.x - second.x) < RESOURCE_FOOTPRINT.width &&
    Math.abs(first.y - second.y) < RESOURCE_FOOTPRINT.depth;
}

function captureResourcePositions() {
  return new Map(scene.resources.map((resource) => [resource.id, { x: resource.x, y: resource.y }]));
}

function restoreResourcePositions(positions) {
  for (const resource of scene.resources) {
    const position = positions.get(resource.id);
    if (position) { resource.x = position.x; resource.y = position.y; }
  }
}

function resolvePushCollisions(movers, deltaX, deltaY) {
  const protectedIds = new Set(movers.map((entry) => entry.item.id));
  const axis = Math.abs(deltaX) >= Math.abs(deltaY) ? "x" : "y";
  const sign = Math.sign(axis === "x" ? deltaX : deltaY) || 1;
  const pushedIds = new Set();
  const queue = movers.map((entry) => entry.item);

  while (queue.length) {
    const pusher = queue.shift();
    const collisions = scene.resources.filter((candidate) =>
      candidate.id !== pusher.id && resourcesOverlap(pusher, candidate));
    for (const collision of collisions) {
      if (protectedIds.has(collision.id)) continue;
      if (pushedIds.has(collision.id)) return false;
      const limits = resourceLimits(collision);
      const separation = axis === "x" ? RESOURCE_FOOTPRINT.width : RESOURCE_FOOTPRINT.depth;
      const edge = (axis === "x" ? pusher.x : pusher.y) + separation * sign;
      const snappedEdge = sign > 0
        ? Math.ceil(edge / WORLD.grid) * WORLD.grid
        : Math.floor(edge / WORLD.grid) * WORLD.grid;
      const desiredX = axis === "x" ? snappedEdge : collision.x;
      const desiredY = axis === "y" ? snappedEdge : collision.y;
      if (desiredX < limits.minX || desiredX > limits.maxX ||
          desiredY < limits.minY || desiredY > limits.maxY) return false;
      collision.x = snap(desiredX);
      collision.y = snap(desiredY);
      pushedIds.add(collision.id);
      queue.push(collision);
    }
  }
  return true;
}

function moveDragGroup(deltaX, deltaY) {
  if (!dragSceneStart) return;
  restoreResourcePositions(dragSceneStart);
  let minDeltaX = -Infinity, maxDeltaX = Infinity;
  let minDeltaY = -Infinity, maxDeltaY = Infinity;
  for (const entry of dragGroup) {
    const limits = resourceLimits(entry.item);
    minDeltaX = Math.max(minDeltaX, limits.minX - entry.x);
    maxDeltaX = Math.min(maxDeltaX, limits.maxX - entry.x);
    minDeltaY = Math.max(minDeltaY, limits.minY - entry.y);
    maxDeltaY = Math.min(maxDeltaY, limits.maxY - entry.y);
  }
  const boundedDeltaX = clamp(snap(deltaX), minDeltaX, maxDeltaX);
  const boundedDeltaY = clamp(snap(deltaY), minDeltaY, maxDeltaY);
  for (const entry of dragGroup) {
    entry.item.x = snap(entry.x + boundedDeltaX);
    entry.item.y = snap(entry.y + boundedDeltaY);
  }
  if (!resolvePushCollisions(dragGroup, boundedDeltaX, boundedDeltaY)) {
    restoreResourcePositions(dragSceneStart);
  }
}

function settleResource(resource) {
  const limits = resourceLimits(resource);
  resource.x = snap(clamp(resource.x, limits.minX, limits.maxX));
  resource.y = snap(clamp(resource.y, limits.minY, limits.maxY));
  const baseline = captureResourcePositions();
  const directions = [[1, 0], [0, 1], [-1, 0], [0, -1]];
  for (const [deltaX, deltaY] of directions) {
    restoreResourcePositions(baseline);
    if (resolvePushCollisions([{ item: resource }], deltaX, deltaY)) return true;
  }
  restoreResourcePositions(baseline);
  return false;
}

function select(hit, additive = false) {
  if (!additive) renderer.selectedIds.clear();
  if (hit) {
    if (additive && renderer.selectedIds.has(hit.item.id)) renderer.selectedIds.delete(hit.item.id);
    else renderer.selectedIds.add(hit.item.id);
  }
  updateSelectionUI();
  draw();
}

function selectedItems() {
  return [...renderer.selectedIds]
    .map((id) => scene.resources.find((item) => item.id === id) ?? scene.regions.find((item) => item.id === id))
    .filter(Boolean);
}

function updateSelectionUI() {
  const items = selectedItems();
  const bar = document.getElementById("selectionBar");
  bar.hidden = items.length === 0;
  document.getElementById("selectionCount").textContent = `${items.length} selected`;
  const panel = document.getElementById("selectionPanel");
  if (!items.length) {
    panel.innerHTML = `<div class="empty-state"><span class="empty-icon">&#9671;</span><strong>No selection</strong><p>Select a resource or boundary to inspect its architecture metadata.</p></div>`;
    return;
  }
  if (items.length > 1) {
    panel.innerHTML = `<div class="empty-state"><span class="empty-icon">${items.length}</span><strong>Multiple selection</strong><p>Move, duplicate or remove the selected architecture objects together.</p></div>`;
    return;
  }
  const item = items[0];
  const isResource = "type" in item;
  if (isResource) {
    const type = CATALOG[item.type];
    const category = CATEGORIES[type.category];
    const parent = scene.regions.find((region) => region.id === item.parentId);
    panel.innerHTML = `
      <div class="detail-head">
        <span class="detail-glyph" style="--glyph-color:${category.color}">${type.label}</span>
        <span><strong>${item.name}</strong><small>${type.name}</small></span>
      </div>
      <div class="detail-grid">
        <div class="detail-row"><span>Status</span><span class="health">${item.status}</span></div>
        <div class="detail-row"><span>Parent</span><span>${parent?.name ?? "Subscription"}</span></div>
        <div class="detail-row"><span>Position</span><span>${item.x.toFixed(1)}, ${item.y.toFixed(1)}</span></div>
        <div class="detail-row"><span>Category</span><span>${category.name}</span></div>
      </div>
      <div class="detail-actions"><button data-detail="focus">Focus</button><button data-detail="duplicate">Duplicate</button></div>`;
  } else {
    const parent = scene.regions.find((region) => region.id === item.parentId);
    panel.innerHTML = `
      <div class="detail-head">
        <span class="detail-glyph" style="--glyph-color:#697586">RG</span>
        <span><strong>${item.name}</strong><small>${item.kind}</small></span>
      </div>
      <div class="detail-grid">
        <div class="detail-row"><span>Address / role</span><span>${item.subtitle}</span></div>
        <div class="detail-row"><span>Parent</span><span>${parent?.name ?? "Tenant"}</span></div>
        <div class="detail-row"><span>Bounds</span><span>${item.w.toFixed(1)} x ${item.h.toFixed(1)}</span></div>
      </div>
      <div class="detail-actions"><button data-detail="focus">Focus</button></div>`;
  }
}

function focusSelection() {
  const item = selectedItems()[0];
  if (!item) return;
  renderer.focus("type" in item ? item : { x: item.x + item.w / 2, y: item.y + item.h / 2 });
  draw();
}

function duplicateSelection() {
  if (!editMode) return;
  const resources = selectedItems().filter((item) => "type" in item);
  if (!resources.length) return;
  snapshot();
  renderer.selectedIds.clear();
  for (const resource of resources) {
    const copy = { ...resource, id: `${resource.type}-copy-${nextId++}`, name: `${resource.name}-copy`, x: clamp(resource.x + .7, .6, WORLD.width - .6), y: clamp(resource.y + .7, .6, WORLD.height - .6) };
    scene.resources.push(copy);
    if (!settleResource(copy)) { scene.resources.pop(); continue; }
    renderer.selectedIds.add(copy.id);
  }
  updateSelectionUI();
  buildLayerFilters();
  draw();
}

function deleteSelection() {
  if (!editMode) return;
  const ids = new Set(renderer.selectedIds);
  if (!ids.size) return;
  snapshot();
  scene.resources = scene.resources.filter((item) => !ids.has(item.id));
  scene.connections = scene.connections.filter((edge) => !ids.has(edge.source) && !ids.has(edge.target));
  renderer.selectedIds.clear();
  updateSelectionUI();
  buildLayerFilters();
  draw();
}

function addResource(type, worldPoint) {
  if (!editMode) { showToast("Switch to Edit mode to add resources"); return; }
  const entry = CATALOG[type];
  if (!entry) return;
  const x = clamp(snap(worldPoint.x), .6, WORLD.width - .6);
  const y = clamp(snap(worldPoint.y), .6, WORLD.height - .6);
  snapshot();
  const resource = {
    id: `${type}-${Date.now()}-${nextId++}`,
    type,
    name: `${type}-${nextId}`,
    x, y,
    parentId: findRegionAt(scene, x, y)?.id ?? "sub-prod",
    status: "healthy",
  };
  scene.resources.push(resource);
  if (!settleResource(resource)) {
    scene.resources.pop();
    history.pop();
    syncHistoryButtons();
    showToast(`No free space remains inside ${scene.regions.find((region) => region.id === resource.parentId)?.name ?? "the boundary"}`);
    return;
  }
  renderer.selectedIds.clear();
  renderer.selectedIds.add(resource.id);
  updateSelectionUI();
  buildLayerFilters();
  draw();
  showToast(`${entry.name} added to ${scene.regions.find((region) => region.id === resource.parentId)?.name ?? "subscription"}`);
}

function copySelection() {
  clipboard = selectedItems().filter((item) => "type" in item).map((item) => structuredClone(item));
  if (clipboard.length) showToast(`${clipboard.length} resource${clipboard.length > 1 ? "s" : ""} copied`);
}

function pasteSelection() {
  if (!editMode || !clipboard.length) return;
  snapshot();
  renderer.selectedIds.clear();
  for (const source of clipboard) {
    const resource = {
      ...structuredClone(source),
      id: `${source.type}-paste-${Date.now()}-${nextId++}`,
      name: `${source.name}-copy`,
      x: clamp(source.x + .8, .6, WORLD.width - .6),
      y: clamp(source.y + .8, .6, WORLD.height - .6),
    };
    resource.parentId = findRegionAt(scene, resource.x, resource.y)?.id ?? "sub-prod";
    scene.resources.push(resource);
    if (!settleResource(resource)) { scene.resources.pop(); continue; }
    renderer.selectedIds.add(resource.id);
  }
  updateSelectionUI(); buildLayerFilters(); draw();
}

canvas.addEventListener("pointerdown", (event) => {
  canvas.setPointerCapture(event.pointerId);
  const point = pointFromEvent(event);
  const hit = renderer.hitTest(scene, point.x, point.y);
  lastPointer = point;
  moved = false;

  if ((event.ctrlKey || event.metaKey) && hit?.kind !== "resource" && hit?.kind !== "map-scale") {
    pointerMode = "box";
    renderer.selectionBox = { x1: point.x, y1: point.y, x2: point.x, y2: point.y };
  } else if (hit?.kind === "map-scale") {
    pointerMode = "map-scale";
    mapScaleStart = { x: point.x, y: point.y, scale: renderer.camera.scale };
  } else if (hit?.kind === "resource" && editMode) {
    pointerMode = "resource";
    activeResource = hit.item;
    if (!renderer.selectedIds.has(activeResource.id)) select(hit, event.shiftKey);
    dragStartWorld = renderer.unproject(point.x, point.y);
    dragGroup = selectedItems().filter((item) => "type" in item).map((item) => ({ item, x: item.x, y: item.y }));
    dragSceneStart = captureResourcePositions();
    snapshot();
  } else if (hit?.kind === "resource") {
    select(hit, event.shiftKey);
    pointerMode = "select";
  } else if (event.shiftKey && hit) {
    select(hit, true);
    pointerMode = "select";
  } else {
    pointerMode = "pan";
    if (hit) select(hit, false);
    else select(null, false);
  }
  canvas.classList.add("is-dragging");
});

canvas.addEventListener("pointermove", (event) => {
  const point = pointFromEvent(event);
  const dx = point.x - lastPointer.x;
  const dy = point.y - lastPointer.y;
  if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;

  if (pointerMode === "pan") {
    renderer.camera.panX += dx;
    renderer.camera.panY += dy;
    draw();
  } else if (pointerMode === "box" && renderer.selectionBox) {
    renderer.selectionBox.x2 = point.x;
    renderer.selectionBox.y2 = point.y;
    draw();
  } else if (pointerMode === "map-scale" && mapScaleStart) {
    const totalX = point.x - mapScaleStart.x;
    const totalY = point.y - mapScaleStart.y;
    const factor = Math.exp((totalX + totalY) * .0045);
    renderer.camera.scale = clamp(mapScaleStart.scale * factor, 18, 132);
    draw();
  } else if (pointerMode === "resource" && activeResource) {
    const world = renderer.unproject(point.x, point.y);
    const deltaX = world.x - dragStartWorld.x;
    const deltaY = world.y - dragStartWorld.y;
    moveDragGroup(deltaX, deltaY);
    updateSelectionUI();
    draw();
  } else if (!pointerMode) {
    const hit = renderer.hitTest(scene, point.x, point.y);
    renderer.hoverId = hit?.item.id ?? null;
    updateTooltip(hit, point);
    draw();
  }
  lastPointer = point;
});

function endPointer() {
  const completedMode = pointerMode;
  if (completedMode === "resource" && !moved && history.length) history.pop();
  if (completedMode === "box" && renderer.selectionBox) {
    const box = renderer.selectionBox;
    const left = Math.min(box.x1, box.x2), right = Math.max(box.x1, box.x2);
    const top = Math.min(box.y1, box.y2), bottom = Math.max(box.y1, box.y2);
    renderer.selectedIds.clear();
    for (const resource of scene.resources) {
      const point = renderer.project(resource.x, resource.y, .2);
      if (point.x >= left && point.x <= right && point.y >= top && point.y <= bottom) renderer.selectedIds.add(resource.id);
    }
    renderer.selectionBox = null;
    updateSelectionUI();
  }
  pointerMode = null;
  activeResource = null;
  dragGroup = [];
  dragStartWorld = null;
  dragSceneStart = null;
  mapScaleStart = null;
  canvas.classList.remove("is-dragging");
  syncHistoryButtons();
  draw();
}

canvas.addEventListener("pointerup", endPointer);
canvas.addEventListener("pointercancel", endPointer);
canvas.addEventListener("pointerleave", () => { if (!pointerMode) updateTooltip(null); });

canvas.addEventListener("wheel", (event) => {
  event.preventDefault();
  const point = pointFromEvent(event);
  const oldScale = renderer.camera.scale;
  const newScale = clamp(oldScale * (event.deltaY < 0 ? 1.1 : .91), 18, 132);
  const ratio = newScale / oldScale;
  renderer.camera.panX = point.x - renderer.viewport.width / 2 - (point.x - renderer.viewport.width / 2 - renderer.camera.panX) * ratio;
  renderer.camera.panY = point.y - renderer.viewport.height / 2 - (point.y - renderer.viewport.height / 2 - renderer.camera.panY) * ratio;
  renderer.camera.scale = newScale;
  draw();
}, { passive: false });

stage.addEventListener("dragover", (event) => {
  if (!editMode || !paletteDragType) return;
  event.preventDefault();
  canvas.classList.add("is-dropping");
  const rect = canvas.getBoundingClientRect();
  const world = renderer.unproject(event.clientX - rect.left, event.clientY - rect.top);
  renderer.dropPreview = { x: snap(world.x), y: snap(world.y), valid: world.x >= 0 && world.x <= WORLD.width && world.y >= 0 && world.y <= WORLD.height };
  draw();
});

stage.addEventListener("dragleave", (event) => {
  if (event.relatedTarget && stage.contains(event.relatedTarget)) return;
  clearDropPreview();
});

stage.addEventListener("drop", (event) => {
  event.preventDefault();
  const rect = canvas.getBoundingClientRect();
  const world = renderer.unproject(event.clientX - rect.left, event.clientY - rect.top);
  if (paletteDragType && renderer.dropPreview?.valid) addResource(paletteDragType, world);
  clearDropPreview();
});

function clearDropPreview() {
  renderer.dropPreview = null;
  paletteDragType = null;
  canvas.classList.remove("is-dropping");
  draw();
}

function buildPalette(filter = "") {
  const root = document.getElementById("resourcePalette");
  root.innerHTML = "";
  const needle = filter.trim().toLowerCase();
  for (const [categoryId, category] of Object.entries(CATEGORIES)) {
    const entries = Object.entries(CATALOG).filter(([, item]) => item.category === categoryId && (!needle || `${item.name} ${item.label}`.toLowerCase().includes(needle)));
    if (!entries.length) continue;
    const section = document.createElement("section");
    section.className = "resource-group";
    section.innerHTML = `<h3>${category.name}</h3><div class="resource-grid"></div>`;
    const grid = section.querySelector(".resource-grid");
    for (const [type, item] of entries) {
      const button = document.createElement("button");
      button.className = "resource-item";
      button.draggable = true;
      button.dataset.type = type;
      button.innerHTML = `<span class="resource-glyph" style="--glyph-color:${category.color}">${item.label}</span><strong>${item.name}</strong>`;
      button.addEventListener("dragstart", (event) => {
        if (!editMode) { event.preventDefault(); showToast("Switch to Edit mode to add resources"); return; }
        paletteDragType = type;
        event.dataTransfer.effectAllowed = "copy";
        event.dataTransfer.setData("text/plain", type);
      });
      button.addEventListener("dragend", clearDropPreview);
      button.addEventListener("click", () => addResource(type, { x: WORLD.width / 2, y: WORLD.height / 2 }));
      grid.appendChild(button);
    }
    root.appendChild(section);
  }
}

function buildLayerFilters() {
  const root = document.getElementById("layerFilters");
  root.innerHTML = "";
  for (const [id, filter] of Object.entries(FILTERS)) {
    const count = id === "scopes" ? scene.regions.filter((r) => r.filter === "scopes").length
      : id === "network" ? scene.regions.filter((r) => r.filter === "network").length
        : id === "connections" ? scene.connections.length
          : scene.resources.filter((resource) => categoryFor(resource) === id).length;
    const button = document.createElement("button");
    button.className = `layer-filter${renderer.visibility.has(id) ? "" : " is-off"}`;
    button.innerHTML = `<span class="filter-swatch" style="--glyph-color:${filter.color}"></span><span><strong>${filter.name}</strong><small>${filter.description}</small></span><span class="filter-count">${count}</span>`;
    button.onclick = () => {
      if (renderer.visibility.has(id)) renderer.visibility.delete(id); else renderer.visibility.add(id);
      buildLayerFilters(); draw();
    };
    root.appendChild(button);
  }
}

function updateTooltip(hit, point) {
  const tooltip = document.getElementById("tooltip");
  if (!hit) { tooltip.hidden = true; return; }
  const item = hit.item;
  tooltip.hidden = false;
  tooltip.style.left = `${point.x + 13}px`;
  tooltip.style.top = `${point.y + 13}px`;
  tooltip.textContent = "type" in item ? `${item.name} / ${CATALOG[item.type].name}` : `${item.name} / ${item.subtitle}`;
}

function showToast(message) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.classList.add("is-on");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("is-on"), 1800);
}

function autoLayout() {
  if (!editMode) return;
  snapshot();
  const positions = {
    edge: [[1.0,.8]], security: [[2.35,3.55],[2.45,7],[8.35,9]], network: [[4.75,4],[4.85,8.1]],
    compute: [[8.45,3],[10.65,3.9],[8.65,6.1],[10.6,7.55]], data: [[13.65,3.15],[15.45,5.35],[13.8,7.8]],
  };
  const indexes = {};
  for (const resource of scene.resources) {
    const category = categoryFor(resource);
    indexes[category] ??= 0;
    const list = positions[category] ?? [[9,6]];
    const point = list[indexes[category] % list.length];
    const wrap = Math.floor(indexes[category] / list.length) * .65;
    resource.x = clamp(point[0] + wrap, .6, WORLD.width - .6);
    resource.y = clamp(point[1] + wrap, .6, WORLD.height - .6);
    resource.parentId = findRegionAt(scene, resource.x, resource.y)?.id ?? "sub-prod";
    indexes[category] += 1;
  }
  draw();
  showToast("Resources aligned by architecture role");
}

function exportScene() {
  const blob = new Blob([serializeScene(scene)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "architecture-atlas.json";
  anchor.click();
  URL.revokeObjectURL(url);
  showToast("Architecture JSON exported");
}

async function importScene(file) {
  if (!editMode || !file) return;
  try {
    const parsed = JSON.parse(await file.text());
    if (!Array.isArray(parsed.regions) || !Array.isArray(parsed.resources) || !Array.isArray(parsed.connections)) {
      throw new Error("The file does not contain an Architecture Atlas scene");
    }
    snapshot();
    scene = { regions: parsed.regions, resources: parsed.resources, connections: parsed.connections };
    renderer.selectedIds.clear();
    updateSelectionUI(); buildLayerFilters(); renderer.fit(); draw();
    showToast("Architecture JSON imported");
  } catch (error) {
    showToast(error instanceof Error ? error.message : "Import failed");
  }
}

function toggleEditMode() {
  editMode = !editMode;
  document.body.classList.toggle("is-read-mode", !editMode);
  const button = document.getElementById("modeBtn");
  button.classList.toggle("is-on", editMode);
  button.textContent = editMode ? "Edit mode" : "Read mode";
  document.getElementById("autoLayoutBtn").disabled = !editMode;
  document.getElementById("importBtn").disabled = !editMode;
  syncHistoryButtons();
  showToast(editMode ? "Edit mode enabled" : "Read-only exploration enabled");
}

function updateCompass() {
  const needle = document.querySelector("#compass i");
  needle.style.transform = `rotate(${renderer.camera.yaw}rad)`;
}

function zoom(factor) {
  renderer.camera.scale = clamp(renderer.camera.scale * factor, 18, 132);
  draw();
}

function bindControls() {
  document.getElementById("resourceSearch").addEventListener("input", (event) => buildPalette(event.target.value));
  document.getElementById("undoBtn").onclick = undo;
  document.getElementById("redoBtn").onclick = redo;
  document.getElementById("autoLayoutBtn").onclick = autoLayout;
  document.getElementById("modeBtn").onclick = toggleEditMode;
  document.getElementById("importBtn").onclick = () => document.getElementById("importInput").click();
  document.getElementById("importInput").onchange = (event) => { importScene(event.target.files?.[0]); event.target.value = ""; };
  document.getElementById("exportBtn").onclick = exportScene;
  document.getElementById("zoomIn").onclick = () => zoom(1.13);
  document.getElementById("zoomOut").onclick = () => zoom(.88);
  document.getElementById("fitBtn").onclick = () => { renderer.fit(); draw(); };
  document.getElementById("focusBtn").onclick = focusSelection;
  document.getElementById("duplicateBtn").onclick = duplicateSelection;
  document.getElementById("deleteBtn").onclick = deleteSelection;
  document.getElementById("toggleEdges").onclick = (event) => {
    renderer.showConnections = !renderer.showConnections;
    event.currentTarget.textContent = renderer.showConnections ? "Hide" : "Show";
    draw();
  };
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.onclick = () => {
      document.querySelectorAll("[data-view]").forEach((item) => item.classList.toggle("is-on", item === button));
      renderer.setView(button.dataset.view); draw();
    };
  });
  document.getElementById("selectionPanel").addEventListener("click", (event) => {
    const action = event.target.closest("[data-detail]")?.dataset.detail;
    if (action === "focus") focusSelection();
    if (action === "duplicate") duplicateSelection();
  });
  document.getElementById("openPalette").onclick = () => document.getElementById("palette").classList.add("is-open");
  document.getElementById("openInspector").onclick = () => document.getElementById("inspector").classList.add("is-open");
  document.querySelectorAll("[data-close]").forEach((button) => {
    button.onclick = () => document.getElementById(button.dataset.close).classList.remove("is-open");
  });
  window.addEventListener("keydown", (event) => {
    if (/input|textarea/i.test(event.target.tagName)) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") { event.shiftKey ? redo() : undo(); event.preventDefault(); }
    else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "c") { copySelection(); event.preventDefault(); }
    else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "v") { pasteSelection(); event.preventDefault(); }
    else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "d") { duplicateSelection(); event.preventDefault(); }
    else if (event.key === "Delete" || event.key === "Backspace") { deleteSelection(); event.preventDefault(); }
    else if (event.key === "Escape") select(null);
    else if (event.key.toLowerCase() === "f") focusSelection();
  });
}

function resize() {
  renderer.resize();
  renderer.fit();
  draw();
}

buildPalette();
buildLayerFilters();
bindControls();
syncHistoryButtons();
window.addEventListener("resize", resize);
resize();