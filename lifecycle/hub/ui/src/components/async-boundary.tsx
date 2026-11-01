import type { ComponentChildren } from "preact";
import type { AsyncState } from "../hooks/use-async";
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
  if (state.status === "loading") {
    return (
      <div class={`loading-placeholder ${layout}`} role="status" aria-label="Loading Hub data" aria-busy="true">
        <span class="loading-label">Loading Hub data...</span>
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
    const classified = classifyHubError(state.error);
    return (
      <div class="banner fail" role="alert">
        <strong>{classified.title}</strong>
        <span>{state.error.message} - {classified.guidance}</span>
        <div><button class="btn" type="button" onClick={state.reload}>Try again</button></div>
      </div>
    );
  }
  return <div class="async-ready">{children(state.data)}</div>;
}
