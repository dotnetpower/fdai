import { render } from "preact";
import { App } from "./app";
import { initializeAuth, showAuthFailure } from "./auth";

const root = document.getElementById("app");
if (!root) throw new Error("missing #app root element in index.html");

void initializeAuth(root).then((ready) => {
  if (ready) render(<App />, root);
}).catch(() => showAuthFailure(root));
