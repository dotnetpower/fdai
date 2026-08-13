import { randomUUID } from "node:crypto";

import { defineConfig, devices } from "@playwright/test";

const apiPort = Number(process.env.FDAI_E2E_OPERATOR_API_PORT ?? "8020");
const frontendPort = Number(process.env.FDAI_E2E_FRONTEND_PORT ?? "5275");
const loopbackHost = "[::1]";
const defaultBaseURL = `http://${loopbackHost}:${frontendPort}`;
const baseURL = process.env.FDAI_E2E_BASE_URL ?? defaultBaseURL;
const externalStack = process.env.FDAI_E2E_BASE_URL !== undefined;
const storageState = process.env.FDAI_E2E_STORAGE_STATE;
const testBearer = process.env.FDAI_E2E_BEARER ?? randomUUID();
process.env.FDAI_E2E_BEARER = testBearer;

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
    ...(!externalStack ? { extraHTTPHeaders: { Authorization: `Bearer ${testBearer}` } } : {}),
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  webServer: externalStack
    ? undefined
    : [
        {
          command:
            `set -a && . ../.fdai/local-operator-service.env && set +a && ` +
            `env -u AZURE_CONFIG_DIR ` +
            `FDAI_E2E_BEARER=${testBearer} ` +
            `FDAI_E2E_OPERATOR_API_PORT=${apiPort} ` +
            `FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS=${defaultBaseURL} ` +
            `PYTHONPATH=../services/operator-service/src:../packages/service-contracts/src ` +
            `../.venv/bin/python tests/live-e2e/operator_service.py`,
          url: `http://${loopbackHost}:${apiPort}/healthz`,
          reuseExistingServer: false,
          stdout: "ignore",
          stderr: "pipe",
          timeout: 120_000,
        },
        {
          command:
            `VITE_DEV_MODE=1 VITE_LOCAL_AZURE_CLI_AUTH=0 VITE_LOCAL_LOGIN_PROMPT=0 ` +
            `VITE_OPERATOR_API_BASE_URL=http://${loopbackHost}:${apiPort} ` +
            `VITE_INGESTION_API_BASE_URL=http://127.0.0.1:8011 ` +
            `npm run dev -- --host ::1 --port ${frontendPort} --strictPort`,
          url: defaultBaseURL,
          reuseExistingServer: false,
          stdout: "ignore",
          stderr: "pipe",
          timeout: 120_000,
        },
      ],
  projects: [{ name: "live-desktop-chromium", use: { ...devices["Desktop Chrome"] } }],
});
