import type { ComponentChildren, JSX, RefObject } from "preact";
import { useId } from "preact/hooks";

export interface SelectOption {
  readonly value: string;
  readonly label: string;
  readonly disabled?: boolean;
}

export interface SelectOptionGroup {
  readonly label: string;
  readonly options: readonly SelectOption[];
}

export interface SelectFieldProps {
  readonly id?: string;
  readonly label: string;
  readonly hideLabel?: boolean;
  readonly value: string;
  readonly options?: readonly SelectOption[];
  readonly groups?: readonly SelectOptionGroup[];
  readonly onChange: (value: string) => void;
  readonly disabled?: boolean;
  readonly required?: boolean;
  readonly error?: string;
  readonly hint?: string;
  readonly size?: "md" | "sm";
  readonly className?: string;
  readonly ariaLabel?: string;
  readonly name?: string;
}

export function SelectField({
  id,
  label,
  hideLabel = false,
  value,
  options,
  groups,
  onChange,
  disabled = false,
  required = false,
  error,
  hint,
  size = "md",
  className,
  ariaLabel,
  name,
}: SelectFieldProps) {
  const autoId = useId();
  const fieldId = id ?? `select-${autoId}`;
  const helpId = error ? `${fieldId}-error` : hint ? `${fieldId}-hint` : undefined;

  return (
    <div class={className ? `cs-field ${className}` : "cs-field"}>
      <label
        for={fieldId}
        class={hideLabel ? "sr-only" : "cs-field-label"}
      >
        <span>{label}</span>
        {required ? <span class="cs-field-required" aria-hidden="true">*</span> : null}
      </label>
      <select
        id={fieldId}
        name={name}
        class={size === "sm" ? "cs-field-select cs-field-select--sm" : "cs-field-select"}
        value={value}
        disabled={disabled}
        required={required}
        aria-label={ariaLabel ?? (hideLabel ? label : undefined)}
        aria-invalid={error ? "true" : undefined}
        aria-describedby={helpId}
        onChange={(event) => onChange((event.currentTarget as HTMLSelectElement).value)}
      >
        {options?.map((opt) => (
          <option key={opt.value} value={opt.value} disabled={opt.disabled}>
            {opt.label}
          </option>
        ))}
        {groups?.map((group) => (
          <optgroup key={group.label} label={group.label}>
            {group.options.map((opt) => (
              <option key={opt.value} value={opt.value} disabled={opt.disabled}>
                {opt.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      {error ? (
        <span id={`${fieldId}-error`} class="cs-field-error" role="alert">
          {error}
        </span>
      ) : hint ? (
        <span id={`${fieldId}-hint`} class="cs-field-hint">
          {hint}
        </span>
      ) : null}
    </div>
  );
}

export interface TextInputProps {
  readonly id?: string;
  readonly type?: "text" | "email" | "url" | "number" | "date" | "datetime-local" | "password";
  readonly label: string;
  readonly hideLabel?: boolean;
  readonly value: string;
  readonly onInput: (value: string) => void;
  readonly placeholder?: string;
  readonly disabled?: boolean;
  readonly required?: boolean;
  readonly readOnly?: boolean;
  readonly min?: string | number;
  readonly max?: string | number;
  readonly step?: string | number;
  readonly maxLength?: number;
  readonly mono?: boolean;
  readonly size?: "md" | "sm";
  readonly error?: string;
  readonly hint?: string;
  readonly className?: string;
  readonly name?: string;
  readonly autoComplete?: string;
  readonly inputRef?: RefObject<HTMLInputElement>;
  readonly onKeyDown?: JSX.KeyboardEventHandler<HTMLInputElement>;
}

export function TextInput({
  id,
  type = "text",
  label,
  hideLabel = false,
  value,
  onInput,
  placeholder,
  disabled = false,
  required = false,
  readOnly = false,
  min,
  max,
  step,
  maxLength,
  mono = false,
  size = "md",
  error,
  hint,
  className,
  name,
  autoComplete,
  inputRef,
  onKeyDown,
}: TextInputProps) {
  const autoId = useId();
  const fieldId = id ?? `input-${autoId}`;
  const helpId = error ? `${fieldId}-error` : hint ? `${fieldId}-hint` : undefined;
  const controlClasses = [
    "cs-field-control",
    size === "sm" ? "cs-field-control--sm" : "",
    mono ? "cs-field-control--mono" : "",
  ].filter(Boolean).join(" ");

  return (
    <div class={className ? `cs-field ${className}` : "cs-field"}>
      <label
        for={fieldId}
        class={hideLabel ? "sr-only" : "cs-field-label"}
      >
        <span>{label}</span>
        {required ? <span class="cs-field-required" aria-hidden="true">*</span> : null}
      </label>
      <input
        {...(inputRef ? { ref: inputRef } : {})}
        id={fieldId}
        name={name}
        type={type}
        class={controlClasses}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        required={required}
        readOnly={readOnly}
        min={min}
        max={max}
        step={step}
        maxLength={maxLength}
        autoComplete={autoComplete}
        aria-label={hideLabel ? label : undefined}
        aria-invalid={error ? "true" : undefined}
        aria-describedby={helpId}
        onKeyDown={onKeyDown}
        onInput={(event) => onInput((event.currentTarget as HTMLInputElement).value)}
      />
      {error ? (
        <span id={`${fieldId}-error`} class="cs-field-error" role="alert">
          {error}
        </span>
      ) : hint ? (
        <span id={`${fieldId}-hint`} class="cs-field-hint">
          {hint}
        </span>
      ) : null}
    </div>
  );
}

export interface SearchInputProps {
  readonly id?: string;
  readonly label: string;
  readonly hideLabel?: boolean;
  readonly value: string;
  readonly onInput: (value: string) => void;
  readonly onClear?: () => void;
  readonly clearLabel?: string;
  readonly placeholder?: string;
  readonly disabled?: boolean;
  readonly maxLength?: number;
  readonly mono?: boolean;
  readonly size?: "md" | "sm";
  readonly error?: string;
  readonly hint?: string;
  readonly className?: string;
  readonly inputRef?: RefObject<HTMLInputElement>;
  readonly onKeyDown?: JSX.KeyboardEventHandler<HTMLInputElement>;
}

export function SearchInput({
  id,
  label,
  hideLabel = false,
  value,
  onInput,
  onClear,
  clearLabel = "Clear search",
  placeholder,
  disabled = false,
  maxLength,
  mono = false,
  size = "md",
  error,
  hint,
  className,
  inputRef,
  onKeyDown,
}: SearchInputProps) {
  const autoId = useId();
  const fieldId = id ?? `search-${autoId}`;
  const helpId = error ? `${fieldId}-error` : hint ? `${fieldId}-hint` : undefined;
  const inputClasses = [
    "cs-field-control",
    "cs-search-input",
    size === "sm" ? "cs-field-control--sm" : "",
    mono ? "cs-field-control--mono" : "",
  ].filter(Boolean).join(" ");

  function handleClear() {
    if (onClear) {
      onClear();
    } else {
      onInput("");
    }
  }

  return (
    <div class={className ? `cs-field ${className}` : "cs-field"}>
      <label
        for={fieldId}
        class={hideLabel ? "sr-only" : "cs-field-label"}
      >
        {label}
      </label>
      <div class="cs-search-wrap">
        <svg
          class="cs-search-icon"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <circle cx="7" cy="7" r="4.8" />
          <path d="M10.7 10.7L14 14" />
        </svg>
        <input
          {...(inputRef ? { ref: inputRef } : {})}
          id={fieldId}
          type="search"
          class={inputClasses}
          value={value}
          placeholder={placeholder}
          disabled={disabled}
          maxLength={maxLength}
          aria-label={hideLabel ? label : undefined}
          aria-invalid={error ? "true" : undefined}
          aria-describedby={helpId}
          onKeyDown={onKeyDown}
          onInput={(event) => onInput((event.currentTarget as HTMLInputElement).value)}
        />
        {value.length > 0 && !disabled ? (
          <button
            type="button"
            class="cs-search-clear"
            aria-label={clearLabel}
            onClick={handleClear}
          >
            <svg
              width="12"
              height="12"
              viewBox="0 0 12 12"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linecap="round"
              aria-hidden="true"
            >
              <path d="M2.5 2.5L9.5 9.5M9.5 2.5L2.5 9.5" />
            </svg>
          </button>
        ) : null}
      </div>
      {error ? (
        <span id={`${fieldId}-error`} class="cs-field-error" role="alert">
          {error}
        </span>
      ) : hint ? (
        <span id={`${fieldId}-hint`} class="cs-field-hint">
          {hint}
        </span>
      ) : null}
    </div>
  );
}

export interface TextareaFieldProps {
  readonly id?: string;
  readonly label: string;
  readonly hideLabel?: boolean;
  readonly value: string;
  readonly onInput: (value: string) => void;
  readonly placeholder?: string;
  readonly rows?: number;
  readonly maxLength?: number;
  readonly showCounter?: boolean;
  readonly disabled?: boolean;
  readonly required?: boolean;
  readonly mono?: boolean;
  readonly error?: string;
  readonly hint?: string;
  readonly className?: string;
  readonly name?: string;
}

export function TextareaField({
  id,
  label,
  hideLabel = false,
  value,
  onInput,
  placeholder,
  rows = 3,
  maxLength,
  showCounter = false,
  disabled = false,
  required = false,
  mono = false,
  error,
  hint,
  className,
  name,
}: TextareaFieldProps) {
  const autoId = useId();
  const fieldId = id ?? `textarea-${autoId}`;
  const helpId = error ? `${fieldId}-error` : hint ? `${fieldId}-hint` : undefined;

  return (
    <div class={className ? `cs-field ${className}` : "cs-field"}>
      <label
        for={fieldId}
        class={hideLabel ? "sr-only" : "cs-field-label"}
      >
        <span>{label}</span>
        {required ? <span class="cs-field-required" aria-hidden="true">*</span> : null}
      </label>
      <textarea
        id={fieldId}
        name={name}
        rows={rows}
        class={mono ? "cs-field-textarea cs-field-textarea--mono" : "cs-field-textarea"}
        value={value}
        placeholder={placeholder}
        maxLength={maxLength}
        disabled={disabled}
        required={required}
        aria-label={hideLabel ? label : undefined}
        aria-invalid={error ? "true" : undefined}
        aria-describedby={helpId}
        onInput={(event) => onInput((event.currentTarget as HTMLTextAreaElement).value)}
      />
      {(error || hint || (showCounter && maxLength !== undefined)) ? (
        <div class="cs-field-meta">
          {error ? (
            <span id={`${fieldId}-error`} class="cs-field-error" role="alert">
              {error}
            </span>
          ) : hint ? (
            <span id={`${fieldId}-hint`} class="cs-field-hint">
              {hint}
            </span>
          ) : <span />}
          {showCounter && maxLength !== undefined ? (
            <span class="cs-field-counter" aria-live="polite">
              {value.length} / {maxLength}
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export interface CheckboxFieldProps {
  readonly id?: string;
  readonly label: ComponentChildren;
  readonly hint?: string;
  readonly checked: boolean;
  readonly onChange: (checked: boolean) => void;
  readonly disabled?: boolean;
  readonly className?: string;
}

export function CheckboxField({
  id,
  label,
  hint,
  checked,
  onChange,
  disabled = false,
  className,
}: CheckboxFieldProps) {
  const autoId = useId();
  const fieldId = id ?? `checkbox-${autoId}`;
  const rowClass = [
    "cs-choice-row",
    disabled ? "is-disabled" : "",
    className ?? "",
  ].filter(Boolean).join(" ");

  return (
    <label for={fieldId} class={rowClass}>
      <input
        id={fieldId}
        type="checkbox"
        class="cs-choice-input"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange((event.currentTarget as HTMLInputElement).checked)}
      />
      <span class="cs-choice-copy">
        <span>{label}</span>
        {hint ? <span class="cs-choice-hint">{hint}</span> : null}
      </span>
    </label>
  );
}

export interface RadioFieldProps {
  readonly id?: string;
  readonly name: string;
  readonly value: string;
  readonly label: ComponentChildren;
  readonly hint?: string;
  readonly checked: boolean;
  readonly onChange: (value: string) => void;
  readonly disabled?: boolean;
  readonly className?: string;
}

export function RadioField({
  id,
  name,
  value,
  label,
  hint,
  checked,
  onChange,
  disabled = false,
  className,
}: RadioFieldProps) {
  const autoId = useId();
  const fieldId = id ?? `radio-${autoId}`;
  const rowClass = [
    "cs-choice-row",
    disabled ? "is-disabled" : "",
    className ?? "",
  ].filter(Boolean).join(" ");

  return (
    <label for={fieldId} class={rowClass}>
      <input
        id={fieldId}
        type="radio"
        name={name}
        value={value}
        class="cs-choice-input"
        checked={checked}
        disabled={disabled}
        onChange={() => onChange(value)}
      />
      <span class="cs-choice-copy">
        <span>{label}</span>
        {hint ? <span class="cs-choice-hint">{hint}</span> : null}
      </span>
    </label>
  );
}

export interface ToggleSwitchProps {
  readonly id?: string;
  readonly label: string;
  readonly hint?: string;
  readonly checked: boolean;
  readonly onChange: (checked: boolean) => void;
  readonly disabled?: boolean;
  readonly className?: string;
}

export function ToggleSwitch({
  id,
  label,
  hint,
  checked,
  onChange,
  disabled = false,
  className,
}: ToggleSwitchProps) {
  const autoId = useId();
  const switchId = id ?? `switch-${autoId}`;
  const labelId = `${switchId}-label`;

  return (
    <div class={className ? `cs-switch-row ${className}` : "cs-switch-row"}>
      <span class="cs-choice-copy">
        <span id={labelId}>{label}</span>
        {hint ? <span class="cs-choice-hint">{hint}</span> : null}
      </span>
      <button
        id={switchId}
        type="button"
        role="switch"
        class="cs-switch-btn"
        aria-checked={checked ? "true" : "false"}
        aria-labelledby={labelId}
        disabled={disabled}
        onClick={() => onChange(!checked)}
      >
        <span class="cs-switch-thumb" aria-hidden="true" />
      </button>
    </div>
  );
}

export interface FilterToolbarProps {
  readonly ariaLabel?: string;
  readonly activeFilterCount?: number;
  readonly onReset?: () => void;
  readonly resetLabel?: string;
  readonly actions?: ComponentChildren;
  readonly className?: string;
  readonly children: ComponentChildren;
}

export function FilterToolbar({
  ariaLabel = "Filters",
  activeFilterCount = 0,
  onReset,
  resetLabel = "Reset",
  actions,
  className,
  children,
}: FilterToolbarProps) {
  return (
    <div
      class={className ? `cs-filter-toolbar ${className}` : "cs-filter-toolbar"}
      role="search"
      aria-label={ariaLabel}
    >
      <div class="cs-filter-toolbar-items">{children}</div>
      {(onReset || actions) ? (
        <div class="cs-filter-toolbar-actions">
          {actions}
          {onReset ? (
            <button
              type="button"
              class="cs-filter-reset"
              disabled={activeFilterCount === 0}
              onClick={onReset}
            >
              <span>{resetLabel}</span>
              {activeFilterCount > 0 ? (
                <span class="cs-seg-count">({activeFilterCount})</span>
              ) : null}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export interface SegmentedOption<T extends string = string> {
  readonly value: T;
  readonly label: string;
  readonly count?: number;
  readonly disabled?: boolean;
}

export interface SegmentedControlProps<T extends string = string> {
  readonly ariaLabel: string;
  readonly value: T;
  readonly options: readonly SegmentedOption<T>[];
  readonly onChange: (value: T) => void;
  readonly role?: "group" | "tablist";
  readonly className?: string;
}

export function SegmentedControl<T extends string = string>({
  ariaLabel,
  value,
  options,
  onChange,
  role = "group",
  className,
}: SegmentedControlProps<T>) {
  return (
    <div
      class={className ? `cs-seg-group ${className}` : "cs-seg-group"}
      role={role}
      aria-label={ariaLabel}
    >
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            role={role === "tablist" ? "tab" : undefined}
            class={active ? "cs-seg-btn is-active" : "cs-seg-btn"}
            aria-selected={role === "tablist" ? (active ? "true" : "false") : undefined}
            aria-pressed={role === "group" ? (active ? "true" : "false") : undefined}
            disabled={opt.disabled}
            onClick={() => onChange(opt.value)}
          >
            <span>{opt.label}</span>
            {opt.count !== undefined ? (
              <span class="cs-seg-count">{opt.count}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
