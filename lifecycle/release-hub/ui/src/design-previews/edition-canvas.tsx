import { useRef } from "preact/hooks";
import { buildConnectorGeometry, CARD_WIDTH } from "../release-lineage.geometry";
import { RELEASE_EXAMPLES, type ReleaseExample } from "./data";
import { Status } from "../../../../hub/ui/src/design-previews/shell";
import "./edition-canvas.css";

type EditionNode = { id: string; x: number; y: number; parent?: string };

// Fixed illustrative relationships, not an observed catalog lineage.
export const EDITION_NODES: readonly EditionNode[] = [
  { id: "0.5.1", x: 42, y: 150 },
  { id: "0.5.2", x: 270, y: 150, parent: "0.5.1" },
  { id: "0.5.3", x: 540, y: 46, parent: "0.5.2" },
  { id: "0.5.4", x: 540, y: 246, parent: "0.5.2" },
];

export function EditionCanvas({ release, onRelease, onHighlight }: {
  release: ReleaseExample;
  onRelease: (item: ReleaseExample) => void;
  onHighlight: (item: ReleaseExample) => void;
}) {
  const mapRef = useRef<HTMLDivElement>(null);
  const releases = RELEASE_EXAMPLES.records;

  function navigate(event: KeyboardEvent, index: number) {
    const nextIndex = event.key === "Home" ? 0
      : event.key === "End" ? EDITION_NODES.length - 1
      : event.key === "ArrowRight" || event.key === "ArrowDown" ? index + 1
      : event.key === "ArrowLeft" || event.key === "ArrowUp" ? index - 1 : null;
    if (nextIndex === null) return;
    event.preventDefault();
    const clamped = Math.max(0, Math.min(EDITION_NODES.length - 1, nextIndex));
    const target = mapRef.current?.querySelectorAll<HTMLButtonElement>(".dp-edition-node")[clamped];
    target?.focus();
    const nextRelease = releases.find((item) => item.id === EDITION_NODES[clamped]?.id);
    if (nextRelease) onHighlight(nextRelease);
  }

  return <section class="dp-edition-canvas" aria-label="예시 릴리스 노드 캔버스">
    <div class="dp-edition-canvas-head">
      <h2>릴리스 계통</h2>
      <span class="dp-edition-caption" role="status">v{release.id} · {release.edition}</span>
    </div>
    <div class="dp-edition-scroll" role="region" aria-label="릴리스 버전 계통 캔버스, 가로로 스크롤 가능" tabIndex={0}>
      <div ref={mapRef} class="dp-edition-map">
        <div class="dp-edition-map-labels" aria-hidden="true"><span>ORIGIN / 01</span><span>RELEASE / 02</span><span>NEXT / 03</span></div>
        <svg class="dp-edition-lines" width="790" height="398" viewBox="0 0 790 398" aria-hidden="true">
          {EDITION_NODES.filter((node) => node.parent).map((node) => {
            const parent = EDITION_NODES.find((item) => item.id === node.parent)!;
            const { pathD, arrowD, portCx, portCy } = buildConnectorGeometry({
              startX: parent.x + CARD_WIDTH,
              startY: parent.y + 54,
              endX: node.x,
              endY: node.y + 54,
            });
            return <g key={node.id} class={node.id === release.id ? "is-current" : ""}>
              <path d={pathD} /><circle cx={portCx} cy={portCy} r="3.5" /><path d={arrowD} />
            </g>;
          })}
        </svg>
        {EDITION_NODES.map((node, index) => {
          const item = releases.find((candidate) => candidate.id === node.id);
          if (!item) throw new Error(`Missing Edition example: ${node.id}`);
          return <button key={node.id} type="button" class="dp-edition-node"
            style={{ left: node.x, top: node.y }}
            aria-label={`예시 릴리스 ${item.id}, ${item.title}, ${item.channel}`}
            aria-pressed={release.id === item.id} aria-controls="release-detail"
            onClick={() => onRelease(item)} onKeyDown={(event) => navigate(event, index)}>
            <span class="dp-edition-node-meta">{item.channel === "RELEASE_CANDIDATE" ? "RC" : item.channel}<span aria-hidden="true">↗</span></span>
            <strong>v{item.id}</strong>
            <span class="dp-edition-node-title">{item.title}</span>
            <Status value={item.status} />
          </button>;
        })}
      </div>
    </div>
  </section>;
}
