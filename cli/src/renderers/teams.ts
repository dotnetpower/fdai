/**
 * Teams renderer: `Block[] -> Adaptive Card`.
 *
 * Same content again, as an Adaptive Card (the surface FDAI uses for HIL
 * approvals - app-shape.instructions.md, Human channel). Decision cards become
 * styled Containers with a FactSet and an ActionSet; tone maps to Adaptive
 * Card's color / container-style enums.
 */

import type { Block, RiskLevel, Tone } from "../view-model/blocks.js";
import { sparkline } from "./shared/sparkline.js";

type AdaptiveColor =
  | "Default"
  | "Dark"
  | "Light"
  | "Accent"
  | "Good"
  | "Warning"
  | "Attention";
type ContainerStyle = "default" | "emphasis" | "good" | "warning" | "attention";

export interface AdaptiveCard {
  type: "AdaptiveCard";
  $schema: string;
  version: string;
  body: Array<Record<string, unknown>>;
}

function toneColor(tone?: Tone): AdaptiveColor {
  switch (tone) {
    case "good":
      return "Good";
    case "warn":
    case "medium":
      return "Warning";
    case "danger":
    case "high":
      return "Attention";
    case "t0":
    case "t1":
    case "t2":
    case "accent":
      return "Accent";
    default:
      return "Default";
  }
}

function riskStyle(risk: RiskLevel): ContainerStyle {
  return risk === "LOW" ? "good" : risk === "MEDIUM" ? "warning" : "attention";
}

function text(
  value: string,
  opts: Record<string, unknown> = {},
): Record<string, unknown> {
  return { type: "TextBlock", text: value, wrap: true, ...opts };
}

function bar(pct: number, width = 20): string {
  const on = Math.round((pct / 100) * width);
  return "\u2588".repeat(on) + "\u2591".repeat(width - on);
}

export function renderTeams(blocks: readonly Block[]): AdaptiveCard {
  const body: Array<Record<string, unknown>> = [];

  for (const b of blocks) {
    switch (b.type) {
      case "header":
        body.push(text(b.title, { size: "Large", weight: "Bolder" }));
        body.push(text(b.context, { isSubtle: true, spacing: "None" }));
        break;
      case "narration":
        body.push(text(b.text, b.tone === "dim" ? { isSubtle: true } : {}));
        break;
      case "barChart":
        body.push(text(b.title, { weight: "Bolder" }));
        body.push(text(sparkline(b.series), { fontType: "Monospace" }));
        body.push(text(b.caption, { isSubtle: true, spacing: "None" }));
        break;
      case "statBars":
        body.push(text(b.title, { weight: "Bolder" }));
        for (const r of b.rows) {
          body.push(
            text(`${bar(r.pct)}  ${r.pct}%  ${r.label} (${r.sub})`, {
              fontType: "Monospace",
              color: toneColor(r.tone),
              spacing: "None",
            }),
          );
        }
        break;
      case "summary":
        body.push({
          type: "FactSet",
          facts: b.items.map((i) => ({ title: i.label, value: i.value })),
        });
        break;
      case "list":
        body.push(text(b.items.map((i) => `\u2022 ${i}`).join("\n")));
        break;
      case "decisionCard":
        body.push({
          type: "Container",
          style: riskStyle(b.risk),
          bleed: true,
          items: [
            text(`${b.index}/${b.total} \u00b7 ${b.title}`, {
              weight: "Bolder",
            }),
            text(`${b.actionType}  \u00b7  ${b.risk} risk - ${b.chip}`, {
              isSubtle: true,
              spacing: "None",
            }),
            {
              type: "FactSet",
              facts: b.fields.map((f) => ({ title: f.label, value: f.value })),
            },
            {
              type: "ActionSet",
              actions: b.actions.map((a) => {
                const breakGlass =
                  a.sideEffect === "approve" &&
                  (b.risk === "HIGH" || b.chipSideEffect === "breakglass");
                return {
                  type: "Action.Submit",
                  title: a.label,
                  data: { key: a.key, reference: b.reference },
                  ...(a.sideEffect === "breakglass" || breakGlass
                    ? { style: "destructive" }
                    : a.sideEffect === "approve"
                      ? { style: "positive" }
                      : {}),
                };
              }),
            },
            text(`logged as ${b.reference}`, {
              isSubtle: true,
              spacing: "None",
            }),
          ],
        });
        break;
      case "prompt":
        body.push(
          text(b.hint ? `${b.text}  \u00b7  ${b.hint}` : b.text, {
            isSubtle: true,
          }),
        );
        break;
      case "divider":
        body.push({ type: "TextBlock", text: "", separator: true });
        break;
    }
  }

  return {
    type: "AdaptiveCard",
    $schema: "http://adaptivecards.io/schemas/adaptive-card.json",
    version: "1.5",
    body,
  };
}
