import test from "node:test";
import assert from "node:assert/strict";
import { memoryBytes } from "../../web/logic.mjs";

test("View > Cache memory > Custom… reads a size in MB or GB, and refuses one outside 128 MB to 32 GB", () => {
  assert.equal(memoryBytes("1.5 GB"), 1.5e9);
  assert.equal(memoryBytes("2g"), 2e9);
  assert.equal(memoryBytes(" 800 MB "), 800e6);
  assert.equal(memoryBytes("800"), 800e6); // a number alone is MB
  assert.equal(memoryBytes("1,5 GB"), 1.5e9); // a decimal comma
  for (const no of ["5 TB", "64 MB", "40 GB", "", "lots", "-1 GB"]) assert.equal(memoryBytes(no), null, no);
});
