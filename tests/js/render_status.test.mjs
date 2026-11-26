// The Render panel's status line (logic.renderStatus): the class of steps at work, « preview », « full size » or « finish »,
// with the time until that class is done, then what is ready.
import test from "node:test";
import assert from "node:assert/strict";
import { renderStatus, secs, stepClasses } from "../../web/logic.mjs";

const st = (id, o = {}) => ({ id, ...o });
const PAINT = [st("shot", { preview: true }), st("track", { preview: true }), st("comp", { preview: true }), st("full", { final: true }), st("trackfull", { final: true }),
  st("hdrshot", { final: true }), st("review", { final: true })];
const HDR = [st("hdrplate", { final: true, hdr: true }), st("hdrlayer", { final: true, hdr: true }), st("hdr", { final: true, hdr: true })];
const UP = [st("upplate", { final: true, up: true }), st("uplayer", { final: true, up: true }), st("upcomp", { final: true, up: true })];
const ids = (steps) => steps.map((s) => s.id);
const line = (steps, done, opts) => { // every step still due has 10 s left
  const cls = stepClasses(steps);
  return renderStatus(steps.map((s) => ({ cls: cls[s.id], done: done.includes(s.id), left: 10 })), opts);
};

test("a step's class: the preview, the full size, then Finish for SDR to HDR's steps and for Upscale's", () => {
  assert.deepEqual(stepClasses([...PAINT, ...HDR, ...UP, st("export", { final: true, onDemand: true })]), { shot: "preview", track: "preview", comp: "preview", full: "full",
    trackfull: "full", hdrshot: "full", review: "full", hdrplate: "finish", hdrlayer: "finish", hdr: "finish", upplate: "finish", uplayer: "finish", upcomp: "finish", export: "export" });
  assert.equal(stepClasses([st("hdr", { final: true, hdr: true })]).hdr, "finish", "the plate alone: its SDR to HDR is a Finish pass");
  assert.equal(stepClasses([st("erase"), st("clean", { preview: true }), st("cleanfull", { final: true })]).erase, "preview", "a Clean's tracking runs first, with the preview");
  assert.equal(stepClasses([st("erase"), st("cleanfull", { final: true })]).erase, "full", "with the preview off, it counts with the full size");
});

test("the line names the class at work and its time, and a class that is made is not named again", () => {
  assert.equal(line(PAINT, []), `preview ${secs(30)}`);
  assert.equal(line(PAINT, ["shot", "track"]), `preview ${secs(10)}`);
  assert.equal(line(PAINT, ["shot", "track", "comp"]), `full size ${secs(40)}`, "the preview is made: the full size alone is named");
  assert.equal(line(PAINT, ids(PAINT)), "full size ready");
});

test("with a Finish pass, the full size that is made is not announced again: « finish », then « finish ready »", () => {
  const all = [...PAINT, ...UP];
  assert.equal(line(all, ids(PAINT)), `finish ${secs(30)}`);
  assert.equal(line(all, [...ids(PAINT), "upplate", "uplayer"]), `finish ${secs(10)}`);
  assert.equal(line(all, ids(all)), "finish ready");
  assert.equal(line([...PAINT, ...HDR], [...ids(PAINT), "hdrplate", "hdrlayer"]), `finish ${secs(10)}`, "SDR to HDR after the composite");
  assert.equal(line([st("hdr", { final: true, hdr: true })], []), `finish ${secs(10)}`, "the plate alone: its one step is a Finish pass");
  assert.equal(line([st("hdr", { final: true, hdr: true })], ["hdr"]), "finish ready");
});

test("a class whose time is spent says « almost ready » while a step runs; the export has its own words", () => {
  const cls = stepClasses(PAINT), at = (opts) => renderStatus(PAINT.map((s) => ({ cls: cls[s.id], done: s.id === "shot" || s.id === "track", left: s.id === "comp" ? 0 : 10 })), opts);
  assert.equal(at({ busy: true }), "preview almost ready");
  assert.equal(at({}), "");
  const steps = [...PAINT, st("export", { final: true, onDemand: true })];
  assert.equal(line(steps, ids(PAINT), { exporting: true }), `export ${secs(10)}`);
  assert.equal(line(steps, ids(steps), { exported: true }), "exported");
});
