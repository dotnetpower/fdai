import { render } from "preact";
import { App } from "./app";
import { PanelErrorBoundary } from "./components/panel-error-boundary";
import { applyConsolePreferences, readConsolePreferences } from "./preferences";

applyConsolePreferences(readConsolePreferences());

const root = document.getElementById("app");
if (!root) {
  throw new Error("missing #app root element in index.html");
}
render(
  <PanelErrorBoundary>
    <App />
  </PanelErrorBoundary>,
  root,
);
