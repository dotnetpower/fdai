/**
 * Slack renderer: `Block[] -> Block Kit message`.
 *
 * Same content as the CLI, expressed in Slack's Block Kit. A multi-row ASCII
 * chart does not belong in Slack, so the `barChart` block becomes a sparkline
 * in a code span; decision cards become a section + fields + buttons. Tone maps
 * to Slack's limited affordances (button style, emoji).
 */

import type { Block, SideEffectClass, Tone } from "../view-model/blocks.js";
import { sparkline } from "./shared/sparkline.js";

// Block Kit is loosely typed here on purpose - this mock emits JSON, it does
// not depend on the Slack SDK.
export interface SlackMessage {
  blocks: Array<Record<string, unknown>>;
}

function section(text: string): Record<string, unknown> {
  return { type: "section", text: { type: "mrkdwn", text } };
}
function context(text: string): Record<string, unknown> {
  return { type: "context", elements: [{ type: "mrkdwn", text }] };
}
const divider = (): Record<string, unknown> => ({ type: "divider" });

function toneEmoji(tone?: Tone): string {
  switch (tone) {
    case "good":
      return ":large_green_circle:";
    case "warn":
    case "medium":
      return ":large_orange_circle:";
    case "danger":
    case "high":
      return ":red_circle:";
    case "low":
      return ":white_circle:";
    default:
      return "";
  }
}

function buttonStyle(se: SideEffectClass): "primary" | "danger" | undefined {
  if (se === "approve") return "primary";
  if (se === "breakglass") return "danger";
  return undefined;
}

function bar(pct: number, width = 20): string {
  const on = Math.round((pct / 100) * width);
  return "\u2588".repeat(on) + "\u2591".repeat(width - on);
}

export function renderSlack(blocks: readonly Block[]): SlackMessage {
  const out: Array<Record<string, unknown>> = [];

  for (const b of blocks) {
    switch (b.type) {
      case "header":
        out.push({
          type: "header",
          text: { type: "plain_text", text: b.title, emoji: true },
        });
        out.push(context(`${b.version}  \u00b7  ${b.context}`));
        out.push(divider());
        break;
      case "narration":
        out.push(section(b.text));
        break;
      case "barChart":
        out.push(section(`*${b.title}*`));
        out.push(section("`" + sparkline(b.series) + "`"));
        out.push(context(b.caption));
        break;
      case "statBars":
        out.push(section(`*${b.title}*`));
        out.push(
          section(
            b.rows
              .map(
                (r) =>
                  `${r.label} _(${r.sub})_\n\`${bar(r.pct)}\` ${r.pct}%`,
              )
              .join("\n"),
          ),
        );
        break;
      case "summary":
        out.push(
          context(
            b.items
              .map((i) => `${toneEmoji(i.tone)} *${i.value}* ${i.label}`.trim())
              .join("   \u00b7   "),
          ),
        );
        break;
      case "list":
        out.push(section(b.items.map((i) => `\u2022 ${i}`).join("\n")));
        break;
      case "decisionCard": {
        out.push(divider());
        out.push(
          section(
            `${toneEmoji(riskTone(b.risk))} *${b.index}/${b.total} \u00b7 ${b.title}*  \`${b.actionType}\`\n${b.risk} risk - ${b.chip}`,
          ),
        );
        out.push({
          type: "section",
          fields: b.fields.map((f) => ({
            type: "mrkdwn",
            text: `*${f.label}*\n${f.value}`,
          })),
        });
        out.push({
          type: "actions",
          elements: b.actions.map((a) => {
            const el: Record<string, unknown> = {
              type: "button",
              text: { type: "plain_text", text: a.label, emoji: true },
              action_id: `${a.key}:${b.reference}`,
            };
            // A break-glass / HIGH-risk approval is dangerous - surface that.
            const breakGlass =
              a.sideEffect === "approve" &&
              (b.risk === "HIGH" || b.chipSideEffect === "breakglass");
            const style = breakGlass ? "danger" : buttonStyle(a.sideEffect);
            if (style) el.style = style;
            return el;
          }),
        });
        out.push(context(`logged as ${b.reference}`));
        break;
      }
      case "prompt":
        out.push(context(b.hint ? `${b.text}  \u00b7  ${b.hint}` : b.text));
        break;
      case "divider":
        out.push(divider());
        break;
    }
  }

  return { blocks: out };
}

function riskTone(risk: "LOW" | "MEDIUM" | "HIGH"): Tone {
  return risk === "LOW" ? "low" : risk === "MEDIUM" ? "medium" : "high";
}
