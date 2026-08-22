import { Tooltip } from "./tooltip";
import {
  TREMOR_CHART_HEX,
  tremorChartColor,
  type TremorChartColor,
} from "./chart-colors";

export interface ScatterChartPoint {
  readonly label: string;
  readonly x: number;
  readonly y: number;
  readonly group?: string;
  readonly color?: TremorChartColor;
  readonly detail?: string;
}

interface ScatterChartProps {
  readonly label: string;
  readonly points: readonly ScatterChartPoint[];
  readonly formatX: (value: number) => string;
  readonly formatY: (value: number) => string;
}

const WIDTH = 360;
const HEIGHT = 180;
const PAD_X = 28;
const PAD_Y = 20;

export function ScatterChart({ label, points, formatX, formatY }: ScatterChartProps) {
  const finite = points.filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
  if (finite.length === 0) return null;
  const xs = finite.map((point) => point.x);
  const ys = finite.map((point) => point.y);
  const minimumX = Math.min(...xs);
  const maximumX = Math.max(...xs);
  const minimumY = Math.min(...ys);
  const maximumY = Math.max(...ys);
  const rangeX = Math.max(1, maximumX - minimumX);
  const rangeY = Math.max(1, maximumY - minimumY);
  const x = (value: number) => PAD_X + (value - minimumX) / rangeX * (WIDTH - PAD_X * 2);
  const y = (value: number) => HEIGHT - PAD_Y - (value - minimumY) / rangeY * (HEIGHT - PAD_Y * 2);
  const groups = [...new Set(finite.map((point) => point.group ?? "default"))];

  return (
    <div class="fd-scatter-chart" role="group" aria-label={label}>
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} aria-hidden="true" preserveAspectRatio="none">
        <path class="fd-chart-grid" d={`M${PAD_X} ${PAD_Y}V${HEIGHT - PAD_Y}H${WIDTH - PAD_X} M${PAD_X} ${HEIGHT / 2}H${WIDTH - PAD_X} M${WIDTH / 2} ${PAD_Y}V${HEIGHT - PAD_Y}`} />
        {finite.map((point, index) => {
          const groupIndex = groups.indexOf(point.group ?? "default");
          const color = TREMOR_CHART_HEX[point.color ?? tremorChartColor(groupIndex)];
          return <circle key={`${point.label}-${index}`} cx={x(point.x)} cy={y(point.y)} r="4" fill={color} />;
        })}
      </svg>
      {finite.map((point, index) => {
        const groupIndex = groups.indexOf(point.group ?? "default");
        const color = TREMOR_CHART_HEX[point.color ?? tremorChartColor(groupIndex)];
        const accessible = `${point.label}: x ${formatX(point.x)}, y ${formatY(point.y)}${point.group ? `, ${point.group}` : ""}${point.detail ? `. ${point.detail}` : ""}`;
        return (
          <Tooltip key={`${point.label}-${index}`} content={accessible} placement="top">
            <button
              type="button"
              aria-label={accessible}
              style={{
                "--series-color": color,
                "--scatter-x": `${x(point.x) / WIDTH * 100}%`,
                "--scatter-y": `${y(point.y) / HEIGHT * 100}%`,
              }}
            />
          </Tooltip>
        );
      })}
    </div>
  );
}
