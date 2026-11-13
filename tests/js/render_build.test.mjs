// Render workstream, wave 5 (RX1): the job index's key holds what computes. The server answers a build, a hash made when
// ComfyUI starts (routes.build_parts). The key takes it in place of the pack's version, and the page reads it again when
// ComfyUI comes back after a stop.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { connect, indexParts, onBack } from "../../web/comfy.mjs";
import { plateIdentity } from "../../web/logic.mjs";

const values = { seed: 7, caption: "a red fire" };
const st = { files: 1, size: 5242880, mtime: 1762900000 };
const key = (build, on = true) => indexParts(build, "wf-hash", plateIdentity("plates/horse.mp4", st, on), values);

test("a job index key holds the server's build: another build makes another key, and no build makes none", () => {
  assert.equal(key("0123456789abcdef"), key("0123456789abcdef"), "the same code and model files: the same key");
  assert.notEqual(key("0123456789abcdef"), key("fedcba9876543210"), "a branch, a local edit, an update or a new model file");
  assert.equal(key(""), null, "a ComfyUI that answers no build, or a page that saw it change: no index");
  assert.equal(key("0123456789abcdef", false), null, "?index=0 still gives no key");
});

test("the page's check runs when the WebSocket opens again after a close, not at its first opening", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "setInterval"] });
  const sockets = [];
  globalThis.location = { protocol: "http:", host: "127.0.0.1:8188" };
  globalThis.WebSocket = class { constructor(url) { this.url = url; sockets.push(this); } send() {} };
  let backs = 0;
  onBack(() => { backs += 1; });
  connect();
  sockets[0].onopen();
  assert.equal(backs, 0, "the first opening: boot has just read the build");
  sockets[0].onclose();
  t.mock.timers.tick(2000);
  sockets[1].onclose(); // ComfyUI is still stopped
  t.mock.timers.tick(2000);
  assert.equal(sockets.length, 3, "a new WebSocket two seconds after each close");
  sockets[2].onopen();
  assert.equal(backs, 1, "ComfyUI answers again: the page reads its build again, once");
});

test("boot keys by the build it read, and turns the index off when ComfyUI comes back with another", () => {
  const app = readFileSync(new URL("../../web/app.mjs", import.meta.url), "utf8");
  const boot = app.slice(app.indexOf("async function boot()"), app.indexOf("connect();", app.indexOf("async function boot()")));
  assert.match(boot, /const \{ version = "", build = "" \} = await served\(\);/);
  assert.match(boot, /\n  setBuild\(build\);/);
  assert.match(boot, /onBack\(async \(\) => \{[\s\S]*now === build\) return;[\s\S]*setBuild\(""\);[\s\S]*told\("ComfyUI restarted with other code or model files"/);
});
