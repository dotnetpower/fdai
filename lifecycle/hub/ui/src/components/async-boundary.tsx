import type { ComponentChildren } from "preact";
import type { AsyncState } from "../hooks/use-async";

/** Renders loading/error/ready states for a `useAsync` result so route components don't repeat it. */
export function AsyncBoundary<T>({
  state,
  children,
}: {
  state: AsyncState<T>;
  children: (data: T) => ComponentChildren;
}) {
  if (state.status === "loading") return <p class="empty">Loading...</p>;
  if (state.status === "error") return <p class="empty">{state.error.message}</p>;
  return <>{children(state.data)}</>;
}
