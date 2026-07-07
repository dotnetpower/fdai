/**
 * Ink (terminal) renderer: `Block[] -> React tree`.
 *
 * The richest surface. Each block type is one small component; tone becomes a
 * hex color via `theme.ts`. This file holds only presentation - all wording and
 * ordering come from the shared view-model.
 */

import { Box, Text } from "ink";

import type { Block, RiskLevel, Tone } from "../../view-model/blocks.js";
import { asciiBarChart } from "../shared/ascii-chart.js";
import { toneHex } from "./theme.js";

const CARD_WIDTH = 78;

function riskTone(risk: RiskLevel): Tone {
  return risk === "LOW" ? "low" : risk === "MEDIUM" ? "medium" : "high";
}

function Header({ title, version, context }: { title: string; version: string; context: string }) {
  return (
    <Box flexDirection="column" marginBottom={1}>
      <Box>
        <Text color={toneHex("t0")} bold>
          {title}
        </Text>
        <Text color={toneHex("dim")}>{`  ${version}`}</Text>
      </Box>
      <Text color={toneHex("dim")}>{context}</Text>
    </Box>
  );
}

function Narration({ text, tone }: { text: string; tone?: Tone }) {
  return (
    <Box marginBottom={1} width={CARD_WIDTH}>
      <Text>
        <Text color={toneHex("accent")}>{"\u25c7"}</Text>
        {" "}
        <Text color={toneHex(tone)}>{text}</Text>
      </Text>
    </Box>
  );
}

function BarChart({
  series,
  axisLabels,
  caption,
  tone,
}: {
  series: readonly number[];
  axisLabels: ReadonlyArray<{ at: number; text: string }>;
  caption: string;
  tone: Tone;
}) {
  const chart = asciiBarChart(series, axisLabels);
  const barColor = toneHex(tone);
  const dim = toneHex("dim");
  return (
    <Box flexDirection="column" marginBottom={1}>
      {chart.rows.map((r, i) => (
        <Box key={i}>
          <Text color={dim}>{r.gutter}</Text>
          <Text color={barColor}>{r.bars}</Text>
        </Box>
      ))}
      <Text color={dim}>{chart.axis}</Text>
      <Text color={dim}>{`${chart.labels}   (hour, UTC)`}</Text>
      <Text color={dim}>{`  ${caption}`}</Text>
    </Box>
  );
}

function StatBars({
  rows,
}: {
  rows: ReadonlyArray<{ label: string; sub?: string; pct: number; tone: Tone }>;
}) {
  const width = 22;
  const dim = toneHex("dim");
  return (
    <Box flexDirection="column" marginBottom={1}>
      {rows.map((r, i) => {
        const on = Math.round((r.pct / 100) * width);
        const label = `${r.label} (${r.sub})`.padEnd(30);
        return (
          <Box key={i}>
            <Text color={dim}>{`  ${label} `}</Text>
            <Text color={toneHex(r.tone)}>{"\u2588".repeat(on)}</Text>
            <Text color={dim}>{"\u2591".repeat(width - on)}</Text>
            <Text color={dim}>{`  ${String(r.pct).padStart(3)}%`}</Text>
          </Box>
        );
      })}
    </Box>
  );
}

function Summary({
  items,
}: {
  items: ReadonlyArray<{ label: string; value: string; tone?: Tone }>;
}) {
  const dim = toneHex("dim");
  return (
    <Box marginBottom={1} borderStyle="round" borderColor={toneHex("dim")} paddingX={1}>
      <Text>
        {items.map((it, i) => (
          <Text key={i}>
            {i > 0 ? <Text color={dim}>{"  \u00b7  "}</Text> : null}
            <Text color={dim}>{`${it.label} `}</Text>
            <Text color={toneHex(it.tone)} bold>
              {it.value}
            </Text>
          </Text>
        ))}
      </Text>
    </Box>
  );
}

function List({ items, tone }: { items: readonly string[]; tone?: Tone }) {
  const dim = toneHex("dim");
  return (
    <Box flexDirection="column" marginBottom={1}>
      {items.map((it, i) => (
        <Box key={i}>
          <Text color={dim}>{"   \u2022 "}</Text>
          <Text color={toneHex(tone)}>{it}</Text>
        </Box>
      ))}
    </Box>
  );
}

function KeyBadge({ k, tone }: { k: string; tone: Tone }) {
  return (
    <Text backgroundColor={toneHex(tone)} color="#0E1216" bold>
      {` ${k} `}
    </Text>
  );
}

function DecisionCard({ block }: { block: Extract<Block, { type: "decisionCard" }> }) {
  const tone = riskTone(block.risk);
  const dim = toneHex("dim");
  const actionTone: Record<string, Tone> = { a: "good", r: "danger", w: "t1" };
  return (
    <Box
      flexDirection="column"
      marginBottom={1}
      width={CARD_WIDTH}
      borderStyle="round"
      borderColor={toneHex(tone)}
      paddingX={1}
    >
      <Box justifyContent="space-between">
        <Box flexShrink={1} marginRight={1}>
          <Text bold>{`${block.index}/${block.total} \u00b7 ${block.title}`}</Text>
        </Box>
        <Text color={toneHex(tone)} bold>
          {`${block.risk} risk`}
        </Text>
      </Box>
      <Text color={dim}>{block.actionType}</Text>
      <Text color={toneHex(tone)}>{block.chip}</Text>
      <Box flexDirection="column" marginTop={1}>
        {block.fields.map((f, i) => (
          <Box key={i}>
            <Box width={12} flexShrink={0}>
              <Text color={dim}>{f.label}</Text>
            </Box>
            <Box flexGrow={1}>
              <Text>{f.value}</Text>
            </Box>
          </Box>
        ))}
      </Box>
      <Box marginTop={1}>
        {block.actions.map((a, i) => (
          <Box key={i}>
            <KeyBadge k={a.key} tone={actionTone[a.key] ?? "dim"} />
            <Text>{` ${a.label}   `}</Text>
          </Box>
        ))}
      </Box>
      <Text color={dim}>{`logged as ${block.reference}`}</Text>
    </Box>
  );
}

function Prompt({ text, hint }: { text: string; hint?: string }) {
  const dim = toneHex("dim");
  return (
    <Box flexDirection="column">
      <Box>
        <Text color={toneHex("t0")}>{"\u203a "}</Text>
        <Text color={dim}>{text}</Text>
      </Box>
      {hint ? <Text color={dim}>{`  (${hint})`}</Text> : null}
    </Box>
  );
}

export function BlockView({ block }: { block: Block }) {
  switch (block.type) {
    case "header":
      return <Header title={block.title} version={block.version} context={block.context} />;
    case "narration":
      return <Narration text={block.text} tone={block.tone} />;
    case "barChart":
      return (
        <BarChart
          series={block.series}
          axisLabels={block.axisLabels}
          caption={block.caption}
          tone={block.tone}
        />
      );
    case "statBars":
      return <StatBars rows={block.rows} />;
    case "summary":
      return <Summary items={block.items} />;
    case "list":
      return <List items={block.items} tone={block.tone} />;
    case "decisionCard":
      return <DecisionCard block={block} />;
    case "prompt":
      return <Prompt text={block.text} hint={block.hint} />;
    case "divider":
      return <Text color={toneHex("dim")}>{"\u2500".repeat(CARD_WIDTH)}</Text>;
    default:
      return null;
  }
}
