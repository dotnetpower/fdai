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
  contentViewBox,
  interactiveInitialViewBox,
  panViewBox,
  zoomPercentage,
  zoomViewBox,
  type ViewBox,
} from "./viewport.js";

type Locale = "en" | "ko";

interface ManifestText {
  title: string;
  description: string;
  alt: string;
}

interface DiagramManifest {
  id: string;
  locales: Record<Locale, ManifestText>;
  assets: Record<Locale, { svg: string; png: string }>;
  nodes: Array<{
    id: string;
    kind: string;
    label: Record<Locale, string>;
    description: Record<Locale, string>;
  }>;
  edges: Array<{
    id: string;
    from: string;
    to: string;
    kind: string;
    label: Record<Locale, string> | null;
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
    diagram: "인터랙티브 아키텍처 다이어그램입니다. 방향키로 이동하고 더하기와 빼기로 확대 또는 축소하며 0으로 초기화합니다.",
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

    const contentBounds = contentViewBox(parseViewBox(svg));
    const compact = window.matchMedia("(max-width: 44rem)").matches;
    const initialViewBox = interactiveInitialViewBox(
      contentBounds,
      Math.max(320, this.getBoundingClientRect().width),
      Math.min(480, window.innerHeight * 0.72),
      compact,
    );
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
      :host { --fdai-diagram-canvas: #faf9f8; --fdai-diagram-surface: #ffffff; --fdai-diagram-node: #ffffff; --fdai-diagram-label-surface: #ffffff; --fdai-diagram-text: #323130; --fdai-diagram-muted: #605e5c; --fdai-diagram-border: #a19f9d; --fdai-diagram-border-strong: #605e5c; --fdai-diagram-neutral-header: #edebe9; --fdai-diagram-control-surface: #eff6fc; --fdai-diagram-control-header: #deecf9; --fdai-diagram-delivery-surface: #f0fbfd; --fdai-diagram-delivery-header: #d9f8ff; --fdai-diagram-azure: #0078d4; --fdai-diagram-azure-dark: #005a9e; --fdai-diagram-azure-soft: #deecf9; --fdai-diagram-cyan-dark: #35b4e3; display: block; width: 100%; max-width: 100%; min-width: 0; margin: 1.5rem 0 2rem; color: var(--sl-color-text, #323130); contain: inline-size; }
      :host-context([data-theme="dark"]) { --fdai-diagram-canvas: #11100f; --fdai-diagram-surface: #1b1a19; --fdai-diagram-node: #201f1e; --fdai-diagram-label-surface: #1b1a19; --fdai-diagram-text: #f3f2f1; --fdai-diagram-muted: #d2d0ce; --fdai-diagram-border: #605e5c; --fdai-diagram-border-strong: #a19f9d; --fdai-diagram-neutral-header: #323130; --fdai-diagram-control-surface: #10243a; --fdai-diagram-control-header: #163b5c; --fdai-diagram-delivery-surface: #102a30; --fdai-diagram-delivery-header: #123b44; --fdai-diagram-azure: #50e6ff; --fdai-diagram-azure-dark: #71afe5; --fdai-diagram-azure-soft: #163b5c; --fdai-diagram-cyan-dark: #50e6ff; }
      .shell { box-sizing: border-box; width: 100%; max-width: 100%; min-width: 0; border: 1px solid var(--sl-color-hairline, var(--fdai-diagram-border)); border-radius: 8px; overflow: hidden; background: var(--fdai-diagram-canvas); }
      .toolbar { box-sizing: border-box; display: flex; width: 100%; align-items: center; justify-content: flex-end; gap: 0.2rem; padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--sl-color-hairline, #d6e0ec); background: var(--sl-color-bg, #fff); }
      .zoom-status { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
      button { display: inline-grid; flex: 0 0 auto; place-items: center; width: 2.5rem; height: 2.5rem; padding: 0; border: 1px solid transparent; border-radius: 6px; background: transparent; color: var(--sl-color-gray-2, #64748b); cursor: pointer; }
      button svg { width: 1rem; height: 1rem; color: inherit; stroke: currentColor; }
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
      .connections { display: flex; flex-wrap: wrap; align-content: flex-start; gap: 0.4rem; }
      .flow { padding: 0.2rem 0.55rem; border-radius: 999px; border: 1px solid var(--sl-color-hairline, #cbd5e1); font-size: 0.78rem; }
      .shell:fullscreen { width: 100vw; height: 100vh; border: 0; border-radius: 0; }
      .shell:fullscreen .stage { height: calc(100vh - 3.5rem); }
      .shell:fullscreen .details.open { position: absolute; inset-inline: 1rem; inset-block-end: 1rem; width: auto; max-height: 13rem; overflow: auto; border: 1px solid var(--sl-color-hairline, #d6e0ec); border-radius: 8px; box-shadow: 0 8px 28px rgb(15 23 42 / 0.24); }
      @media (max-width: 44rem) { .toolbar { gap: 0.1rem; padding: 0.3rem 0.35rem; } button { width: 2.35rem; height: 2.35rem; } .stage { height: min(72vh, 30rem); min-height: 24rem; } .details { grid-template-columns: 1fr; } }
      @media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important; } }
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
      stage.style.aspectRatio = `${contentBounds.width} / ${contentBounds.height}`;
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
      flow.textContent = `${outgoing ? labels.outgoing : labels.incoming}: ${kind} - ${peer?.label[locale] ?? peerId}`;
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
