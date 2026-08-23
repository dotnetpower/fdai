---
name: vscode-profile-onboarding
description: "Configure, validate, troubleshoot, or explain the shared FDAI VS Code Profile and local servers. Use for VS Code setup, Profiles, extensions, WSL remote settings, editor slowness, Playwright tests, browser tools, screenshots, frontend visual validation, browser-tool slowness, onboarding, importing fdai.code-profile, or starting, restarting, and checking the Console, design mock server, backend, local servers, or full stack."
argument-hint: "Set up or diagnose the FDAI VS Code Profile"
---

# FDAI VS Code Profile Onboarding

Use the repository artifacts as the source of truth. Do not reconstruct the profile from a
maintainer's local VS Code state.

## Source of truth

- [../../../.vscode/fdai.code-profile](../../../.vscode/fdai.code-profile) contains portable
  profile settings and extensions.
- [../../../.vscode/extensions.json](../../../.vscode/extensions.json) is the canonical extension
  recommendation and unwanted-extension list.
- [../../../.vscode/fdai.machine-settings.json](../../../.vscode/fdai.machine-settings.json)
  contains path-free WSL remote machine settings that VS Code Profile sync does not carry.
- [../../../scripts/automation/configure-vscode-profile.py](../../../scripts/automation/configure-vscode-profile.py)
  validates drift and safely merges remote machine settings.
- [../../../DEVELOPING.md](../../../DEVELOPING.md#1-vs-code-profile-recommended) is the human
  onboarding checklist.

## Procedure

1. Detect whether the current window is local, SSH, a dev container, or WSL. Use `code --status`
   when available. Never infer the remote type only from the host OS.
2. Run `python3 scripts/automation/configure-vscode-profile.py` from the repository root. Stop on
   artifact drift; do not improvise a different extension list.
3. If the window is WSL, run:

   ```bash
   python3 scripts/automation/configure-vscode-profile.py \
     --apply-machine-settings --check-machine-settings
   ```

   The merger preserves unrelated JSON settings. If the existing file is JSONC, it fails without
   writing. In that case, explain the conflict and merge the template with a structured JSONC-aware
   editor instead of stripping comments.
4. Ask the collaborator to run `Profiles: Import Profile`, select
   `.vscode/fdai.code-profile`, review the Settings and Extensions sections, and create or replace
   `FDAI`. Profile import is a user-visible VS Code action; do not edit VS Code profile databases.
5. Ask the collaborator to switch with `Profiles: Switch Profile`, select `FDAI`, and reopen this
   repository in WSL when WSL is the development target.
6. Verify the active profile from the title bar or Manage-button badge. Confirm that HashiCorp
   Terraform is active and Microsoft Terraform is not installed in this profile.
7. Run the validator again with `--check-machine-settings` in WSL and report any remaining gap.

## Local server start requests

- Launch long-running local services through the committed VS Code tasks or launch configurations,
  never through a persistent `run_in_terminal` session. Copilot monitors its own persistent
  terminals for input and can inject a noisy input-needed notification into later chat turns when
  a healthy service continuously emits logs. Use `console: start core runtime` when only the Core
  Runtime needs recovery; that task waits for a fresh Pantheon heartbeat. The `console: start full
  stack` task returns after the supervisor spawns every managed launcher while the supervisor keeps
  the 60-second readiness gate. Run `console: wait full stack ready` before reporting success or
  starting work that requires the complete topology. Close any earlier agent-owned service terminal
  after its process has been replaced by the task-owned process.
- For a background task with a readiness problem matcher, treat the task tool's ready return as the
  terminal result. Do not call `get_task_output`, wait for process exit, or retry the task after its
  ready event; the service is intentionally long-running. If readiness is still in doubt, run one
  separate 5-second health check for the named component and act on that result immediately.
- Treat an unqualified request to start the Console, Console web, local server, servers, backend,
  or full stack as a request for the complete `Console Web: Full Stack` topology. Start or verify
  all five independently packaged backend services plus the SPA: Core Control Plane, Operator
  Service, Document Ingestion API, Document Processing Worker, isolated Executor, and Console
  Frontend. A listening frontend or partial backend set is not a complete start.
- Use the existing VS Code tasks or launch configurations. Run `console: prepare full stack` before
  starting any missing backend process. Preparation MUST start Docker PostgreSQL, Redpanda, and
  ClamAV, upgrade all five service migration branches, and generate role-scoped private service
  environments. Do not replace the standard browser Entra profile with a test, fixture,
  ingestion-gateway, or CLI-principal profile.
- If the standard local stack is already healthy and its configuration inputs have not changed,
  reuse its processes, generated `.fdai/local-*.env` files, logs, and database records. Do not
  restart the stack, rerun full preparation, or regenerate state merely to begin an investigation.
  Run only the affected preparation task when a migration, binding, or environment input changed.
- The local launcher sets `FDAI_EXECUTION_VENUE=local`; every stateful service uses the loopback
  Docker PostgreSQL DSN under its service-owned role. The Azure launcher sets
  `FDAI_EXECUTION_VENUE=deployed`; every deployed service uses its Azure Database for PostgreSQL
  DSN. Never copy a local DSN into Azure configuration or an Azure PostgreSQL DSN into the local
  interactive profile.
- For a local bug, query, or state investigation, inspect the generated local service environment
  and loopback PostgreSQL first. Confirm the local service is using its expected role, the local
  migrations are current, and the relevant local row is absent before considering remote evidence.
  Azure PostgreSQL migration or synchronization belongs to the protected deployment workflow;
  direct Azure database access is reserved for an explicitly requested live validation and never
  substitutes for checking the local reproduction.
- Treat VPN connectivity as observed state. Check the existing
  `dev-access: configure VPN on folder open` task result first. If the exact private target still
  needs diagnosis, run `tools/dev-access/scripts/doctor.sh <host[:port]>` with its configured
  non-secret endpoint. Do not report the VPN as disconnected merely because a target is private or
  a request failed; separate VPN route, DNS, TCP endpoint, authorization, and application errors.
- Start the local isolated Executor only from its committed local environment. It is a durable
  shadow consumer with no managed-resource identity, and `FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER`
  remains `0`. A local cutover request is a startup failure, not a reason to inject Azure or user
  credentials.
- A request that also names the design or mock server starts `design mocks: serve (5373)` in
  addition to the complete Console stack. The design server never substitutes for a Console
  backend process.
- Before reporting success, verify the Core Runtime process and Pantheon readiness, Operator API
  `127.0.0.1:8010`, Document Ingestion API `127.0.0.1:8011`, Document Processing Worker readiness
  `127.0.0.1:8012`, isolated Executor readiness `127.0.0.1:8013`, and frontend
  `127.0.0.1:5273`. When requested, also verify the design server on `127.0.0.1:5373`. Do not infer
  backend readiness from a frontend HTTP `200` response.
- Start only the specifically named component when the user explicitly narrows the request, such as
  "frontend only", "Operator API only", or "design server only".

## Playwright and browser-tool latency

Preserve the authentication and port rules in the
[Local Console Port Contract](../../instructions/app-shape.instructions.md#local-console-port-contract-must).
Do not treat the repository Playwright runner and Copilot browser tools as one performance path.

Use the committed entry points instead of searching for a config before each run:

- Run or debug one test from the VS Code Testing sidebar. The shared profile recommends the
  Playwright extension, and its default Chrome profile is the fastest editor feedback path.
- Run `console: Playwright quick (desktop)` from **Tasks: Run Test Task** for the complete desktop
  E2E slice.
- From the repository root, run
  `npm --prefix console run test:e2e:quick -- tests/e2e/<name>.spec.ts` for one file or omit the
  file for the desktop slice. Reserve `npm --prefix console run test:e2e` for the complete desktop
  and mobile matrix.

1. Classify the slow operation:
  - CLI runner: `playwright test`, worker startup, configured projects, `webServer`, traces, or tests.
  - Browser tool: `read_page`, `run_playwright_code`, interactions, screenshots, and the following
    model round.
2. Benchmark one CLI test sequentially. Use one file or `--grep` title and one project. Add
  `DEBUG=pw:webserver` only when startup readiness is suspect. Never run timing samples in
  parallel terminals that share the same directory, port, or Playwright output.
3. For a shared page, reuse its page ID and gather navigation timing, DOM size, and required state
  in one browser call. A sub-second page with a large accessibility snapshot indicates tool
  serialization and context cost, not a slow renderer.
4. Check host pressure separately with `code --status`, `/proc/pressure/{cpu,io,memory}`, and the
  remote extension host's CPU and RSS. Identify the process that owns the Console port before
  assuming the page belongs to the current checkout.
5. Apply the narrow remedy: focused CLI tests for behavior, one batched browser call for
  authenticated or interactive state, and one targeted screenshot for visual evidence. Reload
  the VS Code window only when extension-host growth is material and active work can tolerate it.

### Browser Entra storage-state capture

The shared browser page runs inside VS Code's Electron host. Its CDP compatibility layer accepts
`Browser.setDownloadBehavior` without applying a download path, so
`page.context().storageState({ path })` can open a native **Save As** dialog instead of writing the
requested WSL path. A Blob or anchor download has the same user-visible failure mode.

- MUST NOT use `storageState({ path })`, a Blob URL, or an anchor download to export authentication
  state from a shared Browser Entra page.
- MUST NOT import `node:fs` from `run_playwright_code`; the browser tool sandbox does not expose a
  dynamic-import callback. Start `scripts/automation/capture_browser_entra_state.py` in a terminal,
  wait for its `receiver-ready` marker, and leave it running for one request.
- When the shared Console and isolated Playwright target use different loopback origins, pass the
  shared page as `--origin` and the Playwright target as `--storage-origin`. The receiver validates
  the POST against the shared origin while writing the bootstrap local storage for the target
  origin.
- In one browser evaluation, POST an object containing `location.origin`,
  `Object.entries(localStorage)`, and `Object.entries(sessionStorage)` to the receiver as
  `text/plain;charset=UTF-8`. Keep this a CORS simple request: adding JSON content type or custom
  headers introduces an `OPTIONS` preflight that consumes the one-request receiver. Return only the
  HTTP status and item counts; never return or log the serialized authentication values.
- The receiver accepts only the configured Console origin, validates the payload shape and size,
  serializes `fdai:e2e:browser-entra-session` in the Playwright bootstrap shape used by
  `console/tests/live-e2e/browser-entra-state.ts`, writes beneath ignored `.fdai/live-validation/`
  with mode `0600`, and exits.
- Verify the destination with `stat` and a shape-only JSON check. Do not inspect or print token,
  cookie, or storage values. The resulting file can then be supplied through
  `FDAI_E2E_STORAGE_STATE` to the isolated Playwright context.

The isolated runner waits for Vite's `ready in` stdout marker. This avoids an unused-loopback HTTP
or dual-stack TCP readiness probe stalling before Vite starts under WSL or VPN networking. Do not
replace the stdout marker with `webServer.url` or `webServer.port` unless a clean sequential
benchmark proves the probe returns promptly in the supported environment.

Both isolated Playwright configurations atomically lease one of ten shared slots. Frontend ports
are `5274-5283`; a live E2E slot pairs them with Operator API ports `8020-8029`. The lease is shared
with Playwright workers, stale locks from exited PIDs are reclaimed, and artifacts are written
under the leased slot's output directory. Do not hard-code or randomly select another port. If all
ten slots are occupied, stop a stale test session or wait for one slot to be released.

Do not change Console behavior, Playwright timeouts, workers, or server topology merely to hide a
large browser-tool payload. Change runner configuration only when a clean sequential CLI benchmark
reproduces the delay.

## Boundaries

- A profile configures editor behavior only. It never configures Azure accounts, tenants,
  subscriptions, endpoints, credentials, App Roles, runtime mode, promotion state, or executor
  identity.
- Do not commit exported local profile storage. It contains machine paths, UUIDs, versions, and
  timestamps. Update only the portable repository artifacts.
- Do not pin extension versions in the shared profile. Marketplace resolution selects the build
  for the collaborator's OS and remote environment.
- Settings Sync does not install remote extensions into WSL, SSH, or dev-container windows. Always
  validate inside the target remote window.
- Preserve personal keybindings, themes, snippets, MCP servers, UI state, and language models.
  They are intentionally absent from the shared profile.
