// The documents name an export's files as the code names them. Every file of a zip that README.md, ARCHITECTURE.md or
// TESTING.md gives after its stem (<stem>, <name>, <n>, or the name of an example plate or scene) is a name that the code
// makes for some export: a cell's label through logic.zipName (app.exportCells: the Render panel's steps, logic.X_LABELS),
// a ComfyUI graph's row, alone or among several (logic.graphRows), the models' list, or a fluid shot's zip.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { exportWords, GRAPH_KINDS, graphRows, X_LABELS, zipName } from "../../web/logic.mjs";

const read = (f) => readFileSync(new URL(`../../${f}`, import.meta.url), "utf8");
const app = read("web/app.mjs"), routes = read("routes.py");
const label = (id) => app.match(new RegExp(`id: "${id}", label: "([^"]+)"`))[1]; // a step's name in the Render panel (STAGES)
const hdrUp = (id) => app.match(new RegExp(`${id}: "([^"]+, HDR, upscaled)"`))[1]; // Upscale's step on SDR to HDR's set (labelOf)

function codeNames() {
  const cells = app.slice(app.indexOf("function exportCells("), app.indexOf("const ticked = ")); // the cells Export can zip
  const steps = [...new Set([...cells.matchAll(/name\("(\w+)"\)/g)].map(([, id]) => id))].map(label);
  const ups = [...new Set([...cells.matchAll(/name\("(up\w+)"\)/g)].map(([, id]) => id))].map(hdrUp); // Upscale's steps on SDR to HDR's set (labelOf)
  const labels = [...steps, ...ups, ...Object.values(X_LABELS), exportWords({ kind: "edits" }).elements.graph.label];
  const graphs = graphRows(Object.keys(GRAPH_KINDS)).map((g) => g.row); // several graphs: each named after what it makes
  return new Set([routes.match(/f"\{stem\}_(\w+)\.md"/)[1], app.match(/\? `(\w+)_v\$\{fluidEdit/)[1], ...labels.map(zipName), ...graphs]);
}

const FILE = /(?:<stem>|<name>|<n>|desk|smoke)_([a-z_]+?)(?:_v(?:<N>|\d+))?(?:_\d{5}_)?\.(?:mp4|mov|png|exr|json|md|zip)\b/g;

test("the documents name an export's files as the code does", () => {
  const names = codeNames(), wrong = [];
  for (const doc of ["README.md", "ARCHITECTURE.md", "TESTING.md"]) {
    for (const [, token] of read(doc).matchAll(/`([^`\n]+)`/g)) {
      for (const [, row] of token.matchAll(FILE)) if (!names.has(row)) wrong.push(`${doc}: ${token}`);
    }
  }
  assert.deepEqual(wrong, [], `the code names its files: ${[...names].sort().join(", ")}`);
});
