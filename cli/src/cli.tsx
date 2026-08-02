/**
 * FDAI operator-console CLI - entrypoint.
 *
 * Demonstrates the one-content-many-renderers architecture: the briefing is
 * compiled ONCE into the surface-neutral block IR, then handed to whichever
 * renderer the `--surface` flag selects. Switching surfaces never changes the
 * content, only the rendering.
 *
 *   npm run cli                              # Ink terminal (synthetic sample)
 *   tsx src/cli.tsx --source=api             # live data from the Operator API
 *   tsx src/cli.tsx --surface=slack          # Slack Block Kit JSON
 *   tsx src/cli.tsx --surface=cli --mode=all-clear
 */

import { CLI_HELP, isHelpRequest, parseCliArgs } from "./args.js";
import { fetchSnapshot } from "./data/operator-api.js";
import { sampleBriefing } from "./data/sample-briefing.js";
import type { Block } from "./view-model/blocks.js";
import { buildBriefing } from "./view-model/build-briefing.js";
import { buildFromReadModel } from "./view-model/build-from-readmodel.js";
import { renderSlack } from "./renderers/slack.js";
import { renderTeams } from "./renderers/teams.js";
import { renderText } from "./renderers/text.js";
import type { BriefingPayload } from "./view-model/contract.js";

const argv = process.argv.slice(2);
if (isHelpRequest(argv)) {
  console.log(CLI_HELP);
  process.exit(0);
}

let options;
try {
  options = parseCliArgs(argv);
} catch (error) {
  console.error((error as Error).message);
  process.exit(2);
}
const { surface, mode, source, apiUrl, locale } = options;

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
      `could not reach the Operator API at ${apiUrl}: ${(err as Error).message}`,
    );
    console.error(
      "start it with: FDAI_OPERATOR_API_DEV_MODE=1 uv run --with uvicorn " +
        "uvicorn 'fdai.delivery.operator_api.dev.local:app' --factory --port 8010",
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
      await startCockpit({ apiUrl: liveApi, payload: null, locale });
    } else {
      // Sample data (or non-TTY): Ink briefing once, then the bottom-fixed REPL.
      const { renderBriefing } = await import(
        "./renderers/ink/briefing-oneshot.js"
      );
      await renderBriefing(blocks);
      const { startRepl } = await import("./repl.js");
      await startRepl({ apiUrl: liveApi, payload: payload ?? null, locale });
    }
    break;
  }
}

// A CLI is done once its work is done. `fetch` (undici) keeps keep-alive sockets
// referenced, which would otherwise delay exit, so exit explicitly.
process.exit(0);
