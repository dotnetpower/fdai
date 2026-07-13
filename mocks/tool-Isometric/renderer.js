import { CATALOG, CATEGORIES, RESOURCE_FOOTPRINT, WORLD, categoryFor } from "./model.js?v=10";

const REGION_PALETTE = {
  subscription: { fill: "#f8fafb", stroke: "#7d8996", label: "#354252" },
  "resource-group": { fill: "rgba(255,255,255,.63)", stroke: "#a7b2bd", label: "#4d5d6d" },
  vnet: { fill: "rgba(202,232,233,.58)", stroke: "#3f8589", label: "#23656a" },
  subnet: { fill: "rgba(224,242,238,.7)", stroke: "#68a093", label: "#39776a" },
};

const EDGE_STYLES = {
  ingress: { color: "#c85843", dash: [], width: 2.3 },
  internal: { color: "#347785", dash: [], width: 1.8 },
  data: { color: "#75599b", dash: [], width: 2 },
  private: { color: "#397a5d", dash: [5, 4], width: 1.8 },
};

const RESOURCE_LIFT = .14;
const RESOURCE_HEIGHT = .34;

export class AtlasRenderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.camera = { yaw: Math.PI / 4, pitch: 0.58, scale: 42, panX: 0, panY: 20 };
    this.fitScale = 42;
    this.viewport = { width: 0, height: 0, dpr: 1 };
    this.visibility = new Set(["scopes", "network", "security", "compute", "data", "connections"]);
    this.selectedIds = new Set();
    this.hoverId = null;
    this.showConnections = true;
    this.dropPreview = null;
    this.selectionBox = null;
  }

  resize() {
    const width = this.canvas.clientWidth;
    const height = this.canvas.clientHeight;
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.round(width * dpr);
    this.canvas.height = Math.round(height * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.viewport = { width, height, dpr };
  }

  project(x, y, z = 0) {
    const { yaw, pitch, scale, panX, panY } = this.camera;
    const ox = x - WORLD.width / 2;
    const oy = y - WORLD.height / 2;
    const cosYaw = Math.cos(yaw), sinYaw = Math.sin(yaw);
    const cosPitch = Math.cos(pitch), sinPitch = Math.sin(pitch);
    const rotatedX = ox * cosYaw - oy * sinYaw;
    const rotatedY = ox * sinYaw + oy * cosYaw;
    return {
      x: this.viewport.width / 2 + panX + rotatedX * scale,
      y: this.viewport.height / 2 + panY - (rotatedY * sinPitch + z * cosPitch) * scale,
      depth: rotatedY * cosPitch - z * sinPitch,
    };
  }

  unproject(screenX, screenY, z = 0) {
    const { yaw, pitch, scale, panX, panY } = this.camera;
    const cosYaw = Math.cos(yaw), sinYaw = Math.sin(yaw);
    const cosPitch = Math.cos(pitch), sinPitch = Math.sin(pitch);
    const rotatedX = (screenX - this.viewport.width / 2 - panX) / scale;
    const screenUp = -(screenY - this.viewport.height / 2 - panY) / scale;
    const rotatedY = (screenUp - z * cosPitch) / sinPitch;
    return {
      x: rotatedX * cosYaw + rotatedY * sinYaw + WORLD.width / 2,
      y: -rotatedX * sinYaw + rotatedY * cosYaw + WORLD.height / 2,
    };
  }

  projectUnit(x, y, z = 0) {
    const { yaw, pitch } = this.camera;
    const ox = x - WORLD.width / 2;
    const oy = y - WORLD.height / 2;
    const rotatedX = ox * Math.cos(yaw) - oy * Math.sin(yaw);
    const rotatedY = ox * Math.sin(yaw) + oy * Math.cos(yaw);
    return {
      x: rotatedX,
      y: -(rotatedY * Math.sin(pitch) + z * Math.cos(pitch)),
    };
  }

  fit() {
    const corners = [[0, 0], [WORLD.width, 0], [WORLD.width, WORLD.height], [0, WORLD.height]];
    const unit = corners.map(([x, y]) => this.projectUnit(x, y));
    const minX = Math.min(...unit.map((p) => p.x));
    const maxX = Math.max(...unit.map((p) => p.x));
    const minY = Math.min(...unit.map((p) => p.y));
    const maxY = Math.max(...unit.map((p) => p.y));
    const margin = Math.max(34, Math.min(76, this.viewport.width * .08));
    this.camera.scale = Math.max(22, Math.min(70,
      (this.viewport.width - margin * 2) / (maxX - minX),
      (this.viewport.height - margin * 2) / (maxY - minY)));
    if (this.viewport.width > 900) this.camera.scale = Math.min(70, this.camera.scale * 1.2);
    this.fitScale = this.camera.scale;
    this.camera.panX = -((minX + maxX) / 2) * this.camera.scale;
    this.camera.panY = -((minY + maxY) / 2) * this.camera.scale + 4;
  }

  setView(view) {
    if (view === "top") { this.camera.yaw = 0; this.camera.pitch = 1.5; }
    if (view === "iso") { this.camera.yaw = Math.PI / 4; this.camera.pitch = 0.58; }
    if (view === "front") { this.camera.yaw = 0; this.camera.pitch = 0.23; }
    this.fit();
  }

  render(scene) {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.viewport.width, this.viewport.height);
    this.drawBackdrop();
    this.drawBaseplate();
    if (this.visibility.has("scopes") || this.visibility.has("network")) this.drawRegions(scene);
    this.drawSnapPoints(scene);
    this.drawFloorReflections(scene);
    this.drawResources(scene);
    if (this.showConnections && this.visibility.has("connections")) this.drawConnections(scene);
    this.drawResourceOverlays(scene);
    if (this.dropPreview) this.drawDropPreview();
    if (this.selectionBox) this.drawSelectionBox();
  }

  drawBackdrop() {
    const gradient = this.ctx.createLinearGradient(0, 0, 0, this.viewport.height);
    gradient.addColorStop(0, "#f2f5f7");
    gradient.addColorStop(1, "#e7ecef");
    this.ctx.fillStyle = gradient;
    this.ctx.fillRect(0, 0, this.viewport.width, this.viewport.height);
  }

  drawBaseplate() {
    const points = [[0, 0], [WORLD.width, 0], [WORLD.width, WORLD.height], [0, WORLD.height]].map(([x, y]) => this.project(x, y));
    this.path(points);
    this.ctx.fillStyle = "#fbfcfd";
    this.ctx.fill();
    this.ctx.strokeStyle = "#aeb9c3";
    this.ctx.lineWidth = 1.5;
    this.ctx.stroke();

    this.ctx.save();
    this.ctx.strokeStyle = "rgba(111,128,143,.12)";
    this.ctx.lineWidth = 1;
    for (let x = 0; x <= WORLD.width; x += 1) this.line(this.project(x, 0), this.project(x, WORLD.height));
    for (let y = 0; y <= WORLD.height; y += 1) this.line(this.project(0, y), this.project(WORLD.width, y));
    this.ctx.restore();
  }

  drawSnapPoints(scene) {
    const workAreas = scene.regions.filter((region) => region.kind === "resource-group");
    this.ctx.save();
    this.ctx.fillStyle = "rgba(68,86,101,.2)";
    for (let x = 1; x < WORLD.width; x += 1) {
      for (let y = 1; y < WORLD.height; y += 1) {
        const inWorkArea = workAreas.some((region) =>
          x > region.x && x < region.x + region.w &&
          y > region.y && y < region.y + region.h);
        if (!inWorkArea) continue;
        const point = this.project(x, y, .002);
        this.ctx.beginPath();
        this.ctx.arc(point.x, point.y, .75, 0, Math.PI * 2);
        this.ctx.fill();
      }
    }
    this.ctx.restore();
  }

  drawRegions(scene) {
    const visible = scene.regions
      .filter((region) => this.visibility.has(region.filter))
      .sort((a, b) => b.w * b.h - a.w * a.h);
    for (const region of visible) {
      const palette = REGION_PALETTE[region.kind];
      const points = this.regionPoints(region, .015);
      this.path(points);
      this.ctx.fillStyle = palette.fill;
      this.ctx.fill();
      this.ctx.save();
      this.ctx.strokeStyle = this.selectedIds.has(region.id) ? "#146c77" : palette.stroke;
      this.ctx.lineWidth = this.selectedIds.has(region.id) ? 2.5 : region.kind === "subscription" ? 1.5 : 1.2;
      this.ctx.setLineDash(region.kind === "subnet" ? [5, 3] : []);
      this.ctx.stroke();
      this.ctx.restore();
      this.drawRegionLabel(region, palette);
      if (this.selectedIds.has(region.id) && region.kind === "subscription") {
        this.drawMapScaleHandle(region);
      }
    }
  }

  drawRegionLabel(region, palette) {
    const point = this.project(region.x + .18, region.y + .18, .03);
    this.ctx.font = `700 ${region.kind === "subscription" ? 10 : 9}px ${getComputedStyle(document.body).fontFamily}`;
    const labelWidth = this.ctx.measureText(region.name).width + 10;
    this.ctx.fillStyle = region.kind === "subscription" ? "rgba(53,66,82,.9)" : "rgba(255,255,255,.86)";
    this.roundRect(point.x - 2, point.y - 3, labelWidth, 14, 3);
    this.ctx.fill();
    this.ctx.textAlign = "left";
    this.ctx.textBaseline = "middle";
    this.ctx.fillStyle = region.kind === "subscription" ? "#fff" : palette.label;
    this.ctx.fillText(region.name, point.x + 3, point.y + 4);
    if (this.selectedIds.has(region.id)) {
      this.ctx.fillStyle = "rgba(53,66,82,.78)";
      this.ctx.font = `500 8px ${getComputedStyle(document.body).fontFamily}`;
      this.ctx.fillText(region.subtitle, point.x + 3, point.y + 18);
    }
  }

  drawResources(scene) {
    const resources = scene.resources
      .filter((resource) => this.visibility.has(categoryFor(resource)))
      .sort((a, b) => this.project(b.x, b.y).depth - this.project(a.x, a.y).depth);
    for (const resource of resources) this.drawResource(resource);
  }

  drawResource(resource) {
    const type = CATALOG[resource.type];
    const category = CATEGORIES[type.category];
    const selected = this.selectedIds.has(resource.id);
    const hovered = this.hoverId === resource.id;
    const w = RESOURCE_FOOTPRINT.width, d = RESOURCE_FOOTPRINT.depth;
    const baseZ = RESOURCE_LIFT;
    const topZ = RESOURCE_LIFT + RESOURCE_HEIGHT;
    const x0 = resource.x - w / 2, x1 = resource.x + w / 2;
    const y0 = resource.y - d / 2, y1 = resource.y + d / 2;
    const top = [
      this.project(x0, y0, topZ), this.project(x1, y0, topZ),
      this.project(x1, y1, topZ), this.project(x0, y1, topZ),
    ];
    const base = [
      this.project(x0, y0, baseZ), this.project(x1, y0, baseZ),
      this.project(x1, y1, baseZ), this.project(x0, y1, baseZ),
    ];
    const floor = [
      this.project(x0, y0, .004), this.project(x1, y0, .004),
      this.project(x1, y1, .004), this.project(x0, y1, .004),
    ];

    const baseCentre = this.project(resource.x, resource.y, 0);
    const shadow = this.ctx.createRadialGradient(baseCentre.x, baseCentre.y + 4, 1, baseCentre.x, baseCentre.y + 4, this.camera.scale * .62);
    shadow.addColorStop(0, "rgba(29,42,56,.22)");
    shadow.addColorStop(.55, "rgba(29,42,56,.08)");
    shadow.addColorStop(1, "rgba(29,42,56,0)");
    this.path(floor);
    this.ctx.fillStyle = shadow;
    this.ctx.fill();

    const sides = top.map((point, index) => {
      const next = (index + 1) % top.length;
      const points = [point, top[next], base[next], base[index]];
      return { points, depth: points.reduce((sum, item) => sum + item.depth, 0) / points.length };
    }).sort((a, b) => b.depth - a.depth);
    sides.forEach(({ points }, index) => {
      this.path(points);
      const gradient = this.ctx.createLinearGradient(points[0].x, points[0].y, points[2].x, points[2].y);
      gradient.addColorStop(0, index % 2 ? category.color : this.mix(category.color, .9));
      gradient.addColorStop(.42, index % 2 ? this.mix(category.color, .82) : this.mix(category.color, .72));
      gradient.addColorStop(1, this.mix(category.color, index % 2 ? .54 : .46));
      this.ctx.fillStyle = gradient;
      this.ctx.fill();
      this.ctx.strokeStyle = this.mix(category.color, .48);
      this.ctx.lineWidth = .85;
      this.ctx.stroke();
    });

    this.path(top);
    const topGradient = this.ctx.createLinearGradient(top[0].x, top[0].y, top[2].x, top[2].y);
    topGradient.addColorStop(0, category.color);
    topGradient.addColorStop(.42, this.mix(category.color, .94));
    topGradient.addColorStop(.76, this.mix(category.color, .82));
    topGradient.addColorStop(1, this.mix(category.color, .7));
    this.ctx.fillStyle = topGradient;
    this.ctx.fill();
    this.ctx.save();
    if (selected || hovered) {
      this.ctx.shadowColor = selected ? "rgba(20,108,119,.45)" : this.rgba(category.color, .34);
      this.ctx.shadowBlur = selected ? 11 : 7;
    }
    this.ctx.strokeStyle = selected ? "#102f36" : hovered ? "#146c77" : this.rgba(category.color, .72);
    this.ctx.lineWidth = selected ? 2.5 : hovered ? 2 : 1;
    this.ctx.stroke();
    this.ctx.restore();

    const topCentre = polygonCentre(top);
    const innerTop = top.map((point) => ({ ...point,
      x: point.x + (topCentre.x - point.x) * .08,
      y: point.y + (topCentre.y - point.y) * .08,
    }));
    this.path(innerTop);
    this.ctx.strokeStyle = "rgba(255,255,255,.34)";
    this.ctx.lineWidth = .7;
    this.ctx.stroke();
    this.ctx.beginPath();
    this.ctx.moveTo(top[0].x, top[0].y);
    this.ctx.lineTo(top[1].x, top[1].y);
    this.ctx.strokeStyle = "rgba(255,255,255,.42)";
    this.ctx.lineWidth = .9;
    this.ctx.stroke();

  }

  drawResourceOverlays(scene) {
    const resources = scene.resources
      .filter((resource) => this.visibility.has(categoryFor(resource)))
      .sort((a, b) => this.project(b.x, b.y).depth - this.project(a.x, a.y).depth);
    for (const resource of resources) this.drawResourceOverlay(resource);
  }

  drawResourceOverlay(resource) {
    const type = CATALOG[resource.type];
    const category = CATEGORIES[type.category];
    const selected = this.selectedIds.has(resource.id);
    const hovered = this.hoverId === resource.id;
    const topZ = RESOURCE_LIFT + RESOURCE_HEIGHT;
    const centre = this.project(resource.x, resource.y, topZ + .02);
    this.ctx.fillStyle = "#fff";
    this.ctx.font = `800 ${Math.max(8, Math.min(14, this.camera.scale * .24))}px ${getComputedStyle(document.body).fontFamily}`;
    this.ctx.textAlign = "center";
    this.ctx.textBaseline = "middle";
    this.ctx.strokeStyle = "rgba(25,35,47,.38)";
    this.ctx.lineWidth = 2.4;
    this.ctx.strokeText(type.label, centre.x, centre.y);
    this.ctx.fillText(type.label, centre.x, centre.y);

    if (this.camera.scale >= 28 || selected || hovered) {
      const label = this.project(resource.x, resource.y, 0);
      this.drawTextPill(resource.name, label.x, label.y + 14, selected || hovered);
    }
    const status = this.project(
      resource.x + RESOURCE_FOOTPRINT.width / 2 - .06,
      resource.y - RESOURCE_FOOTPRINT.depth / 2 + .06,
      topZ + .05,
    );
    this.ctx.beginPath();
    this.ctx.arc(status.x, status.y, 3, 0, Math.PI * 2);
    this.ctx.fillStyle = resource.status === "warning" ? "#e1a23e" : "#52a377";
    this.ctx.fill();
    this.ctx.strokeStyle = "#fff";
    this.ctx.lineWidth = 1;
    this.ctx.stroke();

    const portZ = RESOURCE_LIFT + RESOURCE_HEIGHT * .6;
    for (const [x, y] of [
      [resource.x - RESOURCE_FOOTPRINT.width / 2, resource.y],
      [resource.x + RESOURCE_FOOTPRINT.width / 2, resource.y],
    ]) {
      const port = this.project(x, y, portZ);
      this.ctx.beginPath();
      this.ctx.arc(port.x, port.y, 2.2, 0, Math.PI * 2);
      this.ctx.fillStyle = "#f7fafb";
      this.ctx.fill();
      this.ctx.strokeStyle = category.color;
      this.ctx.lineWidth = 1;
      this.ctx.stroke();
    }
  }

  drawFloorReflections(scene) {
    const resources = scene.resources.filter((resource) => this.visibility.has(categoryFor(resource)));
    this.ctx.save();
    this.ctx.globalCompositeOperation = "source-over";
    for (const resource of resources) {
      const category = CATEGORIES[CATALOG[resource.type].category];
      const x0 = resource.x - RESOURCE_FOOTPRINT.width / 2;
      const x1 = resource.x + RESOURCE_FOOTPRINT.width / 2;
      const y0 = resource.y - RESOURCE_FOOTPRINT.depth / 2;
      const y1 = resource.y + RESOURCE_FOOTPRINT.depth / 2;
      const mirrorBase = [
        this.project(x0, y0, -RESOURCE_LIFT),
        this.project(x1, y0, -RESOURCE_LIFT),
        this.project(x1, y1, -RESOURCE_LIFT),
        this.project(x0, y1, -RESOURCE_LIFT),
      ];
      const mirrorTop = [
        this.project(x0, y0, -(RESOURCE_LIFT + RESOURCE_HEIGHT)),
        this.project(x1, y0, -(RESOURCE_LIFT + RESOURCE_HEIGHT)),
        this.project(x1, y1, -(RESOURCE_LIFT + RESOURCE_HEIGHT)),
        this.project(x0, y1, -(RESOURCE_LIFT + RESOURCE_HEIGHT)),
      ];
      const floorCentre = this.project(resource.x, resource.y, .005);
      const radiusX = Math.max(9, this.camera.scale * .46);
      const radiusY = Math.max(5, this.camera.scale * .18);
      this.ctx.save();
      this.ctx.translate(floorCentre.x, floorCentre.y + 2);
      this.ctx.scale(1, radiusY / radiusX);
      const glow = this.ctx.createRadialGradient(0, 0, 0, 0, 0, radiusX);
      glow.addColorStop(0, this.rgba(category.color, .2));
      glow.addColorStop(.42, this.rgba(category.color, .08));
      glow.addColorStop(1, this.rgba(category.color, 0));
      this.ctx.fillStyle = glow;
      this.ctx.beginPath();
      this.ctx.arc(0, 0, radiusX, 0, Math.PI * 2);
      this.ctx.fill();
      this.ctx.restore();

      this.ctx.save();
      this.ctx.filter = "blur(.9px)";
      for (let index = 0; index < mirrorBase.length; index += 1) {
        const next = (index + 1) % mirrorBase.length;
        const face = [mirrorBase[index], mirrorBase[next], mirrorTop[next], mirrorTop[index]];
        this.path(face);
        const fade = this.ctx.createLinearGradient(
          mirrorBase[index].x, mirrorBase[index].y,
          mirrorTop[index].x, mirrorTop[index].y,
        );
        fade.addColorStop(0, this.rgba(category.color, .19));
        fade.addColorStop(.45, this.rgba(category.color, .08));
        fade.addColorStop(1, this.rgba(category.color, 0));
        this.ctx.fillStyle = fade;
        this.ctx.fill();
      }
      this.path(mirrorTop);
      this.ctx.fillStyle = this.rgba(category.color, .025);
      this.ctx.fill();
      this.ctx.restore();
    }
    this.ctx.restore();
  }

  drawConnections(scene) {
    for (const edge of scene.connections) {
      const source = scene.resources.find((resource) => resource.id === edge.source);
      const target = scene.resources.find((resource) => resource.id === edge.target);
      if (!source || !target) continue;
      if (!this.visibility.has(categoryFor(source)) || !this.visibility.has(categoryFor(target))) continue;
      const style = EDGE_STYLES[edge.kind];
      const connectionZ = RESOURCE_LIFT + RESOURCE_HEIGHT * .64;
      const sourceAnchor = this.connectionAnchor(source, target);
      const targetAnchor = this.connectionAnchor(target, source);
      const start = this.project(sourceAnchor.x, sourceAnchor.y, connectionZ);
      const end = this.project(targetAnchor.x, targetAnchor.y, connectionZ);
      const vector = { x: end.x - start.x, y: end.y - start.y };
      const length = Math.max(1, Math.hypot(vector.x, vector.y));
      let normal = { x: -vector.y / length, y: vector.x / length };
      if (normal.y > 0) normal = { x: -normal.x, y: -normal.y };
      const bend = Math.max(10, Math.min(32, length * .12));
      const control1 = {
        x: start.x + vector.x * .28 + normal.x * bend,
        y: start.y + vector.y * .28 + normal.y * bend,
      };
      const control2 = {
        x: start.x + vector.x * .72 + normal.x * bend,
        y: start.y + vector.y * .72 + normal.y * bend,
      };
      this.ctx.save();
      this.ctx.strokeStyle = style.color;
      this.ctx.lineWidth = style.width;
      this.ctx.setLineDash(style.dash);
      this.ctx.globalAlpha = .78;
      this.ctx.beginPath();
      this.ctx.moveTo(start.x, start.y);
      this.ctx.bezierCurveTo(control1.x, control1.y, control2.x, control2.y, end.x, end.y);
      this.ctx.stroke();
      this.ctx.setLineDash([]);
      this.arrowHead(end, { x: end.x - control2.x, y: end.y - control2.y }, style.color);
      this.ctx.beginPath();
      this.ctx.arc(start.x, start.y, 2.1, 0, Math.PI * 2);
      this.ctx.fillStyle = style.color;
      this.ctx.fill();
      if (this.hoverId === edge.id && this.camera.scale > 26) {
        const mx = (start.x + end.x) / 2 + normal.x * bend * .72;
        const my = (start.y + end.y) / 2 + normal.y * bend * .72;
        this.drawTextPill(edge.label, mx, my, true);
      }
      this.ctx.restore();
    }
  }

  connectionAnchor(resource, target) {
    const deltaX = target.x - resource.x;
    const deltaY = target.y - resource.y;
    const scaleX = Math.abs(deltaX) > 1e-6
      ? (RESOURCE_FOOTPRINT.width / 2) / Math.abs(deltaX)
      : Infinity;
    const scaleY = Math.abs(deltaY) > 1e-6
      ? (RESOURCE_FOOTPRINT.depth / 2) / Math.abs(deltaY)
      : Infinity;
    const scale = Math.min(scaleX, scaleY);
    return {
      x: resource.x + deltaX * scale,
      y: resource.y + deltaY * scale,
    };
  }

  drawDropPreview() {
    const preview = this.dropPreview;
    const points = this.regionPoints({ x: preview.x - .55, y: preview.y - .4, w: 1.1, h: .8 }, .04);
    this.path(points);
    this.ctx.fillStyle = preview.valid ? "rgba(20,108,119,.2)" : "rgba(181,71,53,.2)";
    this.ctx.fill();
    this.ctx.strokeStyle = preview.valid ? "#146c77" : "#b54735";
    this.ctx.lineWidth = 2;
    this.ctx.setLineDash([5, 3]);
    this.ctx.stroke();
    this.ctx.setLineDash([]);
  }

  drawMapScaleHandle(region) {
    const point = this.project(region.x + region.w, region.y + region.h, .06);
    this.ctx.fillStyle = "#fff";
    this.ctx.fillRect(point.x - 5, point.y - 5, 10, 10);
    this.ctx.strokeStyle = "#146c77";
    this.ctx.lineWidth = 2;
    this.ctx.strokeRect(point.x - 5, point.y - 5, 10, 10);
    this.ctx.beginPath();
    this.ctx.moveTo(point.x - 2, point.y + 2);
    this.ctx.lineTo(point.x + 3, point.y - 3);
    this.ctx.strokeStyle = "#146c77";
    this.ctx.lineWidth = 1;
    this.ctx.stroke();
  }

  drawSelectionBox() {
    const box = this.selectionBox;
    const x = Math.min(box.x1, box.x2), y = Math.min(box.y1, box.y2);
    const width = Math.abs(box.x2 - box.x1), height = Math.abs(box.y2 - box.y1);
    this.ctx.fillStyle = "rgba(20,108,119,.1)";
    this.ctx.fillRect(x, y, width, height);
    this.ctx.strokeStyle = "#146c77";
    this.ctx.lineWidth = 1;
    this.ctx.setLineDash([4, 3]);
    this.ctx.strokeRect(x, y, width, height);
    this.ctx.setLineDash([]);
  }

  hitTest(scene, screenX, screenY) {
    for (const region of scene.regions) {
      if (!this.selectedIds.has(region.id) || region.kind !== "subscription") continue;
      const handle = this.project(region.x + region.w, region.y + region.h, .06);
      if (Math.hypot(screenX - handle.x, screenY - handle.y) <= 12) {
        return { kind: "map-scale", item: region };
      }
    }
    const resources = [...scene.resources].reverse();
    for (const resource of resources) {
      if (!this.visibility.has(categoryFor(resource))) continue;
      const hitZ = RESOURCE_LIFT + RESOURCE_HEIGHT * .55;
      const point = this.unproject(screenX, screenY, hitZ);
      if (Math.abs(point.x - resource.x) <= .65 && Math.abs(point.y - resource.y) <= .55) return { kind: "resource", item: resource };
    }
    const world = this.unproject(screenX, screenY, 0);
    const regions = [...scene.regions]
      .filter((region) => this.visibility.has(region.filter))
      .sort((a, b) => a.w * a.h - b.w * b.h);
    const region = regions.find((item) => world.x >= item.x && world.x <= item.x + item.w && world.y >= item.y && world.y <= item.y + item.h);
    return region ? { kind: "region", item: region } : null;
  }

  focus(resource) {
    const point = this.project(resource.x, resource.y, RESOURCE_LIFT + RESOURCE_HEIGHT * .5);
    this.camera.panX += this.viewport.width / 2 - point.x;
    this.camera.panY += this.viewport.height / 2 - point.y + 30;
    this.camera.scale = Math.min(104, this.camera.scale * 1.55);
  }

  regionPoints(region, z = 0) {
    return [
      this.project(region.x, region.y, z),
      this.project(region.x + region.w, region.y, z),
      this.project(region.x + region.w, region.y + region.h, z),
      this.project(region.x, region.y + region.h, z),
    ];
  }

  path(points) {
    this.ctx.beginPath();
    this.ctx.moveTo(points[0].x, points[0].y);
    for (let i = 1; i < points.length; i += 1) this.ctx.lineTo(points[i].x, points[i].y);
    this.ctx.closePath();
  }

  line(a, b) {
    this.ctx.beginPath(); this.ctx.moveTo(a.x, a.y); this.ctx.lineTo(b.x, b.y); this.ctx.stroke();
  }

  arrowHead(end, vector, color) {
    const angle = Math.atan2(vector.y, vector.x);
    this.ctx.beginPath();
    this.ctx.moveTo(end.x, end.y);
    this.ctx.lineTo(end.x - 7 * Math.cos(angle - .45), end.y - 7 * Math.sin(angle - .45));
    this.ctx.lineTo(end.x - 7 * Math.cos(angle + .45), end.y - 7 * Math.sin(angle + .45));
    this.ctx.closePath();
    this.ctx.fillStyle = color;
    this.ctx.fill();
  }

  drawTextPill(text, x, y, active) {
    const fontSize = Math.max(9, Math.min(13, this.camera.scale * .11));
    this.ctx.font = `600 ${fontSize}px ${getComputedStyle(document.body).fontFamily}`;
    const width = this.ctx.measureText(text).width + 10;
    const height = fontSize + 6;
    this.ctx.fillStyle = active ? "rgba(24,33,45,.94)" : "rgba(255,255,255,.9)";
    this.roundRect(x - width / 2, y - height / 2, width, height, 4);
    this.ctx.fill();
    this.ctx.fillStyle = active ? "#fff" : "#354252";
    this.ctx.textAlign = "center";
    this.ctx.textBaseline = "middle";
    this.ctx.fillText(text, x, y);
  }

  roundRect(x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2);
    this.ctx.beginPath();
    this.ctx.moveTo(x + r, y);
    this.ctx.arcTo(x + width, y, x + width, y + height, r);
    this.ctx.arcTo(x + width, y + height, x, y + height, r);
    this.ctx.arcTo(x, y + height, x, y, r);
    this.ctx.arcTo(x, y, x + width, y, r);
    this.ctx.closePath();
  }

  mix(color, multiplier) {
    const value = parseInt(color.slice(1), 16);
    const r = Math.round(((value >> 16) & 255) * multiplier);
    const g = Math.round(((value >> 8) & 255) * multiplier);
    const b = Math.round((value & 255) * multiplier);
    return `rgb(${r},${g},${b})`;
  }

  rgba(color, alpha) {
    if (color.startsWith("rgb(")) {
      return color.replace("rgb(", "rgba(").replace(")", `,${alpha})`);
    }
    const value = parseInt(color.slice(1), 16);
    return `rgba(${(value >> 16) & 255},${(value >> 8) & 255},${value & 255},${alpha})`;
  }
}

function polygonCentre(points) {
  return {
    x: points.reduce((total, point) => total + point.x, 0) / points.length,
    y: points.reduce((total, point) => total + point.y, 0) / points.length,
  };
}
