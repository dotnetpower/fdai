import { StatusPill } from "../components/ui";
import { displayValue, type RenderedWidget } from "./processes.model";
import { asRows, finiteNumber } from "./process-view-widget-utils";

export const CONTENT_WIDGET_TYPES = new Set([
  "free_text",
  "note",
  "image",
  "hostmap",
  "geomap",
]);

const RASTER_EXTENSION = /\.(?:png|jpe?g|gif|webp|avif)$/i;

export function safeRasterImageSrc(value: unknown): string | null {
  if (typeof value !== "string" || value.trim().length === 0) return null;
  const source = value.trim();
  try {
    const url = new URL(source, "https://console.invalid");
    if (url.protocol !== "https:" || url.username || url.password) return null;
    if (!RASTER_EXTENSION.test(url.pathname)) return null;
    return source;
  } catch {
    return null;
  }
}

export function ContentWidget({ widget }: { readonly widget: RenderedWidget }) {
  if (widget.type === "free_text") return <FreeTextWidget widget={widget} />;
  if (widget.type === "note") return <NoteWidget widget={widget} />;
  if (widget.type === "image") return <ImageWidget widget={widget} />;
  if (widget.type === "hostmap") return <HostmapWidget widget={widget} />;
  return <GeomapWidget widget={widget} />;
}

function FreeTextWidget({ widget }: { readonly widget: RenderedWidget }) {
  const body = displayValue(widget.data["body"]);
  return <section class="process-widget-section report-prose" aria-labelledby={`${widget.id}-title`}><h3 id={`${widget.id}-title`}>{widget.title}</h3><div>{body}</div></section>;
}

function NoteWidget({ widget }: { readonly widget: RenderedWidget }) {
  const severity = noteSeverity(displayValue(widget.data["severity"]));
  const alert = severity === "critical" || severity === "warning";
  return <section class={`process-widget-section report-note is-${severity}`} role={alert ? "alert" : "status"} aria-labelledby={`${widget.id}-title`}><div class="report-summary-head"><h3 id={`${widget.id}-title`}>{widget.title}</h3><StatusPill kind={noteTone(severity)} label={severity} /></div><p>{displayValue(widget.data["body"])}</p></section>;
}

function ImageWidget({ widget }: { readonly widget: RenderedWidget }) {
  const source = safeRasterImageSrc(widget.data["src"]);
  const alt = typeof widget.data["alt"] === "string" ? widget.data["alt"] : "";
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><h3 id={`${widget.id}-title`}>{widget.title}</h3>{source ? <figure class="report-image"><img src={source} alt={alt} loading="lazy" decoding="async" referrerPolicy="no-referrer" />{widget.data["caption"] === undefined ? null : <figcaption>{displayValue(widget.data["caption"])}</figcaption>}</figure> : <p class="state-unavailable">The image source is missing or blocked by the raster URL policy.</p>}</section>;
}

function HostmapWidget({ widget }: { readonly widget: RenderedWidget }) {
  const tiles = asRows(widget.data["tiles"]);
  const values = tiles.map((tile) => finiteNumber(tile["value"])).filter((value): value is number => value !== null);
  const minimum = values.length > 0 ? Math.min(...values) : 0;
  const maximum = values.length > 0 ? Math.max(...values) : 1;
  const range = maximum - minimum || 1;
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><h3 id={`${widget.id}-title`}>{widget.title}</h3><div class="report-hostmap">{tiles.map((tile, index) => {
    const value = finiteNumber(tile["value"]);
    const intensity = value === null ? 0 : Math.max(0, Math.min(1, (value - minimum) / range));
    return <article key={`${displayValue(tile["host"])}-${index}`} style={{ "--cell-intensity": intensity }}><span>{displayValue(tile["group"])}</span><strong>{displayValue(tile["host"])}</strong><small>{displayValue(tile["value"])}</small></article>;
  })}</div>{tiles.length === 0 ? <p class="muted small">No hosts.</p> : null}</section>;
}

function GeomapWidget({ widget }: { readonly widget: RenderedWidget }) {
  const points = asRows(widget.data["points"]);
  const areas = asRows(widget.data["areas"]);
  return <section class="process-widget-section" aria-labelledby={`${widget.id}-title`}><h3 id={`${widget.id}-title`}>{widget.title}</h3><p class="muted small">Geographic evidence is shown as an accessible coordinate and region table. No remote map script is loaded.</p><div class="report-geo-grid"><table class="data-table"><caption>Points</caption><thead><tr><th scope="col">Label</th><th scope="col">Latitude</th><th scope="col">Longitude</th><th scope="col">Value</th></tr></thead><tbody>{points.map((point, index) => <tr key={index}><td>{displayValue(point["label"])}</td><td>{displayValue(point["lat"])}</td><td>{displayValue(point["lon"])}</td><td>{displayValue(point["value"])}</td></tr>)}</tbody></table><table class="data-table"><caption>Regions</caption><thead><tr><th scope="col">Region</th><th scope="col">Value</th></tr></thead><tbody>{areas.map((area, index) => <tr key={index}><td>{displayValue(area["region"])}</td><td>{displayValue(area["value"])}</td></tr>)}</tbody></table></div>{points.length + areas.length === 0 ? <p class="muted small">No geographic records.</p> : null}</section>;
}

function noteSeverity(value: string): "info" | "warning" | "critical" | "ok" {
  return value === "warning" || value === "critical" || value === "ok" ? value : "info";
}

function noteTone(value: "info" | "warning" | "critical" | "ok"): "neutral" | "warning" | "danger" | "success" {
  if (value === "critical") return "danger";
  if (value === "warning") return "warning";
  if (value === "ok") return "success";
  return "neutral";
}
