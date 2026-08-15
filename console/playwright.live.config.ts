import { randomUUID } from "node:crypto";

import { defineConfig, devices } from "@playwright/test";
import { acquirePlaywrightPortLease } from "./scripts/playwright-port-pool";

const configuredApiPort = process.env.FDAI_E2E_OPERATOR_API_PORT;
const configuredFrontendPort = process.env.FDAI_E2E_FRONTEND_PORT;
const externalStack = process.env.FDAI_E2E_BASE_URL !== undefined;
const portLease =
  externalStack || configuredApiPort !== undefined || configuredFrontendPort !== undefined
    ? null
    : acquirePlaywrightPortLease();
const apiPort = Number(configuredApiPort ?? portLease?.operatorApiPort ?? "8020");
const frontendPort = Number(configuredFrontendPort ?? portLease?.frontendPort ?? "5275");
const loopbackHost = "[::1]";
const defaultBaseURL = `http://${loopbackHost}:${frontendPort}`;
const baseURL = process.env.FDAI_E2E_BASE_URL ?? defaultBaseURL;
const storageState = process.env.FDAI_E2E_STORAGE_STATE;
const testBearer = process.env.FDAI_E2E_BEARER ?? randomUUID();
process.env.FDAI_E2E_BEARER = testBearer;

export default defineConfig({
  testDir: "./tests/live-e2e",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: "list",
  outputDir: portLease ? `test-results/live/slot-${portLease.slot}` : "test-results/live/external",
  timeout: 30_000,
  use: {
    baseURL,
    ...(storageState ? { storageState } : {}),
    ...(!externalStack ? { extraHTTPHeaders: { Authorization: `Bearer ${testBearer}` } } : {}),
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  ...(!externalStack
    ? {
        webServer: [
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
            timeout: 60_000,
          },
          {
            command:
              `VITE_DEV_MODE=1 VITE_LOCAL_AZURE_CLI_AUTH=0 VITE_LOCAL_LOGIN_PROMPT=0 ` +
              `VITE_OPERATOR_API_BASE_URL=http://${loopbackHost}:${apiPort} ` +
              `VITE_INGESTION_API_BASE_URL=http://127.0.0.1:8011 ` +
              `npm run dev -- --host ::1 --port ${frontendPort} --strictPort`,
            wait: { stdout: /ready in/ },
            stdout: "ignore",
            stderr: "pipe",
            timeout: 60_000,
          },
        ],
      }
    : {}),
  projects: [{ name: "live-desktop-chromium", use: { ...devices["Desktop Chrome"] } }],
});
