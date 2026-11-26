// Every module of the page loads, and the names it uses from the page's other modules are its own: a name it calls from
// another module is imported, or declared in it; a name it imports is not declared again, which stops the module from
// loading (a SyntaxError that only a browser or node --check shows: G1's « addPoint »).
import { test } from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cpSync, mkdtempSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const WEB = new URL("../../web/", import.meta.url).pathname;
const bare = (src) => src.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/(^|[^:\\])\/\/.*$/gm, "$1") // comments and plain strings out
  .replace(/'(?:\\.|[^\\'\n])*'|"(?:\\.|[^\\"\n])*"/g, '""');
const words = (re, src) => [...src.matchAll(re)].map((m) => m[1]);

export function faults(dir) {
  const raws = Object.fromEntries(readdirSync(dir).filter((f) => f.endsWith(".mjs")).map((f) => [f, readFileSync(join(dir, f), "utf8")]));
  const mods = Object.fromEntries(Object.entries(raws).map(([f, r]) => [f, bare(r).replace(/^import\s[^;]*;/gm, "")])); // the code, without its imports
  const exported = Object.fromEntries(Object.entries(mods).map(([f, s]) => [f, words(/^export\s+(?:async\s+)?(?:function\*?|const|let|class)\s+(\w+)/gm, s)]));
  const out = [];
  for (const [f, s] of Object.entries(mods)) {
    const run = spawnSync(process.execPath, ["--check", join(dir, f)], { encoding: "utf8" });
    if (run.status) out.push(`${f}: does not load: ${(run.stderr.match(/SyntaxError: .*/) ?? [run.stderr.trim()])[0]}`);
    const imported = [...raws[f].matchAll(/^import\s+\{([^}]*)\}\s+from\s+"\.\/[\w.]+";/gm)].flatMap((m) => m[1].split(",").map((x) => x.trim().split(/\s+as\s+/).pop()).filter(Boolean));
    const top = words(/^(?:export\s+)?(?:async\s+)?(?:function\*?|const|let|var|class)\s+(\w+)/gm, s);
    for (const name of imported.filter((n) => top.includes(n))) out.push(`${f}: imports ${name} and declares it again`);
    for (const [g, names] of Object.entries(exported)) {
      if (g === f) continue;
      for (const name of names) {
        if (imported.includes(name) || !new RegExp(`(?<![\\w$.])${name}\\(`).test(s)) continue;
        const own = new RegExp(`\\b(?:const|let|var|function\\*?|class)\\s+${name}\\b|[({,]\\s*${name}\\s*(?:[,)}]|=(?!=))`).test(s); // declared, a parameter or destructured
        if (!own) out.push(`${f}: calls ${name}, from ${g}, without importing it`);
      }
    }
  }
  return out;
}

test("every module of the page loads, imports what it calls from the others, and declares no name it imports", () => {
  assert.deepEqual(faults(WEB), []);
});

test("the check finds a call with no import, and an import declared again", () => {
  const dir = mkdtempSync(join(tmpdir(), "page3_imports_"));
  cpSync(WEB, dir, { recursive: true });
  const app = readFileSync(join(dir, "app.mjs"), "utf8");
  writeFileSync(join(dir, "app.mjs"), app.replace(", stepFamily,", ",").replace(/\n/, "\nfunction addSampled() {}\n"));
  const got = faults(dir);
  assert.ok(got.includes("app.mjs: calls stepFamily, from logic.mjs, without importing it"), got.join("\n"));
  assert.ok(got.includes("app.mjs: imports addSampled and declares it again"), got.join("\n"));
  assert.ok(got.some((x) => x.startsWith("app.mjs: does not load: SyntaxError")), got.join("\n"));
});
