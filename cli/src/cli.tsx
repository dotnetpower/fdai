/**
 * FDAI operator-console CLI - entrypoint.
 *
 * Demonstrates the one-content-many-renderers architecture: the briefing is
 * compiled ONCE into the surface-neutral block IR, then handed to whichever
 * renderer the `--surface` flag selects. Switching surfaces never changes the
 * content, only the rendering.
 *
 *   npm run cli                              # Ink terminal (synthetic sample)
 *   tsx src/cli.tsx --source=api             # live data from the read API
 *   tsx src/cli.tsx --surface=slack          # Slack Block Kit JSON
 *   tsx src/cli.tsx --surface=cli --mode=all-clear
 */

import { fetchSnapshot } from "./data/read-api.js";
import { sampleBriefing, type BriefingMode } from "./data/sample-briefing.js";
import { resolveLocale } from "./i18n/index.js";
import type { Block } from "./view-model/blocks.js";
import { buildBriefing } from "./view-model/build-briefing.js";
import { buildFromReadModel } from "./view-model/build-from-readmodel.js";
import { renderSlack } from "./renderers/slack.js";
import { renderTeams } from "./renderers/teams.js";
import { renderText } from "./renderers/text.js";
import type { BriefingPayload } from "./view-model/contract.js";

type Surface = "cli" | "text" | "slack" | "teams";
type Source = "sample" | "api";

function flag(name: string, fallback: string): string {
  const prefix = `--${name}=`;
  const hit = process.argv.find((a) => a.startsWith(prefix));
  return hit ? hit.slice(prefix.length) : fallback;
}

const surface = flag("surface", "cli") as Surface;
const mode = flag("mode", "needs-me") as BriefingMode;
const source = flag("source", "sample") as Source;
const apiUrl = flag("api", "http://127.0.0.1:8010");
// Locale resolution: --locale flag (highest) -> FDAI_LOCALE env -> en.
const locale = resolveLocale(flag("locale", process.env.FDAI_LOCALE ?? "en"));

if (!["cli", "text", "slack", "teams"].includes(surface)) {
  console.error(`unknown --surface=${surface} (cli | text | slack | teams)`);
  process.exit(2);
}
if (!["needs-me", "all-clear"].includes(mode)) {
  console.error(`unknown --mode=${mode} (needs-me | all-clear)`);
  process.exit(2);
}
if (!["sample", "api"].includes(source)) {
  console.error(`unknown --source=${source} (sample | api)`);
  process.exit(2);
}

// Compile the content exactly once - this is what every surface shares.
// `sample` uses synthetic data; `api` pulls the live read-only snapshot.
let blocks: Block[];
let payload: BriefingPayload | null = null;
let liveApi: string | null = null;

if (source === "api") {
  try {
    const snap = await fetchSnapshot(apiUrl);
    blocks = buildFromReadModel(snap, "live", locale);
    liveApi = apiUrl;
  } catch (err) {
    console.error(
      `could not reach the read API at ${apiUrl}: ${(err as Error).message}`,
    );
    console.error(
      "start it with: FDAI_READ_API_DEV_MODE=1 uv run --with uvicorn " +
        "uvicorn 'fdai.delivery.read_api._local:app' --factory --port 8010",
    );
    process.exit(1);
  }
} else {
  payload = sampleBriefing(mode);
  blocks = buildBriefing(payload, locale);
}

switch (surface) {
  case "slack":
    console.log(JSON.stringify(renderSlack(blocks), null, 2));
    break;
  case "teams":
    console.log(JSON.stringify(renderTeams(blocks), null, 2));
    break;
  case "text":
    console.log(renderText(blocks));
    break;
  case "cli":
  default: {
    if (source === "api" && liveApi && process.stdin.isTTY) {
      // Live data: a one-screen cockpit fed by the real pipeline over SSE.
      const { startCockpit } = await import("./cockpit.js");
      await startCockpit({ apiUrl: liveApi, payload: null });
    } else {
      // Sample data (or non-TTY): Ink briefing once, then the bottom-fixed REPL.
      const { renderBriefing } = await import(
        "./renderers/ink/briefing-oneshot.js"
      );
      await renderBriefing(blocks);
      const { startRepl } = await import("./repl.js");
      await startRepl({ apiUrl: liveApi, payload: payload ?? null });
    }
    break;
  }
}

// A CLI is done once its work is done. `fetch` (undici) keeps keep-alive sockets
// referenced, which would otherwise delay exit, so exit explicitly.
process.exit(0);
