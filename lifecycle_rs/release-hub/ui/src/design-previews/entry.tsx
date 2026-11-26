import { resolvePreview } from "../../../../hub/ui/src/design-previews/model";

const route = resolvePreview("release", window.location.pathname);
const root = document.getElementById("app");
if (!root) throw new Error("Missing #app root element.");

async function start(): Promise<void> {
  if (route.kind === "operational") {
    // Keep authentication, hash routes, live data and all production styling unchanged.
    await import("../main");
    return;
  }
  const { render } = await import("preact");
  if (route.kind === "preview" && route.hub === "release") {
    const { ReleasePreview } = await import("./previews");
    document.title = `${route.page === "installations" ? "설치 현황" : route.design} | Release Hub design preview`;
    render(<ReleasePreview design={route.design} page={route.page} />, root!);
  } else {
    const { PreviewNotFound } = await import("../../../../hub/ui/src/design-previews/shell");
    render(<PreviewNotFound hub="release" />, root!);
  }
}

void start().catch(() => {
  root.textContent = "Unable to load this screen. Reload the page to try again.";
  root.setAttribute("role", "alert");
});
