// SDR to HDR before or after the composite (logic.hdrAfterComposite): over a fluid shot, whose plate is generated, the
// composite goes through SDR to HDR whole, as a relit one does; over a real plate, only the shot inside the mattes does.
import { test } from "node:test";
import assert from "node:assert/strict";
import { hdrAfterComposite, passMovie } from "../../web/logic.mjs";

const SDR = { ext: ".mov", codec: "prores", pix_fmt: "yuv444p12le", width: 1280, height: 704 }, EXR = { ext: ".exr", pix_fmt: "rgbaf16", width: 1280, height: 704 };

test("over a fluid shot on an SDR blank plate, SDR to HDR runs on the composite whole", () => {
  assert.equal(hdrAfterComposite(SDR, ["paint", "fluid"], true), true);
  assert.equal(hdrAfterComposite(SDR, ["fluid"], true), true);
  assert.equal(hdrAfterComposite(SDR, ["paint", "fluid"], false), false, "with the switch off, no SDR to HDR");
});

test("over a real SDR plate a paint keeps the plate's own pixels, and a plate that holds HDR keeps its values", () => {
  assert.equal(hdrAfterComposite(SDR, ["paint"], true), false);
  assert.equal(hdrAfterComposite(SDR, ["light"], true), true);
  assert.equal(hdrAfterComposite(EXR, ["paint", "fluid"], true), false);
});

test("once SDR to HDR has run after the composite, the composite's step still shows the composite, SDR to HDR's step its own frames", () => {
  const comp = { review: "/view?review.mp4", reviewSpace: "@model", reviewFrames: "output:v2/review/frames/f_%05d.exr", play: "/view?review.mp4", playSpace: "@model" };
  const r = { ...comp, compResult: comp, hdrMovie: "/view?hdr_movie.mp4", hdrFrames: "output:v2/hdr/f_%05d.exr" };
  Object.assign(r, { review: r.hdrMovie, reviewSpace: "ACEScct", reviewFrames: r.hdrFrames, reviewFramesSpace: "ACES2065-1", play: null, playSpace: null }); // the result displayed
  const spaces = { log: "ACEScct", hdr: "ACES2065-1" };
  assert.deepEqual(passMovie("review", r, {}, spaces), { url: comp.play, space: "@model", frames: comp.reviewFrames });
  assert.deepEqual(passMovie("hdr", r, {}, spaces), { url: r.hdrMovie, space: "ACEScct", frames: r.hdrFrames, framesSpace: "ACES2065-1" });
});
