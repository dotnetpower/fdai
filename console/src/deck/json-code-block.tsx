import { t } from "../i18n";
import { CodeBlock } from "./rich-content";

export interface FormattedJsonValue {
  readonly text: string;
  readonly isJson: boolean;
}

export function formatJsonValue(value: unknown): FormattedJsonValue {
  if (typeof value !== "string") {
    if (typeof value !== "object" || value === null) {
      return { text: String(value), isJson: false };
    }
    return { text: JSON.stringify(value, null, 2), isJson: true };
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
    return { text: JSON.stringify(parsed, null, 2), isJson: true };
  } catch {
    return { text: value, isJson: false };
  }
}

export function JsonCodeBlock({ value }: { readonly value: unknown }) {
  const formatted = formatJsonValue(value);
  if (formatted.isJson) {
    return <CodeBlock lang="json" code={formatted.text} pending={false}
      copyLabel={t("deck.rich.copyJson")} />;
  }
  return <pre><code>{formatted.text}</code></pre>;
}
