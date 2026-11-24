// A scene saved before the fluid shot was History's first row opens through one conversion (logic.sceneV7)
import { test } from "node:test";
import assert from "node:assert/strict";
import { sceneV7 } from "../../web/logic.mjs";

const keys = [{ frame: 0, strokes: [] }, { frame: 32, strokes: [] }];

test("a version 6 scene's fluid shot becomes History's first row, and its 16-bit turns Finish > SDR to HDR on", () => {
  const v6 = { format: "paintaplate-scene", version: 6, deliver: { hdr: false, upscale: false }, edits: [{ tool: "paint", prompt: "a lantern", seed: 7, strokes: [] }],
    fluid: { prompt: "thick white smoke", seed: 42, depth: 16, made: true, on: true, keys } };
  const v7 = sceneV7(v6);
  assert.equal(v7.version, 7);
  assert.equal(v7.fluid, undefined);
  assert.deepEqual(v7.edits, [{ tool: "fluid", prompt: "thick white smoke", seed: 42, on: true, made: true, keys }, v6.edits[0]]);
  assert.deepEqual(v7.deliver, { hdr: true, upscale: false });
  assert.equal(v6.version, 6, "the scene as read stays as it was");
});

test("an 8-bit fluid shot keeps the switch as the scene saved it; version 5 named the switch hdr", () => {
  assert.equal(sceneV7({ version: 6, deliver: { hdr: true }, edits: [], fluid: { depth: 8, keys } }).deliver.hdr, true);
  assert.equal(sceneV7({ version: 6, deliver: { hdr: false }, edits: [], fluid: { depth: 8, keys } }).deliver.hdr, false);
  assert.equal(sceneV7({ version: 5, hdr: true, edits: [] }).deliver.hdr, true);
  assert.equal(sceneV7({ version: 5, hdr: true, edits: [] }).hdr, undefined);
  assert.deepEqual(sceneV7({ version: 6, edits: [], fluid: { keys, made: false } }).edits[0].made, false, "keyframes never generated open as keyframes");
});

test("a scene of version 7, or one with no fluid shot, keeps its edits as they are", () => {
  const v7 = { version: 7, edits: [{ tool: "fluid", keys }], deliver: { hdr: true } };
  assert.equal(sceneV7(v7), v7);
  assert.deepEqual(sceneV7({ version: 4, edits: [{ tool: "erase" }] }).edits, [{ tool: "erase" }]);
});
