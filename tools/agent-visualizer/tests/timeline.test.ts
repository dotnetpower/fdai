import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { scenarios } from "../scenarios";
import { agents } from "../src/agents";
import { activityEnergy, advanceTime, advancePlayback, DEFAULT_PLAYBACK_SPEED, formatTime, projectTimeline } from "../src/playback/timeline";
import { seededRandom, makeNeuralGeometry } from "../src/scene/geometry";
import { t } from "../src/ui/i18n";
import en from "../src/ui/messages.en.json";
import ko from "../src/ui/messages.ko.json";
import { codeGraph, pythonFunctions, functionById, functionsFor } from "../src/source-graph";
import { eventFlowAt, argSlotsBetween } from "../src/playback/event-flow";
import { ARG_WORKFLOWS, independentActivityAt, independentWorkloads } from "../src/playback/workloads";

test("the visualization preserves all 15 canonical pantheon identities", () => {
  const source = readFileSync(new URL("../../../services/core-control-plane/src/fdai/agents/_framework/pantheon.py", import.meta.url), "utf8");
  const names = [...source.matchAll(/^\s+name="([^"]+)",$/gm)].map((match) => match[1]);
  assert.deepEqual(agents.map((agent) => agent.id).sort(), names.sort());
  assert.equal(new Set(agents.map((agent) => agent.id)).size, 15);
  for (const agent of agents) {
    assert.equal(agent.capabilities.length, 3);
    assert.ok(agent.role.en && agent.role.ko);
  }
});

test("authored scenarios are bounded, ordered, localized, and explicitly synthetic", () => {
  const names = new Set(agents.map((agent) => agent.id));
  for (const scenario of scenarios) {
    assert.equal(scenario.source, "synthetic-demo");
    assert.ok(scenario.duration > 0 && scenario.duration <= 120);
    assert.ok(scenario.events.length > 0);
    let previous = -1;
    for (const event of scenario.events) {
      assert.ok(names.has(event.agent));
      if (event.from) assert.ok(names.has(event.from));
      assert.notEqual(event.agent, event.from);
      assert.ok(event.at >= previous);
      assert.ok(event.duration > 0 && event.at + event.duration <= scenario.duration);
      assert.ok(event.title.en && event.title.ko && event.detail.en && event.detail.ko);
      previous = event.at;
    }
  }
});

test("seeking is reproducible and never leaks future events or prior-scenario state", () => {
  const scenario = scenarios[0]!;
  const first = projectTimeline(scenario, 18);
  projectTimeline(scenario, 64);
  assert.deepEqual(projectTimeline(scenario, 18), first);
  assert.equal(first.latest?.agent, "Forseti");
  assert.ok(first.occurred.every((event) => event.at <= 18));
  assert.ok(first.active.every((event) => event.at + event.duration > 18));
  assert.equal(projectTimeline(scenario, -10).at, 0);
  assert.equal(projectTimeline(scenario, 999).at, scenario.duration);
  assert.equal(projectTimeline(scenarios[1]!, 0).latest?.agent, "Loki");
});

test("energy follows the scenario instead of random firing and fades to zero", () => {
  const scenario = scenarios[0]!;
  assert.equal(activityEnergy(scenario.events, 1, "Thor"), 0);
  assert.ok(activityEnergy(scenario.events, 2, "Huginn") > 0);
  assert.equal(activityEnergy(scenario.events, 20, "Huginn"), 0);
  for (let time = 0; time < scenario.duration; time++) {
    for (const agent of agents) {
      const energy = activityEnergy(scenario.events, time, agent.id);
      assert.ok(Number.isFinite(energy) && energy >= 0 && energy <= 1);
    }
  }
});

test("playback has precise speed, looping, and terminal boundaries", () => {
  assert.equal(advanceTime(10, 0.5, 2, 72, true), 11);
  assert.equal(advanceTime(71, 2, 1, 72, true), 1);
  assert.equal(advanceTime(71, 2, 1, 72, false), 72);
  assert.equal(advanceTime(10, -2, 1, 72, false), 10);
  assert.equal(formatTime(72), "01:12");
  assert.equal(formatTime(0), "00:00");
});

test("neural geometry stays stable across playback and has only canonical owners", () => {
  const one = makeNeuralGeometry();
  const two = makeNeuralGeometry();
  assert.equal(one.anchors.size, 15);
  assert.equal(one.points.length, 15 + pythonFunctions.length);
  assert.equal(one.functionPositions.size, pythonFunctions.length);
  assert.deepEqual(one.points.map((point) => point.position.toArray()), two.points.map((point) => point.position.toArray()));
  assert.ok(one.points.every((point) => point.functionId ? functionById.has(point.functionId) : point.owner && one.anchors.has(point.owner)));
  const a = seededRandom(15);
  const b = seededRandom(15);
  assert.equal(a(), b());
  one.lines.dispose();
  two.lines.dispose();
});

test("all subordinate nodes point to real Python source definitions", () => {
  const files = new Map<string, string[]>();
  for (const fn of pythonFunctions) {
    if (!files.has(fn.file)) files.set(fn.file, readFileSync(new URL(`../../../${fn.file}`, import.meta.url), "utf8").split("\n"));
    assert.match(files.get(fn.file)![fn.line - 1]!, new RegExp(`(?:async )?def ${fn.name}\\b`));
    assert.ok(fn.end_line >= fn.line);
    assert.ok(fn.owners.every((id) => agents.some((agent) => agent.id === id)));
  }
  assert.equal(functionById.size, pythonFunctions.length);
  for (const call of codeGraph.calls) {
    assert.ok(functionById.has(call.source) && functionById.has(call.target));
    assert.ok(["lexical", "declared-receiver"].includes(call.resolution));
  }
  assert.ok(functionsFor("Huginn", "_bound").some((fn) => fn.name === "_bound"));
  assert.ok(codeGraph.azure_functions.some((id) => id.endsWith("ArgRateLimiter.acquire")));
});

test("broadcasts use canonical ownership and subscriber declarations with concurrent delivery", () => {
  for (const topic of codeGraph.topics) {
    assert.ok(codeGraph.agents.find((agent) => agent.id === topic.publisher)?.publishes.includes(topic.id));
    assert.deepEqual(topic.subscribers, codeGraph.agents.filter((agent) => agent.subscribes.includes(topic.id)).map((agent) => agent.id));
    topic.publisher_functions.forEach((id) => assert.ok(functionById.has(id)));
  }
  const flow = eventFlowAt(22, scenarios[0]!);
  const run = flow.broadcasts.find((broadcast) => broadcast.topic.id === "object.action-run")!;
  assert.ok(run.subscribers.length >= 4);
  assert.ok(flow.broadcasts.length >= 2);
  run.subscribers.forEach((agent) => assert.ok(flow.active.has(agent)));
  assert.deepEqual(eventFlowAt(22, scenarios[0]!), flow);
});

test("1x is the default and Azure Resource Graph requests retain a separate three-per-display-second budget", () => {
  assert.equal(DEFAULT_PLAYBACK_SPEED, 1);
  for (const speed of [0.5, 1, 1.5, 2]) {
    const next = advancePlayback(10, 5, 1, speed, 72, true);
    assert.equal(next.time, 10 + speed);
    assert.equal(next.transportTime, 6);
    assert.equal(argSlotsBetween(5, next.transportTime).length, 3);
  }
  assert.deepEqual(advancePlayback(71, 8, 1, 2, 72, false), { time: 72, transportTime: 8.5 });
  assert.deepEqual(advancePlayback(71, 8, 1, 2, 72, true), { time: 1, transportTime: 9 });
  assert.deepEqual(advancePlayback(10, 8, 0, 2, 72, true), { time: 10, transportTime: 8 });
});

test("all 15 independent workload lanes use real functions and overlap without a global queue", () => {
  assert.equal(independentWorkloads.length, 15);
  assert.equal(new Set(independentWorkloads.map((work) => work.period)).size, 15);
  for (const work of independentWorkloads) {
    assert.ok(functionById.get(work.functionId)?.direct_owners.includes(work.agent));
    assert.ok(work.duration < work.period);
    assert.ok(work.purpose.en && work.purpose.ko);
  }
  for (let time = 0; time < 180; time += 0.25) {
    const active = independentActivityAt(time).filter((work) => work.active);
    assert.ok(active.length >= 2, `No independently concurrent work at ${time}`);
  }
  const before = independentActivityAt(0);
  const after = independentActivityAt(2);
  assert.ok(before.some((work, index) => work.active === after[index]!.active));
  assert.ok(before.some((work, index) => work.active !== after[index]!.active));
  assert.ok(ARG_WORKFLOWS.every((work) => functionById.has(work.entry) && functionById.has(work.query)));
  assert.ok(ARG_WORKFLOWS.some((work) => work.query.endsWith("AzureResourceChangeFeed.poll")));
});

test("Azure Resource Graph is three visual request slots per second, with source budget semantics preserved", () => {
  assert.equal(codeGraph.arg.requests_per_second, 3);
  assert.equal(codeGraph.arg.burst, 15);
  assert.match(codeGraph.arg.semantics, /not a polling scheduler/);
  assert.deepEqual(argSlotsBetween(0, 1), [0, 1, 2]);
  for (let second = 0; second < 100; second++) assert.equal(argSlotsBetween(second, second + 1).length, 3);
});

test("all reusable labels have readable Korean and English fallback", () => {
  assert.deepEqual(Object.keys(en).sort(), Object.keys(ko).sort());
  for (const key of Object.keys(en) as (keyof typeof en)[]) {
    assert.ok(t(key, "ko").length);
    assert.equal(t(key), en[key]);
  }
});
