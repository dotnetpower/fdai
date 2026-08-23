import assert from "node:assert/strict";
import test from "node:test";

import {
  NETWORK_BOUNDARY_ROLES,
  NETWORK_CONNECTION_KINDS,
  NETWORK_CONNECTION_LABELS,
  NETWORK_DIRECTIONS,
  NETWORK_EVIDENCE_POSTURES,
  NETWORK_LAYOUT_PRESETS,
  NETWORK_PATH_STATUSES,
  NETWORK_POLICIES,
  NETWORK_TRAFFIC_CLASSES,
  networkConnectionLabel,
  networkVocabularyHas,
} from "../src/index.js";

test("exports unique non-empty canonical vocabulary sets", () => {
  for (const values of [
    NETWORK_BOUNDARY_ROLES,
    NETWORK_CONNECTION_KINDS,
    NETWORK_DIRECTIONS,
    NETWORK_EVIDENCE_POSTURES,
    NETWORK_LAYOUT_PRESETS,
    NETWORK_PATH_STATUSES,
    NETWORK_POLICIES,
    NETWORK_TRAFFIC_CLASSES,
  ]) {
    assert.ok(values.length > 0);
    assert.equal(new Set(values).size, values.length);
    assert.ok(values.every((value) => /^[a-z][a-z0-9_-]*$/.test(value)));
    assert.ok(Object.isFrozen(values));
  }
});

test("labels every connection kind and rejects unknown values", () => {
  assert.deepEqual(Object.keys(NETWORK_CONNECTION_LABELS).sort(), [...NETWORK_CONNECTION_KINDS].sort());
  assert.equal(networkConnectionLabel("vnet-peering"), "VNet peering");
  assert.equal(networkVocabularyHas(NETWORK_CONNECTION_KINDS, "private-link"), true);
  assert.equal(networkVocabularyHas(NETWORK_CONNECTION_KINDS, "guessed-route"), false);
});
