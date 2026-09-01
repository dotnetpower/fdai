export function SettingsSectionHeader({ id, title, description, scope }: {
  readonly id: string;
  readonly title: string;
  readonly description?: string;
  readonly scope?: string;
}) {
  return (
    <header class="settings-section-head">
      <div>
        <h3 id={id}>{title}</h3>
        {scope ? <span class="settings-scope-label">{scope}</span> : null}
      </div>
      {description ? <p>{description}</p> : null}
    </header>
  );
}

export function SettingRow({ label, hint, children }: {
  readonly label: string;
  readonly hint: string;
  readonly children: preact.ComponentChildren;
}) {
  return (
    <div class="settings-row">
      <div><strong>{label}</strong><small class="muted">{hint}</small></div>
      {children}
    </div>
  );
}

export function SegmentedControl({ label, value, options, onChange }: {
  readonly label: string;
  readonly value: string;
  readonly options: readonly { readonly value: string; readonly label: string }[];
  readonly onChange: (value: string) => void;
}) {
  return (
    <div class="settings-segmented" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          class={option.value === value ? "is-active" : undefined}
          aria-pressed={option.value === value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
