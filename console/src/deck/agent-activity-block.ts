export interface AgentActivityItem {
  readonly agent: string;
  readonly event: string;
  readonly at: string;
}

export interface AgentActivityBlock {
  readonly locale: "en" | "ko";
  readonly items: readonly AgentActivityItem[];
  readonly nextIndex: number;
}

const HEADINGS = new Map<string, "en" | "ko">([
  ["Recorded agent activity:", "en"],
  ["기록된 에이전트 활동:", "ko"],
]);
const EN_ITEM = /^-\s+([A-Za-z][A-Za-z0-9_-]{0,63}):\s+([a-z][a-z0-9_.-]{0,127})\s+at\s+(\S{1,64})$/;
const KO_ITEM = /^-\s+([A-Za-z][A-Za-z0-9_-]{0,63}):\s+(\S{1,64})에\s+([a-z][a-z0-9_.-]{0,127})\s+기록$/;

export function parseAgentActivityBlock(
  lines: readonly string[],
  startIndex: number,
): AgentActivityBlock | null {
  const locale = HEADINGS.get((lines[startIndex] ?? "").trim());
  if (!locale) return null;

  const items: AgentActivityItem[] = [];
  let index = startIndex + 1;
  while (index < lines.length && (lines[index] ?? "").trim() === "") index += 1;
  while (index < lines.length && items.length < 16) {
    const match = (lines[index] ?? "").trim().match(locale === "en" ? EN_ITEM : KO_ITEM);
    if (!match) break;
    const agent = match[1] ?? "";
    const event = (locale === "en" ? match[2] : match[3]) ?? "";
    const at = (locale === "en" ? match[3] : match[2]) ?? "";
    if (!Number.isFinite(Date.parse(at))) return null;
    items.push({ agent, event, at });
    index += 1;
  }
  return items.length > 0 ? { locale, items, nextIndex: index } : null;
}
