// The paint matte's workflow under a Clean edit: the page gives Follow Matte the Clean matte and how far the composite
// moves its edge; with no Clean edit, the link is dropped.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { instantiate } from "../../web/graph.mjs";
import { OPTIONAL, parseWorkflow } from "../../web/logic.mjs";

const WF = parseWorkflow(JSON.parse(readFileSync(new URL("../../web/workflows/matte.json", import.meta.url), "utf8")));
const nodes = (values) => Object.values(instantiate(WF, "matte", values).nodes);
const follow = (values) => nodes(values).find((n) => n.class_type === "PaintAPlate_FollowMatte");
const loader = (values) => nodes(values).find((n) => n._meta.title.endsWith("Clean matte under the paint"));
const VALUES = { path: "plates/car.mp4", mask: "matte_b.png", width: 928, height: 512 };

test("the Clean matte's link is optional, as in the workflow builder", () => {
  assert.deepEqual(OPTIONAL.follow_erased, ["erased"]);
});

test("with no Clean edit under the paint, Follow Matte gets no Clean matte", () => {
  assert.equal(follow(VALUES).inputs.erased, undefined);
  assert.equal(loader(VALUES), undefined); // the nodes that only fed the link go with it
});

test("under a Clean edit, Follow Matte gets the Clean matte and its edge", () => {
  const f = follow({ ...VALUES, erased: "paintaplate/plate/matte_a/", erased_edge: 0.052 });
  assert.ok(Array.isArray(f.inputs.erased));
  assert.equal(loader({ ...VALUES, erased: "paintaplate/plate/matte_a/" }).inputs.path, "paintaplate/plate/matte_a/");
  assert.equal(f.inputs.erased_edge, 0.052);
});
