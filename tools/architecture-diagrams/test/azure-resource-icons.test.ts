import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  azureDiagramIconForResourceType,
  azureDiagramResourceIconEntries,
} from "../src/model/azure-resource-icons.js";

test("maps reviewed Azure network resource types to allowlisted official icons", async () => {
  const lock = JSON.parse(await readFile(
    new URL("../assets/azure/icons.lock.json", import.meta.url),
    "utf8",
  )) as { icons: Record<string, unknown> };
  for (const [resourceType, icon] of azureDiagramResourceIconEntries()) {
    assert.ok(lock.icons[icon], `${resourceType} maps to missing icon ${icon}`);
  }
  assert.equal(
    azureDiagramIconForResourceType("Microsoft.Network/virtualNetworks"),
    "virtual-network",
  );
  assert.equal(azureDiagramIconForResourceType("unknown/provider"), undefined);
});
