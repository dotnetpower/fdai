import { useEffect, useState } from "preact/hooks";

export type AsyncState<T> =
  | { status: "loading"; data: null; error: null }
  | { status: "ready"; data: T; error: null }
  | { status: "error"; data: null; error: Error };

/**
 * Run `fetcher` whenever `deps` changes, and expose its loading/ready/error state.
 * A later effect run's result always wins over a slower earlier one.
 */
export function useAsync<T>(fetcher: () => Promise<T>, deps: readonly unknown[]): AsyncState<T> {
  const [state, setState] = useState<AsyncState<T>>({ status: "loading", data: null, error: null });

  useEffect(() => {
    let current = true;
    setState({ status: "loading", data: null, error: null });
    fetcher().then(
      (data) => {
        if (current) setState({ status: "ready", data, error: null });
      },
      (error: unknown) => {
        if (current) {
          setState({
            status: "error",
            data: null,
            error: error instanceof Error ? error : new Error(String(error)),
          });
        }
      },
    );
    return () => {
      current = false;
    };
    // `fetcher` is intentionally excluded: callers pass a fresh closure each render and list
    // their real dependencies in `deps` instead.
  }, deps);

  return state;
}
