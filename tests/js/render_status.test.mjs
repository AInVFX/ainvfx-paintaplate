// The Render panel's status line (logic.renderStatus): the class of steps at work, « preview », « full size » or « finish »,
// with the time until that class is done, then what is ready.
import test from "node:test";
import assert from "node:assert/strict";
import { renderStatus, secs, stepClasses } from "../../web/logic.mjs";

const st = (id, o = {}) => ({ id, ...o });
const PAINT = [st("shot", { preview: true }), st("track", { preview: true }), st("comp", { preview: true }), st("full", { final: true }), st("trackfull", { final: true }),
  st("hdr", { final: true }), st("review", { final: true })];
const UP = [st("upplate", { final: true, up: true }), st("uplayer", { final: true, up: true }), st("upcomp", { final: true, up: true })];
const ids = (steps) => steps.map((s) => s.id);
const line = (steps, hdrLast, done, opts) => { // every step still due has 10 s left
  const cls = stepClasses(steps, hdrLast);
  return renderStatus(steps.map((s) => ({ cls: cls[s.id], done: done.includes(s.id), left: 10 })), opts);
};

test("a step's class: the preview, the full size, then Finish for SDR to HDR on the result and for Upscale's steps", () => {
  assert.deepEqual(stepClasses([...PAINT, ...UP, st("export", { final: true, onDemand: true })]), { shot: "preview", track: "preview", comp: "preview", full: "full",
    trackfull: "full", hdr: "full", review: "full", upplate: "finish", uplayer: "finish", upcomp: "finish", export: "export" });
  assert.equal(stepClasses(PAINT, true).hdr, "finish", "SDR to HDR after the composite, or on the plate alone");
  assert.equal(stepClasses([st("erase"), st("clean", { preview: true }), st("cleanfull", { final: true })]).erase, "preview", "a Clean's tracking runs first, with the preview");
  assert.equal(stepClasses([st("erase"), st("cleanfull", { final: true })]).erase, "full", "with the preview off, it counts with the full size");
});

test("the line names the class at work and its time, and a class that is made is not named again", () => {
  assert.equal(line(PAINT, false, []), `preview ${secs(30)}`);
  assert.equal(line(PAINT, false, ["shot", "track"]), `preview ${secs(10)}`);
  assert.equal(line(PAINT, false, ["shot", "track", "comp"]), `full size ${secs(40)}`, "the preview is made: the full size alone is named");
  assert.equal(line(PAINT, false, ids(PAINT)), "full size ready");
});

test("with a Finish pass, the full size that is made is not announced again: « finish », then « finish ready »", () => {
  const all = [...PAINT, ...UP];
  assert.equal(line(all, false, ids(PAINT)), `finish ${secs(30)}`);
  assert.equal(line(all, false, [...ids(PAINT), "upplate", "uplayer"]), `finish ${secs(10)}`);
  assert.equal(line(all, false, ids(all)), "finish ready");
  assert.equal(line(PAINT, true, ids(PAINT).filter((id) => id !== "hdr")), `finish ${secs(10)}`, "SDR to HDR after the composite");
  assert.equal(line([st("hdr", { final: true })], true, []), `finish ${secs(10)}`, "the plate alone: its one step is a Finish pass");
  assert.equal(line([st("hdr", { final: true })], true, ["hdr"]), "finish ready");
});

test("a class whose time is spent says « almost ready » while a step runs; the export has its own words", () => {
  const cls = stepClasses(PAINT), at = (opts) => renderStatus(PAINT.map((s) => ({ cls: cls[s.id], done: s.id === "shot" || s.id === "track", left: s.id === "comp" ? 0 : 10 })), opts);
  assert.equal(at({ busy: true }), "preview almost ready");
  assert.equal(at({}), "");
  const steps = [...PAINT, st("export", { final: true, onDemand: true })];
  assert.equal(line(steps, false, ids(PAINT), { exporting: true }), `export ${secs(10)}`);
  assert.equal(line(steps, false, ids(steps), { exported: true }), "exported");
});

test("a planned SDR to HDR that runs on the composite is listed after it, where it will run", async () => {
  const { runOrder } = await import("../../web/logic.mjs");
  assert.deepEqual(ids(runOrder(PAINT, true)), ["shot", "track", "comp", "full", "trackfull", "review", "hdr"]);
  assert.deepEqual(ids(runOrder(PAINT, false)), ids(PAINT), "before the composite, the shot is made again in HDR first");
  assert.deepEqual(ids(runOrder([st("fluid", { preview: true }), st("fluidfull", { final: true }), st("hdr", { final: true })], true)), ["fluid", "fluidfull", "hdr"], "a fluid shot alone has no composite");
});
