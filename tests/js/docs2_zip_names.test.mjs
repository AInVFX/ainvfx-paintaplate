// The documents name an export's files as the code names them. Every file of a zip that README.md, ARCHITECTURE.md or
// TESTING.md gives after its stem (<stem>, <name>, <n>, or the name of an example plate or scene) is a name that
// logic.exportWords and logic.zipNames make for some export, or the models' list or a fluid shot's zip that the code writes.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { exportWords } from "../../web/logic.mjs";

const read = (f) => readFileSync(new URL(`../../${f}`, import.meta.url), "utf8");
const app = read("web/app.mjs"), routes = read("routes.py");
const label = (id) => app.match(new RegExp(`id: "${id}", label: "([^"]+)"`))[1]; // a step's name in the Render panel (STAGES)
const fluidUp = app.match(/\? "(Fluid: [^"]+)"/)[1]; // Upscale's step on a fluid shot alone (labelOf)

function codeNames() {
  const names = new Set([routes.match(/f"\{stem\}_(\w+)\.md"/)[1], app.match(/exportStem\(\)\}_(\w+)_v\$\{/)[1]]);
  const ups = { edits: label("upcomp"), plate: label("upplate"), relit: label("uphdr"), fluid: fluidUp, upscaled: label("upcomp") };
  for (const [kind, up] of Object.entries(ups)) {
    for (const last of [false, true]) {
      for (const upHdr of [false, true]) {
        const { zip } = exportWords({ kind, last, upHdr, steps: { comp: label("review"), shot: label("full"), up } });
        for (const value of Object.values(zip)) (typeof value === "string" ? [value] : Object.values(value)).forEach((n) => names.add(n));
      }
    }
  }
  return names;
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
