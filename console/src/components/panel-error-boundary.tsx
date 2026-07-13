import { Component, type ComponentChildren } from "preact";

interface Props {
  readonly children: ComponentChildren;
}

interface State {
  readonly error: Error | null;
}

export class PanelErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static override getDerivedStateFromError(error: unknown): State {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  render() {
    if (this.state.error) {
      return (
        <div class="state-block state-error" role="alert">
          <span class="state-icon" aria-hidden="true">!</span>
          <div>
            <strong>Panel failed to load.</strong>
            <p class="muted small">{this.state.error.message}</p>
            <button type="button" class="btn" onClick={() => window.location.reload()}>
              Reload console
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
