import {
  Download,
  Maximize2,
  RotateCcw,
  Scan,
  X,
  ZoomIn,
  ZoomOut,
  createElement as createIcon,
  type IconNode,
} from "lucide";

import {
  centerViewBox,
  contentViewBox,
  interactiveInitialViewBox,
  needsReadableInitialCrop,
  panViewBox,
  zoomPercentage,
  zoomViewBox,
  type ViewBox,
} from "./viewport.js";
import { embeddedThemeCss } from "../render/theme.js";

type Locale = "en" | "ko";

interface ManifestText {
  title: string;
  description: string;
  alt: string;
}

interface DiagramManifest {
  id: string;
  kind: string;
  locales: Record<Locale, ManifestText>;
  assets: Record<Locale, { svg: string; png?: string }>;
  nodes: Array<{
    id: string;
    kind: string;
    shape?: string;
    tone?: string;
    badge?: number;
    start?: number | string;
    end?: number | string;
    duration?: number;
    after?: string;
    status?: "planned" | "active" | "done" | "critical" | "milestone";
    progress?: number;
    value?: number;
    xValue?: number;
    yValue?: number;
    size?: number;
    row?: number;
    column?: number;
    label: Record<Locale, string>;
    description: Record<Locale, string>;
    content?: Array<Record<Locale, string>>;
  }>;
  edges: Array<{
    id: string;
    from: string;
    to: string;
    kind: string;
    label: Record<Locale, string> | null;
    weight?: number;
    step?: number;
  }>;
}

const messages = {
  en: {
    zoomIn: "Zoom in",
    zoomOut: "Zoom out",
    reset: "Reset view",
    overview: "Fit overview",
    fullscreen: "Open fullscreen",
    download: "Download SVG",
    details: "Component details",
    connections: "Connected flows",
    incoming: "From",
    outgoing: "To",
    closeDetails: "Clear component selection",
    zoomLevel: "Zoom level",
    status: "Status",
    progress: "Progress",
    value: "Value",
    diagram: "Interactive architecture diagram. Use arrow keys to pan, plus and minus to zoom, and 0 to reset.",
  },
  ko: {
    zoomIn: "확대",
    zoomOut: "축소",
    reset: "보기 초기화",
    overview: "전체 보기",
    fullscreen: "전체 화면 열기",
    download: "SVG 다운로드",
    details: "Component 상세 정보",
    connections: "연결된 flow",
    incoming: "입력",
    outgoing: "출력",
    closeDetails: "Component 선택 해제",
    zoomLevel: "확대 비율",
    status: "상태",
    progress: "진행률",
    value: "값",
    diagram: "인터랙티브 아키텍처 다이어그램입니다. 방향키로 이동하고 더하기와 빼기로 확대 또는 축소하며 0으로 초기화합니다.",
  },
} as const;

const statusLabels = {
  en: {
    planned: "Planned",
    active: "Active",
    done: "Done",
    critical: "Critical",
    milestone: "Milestone",
  },
  ko: {
    planned: "계획",
    active: "진행 중",
    done: "완료",
    critical: "중요",
    milestone: "마일스톤",
  },
} as const;

const edgeKindLabels = {
  en: {
    request: "Decision request",
    event: "Asynchronous event",
    approval: "Human approval",
    mutation: "Governed change",
    audit: "Audit record",
    rollback: "Rollback",
    read: "Read projection",
    write: "Write",
    feedback: "Feedback loop",
    sequence: "Interaction",
    transition: "State transition",
    association: "Association",
    dependency: "Dependency",
    timeline: "Timeline",
  },
  ko: {
    request: "결정 요청",
    event: "비동기 이벤트",
    approval: "사람 승인",
    mutation: "통제된 변경",
    audit: "감사 기록",
    rollback: "롤백",
    read: "읽기 projection",
    write: "쓰기",
    feedback: "피드백 루프",
    sequence: "상호작용",
    transition: "상태 전이",
    association: "연관 관계",
    dependency: "의존 관계",
    timeline: "타임라인",
  },
} as const;

function localeFor(element: HTMLElement): Locale {
  const value = element.getAttribute("locale") ?? document.documentElement.lang;
  return value.toLowerCase().startsWith("ko") ? "ko" : "en";
}

function parseViewBox(svg: SVGSVGElement): ViewBox {
  const values = (svg.getAttribute("viewBox") ?? "0 0 1200 700")
    .split(/\s+/u)
    .map(Number);
  return {
    x: values[0] ?? 0,
    y: values[1] ?? 0,
    width: values[2] ?? 1200,
    height: values[3] ?? 700,
  };
}

function setViewBox(svg: SVGSVGElement, viewBox: ViewBox): void {
  svg.setAttribute(
    "viewBox",
    `${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`,
  );
}

function toolbarButton(
  icon: IconNode,
  label: string,
  action: () => void,
): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "button";
  button.title = label;
  button.setAttribute("aria-label", label);
  button.append(
    createIcon(icon, {
      width: 16,
      height: 16,
      "stroke-width": 1.6,
      "aria-hidden": "true",
    }),
  );
  button.addEventListener("click", action);
  return button;
}

function safeSvg(source: string): SVGSVGElement {
  const parsed = new DOMParser().parseFromString(source, "image/svg+xml");
  const svg = parsed.documentElement;
  if (svg.localName !== "svg" || parsed.querySelector("parsererror")) {
    throw new Error("The diagram asset is not valid SVG");
  }
  if (svg.querySelector("script, foreignObject")) {
    throw new Error("The diagram SVG contains unsupported active content");
  }
  for (const image of svg.querySelectorAll("image")) {
    const href = image.getAttribute("href") ?? "";
    if (!href.startsWith("data:image/svg+xml;base64,")) {
      throw new Error("The diagram SVG contains an external image reference");
    }
  }
  return document.importNode(svg, true) as unknown as SVGSVGElement;
}

class ArchitectureDiagramElement extends HTMLElement {
  async connectedCallback(): Promise<void> {
    const manifestPath = this.getAttribute("manifest");
    if (!manifestPath) return;
    try {
      await this.enhance(new URL(manifestPath, document.baseURI));
    } catch (error) {
      console.warn(
        "Architecture diagram enhancement failed; using static fallback.",
        error,
      );
    }
  }

  private async enhance(manifestUrl: URL): Promise<void> {
    const locale = localeFor(this);
    const labels = messages[locale];
    const manifestResponse = await fetch(manifestUrl);
    if (!manifestResponse.ok) {
      throw new Error(`Unable to load ${manifestUrl.pathname}`);
    }
    const manifest = (await manifestResponse.json()) as DiagramManifest;
    const svgUrl = new URL(manifest.assets[locale].svg, manifestUrl);
    const svgResponse = await fetch(svgUrl);
    if (!svgResponse.ok) throw new Error(`Unable to load ${svgUrl.pathname}`);
    const svg = safeSvg(await svgResponse.text());
    svg.removeAttribute("width");
    svg.removeAttribute("height");
    svg.setAttribute("data-embedded", "");

    const contentBounds = contentViewBox(parseViewBox(svg));
    const compact = window.matchMedia("(max-width: 44rem)").matches;
    const viewportWidth = Math.max(320, this.getBoundingClientRect().width);
    const readableCrop = needsReadableInitialCrop(
      contentBounds,
      viewportWidth,
      compact,
    );
    const compactViewBox = interactiveInitialViewBox(
      contentBounds,
      viewportWidth,
      Math.min(480, window.innerHeight * 0.72),
      readableCrop,
    );
    const centerOnCompact = [
      "pie",
      "radar",
      "quadrant",
      "xy-chart",
      "venn",
      "wardley",
    ].includes(manifest.kind);
    const initialViewBox = readableCrop && centerOnCompact
      ? centerViewBox(compactViewBox, contentBounds)
      : compactViewBox;
    let viewBox = { ...initialViewBox };
    setViewBox(svg, viewBox);
    let dragStart: {
      x: number;
      y: number;
      viewX: number;
      viewY: number;
      moved: boolean;
    } | null = null;
    let suppressStageClick = false;
    const shadow = this.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = `
      :host { --fdai-diagram-canvas: #faf9f8; --fdai-diagram-surface: #ffffff; --fdai-diagram-node: #ffffff; --fdai-diagram-label-surface: #ffffff; --fdai-diagram-text: #323130; --fdai-diagram-muted: #605e5c; --fdai-diagram-border: #a19f9d; --fdai-diagram-border-strong: #605e5c; --fdai-diagram-neutral-header: #edebe9; --fdai-diagram-control-surface: #eff6fc; --fdai-diagram-control-header: #deecf9; --fdai-diagram-delivery-surface: #f0fbfd; --fdai-diagram-delivery-header: #d9f8ff; --fdai-diagram-azure: #0078d4; --fdai-diagram-azure-dark: #005a9e; --fdai-diagram-azure-soft: #deecf9; --fdai-diagram-cyan-dark: #187ea8; --fdai-diagram-tone-input-fill: #f4f8ff; --fdai-diagram-tone-input-stroke: #2563eb; --fdai-diagram-tone-interpretation-fill: #eef6ff; --fdai-diagram-tone-interpretation-stroke: #0f6cbd; --fdai-diagram-tone-model-fill: #eefbf7; --fdai-diagram-tone-model-stroke: #008272; --fdai-diagram-tone-policy-fill: #f1faef; --fdai-diagram-tone-policy-stroke: #2e7d32; --fdai-diagram-tone-decision-fill: #fff8e6; --fdai-diagram-tone-decision-stroke: #9a6500; --fdai-diagram-tone-execution-fill: #f7f2ff; --fdai-diagram-tone-execution-stroke: #6b46c1; --fdai-diagram-tone-feedback-fill: #f5f2ff; --fdai-diagram-tone-feedback-stroke: #6045df; --fdai-diagram-tone-store-fill: #f6f7f8; --fdai-diagram-tone-store-stroke: #5f6b7a; --fdai-diagram-tone-neutral-fill: #ffffff; --fdai-diagram-tone-neutral-stroke: #667085; --fdai-diagram-group-lane-fill: #ffffff; --fdai-diagram-group-lane-stroke: #9fb3c8; --fdai-diagram-group-sidebar-fill: #f7f5ff; --fdai-diagram-group-sidebar-stroke: #7c5ce7; --fdai-diagram-group-feedback-fill: #faf8ff; --fdai-diagram-group-feedback-stroke: #6045df; --fdai-diagram-group-datastore-fill: #f7f8fa; --fdai-diagram-group-datastore-stroke: #6b7280; --fdai-diagram-badge-fill: #173b6c; --fdai-diagram-badge-ring: #ffffff; --fdai-diagram-badge-text: #ffffff; --fdai-diagram-gantt-planned: #e8edf2; --fdai-diagram-gantt-planned-stroke: #667085; --fdai-diagram-gantt-planned-text: #323130; --fdai-diagram-gantt-active: #0f6cbd; --fdai-diagram-gantt-active-stroke: #005a9e; --fdai-diagram-gantt-done: #107c10; --fdai-diagram-gantt-done-stroke: #0b5c0b; --fdai-diagram-gantt-critical: #c43501; --fdai-diagram-gantt-critical-stroke: #8f2600; --fdai-diagram-gantt-milestone: #6b46c1; --fdai-diagram-gantt-milestone-stroke: #51349a; --fdai-diagram-gantt-progress: #ffffff; --fdai-diagram-gantt-text: #ffffff; display: block; width: 100%; max-width: 100%; min-width: 0; margin: 1.5rem 0 2rem; color: var(--sl-color-text, #323130); contain: inline-size; }
      :host-context([data-theme="dark"]) { --fdai-diagram-canvas: #111315; --fdai-diagram-surface: #1b1f23; --fdai-diagram-node: #20252a; --fdai-diagram-label-surface: #1b1f23; --fdai-diagram-text: #f3f5f7; --fdai-diagram-muted: #c5cbd2; --fdai-diagram-border: #69737d; --fdai-diagram-border-strong: #aab2bb; --fdai-diagram-neutral-header: #30363d; --fdai-diagram-control-surface: #10283d; --fdai-diagram-control-header: #153d5c; --fdai-diagram-delivery-surface: #102d32; --fdai-diagram-delivery-header: #134148; --fdai-diagram-azure: #63d9ff; --fdai-diagram-azure-dark: #8bc8ff; --fdai-diagram-azure-soft: #153d5c; --fdai-diagram-cyan-dark: #63d9ff; --fdai-diagram-tone-input-fill: #10243a; --fdai-diagram-tone-input-stroke: #6cb8ff; --fdai-diagram-tone-interpretation-fill: #102a3a; --fdai-diagram-tone-interpretation-stroke: #50c8ff; --fdai-diagram-tone-model-fill: #0e2d28; --fdai-diagram-tone-model-stroke: #5ee0bd; --fdai-diagram-tone-policy-fill: #17331d; --fdai-diagram-tone-policy-stroke: #73d17c; --fdai-diagram-tone-decision-fill: #3a2a0b; --fdai-diagram-tone-decision-stroke: #f3c969; --fdai-diagram-tone-execution-fill: #2b2040; --fdai-diagram-tone-execution-stroke: #c7a0ff; --fdai-diagram-tone-feedback-fill: #261f42; --fdai-diagram-tone-feedback-stroke: #b9a1ff; --fdai-diagram-tone-store-fill: #25292e; --fdai-diagram-tone-store-stroke: #b8c2cc; --fdai-diagram-tone-neutral-fill: #20252a; --fdai-diagram-tone-neutral-stroke: #b8c2cc; --fdai-diagram-edge-request: #6cb8ff; --fdai-diagram-edge-event: #50c8ff; --fdai-diagram-edge-approval: #c7a0ff; --fdai-diagram-edge-mutation: #ff9d72; --fdai-diagram-edge-audit: #73d17c; --fdai-diagram-edge-rollback: #ff8b91; --fdai-diagram-edge-read: #5ee0bd; --fdai-diagram-edge-write: #d6a8ff; --fdai-diagram-edge-feedback: #b9a1ff; --fdai-diagram-edge-sequence: #6cb8ff; --fdai-diagram-edge-transition: #c7a0ff; --fdai-diagram-edge-association: #c5cbd2; --fdai-diagram-edge-dependency: #aab2bb; --fdai-diagram-edge-timeline: #f3c969; --fdai-diagram-group-lane-fill: #1b1f23; --fdai-diagram-group-lane-stroke: #7890a8; --fdai-diagram-group-sidebar-fill: #25203a; --fdai-diagram-group-sidebar-stroke: #b9a1ff; --fdai-diagram-group-feedback-fill: #211d35; --fdai-diagram-group-feedback-stroke: #b9a1ff; --fdai-diagram-group-datastore-fill: #20252a; --fdai-diagram-group-datastore-stroke: #aab2bb; --fdai-diagram-badge-fill: #6cb8ff; --fdai-diagram-badge-ring: #07131f; --fdai-diagram-badge-text: #07131f; --fdai-diagram-gantt-planned: #313840; --fdai-diagram-gantt-planned-stroke: #aab2bb; --fdai-diagram-gantt-planned-text: #f3f5f7; --fdai-diagram-gantt-active: #237bc2; --fdai-diagram-gantt-active-stroke: #8bc8ff; --fdai-diagram-gantt-done: #267a35; --fdai-diagram-gantt-done-stroke: #73d17c; --fdai-diagram-gantt-critical: #b94a2f; --fdai-diagram-gantt-critical-stroke: #ff9d72; --fdai-diagram-gantt-milestone: #7655bd; --fdai-diagram-gantt-milestone-stroke: #c7a0ff; --fdai-diagram-gantt-progress: #ffffff; --fdai-diagram-gantt-text: #ffffff; --fdai-diagram-chart-surface: #1b1f23; --fdai-diagram-chart-1: #6cb8ff; --fdai-diagram-chart-2: #5ee0bd; --fdai-diagram-chart-3: #c7a0ff; --fdai-diagram-chart-4: #ff9d72; --fdai-diagram-chart-5: #f3c969; --fdai-diagram-chart-6: #ff8b91; --fdai-diagram-chart-7: #50c8ff; --fdai-diagram-chart-8: #d6a8ff; --fdai-diagram-pie-text: #07131f; }
      .shell { box-sizing: border-box; position: relative; width: 100%; max-width: 100%; min-width: 0; border: 1px solid var(--sl-color-hairline, var(--fdai-diagram-border)); border-radius: 8px; overflow: hidden; background: var(--fdai-diagram-canvas); }
      .toolbar { box-sizing: border-box; position: absolute; z-index: 4; inset-block-start: 0.45rem; inset-inline-end: 0.45rem; display: flex; width: auto; align-items: center; justify-content: flex-end; gap: 0.1rem; padding: 0.18rem; border: 1px solid var(--sl-color-hairline, #d6e0ec); border-radius: 6px; background: color-mix(in srgb, var(--sl-color-bg, #fff) 92%, transparent); box-shadow: 0 4px 14px rgb(15 23 42 / 0.16); opacity: 0; transform: translateY(-0.2rem); pointer-events: none; transition: opacity 140ms ease, transform 140ms ease; }
      .shell:hover .toolbar, .shell:focus-within .toolbar { opacity: 1; transform: translateY(0); pointer-events: auto; }
      .zoom-status { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
      button { display: inline-grid; flex: 0 0 auto; place-items: center; width: 2rem; height: 2rem; padding: 0; border: 1px solid transparent; border-radius: 5px; background: transparent; color: var(--sl-color-gray-2, #64748b); cursor: pointer; }
      button svg { width: 0.9rem; height: 0.9rem; color: inherit; stroke: currentColor; }
      button:hover { background: var(--sl-color-bg-nav, #eef3f8); border-color: var(--sl-color-hairline, #cbd5e1); color: var(--sl-color-white, #334155); }
      button:focus-visible { outline: 2px solid var(--sl-color-text-accent, #0078d4); outline-offset: 2px; }
      .stage { box-sizing: border-box; position: relative; width: 100%; max-width: 100%; height: auto; overflow: hidden; touch-action: pan-y; cursor: default; }
      .stage.can-pan { touch-action: none; cursor: grab; }
      .stage.dragging { cursor: grabbing; }
      .stage:focus-visible { outline: 3px solid var(--sl-color-text-accent, #0078d4); outline-offset: -3px; }
      svg { display: block; width: 100%; height: 100%; user-select: none; }
      .details { box-sizing: border-box; display: none; position: relative; grid-template-columns: minmax(12rem, 0.7fr) 1.3fr; gap: 1rem; width: 100%; padding: 1rem 3.5rem 1rem 1.25rem; border-top: 1px solid var(--sl-color-hairline, var(--fdai-diagram-border)); background: var(--fdai-diagram-surface); color: var(--fdai-diagram-text); }
      .details.open { display: grid; }
      .details-close { position: absolute; inset-block-start: 0.65rem; inset-inline-end: 0.65rem; }
      .details h3 { margin: 0 0 0.3rem; font-size: 1rem; letter-spacing: 0; }
      .details p { margin: 0; color: var(--fdai-diagram-muted); font-size: 0.9rem; }
      .details ul { margin: 0.65rem 0 0; padding-inline-start: 1.1rem; color: var(--fdai-diagram-muted); font-size: 0.84rem; }
      .details li + li { margin-block-start: 0.2rem; }
      .connections { display: flex; flex-wrap: wrap; align-content: flex-start; gap: 0.4rem; }
      .flow { padding: 0.2rem 0.55rem; border-radius: 999px; border: 1px solid var(--sl-color-hairline, #cbd5e1); font-size: 0.78rem; }
      .shell:fullscreen { width: 100vw; height: 100vh; border: 0; border-radius: 0; }
      .shell:fullscreen .stage { height: 100vh; }
      .shell:fullscreen .details.open { position: absolute; inset-inline: 1rem; inset-block-end: 1rem; width: auto; max-height: 13rem; overflow: auto; border: 1px solid var(--sl-color-hairline, #d6e0ec); border-radius: 8px; box-shadow: 0 8px 28px rgb(15 23 42 / 0.24); }
      ${embeddedThemeCss()}
      @media (max-width: 44rem) { .toolbar { inset-block-start: 0.3rem; inset-inline-end: 0.3rem; } .stage { height: min(72vh, 30rem); min-height: 24rem; } .details { grid-template-columns: 1fr; } }
      @media (hover: none) { .toolbar { opacity: 1; transform: none; pointer-events: auto; } }
      @media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; } .toolbar { transition: none; } }
    `;

    const shell = document.createElement("div");
    shell.className = "shell";
    const toolbar = document.createElement("div");
    toolbar.className = "toolbar";
    toolbar.setAttribute("role", "toolbar");
    toolbar.setAttribute("aria-label", manifest.locales[locale].title);
    const zoomStatus = document.createElement("output");
    zoomStatus.className = "zoom-status";
    zoomStatus.setAttribute("aria-label", labels.zoomLevel);
    zoomStatus.setAttribute("aria-live", "polite");
    const stage = document.createElement("div");
    stage.className = "stage";
    if (!compact) {
      stage.style.aspectRatio = `${initialViewBox.width} / ${initialViewBox.height}`;
    }
    stage.tabIndex = 0;
    stage.setAttribute("role", "region");
    stage.setAttribute("aria-label", `${manifest.locales[locale].title}. ${labels.diagram}`);
    stage.setAttribute("aria-keyshortcuts", "+ - 0 ArrowLeft ArrowRight ArrowUp ArrowDown Escape");
    stage.append(svg);
    const details = document.createElement("aside");
    details.className = "details";
    details.setAttribute("aria-live", "polite");

    const applyViewBox = (): void => {
      setViewBox(svg, viewBox);
      zoomStatus.value = `${zoomPercentage(viewBox, contentBounds)}%`;
      stage.classList.toggle(
        "can-pan",
        viewBox.width < contentBounds.width || viewBox.height < contentBounds.height,
      );
    };
    const zoom = (factor: number, anchorX = 0.5, anchorY = 0.5): void => {
      viewBox = zoomViewBox(
        viewBox,
        contentBounds,
        factor,
        anchorX,
        anchorY,
      );
      applyViewBox();
    };
    const reset = (): void => {
      viewBox = { ...initialViewBox };
      applyViewBox();
      this.selectNode(null, manifest, svg, details, locale, labels);
    };
    applyViewBox();
    toolbar.append(
      zoomStatus,
      toolbarButton(ZoomIn, labels.zoomIn, () => zoom(0.82)),
      toolbarButton(ZoomOut, labels.zoomOut, () => zoom(1.22)),
      toolbarButton(RotateCcw, labels.reset, reset),
      toolbarButton(Scan, labels.overview, () => {
        viewBox = { ...contentBounds };
        applyViewBox();
      }),
      toolbarButton(Maximize2, labels.fullscreen, () => {
        void shell.requestFullscreen().catch(() => undefined);
      }),
      toolbarButton(Download, labels.download, () => {
        const link = document.createElement("a");
        link.href = svgUrl.href;
        link.download = manifest.assets[locale].svg;
        link.click();
      }),
    );

    stage.addEventListener("pointerdown", (event) => {
      if (event.button !== 0) return;
      dragStart = {
        x: event.clientX,
        y: event.clientY,
        viewX: viewBox.x,
        viewY: viewBox.y,
        moved: false,
      };
      stage.classList.add("dragging");
      stage.setPointerCapture(event.pointerId);
    });
    stage.addEventListener("pointermove", (event) => {
      if (!dragStart) return;
      const scaleX = viewBox.width / stage.clientWidth;
      const scaleY = viewBox.height / stage.clientHeight;
      const deltaX = event.clientX - dragStart.x;
      const deltaY = event.clientY - dragStart.y;
      dragStart.moved ||= Math.hypot(deltaX, deltaY) > 4;
      viewBox = panViewBox(
        { ...viewBox, x: dragStart.viewX, y: dragStart.viewY },
        contentBounds,
        -deltaX * scaleX,
        -deltaY * scaleY,
      );
      applyViewBox();
    });
    const finishDrag = (event: PointerEvent): void => {
      suppressStageClick = Boolean(dragStart?.moved);
      dragStart = null;
      stage.classList.remove("dragging");
      if (stage.hasPointerCapture(event.pointerId)) {
        stage.releasePointerCapture(event.pointerId);
      }
      setTimeout(() => {
        suppressStageClick = false;
      }, 0);
    };
    stage.addEventListener("pointerup", finishDrag);
    stage.addEventListener("pointercancel", finishDrag);

    stage.addEventListener("keydown", (event) => {
      const step = viewBox.width * 0.08;
      if (event.key === "+" || event.key === "=") zoom(0.82);
      else if (event.key === "-") zoom(1.22);
      else if (event.key === "0") reset();
      else if (event.key === "ArrowLeft") viewBox = panViewBox(viewBox, contentBounds, -step, 0);
      else if (event.key === "ArrowRight") viewBox = panViewBox(viewBox, contentBounds, step, 0);
      else if (event.key === "ArrowUp") viewBox = panViewBox(viewBox, contentBounds, 0, -step);
      else if (event.key === "ArrowDown") viewBox = panViewBox(viewBox, contentBounds, 0, step);
      else if (event.key === "Escape") this.selectNode(null, manifest, svg, details, locale, labels);
      else return;
      event.preventDefault();
      applyViewBox();
    });

    const diagramNodes = [
      ...svg.querySelectorAll<SVGGElement>("[data-node-id]"),
    ];
    diagramNodes.forEach((node, index) => {
      node.tabIndex = index === 0 ? 0 : -1;
      node.setAttribute("aria-pressed", "false");
      node.addEventListener("focus", () => node.classList.add("is-keyboard-focused"));
      node.addEventListener("blur", () => node.classList.remove("is-keyboard-focused"));
      const select = (): void => {
        this.selectNode(
          node.dataset.nodeId ?? null,
          manifest,
          svg,
          details,
          locale,
          labels,
        );
      };
      node.addEventListener("click", (event) => {
        event.stopPropagation();
        select();
      });
      node.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          event.stopPropagation();
          select();
          return;
        }
        if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
        event.preventDefault();
        event.stopPropagation();
        const current = diagramNodes.indexOf(node);
        const delta = event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 1;
        const next = diagramNodes[(current + delta + diagramNodes.length) % diagramNodes.length];
        node.tabIndex = -1;
        if (next) {
          next.tabIndex = 0;
          next.focus();
        }
      });
    });
    svg.addEventListener("click", () => {
      if (suppressStageClick) return;
      this.selectNode(null, manifest, svg, details, locale, labels);
    });

    shell.append(toolbar, stage, details);
    shadow.append(style, shell);
  }

  private selectNode(
    nodeId: string | null,
    manifest: DiagramManifest,
    svg: SVGSVGElement,
    details: HTMLElement,
    locale: Locale,
    labels: (typeof messages)[Locale],
  ): void {
    const connected = manifest.edges
      .filter((edge) => edge.from === nodeId || edge.to === nodeId)
      .sort((left, right) => Number(left.to === nodeId) - Number(right.to === nodeId));
    const connectedNodeIds = new Set<string>([nodeId ?? ""]);
    for (const edge of connected) {
      connectedNodeIds.add(edge.from);
      connectedNodeIds.add(edge.to);
    }
    for (const node of svg.querySelectorAll<SVGGElement>("[data-node-id]")) {
      const active = nodeId === node.dataset.nodeId;
      node.classList.toggle("is-active", active);
      node.setAttribute("aria-pressed", String(active));
      node.style.opacity = !nodeId
        ? "1"
        : active
          ? "1"
          : connectedNodeIds.has(node.dataset.nodeId ?? "")
            ? "0.82"
            : "0.2";
    }
    for (const edge of svg.querySelectorAll<SVGGElement>("[data-edge-id]")) {
      const active = edge.dataset.edgeFrom === nodeId || edge.dataset.edgeTo === nodeId;
      edge.classList.toggle("is-active", active);
      edge.classList.toggle("is-muted", Boolean(nodeId) && !active);
    }
    const node = manifest.nodes.find((candidate) => candidate.id === nodeId);
    if (!node) {
      details.classList.remove("open");
      details.replaceChildren();
      return;
    }
    const summary = document.createElement("div");
    const heading = document.createElement("h3");
    heading.textContent = node.label[locale];
    const description = document.createElement("p");
    description.textContent = node.description[locale];
    summary.append(heading, description);
    if (node.status || node.progress !== undefined) {
      const state = document.createElement("p");
      state.className = "node-state";
      const status = node.status
        ? `${labels.status}: ${statusLabels[locale][node.status]}`
        : "";
      const progress = node.progress !== undefined
        ? `${labels.progress}: ${node.progress}%`
        : "";
      state.textContent = [status, progress].filter(Boolean).join(" | ");
      summary.append(state);
    }
    if (node.value !== undefined) {
      const value = document.createElement("p");
      value.className = "node-state";
      value.textContent = `${labels.value}: ${node.value}`;
      summary.append(value);
    }
    if (node.content?.length) {
      const content = document.createElement("ul");
      for (const item of node.content) {
        const listItem = document.createElement("li");
        listItem.textContent = item[locale];
        content.append(listItem);
      }
      summary.append(content);
    }
    const flows = document.createElement("div");
    flows.className = "connections";
    flows.setAttribute("aria-label", labels.connections);
    for (const edge of connected) {
      const flow = document.createElement("span");
      flow.className = "flow";
      const outgoing = edge.from === nodeId;
      const peerId = outgoing ? edge.to : edge.from;
      const peer = manifest.nodes.find((candidate) => candidate.id === peerId);
      const kind =
        edgeKindLabels[locale][
          edge.kind as keyof (typeof edgeKindLabels)[Locale]
        ] ?? edge.kind;
      const step = edge.step ? `${edge.step}. ` : "";
      const weight = edge.weight ? ` (${edge.weight})` : "";
      flow.textContent = `${step}${outgoing ? labels.outgoing : labels.incoming}: ${kind}${weight} - ${peer?.label[locale] ?? peerId}`;
      flows.append(flow);
    }
    const close = toolbarButton(X, labels.closeDetails, () => {
      this.selectNode(null, manifest, svg, details, locale, labels);
      svg.querySelector<SVGGElement>(`[data-node-id="${node.id}"]`)?.focus();
    });
    close.className = "details-close";
    details.setAttribute("aria-label", labels.details);
    details.replaceChildren(summary, flows, close);
    details.classList.add("open");
  }
}

if (!customElements.get("fdai-architecture-diagram")) {
  customElements.define("fdai-architecture-diagram", ArchitectureDiagramElement);
}
