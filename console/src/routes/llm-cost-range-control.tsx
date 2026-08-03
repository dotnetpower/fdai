import { useState } from "preact/hooks";
import { getLocale } from "../i18n";
import { t } from "./i18n/llm-cost";
import {
  customLlmUsageRange,
  llmUsageRangeInputDates,
  llmUsageRangeLabel,
  presetLlmUsageRange,
  type LlmUsageRange,
  type LlmUsageRangePreset,
} from "./llm-cost-range";

interface Props {
  readonly range: LlmUsageRange;
  readonly onChange: (range: LlmUsageRange) => void;
}

const PRESETS: readonly Exclude<LlmUsageRangePreset, "custom">[] = ["24h", "7d", "30d"];

export function LlmCostRangeControl({ range, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const [fromDate, setFromDate] = useState(() => llmUsageRangeInputDates(range).fromDate);
  const [toDate, setToDate] = useState(() => llmUsageRangeInputDates(range).toDate);
  const [error, setError] = useState("");
  const locale = getLocale() === "ko" ? "ko-KR" : "en-US";
  const today = new Date().toISOString().slice(0, 10);

  const choosePreset = (preset: Exclude<LlmUsageRangePreset, "custom">) => {
    setOpen(false);
    setError("");
    onChange(presetLlmUsageRange(preset, new Date()));
  };
  const openCustom = () => {
    const dates = llmUsageRangeInputDates(range);
    setFromDate(dates.fromDate);
    setToDate(dates.toDate);
    setError("");
    setOpen(true);
  };
  const applyCustom = () => {
    const next = customLlmUsageRange(fromDate, toDate);
    if (next === null) {
      setError(t("llmCost.invalidRange"));
      return;
    }
    setOpen(false);
    setError("");
    onChange(next);
  };

  return (
    <section
      class="llm-cost-range"
      aria-label={t("llmCost.dateRange")}
      onKeyDown={(event) => {
        if (event.key === "Escape") setOpen(false);
      }}
    >
      <div class="llm-cost-range-copy">
        <strong>{t("llmCost.dateRange")}</strong>
        <span aria-live="polite">{llmUsageRangeLabel(range, locale)}</span>
      </div>
      <div class="llm-cost-range-controls">
        <div class="llm-cost-segmented" role="group" aria-label={t("llmCost.rangePresets")}>
          {PRESETS.map((preset) => (
            <button
              class={`llm-cost-range-option${range.preset === preset ? " is-active" : ""}`}
              type="button"
              aria-pressed={range.preset === preset}
              onClick={() => choosePreset(preset)}
            >
              {preset}
            </button>
          ))}
          <button
            class={`llm-cost-range-option${range.preset === "custom" ? " is-active" : ""}`}
            type="button"
            aria-pressed={range.preset === "custom"}
            aria-expanded={open}
            onClick={openCustom}
          >
            {t("llmCost.custom")}
          </button>
        </div>
        <span class="llm-cost-timezone">UTC</span>
        {open ? (
          <div class="llm-cost-range-popover">
            <div class="llm-cost-date-fields">
              <label>
                <span>{t("llmCost.startDate")}</span>
                <input
                  type="date"
                  value={fromDate}
                  max={today}
                  aria-invalid={error !== ""}
                  onInput={(event) => setFromDate(event.currentTarget.value)}
                />
              </label>
              <label>
                <span>{t("llmCost.endDate")}</span>
                <input
                  type="date"
                  value={toDate}
                  max={today}
                  aria-invalid={error !== ""}
                  onInput={(event) => setToDate(event.currentTarget.value)}
                />
              </label>
            </div>
            <p class="llm-cost-range-error" role="alert">{error}</p>
            <div class="llm-cost-range-actions">
              <button type="button" onClick={() => setOpen(false)}>{t("llmCost.cancel")}</button>
              <button class="is-primary" type="button" onClick={applyCustom}>{t("llmCost.apply")}</button>
            </div>
          </div>
        ) : null}
      </div>
    </section>
  );
}
