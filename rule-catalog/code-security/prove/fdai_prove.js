'use strict';
/*
 * FDAI proof harness for JavaScript: run inside the disposable code-build-prove sandbox only.
 *
 * Node.js standard library only. For each target it loads the module that holds the fix site
 * through a loader that replaces every package with an inert stub and the sink modules
 * (child_process, fs, vm) with recording hooks that never perform the real effect and return an
 * inert stub, so execution continues past one sink to the next. The global eval
 * and Function are recording hooks too. It then calls every function the module exports or
 * registers whose source contains the fix-site line, with the marker in every caller-controlled
 * input. A target is `proven` only when the marker reaches the dangerous argument of a hooked sink
 * in the shape the class predicate requires.
 *
 * This file is a catalog asset, not an FDAI module: the proof lane copies it into the sandbox.
 *
 * Usage: node fdai_prove.js SOURCE_ROOT TARGETS_JSON
 */

const Module = require('module');
const path = require('path');
const realFs = require('fs');

const MARKER = 'FDAICANARYXY';
const PAYLOADS = {
  command_injection: 'x;' + MARKER,
  code_injection: MARKER,
  sql_injection: "x'" + MARKER,
  path_traversal: '../../' + MARKER,
};
const PER_TARGET_MS = 5000;
const writeOut = process.stdout.write.bind(process.stdout);
const functionText = Function.prototype.toString;
let active = 'code_injection';
let hits = [];

function text(value) {
  if (typeof value === 'string') return value;
  if (Buffer.isBuffer(value)) return value.toString('latin1');
  if (Array.isArray(value)) return value.map(text).join(' ');
  if (value === null || value === undefined) return '';
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value) || '';
    } catch (error) {
      return '';
    }
  }
  return String(value);
}

// True when the marker appears outside any quoted span.
function unquoted(value, before) {
  let quote = null;
  for (let i = 0; i < value.length; i += 1) {
    const ch = value[i];
    if (quote) {
      if (ch === '\\' && quote !== "'") i += 1;
      else if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'" || ch === '`') {
      quote = ch;
      continue;
    }
    if (value.startsWith(MARKER, i) && before(value.slice(0, i))) return true;
  }
  return false;
}

const PREDICATES = {
  command_injection: (v) => unquoted(v, (head) => /[;&|]\s*$/.test(head)),
  code_injection: (v) => unquoted(v, (head) => !/[\w$]$/.test(head)),
  sql_injection: (v) => v.includes("x'" + MARKER) && !v.includes("x''" + MARKER)
    && !v.includes("x\\'" + MARKER),
  path_traversal: (v) => v.includes('../../' + MARKER),
};

let site = { file: '', line: 0 };

// The first stack frame outside this harness must be the fix-site file and line.
function calledFromSite() {
  const holder = {};
  const limit = Error.stackTraceLimit;
  Error.stackTraceLimit = 20;
  Error.captureStackTrace(holder, calledFromSite);
  Error.stackTraceLimit = limit;
  for (const frame of String(holder.stack).split('\n').slice(1)) {
    const match = /\(?((?:\/|[A-Za-z]:)[^()]*?):(\d+):\d+\)?\s*$/.exec(frame);
    if (!match || match[1] === __filename) continue;
    return match[1] === site.file && Number(match[2]) === site.line;
  }
  return false;
}

function record(sink, classes, value) {
  if (classes.includes(active) && PREDICATES[active](text(value)) && calledFromSite()) {
    hits.push(sink);
  }
}

function hook(sink, classes, pick) {
  return function recording(...args) {
    record(sink, classes, pick(args));
    return stub();
  };
}

const first = (args) => args[0];
const withShell = (args) => {
  const options = args.find((item) => item && typeof item === 'object' && !Array.isArray(item));
  return options && options.shell ? [args[0], ...(Array.isArray(args[1]) ? args[1] : [])] : '';
};
const COMMAND = ['command_injection'];
const CODE = ['code_injection'];
const PATHS = ['path_traversal'];
const SQL_METHODS = new Set(['query', 'execute', 'raw', 'exec', 'all', 'get', 'run', 'prepare']);

const childProcess = {
  exec: hook('child_process.exec', COMMAND, first),
  execSync: hook('child_process.execSync', COMMAND, first),
  spawn: hook('child_process.spawn', COMMAND, withShell),
  spawnSync: hook('child_process.spawnSync', COMMAND, withShell),
  execFile: hook('child_process.execFile', COMMAND, withShell),
  execFileSync: hook('child_process.execFileSync', COMMAND, withShell),
  fork: hook('child_process.fork', COMMAND, () => ''),
};
const FS_SINKS = [
  'readFile', 'readFileSync', 'writeFile', 'writeFileSync', 'appendFile', 'appendFileSync',
  'createReadStream', 'createWriteStream', 'unlink', 'unlinkSync', 'rm', 'rmSync', 'open',
  'openSync', 'readdir', 'readdirSync',
];
function fsHooks(base) {
  const hooked = { ...base };
  for (const name of FS_SINKS) {
    if (typeof base[name] === 'function') hooked[name] = hook(`fs.${name}`, PATHS, first);
  }
  return hooked;
}
const vmHooks = {
  runInThisContext: hook('vm.runInThisContext', CODE, first),
  runInNewContext: hook('vm.runInNewContext', CODE, first),
  runInContext: hook('vm.runInContext', CODE, first),
  compileFunction: hook('vm.compileFunction', CODE, first),
  Script: hook('vm.Script', CODE, first),
};

function stub() {
  const target = function stubbed() {};
  return new Proxy(target, {
    get(_, key) {
      if (key === 'then' || typeof key === 'symbol') return undefined;
      if (SQL_METHODS.has(key)) return sqlHook(`*.${String(key)}`);
      return stub();
    },
    apply(_, __, args) {
      const callback = args.find((item) => typeof item === 'function');
      return callback && args.length === 1 ? callback : stub();
    },
    construct() {
      return stub();
    },
  });
}
function sqlHook(sink) {
  return function recording(...args) {
    record(sink, ['sql_injection'], typeof args[0] === 'object' ? args[0] && args[0].sql : args[0]);
    return stub();
  };
}

const registered = [];
function router() {
  const app = stub();
  return new Proxy(app, {
    get(_, key) {
      if (typeof key === 'symbol') return undefined;
      return (...args) => {
        for (const item of args) if (typeof item === 'function') registered.push(item);
        return router();
      };
    },
    apply(_, __, args) {
      for (const item of args) if (typeof item === 'function') registered.push(item);
      return router();
    },
  });
}

const BUILTIN_HOOKS = {
  child_process: childProcess,
  fs: fsHooks(realFs),
  'fs/promises': fsHooks(realFs.promises),
  vm: vmHooks,
};
const STUBBED_BUILTINS = new Set(['http', 'https', 'net', 'tls', 'dgram', 'cluster', 'worker_threads']);
const originalLoad = Module._load;
Module._load = function load(request, parent, isMain) {
  const bare = request.replace(/^node:/, '');
  if (Object.prototype.hasOwnProperty.call(BUILTIN_HOOKS, bare)) return BUILTIN_HOOKS[bare];
  if (STUBBED_BUILTINS.has(bare)) return stub();
  if (Module.isBuiltin(request)) return originalLoad.apply(this, arguments);
  if (request.startsWith('.') || request.startsWith('/')) {
    return originalLoad.apply(this, arguments);
  }
  return bare === 'express' || bare === 'koa-router' || bare === '@koa/router' ? routerModule() : stub();
};
function routerModule() {
  const factory = (...args) => router(...args);
  factory.Router = () => router();
  return new Proxy(factory, {
    get(target, key) {
      if (key in target) return target[key];
      return typeof key === 'symbol' ? undefined : stub();
    },
  });
}

globalThis.eval = hook('eval', CODE, first);
globalThis.Function = hook('Function', CODE, (args) => args[args.length - 1]);
const realSetTimeout = setTimeout;
globalThis.setTimeout = function guarded(fn, ...rest) {
  if (typeof fn === 'string') return hook('setTimeout', CODE, first)(fn);
  return realSetTimeout(fn, ...rest);
};

function canaryMap() {
  return new Proxy({}, {
    get(_, key) {
      if (typeof key === 'symbol' || key === 'then' || key === 'toJSON') return undefined;
      return PAYLOADS[active];
    },
    has() {
      return true;
    },
  });
}
function fakeRequest() {
  const value = PAYLOADS[active];
  const request = {
    body: canaryMap(), query: canaryMap(), params: canaryMap(), headers: canaryMap(),
    cookies: canaryMap(), signedCookies: canaryMap(), session: canaryMap(),
    url: '/' + value, originalUrl: '/' + value, path: '/' + value, method: 'POST',
    get: () => value, header: () => value, param: () => value,
  };
  return new Proxy(request, {
    get(target, key) {
      if (key in target) return target[key];
      return typeof key === 'symbol' || key === 'then' ? undefined : stub();
    },
  });
}

function spans(wanted) {
  return (fn) => {
    try {
      return functionText.call(fn).includes(wanted);
    } catch (error) {
      return false;
    }
  };
}

function functionsIn(value, depth, found) {
  if (depth > 2 || value === null || value === undefined) return;
  if (typeof value === 'function') {
    found.add(value);
    if (depth < 2) for (const key of Object.keys(value)) functionsIn(value[key], depth + 1, found);
  } else if (typeof value === 'object') {
    for (const key of Object.keys(value)) functionsIn(value[key], depth + 1, found);
  }
}

function candidates(module, wanted) {
  const found = new Set();
  functionsIn(module, 0, found);
  for (const item of registered) found.add(item);
  return [...found].filter(spans(wanted));
}

async function settle(result) {
  if (result && typeof result.then === 'function') {
    await Promise.race([result, new Promise((resolve) => realSetTimeout(resolve, PER_TARGET_MS))]);
  }
}

// Call one function and return the functions it assigned to its receiver or returned, so
// handlers created inside constructors and factories are reached too.
async function call(fn) {
  const value = PAYLOADS[active];
  const args = fn.length >= 2 ? [fakeRequest(), stub(), () => undefined] : [value, value, value];
  const receiver = {};
  const produced = new Set();
  try {
    const result = fn.apply(receiver, args);
    functionsIn(result, 1, produced);
    await settle(result);
  } catch (error) {
    if (!hits.length && error instanceof TypeError) {
      try {
        functionsIn(new fn(...args.map(() => stub())), 1, produced); // eslint-disable-line new-cap
      } catch (inner) {
        // Not constructible; only recorded hits matter.
      }
    }
  }
  functionsIn(receiver, 1, produced);
  return produced;
}

async function prove(root, target) {
  const outcome = (fields) => ({ issue_id: target.issue_id, ...fields });
  if (!Object.prototype.hasOwnProperty.call(PAYLOADS, target.weakness_class)) {
    return outcome({ outcome: 'not_proven', reason: 'unsupported_class' });
  }
  const file = path.resolve(root, target.path);
  if (!file.startsWith(path.resolve(root) + path.sep)) {
    return outcome({ outcome: 'not_proven', reason: 'outside_source' });
  }
  active = target.weakness_class;
  site = { file, line: Number(target.line) };
  hits = [];
  registered.length = 0;
  let loaded;
  let wanted = '';
  try {
    wanted = (realFs.readFileSync(file, 'utf8').split('\n')[Number(target.line) - 1] || '').trim();
    delete require.cache[file];
    loaded = require(file);
  } catch (error) {
    if (!hits.length) return outcome({ outcome: 'not_proven', reason: 'import_failed' });
  }
  if (!wanted) return outcome({ outcome: 'not_proven', reason: 'no_function' });
  const queue = candidates(loaded, wanted);
  const seen = new Set();
  const matches = spans(wanted);
  while (queue.length && !hits.length && seen.size < 50) {
    const fn = queue.shift();
    if (seen.has(fn)) continue;
    seen.add(fn);
    for (const produced of await call(fn)) {
      if (!seen.has(produced) && matches(produced)) queue.push(produced);
    }
  }
  if (hits.length) return outcome({ outcome: 'proven', reason: 'canary_reached_sink', sink: hits[0] });
  return outcome({ outcome: 'not_proven', reason: 'canary_not_observed' });
}

async function main() {
  const [root, targetsPath] = process.argv.slice(2);
  const targets = JSON.parse(realFs.readFileSync(targetsPath, 'utf8'));
  console.log = console.info = console.warn = console.error = console.debug = () => undefined;
  process.stdout.write = () => true;
  process.on('unhandledRejection', () => undefined);
  process.on('uncaughtException', () => undefined);
  for (const target of targets) {
    let result;
    try {
      result = await prove(root, target);
    } catch (error) {
      result = { issue_id: target.issue_id, outcome: 'not_proven', reason: 'harness_error' };
    }
    writeOut(JSON.stringify(result) + '\n');
  }
  process.exit(0);
}

main();
