import type { ComponentChildren } from "preact";
import type { AsyncState } from "../hooks/use-async";
import { tr, useHubLocale } from "../locale";
import { classifyHubError } from "../readiness-status";

export function AsyncBoundary<T>({
  state,
  children,
  layout = "detail",
}: {
  state: AsyncState<T> & { reload: () => void };
  children: (data: T) => ComponentChildren;
  layout?: "table" | "detail";
}) {
  const [locale] = useHubLocale();
  if (state.status === "loading") {
    return (
      <div
        class={`loading-placeholder ${layout}`}
        role="status"
        aria-label={tr(locale, "Loading Hub data", "Hub 데이터 불러오는 중")}
        aria-busy="true"
      >
        <span class="loading-label">
          {tr(locale, "Loading Hub data...", "Hub 데이터를 불러오는 중...")}
        </span>
        <div class="skeleton skeleton-heading" aria-hidden="true" />
        {[0, 1, 2, 3].map((row) => (
          <div key={row} class="skeleton-row" aria-hidden="true">
            <span class="skeleton" />
            <span class="skeleton" />
            <span class="skeleton" />
          </div>
        ))}
      </div>
    );
  }
  if (state.status === "error") {
    const classified = classifyHubError(state.error, locale);
    return (
      <div class="banner fail" role="alert">
        <strong>{classified.title}</strong>
        <span>{state.error.message} - {classified.guidance}</span>
        <div>
          <button class="btn" type="button" onClick={state.reload}>
            {tr(locale, "Try again", "다시 시도")}
          </button>
        </div>
      </div>
    );
  }
  return <div class="async-ready">{children(state.data)}</div>;
}
