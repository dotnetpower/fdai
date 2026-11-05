import { resolvePreview } from "./model";

const route = resolvePreview("lifecycle", window.location.pathname);
const root = document.getElementById("app");
if (!root) throw new Error("Missing #app root element.");

async function start(): Promise<void> {
  if (route.kind === "operational") {
    // Production still enters its original authenticated router; no sample fallback.
    await import("../styles.css");
    await import("../main");
    return;
  }
  const { render } = await import("preact");
  if (route.kind === "preview" && route.hub === "lifecycle") {
    const { LifecyclePreview } = await import("./previews");
    document.title = `${route.design} | Lifecycle Hub design preview`;
    render(<LifecyclePreview design={route.design} />, root!);
  } else {
    const { PreviewNotFound } = await import("./shell");
    render(<PreviewNotFound hub="lifecycle" />, root!);
  }
}

void start().catch(() => {
  root.textContent = "Unable to load this screen. Reload the page to try again.";
  root.setAttribute("role", "alert");
});
