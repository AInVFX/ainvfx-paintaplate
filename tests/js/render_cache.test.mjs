// logic.foldersIn: the folders under ComfyUI's output folder that a saved scene keeps, read from paths and view addresses
import { test } from "node:test";
import assert from "node:assert/strict";
import { foldersIn } from "../../web/logic.mjs";

const view = (subfolder, filename) => `/view?${new URLSearchParams({ filename, subfolder, type: "output" })}`;

test("foldersIn: a render's folders, the edits' folder and the plate's own files, from paths and view addresses", () => {
  const plate = { proxy: view("paintaplate/mwjy4jpe", "proxy_00001_.mp4"), frames: new Uint8Array(4) };
  const render = { base: "paintaplate/mwjy4jpe/v3", previews: { "960x544": { clean: "paintaplate/mwjy4jpe/v2/960x544/clean" } },
    raw: view("paintaplate/mwjy4jpe/v3/full", "raw_00001_.mp4"), flows: new Set(["shot"]) };
  const edits = [{ patch: view("paintaplate/mwjy4jpe/edits", "e1_00001_.png") }];
  assert.deepEqual(foldersIn([plate, render, edits]),
    ["paintaplate/mwjy4jpe", "paintaplate/mwjy4jpe/edits", "paintaplate/mwjy4jpe/v2", "paintaplate/mwjy4jpe/v3"]);
});

test("foldersIn: a loop, a lone % and plain numbers name nothing", () => {
  const loop = {};
  loop.self = loop;
  assert.deepEqual(foldersIn([loop, "100%", null, 7]), []);
});
