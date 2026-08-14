import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, describe, expect, test } from "vitest";

import {
  acquirePlaywrightPortLease,
  PLAYWRIGHT_FRONTEND_PORT_START,
  PLAYWRIGHT_OPERATOR_API_PORT_START,
  PLAYWRIGHT_PORT_POOL_SIZE,
  type PlaywrightPortLease,
} from "./playwright-port-pool";

const roots: string[] = [];
const leases: PlaywrightPortLease[] = [];

function testRoot(): string {
  const root = mkdtempSync(join(tmpdir(), "fdai-playwright-port-pool-test-"));
  roots.push(root);
  return root;
}

function acquire(lockRoot: string, pid: number): PlaywrightPortLease {
  const lease = acquirePlaywrightPortLease({
    lockRoot,
    pid,
    environment: {},
    isProcessAlive: () => true,
    arePortsAvailable: () => true,
    registerProcessCleanup: false,
  });
  leases.push(lease);
  return lease;
}

afterEach(() => {
  for (const lease of leases.splice(0)) lease.release();
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});

describe("Playwright port pool", () => {
  test("leases and releases the first frontend and Operator API port pair", () => {
    const root = testRoot();
    const lease = acquire(root, 101);

    expect(lease).toMatchObject({
      slot: 0,
      frontendPort: PLAYWRIGHT_FRONTEND_PORT_START,
      operatorApiPort: PLAYWRIGHT_OPERATOR_API_PORT_START,
    });
    expect(existsSync(join(root, "slot-0", "owner.json"))).toBe(true);

    lease.release();
    expect(existsSync(join(root, "slot-0"))).toBe(false);
  });

  test("gives concurrent sessions distinct slots", () => {
    const root = testRoot();

    const first = acquire(root, 201);
    const second = acquire(root, 202);

    expect([first.slot, second.slot]).toEqual([0, 1]);
    expect(second.frontendPort).toBe(PLAYWRIGHT_FRONTEND_PORT_START + 1);
    expect(second.operatorApiPort).toBe(PLAYWRIGHT_OPERATOR_API_PORT_START + 1);
  });

  test("reuses the parent slot when a Playwright worker evaluates the config", () => {
    const root = testRoot();
    const environment: NodeJS.ProcessEnv = {};
    const parent = acquirePlaywrightPortLease({
      lockRoot: root,
      pid: 251,
      environment,
      isProcessAlive: () => true,
      arePortsAvailable: () => true,
      registerProcessCleanup: false,
    });
    leases.push(parent);

    const worker = acquirePlaywrightPortLease({ lockRoot: root, environment });

    expect(worker).toMatchObject({
      slot: parent.slot,
      frontendPort: parent.frontendPort,
      operatorApiPort: parent.operatorApiPort,
    });
  });

  test("skips a slot whose real ports are unavailable", () => {
    const root = testRoot();
    const checkedPorts: readonly number[][] = [];
    const lease = acquirePlaywrightPortLease({
      lockRoot: root,
      pid: 301,
      environment: {},
      isProcessAlive: () => true,
      arePortsAvailable: (ports) => {
        checkedPorts.push([...ports]);
        return ports[0] !== PLAYWRIGHT_FRONTEND_PORT_START;
      },
      registerProcessCleanup: false,
    });
    leases.push(lease);

    expect(lease.slot).toBe(1);
    expect(checkedPorts).toHaveLength(2);
  });

  test("reclaims a lease whose owner process exited", () => {
    const root = testRoot();
    const lockPath = join(root, "slot-0");
    mkdirSync(lockPath, { recursive: true });
    writeFileSync(
      join(lockPath, "owner.json"),
      `${JSON.stringify({
        pid: 999_999,
        nonce: "stale",
        frontendPort: PLAYWRIGHT_FRONTEND_PORT_START,
        operatorApiPort: PLAYWRIGHT_OPERATOR_API_PORT_START,
      })}\n`,
    );

    const lease = acquirePlaywrightPortLease({
      lockRoot: root,
      pid: 401,
      environment: {},
      isProcessAlive: () => false,
      arePortsAvailable: () => true,
      registerProcessCleanup: false,
    });
    leases.push(lease);

    expect(lease.slot).toBe(0);
  });

  test("fails with an actionable error after all ten slots are leased", () => {
    const root = testRoot();
    for (let slot = 0; slot < PLAYWRIGHT_PORT_POOL_SIZE; slot += 1) acquire(root, 500 + slot);

    expect(() => acquire(root, 999)).toThrow(
      `frontend port ${PLAYWRIGHT_FRONTEND_PORT_START}-${PLAYWRIGHT_FRONTEND_PORT_START + 9}`,
    );
  });
});
