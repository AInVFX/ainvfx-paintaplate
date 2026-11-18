// The Preview menu's choices as tests/ui_live.py --preview stores them: the page reads each one back as that choice.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readPreview } from "../../web/logic.mjs";

test("off, latent, half and quarter as ui_live.py stores them read back as the page's choices", () => {
  assert.deepEqual(["off", "latent", "2", "4"].map(readPreview), ["off", "latent", 2, 4]);
});
