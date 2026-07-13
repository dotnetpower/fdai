import { render } from "preact";
import { App } from "./app";
import { applyConsolePreferences, readConsolePreferences } from "./preferences";
import "./styles.css";

applyConsolePreferences(readConsolePreferences());

const root = document.getElementById("app");
if (!root) {
  throw new Error("missing #app root element in index.html");
}
render(<App />, root);
