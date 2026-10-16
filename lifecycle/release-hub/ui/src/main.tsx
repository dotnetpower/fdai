import { render } from "preact";
import { App } from "./app";
import "./styles.css";
import { initializeAuth, showAuthFailure } from "../../../hub/ui/src/auth";

const root = document.getElementById("app");
if (!root) throw new Error("Missing #app root element.");
void initializeAuth(root).then((ready) => {
  if (ready) render(<App />, root);
}).catch(() => showAuthFailure(root));
