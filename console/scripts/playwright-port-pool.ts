import { randomUUID } from "node:crypto";
import {
  mkdirSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

export const PLAYWRIGHT_PORT_POOL_SIZE = 10;
export const PLAYWRIGHT_FRONTEND_PORT_START = 5274;
export const PLAYWRIGHT_OPERATOR_API_PORT_START = 8020;

const PORT_SLOT_ENV = "FDAI_PLAYWRIGHT_PORT_SLOT";
const INCOMPLETE_LEASE_GRACE_MS = 30_000;
const PORT_PROBE_SOURCE = String.raw`
const net = require("node:net");
const ports = process.argv.slice(1).map(Number);
const checks = ports.flatMap((port) => [["127.0.0.1", port], ["::1", port]]);
let index = 0;
const checkNext = () => {
  if (index === checks.length) process.exit(0);
  const [host, port] = checks[index++];
  const server = net.createServer();
  server.unref();
  server.once("error", () => process.exit(1));
  server.listen({ host, port, exclusive: true }, () => server.close(checkNext));
};
checkNext();
`;

interface LeaseOwner {
  readonly pid: number;
  readonly nonce: string;
  readonly frontendPort: number;
  readonly operatorApiPort: number;
}

interface PortPoolOptions {
  readonly lockRoot?: string;
  readonly pid?: number;
  readonly environment?: NodeJS.ProcessEnv;
  readonly now?: () => number;
  readonly isProcessAlive?: (pid: number) => boolean;
  readonly arePortsAvailable?: (ports: readonly number[]) => boolean;
  readonly registerProcessCleanup?: boolean;
}

export interface PlaywrightPortLease {
  readonly slot: number;
  readonly frontendPort: number;
  readonly operatorApiPort: number;
  release(): void;
}

function defaultLockRoot(): string {
  const userId = typeof process.getuid === "function" ? process.getuid() : "user";
  return join(tmpdir(), `fdai-playwright-port-pool-${userId}`);
}

function processIsAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function portsAreAvailable(ports: readonly number[]): boolean {
  const result = spawnSync(process.execPath, ["-e", PORT_PROBE_SOURCE, ...ports.map(String)], {
    stdio: "ignore",
    timeout: 2_000,
  });
  return result.status === 0;
}

function readOwner(lockPath: string): LeaseOwner | null {
  try {
    const value = JSON.parse(readFileSync(join(lockPath, "owner.json"), "utf8")) as Partial<LeaseOwner>;
    if (
      typeof value.pid !== "number" ||
      typeof value.nonce !== "string" ||
      typeof value.frontendPort !== "number" ||
      typeof value.operatorApiPort !== "number"
    ) {
      return null;
    }
    return value as LeaseOwner;
  } catch {
    return null;
  }
}

function reclaimStaleLock(
  lockPath: string,
  now: () => number,
  isProcessAlive: (pid: number) => boolean,
): boolean {
  const owner = readOwner(lockPath);
  if (owner) {
    if (isProcessAlive(owner.pid)) return false;
  } else {
    try {
      if (now() - statSync(lockPath).mtimeMs < INCOMPLETE_LEASE_GRACE_MS) return false;
    } catch {
      return true;
    }
  }
  rmSync(lockPath, { recursive: true, force: true });
  return true;
}

function createLock(lockPath: string): boolean {
  try {
    mkdirSync(lockPath);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") return false;
    throw error;
  }
}

/**
 * Atomically leases one frontend and Operator API port pair for a Playwright process tree.
 * The parent owns the lock; workers inherit its slot, and normal process exit releases it.
 */
export function acquirePlaywrightPortLease(
  options: PortPoolOptions = {},
): PlaywrightPortLease {
  const environment = options.environment ?? process.env;
  const inheritedSlot = Number(environment[PORT_SLOT_ENV]);
  if (
    Number.isInteger(inheritedSlot) &&
    inheritedSlot >= 0 &&
    inheritedSlot < PLAYWRIGHT_PORT_POOL_SIZE
  ) {
    return {
      slot: inheritedSlot,
      frontendPort: PLAYWRIGHT_FRONTEND_PORT_START + inheritedSlot,
      operatorApiPort: PLAYWRIGHT_OPERATOR_API_PORT_START + inheritedSlot,
      release: () => undefined,
    };
  }

  const lockRoot = options.lockRoot ?? defaultLockRoot();
  const pid = options.pid ?? process.pid;
  const now = options.now ?? Date.now;
  const isProcessAlive = options.isProcessAlive ?? processIsAlive;
  const arePortsAvailable = options.arePortsAvailable ?? portsAreAvailable;
  mkdirSync(lockRoot, { recursive: true, mode: 0o700 });

  for (let slot = 0; slot < PLAYWRIGHT_PORT_POOL_SIZE; slot += 1) {
    const frontendPort = PLAYWRIGHT_FRONTEND_PORT_START + slot;
    const operatorApiPort = PLAYWRIGHT_OPERATOR_API_PORT_START + slot;
    const lockPath = join(lockRoot, `slot-${slot}`);

    if (!createLock(lockPath)) {
      if (!reclaimStaleLock(lockPath, now, isProcessAlive) || !createLock(lockPath)) continue;
    }

    if (!arePortsAvailable([frontendPort, operatorApiPort])) {
      rmSync(lockPath, { recursive: true, force: true });
      continue;
    }

    const owner: LeaseOwner = {
      pid,
      nonce: randomUUID(),
      frontendPort,
      operatorApiPort,
    };
    writeFileSync(join(lockPath, "owner.json"), `${JSON.stringify(owner)}\n`, {
      encoding: "utf8",
      mode: 0o600,
    });
    environment[PORT_SLOT_ENV] = String(slot);

    let released = false;
    const release = (): void => {
      if (released) return;
      released = true;
      const currentOwner = readOwner(lockPath);
      if (currentOwner?.pid === owner.pid && currentOwner.nonce === owner.nonce) {
        rmSync(lockPath, { recursive: true, force: true });
      }
    };
    if (options.registerProcessCleanup !== false) process.once("exit", release);

    return { slot, frontendPort, operatorApiPort, release };
  }

  throw new Error(
    "No Playwright port slot is available. Stop a stale test session or free one frontend port " +
      `${PLAYWRIGHT_FRONTEND_PORT_START}-${PLAYWRIGHT_FRONTEND_PORT_START + PLAYWRIGHT_PORT_POOL_SIZE - 1} ` +
      `and its paired Operator API port ${PLAYWRIGHT_OPERATOR_API_PORT_START}-` +
      `${PLAYWRIGHT_OPERATOR_API_PORT_START + PLAYWRIGHT_PORT_POOL_SIZE - 1}.`,
  );
}
