import assert from "node:assert/strict";
import test from "node:test";

import { isSafeEmbeddedImageHref } from "../src/viewer/security.js";

test("viewer accepts only allowlisted embedded image payloads", () => {
  assert.equal(
    isSafeEmbeddedImageHref("data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="),
    true,
  );
  assert.equal(isSafeEmbeddedImageHref("data:image/png;base64,iVBORw0KGgo="), true);

  for (const href of [
    "https://example.com/icon.svg",
    "../icon.svg",
    "blob:https://example.com/id",
    "data:image/jpeg;base64,AA==",
    "data:image/png;base64,",
    "data:image/png;base64,AA==\nhttps://example.com/icon.svg",
  ]) {
    assert.equal(isSafeEmbeddedImageHref(href), false, href);
  }
});
