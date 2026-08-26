import { t } from "../i18n";
import { CodeBlock } from "./rich-content";

export interface FormattedJsonValue {
  readonly text: string;
  readonly isJson: boolean;
}

export interface JsonFormatOptions {
  readonly expandNestedStrings?: boolean;
}

const MAX_NESTED_JSON_DEPTH = 6;
const MAX_NESTED_JSON_NODES = 1024;

export function formatJsonValue(
  value: unknown,
  options: JsonFormatOptions = {},
): FormattedJsonValue {
  if (typeof value !== "string") {
    if (typeof value !== "object" || value === null) {
      return { text: String(value), isJson: false };
    }
    return {
      text: JSON.stringify(
        options.expandNestedStrings ? expandNestedJsonStrings(value) : value,
        null,
        2,
      ),
      isJson: true,
    };
  }
  const trimmed = value.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) {
    return { text: value, isJson: false };
  }
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (typeof parsed !== "object" || parsed === null) {
      return { text: value, isJson: false };
    }
    return {
      text: JSON.stringify(
        options.expandNestedStrings ? expandNestedJsonStrings(parsed) : parsed,
        null,
        2,
      ),
      isJson: true,
    };
  } catch {
    return { text: value, isJson: false };
  }
}

export function JsonCodeBlock({
  value,
  expandNestedStrings = false,
}: {
  readonly value: unknown;
  readonly expandNestedStrings?: boolean;
}) {
  const formatted = formatJsonValue(value, { expandNestedStrings });
  if (formatted.isJson) {
    return <CodeBlock lang="json" code={formatted.text} pending={false}
      copyLabel={t("deck.rich.copyJson")} />;
  }
  return <pre><code>{formatted.text}</code></pre>;
}

function expandNestedJsonStrings(value: unknown): unknown {
  const state = { nodes: 0 };
  return expandNestedJsonValue(value, 0, state);
}

function expandNestedJsonValue(
  value: unknown,
  depth: number,
  state: { nodes: number },
): unknown {
  state.nodes += 1;
  if (state.nodes > MAX_NESTED_JSON_NODES || depth >= MAX_NESTED_JSON_DEPTH) return value;
  if (typeof value === "string") {
    const parsed = parseNestedJsonString(value);
    return parsed === null ? value : expandNestedJsonValue(parsed, depth + 1, state);
  }
  if (Array.isArray(value)) {
    return value.map((item) => expandNestedJsonValue(item, depth + 1, state));
  }
  if (typeof value === "object" && value !== null) {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        expandNestedJsonValue(item, depth + 1, state),
      ]),
    );
  }
  return value;
}

function parseNestedJsonString(value: string): object | readonly unknown[] | null {
  const trimmed = value.trim();
  if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return null;
  try {
    const parsed: unknown = JSON.parse(trimmed);
    return typeof parsed === "object" && parsed !== null ? parsed : null;
  } catch {
    return null;
  }
}
