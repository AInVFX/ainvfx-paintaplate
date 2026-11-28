import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { modelsBehind } from "../../web/models.mjs";
import { resultFlows, STEP_FLOWS } from "../../web/logic.mjs";

// The models behind a result, as the Models and licences dialog and an export's MODELS.md find them: the workflows of the
// result's edits and of its render's steps (resultFlows, STEP_FLOWS), each workflow's model files, matched to the registry.
const registry = JSON.parse(readFileSync(new URL("../../web/models.json", import.meta.url)));
const prompt = (name) => JSON.parse(readFileSync(new URL(`../../web/workflows/${name}.json`, import.meta.url))).prompt ??
  JSON.parse(readFileSync(new URL(`../../web/workflows/${name}.json`, import.meta.url)));
const ids = (workflows) => modelsBehind(registry, workflows, prompt).map((m) => m.id);
const ran = (...steps) => steps.flatMap((s) => STEP_FLOWS[s]);

test("the models behind a result follow its edits and its render's steps", () => {
  const fluid = ids(resultFlows({ fluid: true }));
  assert.ok(fluid.includes("fluid") && fluid.includes("ltx") && !fluid.includes("klein") && !fluid.includes("sam"));
  const erase = ids(resultFlows({ tools: ["erase"], render: ran("erase", "clean", "comp", "cleanfull", "trackfull", "review", "export") }));
  assert.ok(["klein", "klein-upsampler", "sam", "inoutpaint", "ltx"].every((i) => erase.includes(i)) && !erase.includes("ripple"));
  const paint = ids(resultFlows({ tools: ["paint"], render: ran("shot", "track", "comp", "full", "trackfull", "hdr", "review", "export") }));
  assert.ok(paint.includes("ripple") && paint.includes("hdr") && !paint.includes("inoutpaint"));
  assert.deepEqual(resultFlows({}), []);
});
