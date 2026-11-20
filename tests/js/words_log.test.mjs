// The log says what happened in plain words: the viewer repeats a missing frame, a mask covers an object, SeedVR2 upscales,
// results already made are reused, and a job is named as a person reads it (« Memory freed before the shot »), never by
// the id of its workflow.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as logic from "../../web/logic.mjs";

const read = (f) => readFileSync(new URL(`../../web/${f}`, import.meta.url), "utf8");
const code = (src) => src.split("\n").map((l) => l.split(/(?<![:"'`])\/\/ /)[0]).join("\n"); // each line without its comment
const app = code(read("app.mjs")), all = app + code(read("logic.mjs")) + code(read("comfy.mjs"));

test("no idiom that a reader who is not fluent must decode", () => {
  const idioms = ["frame before holds", "mask holds", "restored from", "SeedVR2 restores the plate", "composed from", "come from the job index",
    "for now:", "was not cleared", "Keyframes sit", "is in use: right-click", "the models of ${last}"];
  assert.deepEqual(idioms.filter((i) => all.includes(i)), []);
});

test("a keyframe snaps to the first frame, the last frame or every 8 frames between", () => {
  assert.equal(logic.keyframeSlotLine(17), "Keyframes snap to the first frame, the last frame or every 8 frames between: frame 17.");
});

test("every workflow the page posts has a name for the log", () => {
  const kinds = JSON.parse(app.match(/const WORKFLOWS = (\[[^\]]*\]);/)[1]);
  assert.deepEqual(kinds.filter((k) => !logic.JOB_NAME?.[k]), []);
  assert.match(all, /Memory freed before \$\{JOB_NAME\[name\] \?\? name\}: /);
});
