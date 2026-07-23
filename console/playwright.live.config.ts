import { defineConfig, devices } from "@playwright/test";

const apiPort = Number(process.env.FDAI_E2E_READ_API_PORT ?? "8012");
const frontendPort = Number(process.env.FDAI_E2E_FRONTEND_PORT ?? "5275");
const defaultBaseURL = `http://127.0.0.1:${frontendPort}`;
const baseURL = process.env.FDAI_E2E_BASE_URL ?? defaultBaseURL;
const externalStack = process.env.FDAI_E2E_BASE_URL !== undefined;
const storageState = process.env.FDAI_E2E_STORAGE_STATE;

export default defineConfig({
  testDir: "./tests/live-e2e",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: "list",
  outputDir: "test-results/live",
  timeout: 30_000,
  use: {
    baseURL,
    ...(storageState ? { storageState } : {}),
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: externalStack
    ? undefined
    : [
        {
          command:
            `set -a && . ../.fdai/local-runtime.env && set +a && ` +
            `env -u AZURE_CONFIG_DIR -u FDAI_READ_API_DEV_MODE -u FDAI_READ_API_LOCAL_ENTRA ` +
            `FDAI_READ_API_LOCAL_AZURE_CLI=1 FDAI_READ_API_EMBED_PANTHEON=0 ` +
            `FDAI_READ_API_CORS_ALLOW_ORIGINS=${defaultBaseURL} ` +
            `../.venv/bin/python -m uvicorn fdai.delivery.read_api.dev.local:app ` +
            `--factory --host 127.0.0.1 --port ${apiPort}`,
          url: `http://127.0.0.1:${apiPort}/healthz`,
          reuseExistingServer: true,
          stdout: "ignore",
          stderr: "pipe",
          timeout: 120_000,
        },
        {
          command:
            `VITE_DEV_MODE=0 VITE_LOCAL_AZURE_CLI_AUTH=1 VITE_LOCAL_LOGIN_PROMPT=0 ` +
            `VITE_READ_API_BASE_URL=http://127.0.0.1:${apiPort} ` +
            `VITE_INGESTION_API_BASE_URL=http://127.0.0.1:8011 ` +
            `npm run dev -- --host 127.0.0.1 --port ${frontendPort} --strictPort`,
          url: defaultBaseURL,
          reuseExistingServer: true,
          stdout: "ignore",
          stderr: "pipe",
          timeout: 120_000,
        },
      ],
  projects: [{ name: "live-desktop-chromium", use: { ...devices["Desktop Chrome"] } }],
});
