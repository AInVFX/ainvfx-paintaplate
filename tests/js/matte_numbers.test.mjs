// Follow Matte names the plate's frames by their own numbers: the matte workflow takes the plate's first frame number,
// 1 by default, as a movie counts.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { instantiate } from "../../web/graph.mjs";
import { parseWorkflow } from "../../web/logic.mjs";

const WF = parseWorkflow(JSON.parse(readFileSync(new URL("../../web/workflows/matte.json", import.meta.url), "utf8")));
const follow = (values) => Object.values(instantiate(WF, "matte", values).nodes).find((n) => n.class_type === "PaintAPlate_FollowMatte");
const VALUES = { path: "plates/car.mp4", mask: "matte_b.png", width: 928, height: 512 };

test("the matte workflow gives Follow Matte the plate's first frame number", () => {
  assert.equal(follow({ ...VALUES, first_frame: 480 }).inputs.first_frame, 480);
});

test("with no number, Follow Matte counts as a movie does, from 1", () => {
  assert.equal(follow(VALUES).inputs.first_frame, 1);
});

test("the page gives the matte job the plate's first frame number, as its timeline counts", () => {
  const app = readFileSync(new URL("../../web/app.mjs", import.meta.url), "utf8");
  const track = app.slice(app.indexOf("async function track("), app.indexOf("function mattesOf("));
  assert.ok(track.includes("const p = S.plate,"));
  const call = track.slice(track.indexOf('run("matte", {'), track.indexOf('{ kind: "matte", progress }'));
  assert.ok(call.includes("first_frame: p.first,"), call);
});
