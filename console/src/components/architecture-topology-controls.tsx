import { Tooltip } from "./tooltip";
import { t } from "../routes/i18n/architecture";
import {
  ARCHITECTURE_TOPOLOGY_MAX_SCALE,
  ARCHITECTURE_TOPOLOGY_MIN_SCALE,
} from "./architecture-topology-graph.model";

interface Props {
  readonly scale: number;
  readonly fullscreen: boolean;
  readonly allowFullscreen: boolean;
  readonly onZoomOut: () => void;
  readonly onZoomIn: () => void;
  readonly onFit: () => void;
  readonly onToggleFullscreen: () => void;
}

/** Presents bounded topology viewport controls without owning graph state. */
export function ArchitectureTopologyControls({
  scale,
  fullscreen,
  allowFullscreen,
  onZoomOut,
  onZoomIn,
  onFit,
  onToggleFullscreen,
}: Props) {
  return (
    <div class="architecture-topology-tools" aria-label={t("graphControls")}>
      <Tooltip content={t("zoomOut")}>
        <button
          type="button"
          aria-label={t("zoomOut")}
          disabled={scale <= ARCHITECTURE_TOPOLOGY_MIN_SCALE}
          onClick={onZoomOut}
        >
          -
        </button>
      </Tooltip>
      <output aria-label={t("zoomLevel")}>{Math.round(scale * 100)}%</output>
      <Tooltip content={t("zoomIn")}>
        <button
          type="button"
          aria-label={t("zoomIn")}
          disabled={scale >= ARCHITECTURE_TOPOLOGY_MAX_SCALE}
          onClick={onZoomIn}
        >
          +
        </button>
      </Tooltip>
      <Tooltip content={t("fitMap")}>
        <button type="button" aria-label={t("fitMap")} onClick={onFit}>
          {t("fit")}
        </button>
      </Tooltip>
      {allowFullscreen ? (
        <Tooltip content={t(fullscreen ? "exitFullscreen" : "fullscreen")}>
          <button
            type="button"
            aria-label={t(fullscreen ? "exitFullscreen" : "fullscreen")}
            aria-pressed={fullscreen}
            onClick={onToggleFullscreen}
          >
            {fullscreen ? "Exit" : "Full"}
          </button>
        </Tooltip>
      ) : null}
    </div>
  );
}
