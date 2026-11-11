// The frame cache's budget and eviction (web/frames.mjs), with plain objects standing in for videos and frames.
import assert from "node:assert/strict";
import { test } from "node:test";
import { DeepFrames, FrameCache } from "../../web/frames.mjs";

const video = (src) => ({ getAttribute: () => src });
const frame = () => ({ width: 10, height: 10, closed: false, close() { this.closed = true; } }); // 400 bytes

test("frames stay within the budget, the least useful going first, never one more useful than the new one", () => {
  const view = { fps: 24, frame: 0, inPt: 0, outPt: 99 };
  let changes = 0;
  const cache = new FrameCache(video("a.mp4"), { view: () => view, changed: () => changes++, budget: 1200 });
  cache.reset();
  const kept = [0, 1, 2].map((f) => { const b = frame(); cache.put(f, b); return b; });
  assert.equal(cache.bytes, 1200);
  assert.ok(cache.get(2));
  const near = frame();
  view.frame = 3;
  cache.put(3, near); // the frame on screen: the least useful frame (0, now furthest behind) goes
  assert.ok(kept[0].closed && !cache.get(0) && cache.get(3) === near);
  const far = frame();
  cache.put(60, far); // further than everything kept: refused, and released
  assert.ok(far.closed && !cache.get(60));
  assert.ok(changes > 0);
  cache.put(3, frame()); // a frame already kept is not stored twice
  assert.equal(cache.bytes, 1200);
});

test("evicting a frame frees its own size, whatever the size of the new one", () => {
  const view = { fps: 24, frame: 0, inPt: 0, outPt: 99 };
  const cache = new FrameCache(video("a.mp4"), { view: () => view, changed: () => {}, budget: 1000 });
  cache.reset();
  const big = { width: 20, height: 10, closed: false, close() { this.closed = true; } }; // 800 bytes
  cache.put(5, big);
  const small = frame(); // 400 bytes, on the playhead: the big frame goes
  cache.put(0, small);
  assert.ok(big.closed && cache.get(0) === small);
  assert.equal(cache.bytes, 400);
});

test("a new source empties the cache", () => {
  let src = "a.mp4";
  const cache = new FrameCache({ getAttribute: () => src }, { view: () => ({ fps: 24, frame: 0, inPt: 0, outPt: 9 }) });
  cache.reset();
  const b = frame();
  cache.put(0, b);
  src = "b.mp4";
  assert.equal(cache.get(0), undefined); // frames of the old source are never shown for the new one
  cache.reset();
  assert.ok(b.closed);
  assert.equal(cache.frames.size, 0);
});

test("full-precision frames: the playhead's first, half floats untouched, within the budget", async () => {
  const view = { fps: 24, frame: 5, inPt: 0, outPt: 9 }, asked = [];
  const cache = new DeepFrames({ getAttribute: () => "plate.mp4" }, { view: () => view, budget: 36 * 8 });
  const fetchFrames = async (first, count) => { asked.push([first, count]); return { width: 2, height: 3, data: new Uint16Array(18 * count).fill(0x4000) }; };
  cache.fillDeep(fetchFrames, "plate");
  cache.fillDeep(fetchFrames, "plate"); // the same path while it fills: nothing more
  await new Promise((ok) => setTimeout(ok, 30));
  assert.equal(asked.filter(([f]) => f === 5).length, 1);
  assert.equal(asked[0][0], 5);
  assert.equal(cache.get(5).data[0], 0x4000); // 2.0 as a half float: above white, kept
  assert.equal(cache.get(5).bytes, 36);
  assert.equal(cache.frames.size, 8);
  assert.ok(cache.bytes <= cache.budget);
  cache.fillDeep(fetchFrames, "export"); // another path starts again
  assert.equal(cache.frames.size, 0);
});

test("full-precision frames: a failed path is not fetched again; a full budget fetches nothing", async () => {
  const view = { fps: 24, frame: 0, inPt: 0, outPt: 9 }, tick = () => new Promise((ok) => setTimeout(ok, 20));
  const cache = new DeepFrames({ getAttribute: () => "plate.mp4" }, { view: () => view, budget: 36 * 4 });
  let calls = 0;
  const fail = async () => { calls++; throw new Error("404"); };
  assert.equal(cache.fillDeep(fail, "plate"), true); // a new path
  await tick();
  assert.equal(cache.fillDeep(fail, "plate"), false);
  await tick();
  assert.equal(calls, 1);
  const ok = async (first, count) => { calls++; return { width: 2, height: 3, data: new Uint16Array(18 * count) }; };
  cache.fillDeep(ok, "export");
  await tick();
  const made = calls;
  assert.equal(cache.frames.size, 4);
  cache.fillDeep(ok, "export");
  await tick();
  assert.equal(calls, made); // the budget holds the four frames of most use: nothing more to fetch
});

// ---------- The viewer, round 1: one cache budget, the size frames are kept at, playback statistics ----------
import * as viewerFrames from "../../web/frames.mjs";

test("the Auto budget: 512 MB beside ComfyUI on the small memory profile, 1 GB on the others, up to 2 GB with ComfyUI elsewhere", () => {
  const auto = viewerFrames.autoBudget;
  assert.equal(auto({ host: "127.0.0.1", profile: "small" }), 512e6);
  assert.equal(auto({ host: "localhost" }), 512e6); // the card is not known yet: the page starts on the small profile
  assert.equal(auto({ host: "[::1]", profile: "medium" }), 1e9);
  assert.equal(auto({ host: "[::1]", profile: "large" }), 1e9);
  assert.equal(auto({ host: "abc-8188.proxy.runpod.net", profile: "large", deviceMemory: 8 }), 2e9);
  assert.equal(auto({ host: "abc-8188.proxy.runpod.net", deviceMemory: 2 }), 512e6);
  assert.equal(auto({ host: "abc-8188.proxy.runpod.net" }), 1e9); // Firefox and Safari do not report the device's memory
});

test("the frame cache's line of the log: the budget and where it comes from, then what fits, with no card size", () => {
  const line = viewerFrames.cacheLine;
  assert.equal(line("512 MB", "Auto", [{ name: "the plate", fits: 121, frames: 121, width: 960, height: 512 }]), "Frame cache: 512 MB (Auto), 121 of 121 frames at 960 x 512");
  assert.equal(line("8 MB", "set in the address", [{ name: "the plate", fits: 3, frames: 49, width: 960, height: 528 }, { name: "the shot", fits: 3, frames: 49, width: 960, height: 528 }]),
    "Frame cache: 8 MB (set in the address), 3 of 49 frames of the plate at 960 x 528; 3 of 49 frames of the shot at 960 x 528");
});

test("frames are kept at the size on show, smaller when the range does not fit, never under 960 px", () => {
  const size = viewerFrames.cacheSize, uhd = [3840, 2160];
  const a = size({ budget: 512e6, frames: 121, movie: uhd, fit: [1700, 956] }); // a 3840 x 2160 shot of 121 frames in 512 MB
  assert.equal(a.fits, 121);
  assert.ok(a.width >= 960 && a.width <= 1728 && 121 * a.width * a.height * 4 <= 512e6, JSON.stringify(a));
  assert.deepEqual(size({ budget: 4e9, frames: 121, movie: [1920, 1080], fit: [2400, 1350] }), { width: 1920, height: 1080, fits: 121 }); // never larger than the movie
  assert.deepEqual(size({ budget: 64e6, frames: 121, movie: uhd, fit: [1700, 956] }), { width: 960, height: 540, fits: 30 }); // at the floor: a window round the playhead
  assert.deepEqual(size({ budget: 512e6, frames: 121, movie: [640, 360], fit: [1700, 956] }), { width: 640, height: 360, fits: 121 });
});

test("one budget: the source on show first, both sides of the wipe in equal shares, EXR frames at their own size", () => {
  const plan = viewerFrames.cachePlan, uhd = [3840, 2160], fit = [1700, 956];
  const alone = plan({ budget: 512e6, frames: 121, fit, sources: [{ id: "plate", movie: uhd, show: false }, { id: "shot", movie: uhd, show: true }] });
  assert.equal(alone.shot.fits, 121);
  assert.equal(alone.plate.fits, 0); // the shot on show took the budget
  const wipe = plan({ budget: 512e6, frames: 121, fit, sources: [{ id: "plate", movie: uhd, show: true }, { id: "shot", movie: uhd, show: true }] });
  assert.ok(wipe.plate.fits === 121 && wipe.shot.fits === 121 && wipe.plate.width >= 960 && wipe.shot.width >= 960, JSON.stringify(wipe));
  assert.ok(wipe.plate.budget + wipe.shot.budget <= 512e6);
  const exr = plan({ budget: 1e9, frames: 121, fit, sources: [{ id: "plate", movie: [960, 540], show: false }, { id: "deep", movie: [960, 540], show: true, bytes: 6 }] });
  assert.deepEqual([exr.deep.width, exr.deep.height, exr.deep.fits], [960, 540, 121]);
  assert.ok(exr.deep.budget + exr.plate.budget <= 1e9 && exr.plate.fits === 121);
});

test("a cache follows its plan: a smaller share frees the frames of least use, another size starts again, no share keeps nothing", () => {
  const frame = () => ({ width: 10, height: 10, close() {} }); // 400 bytes
  const c = new viewerFrames.FrameCache({ getAttribute: () => "a.mp4" }, { view: () => ({ fps: 24, frame: 0, inPt: 0, outPt: 9 }), budget: 4000 });
  c.reset();
  for (let f = 0; f < 10; f++) c.put(f, frame());
  assert.deepEqual([c.frames.size, c.missing()], [10, []]);
  c.plan(1600);
  assert.ok(c.frames.size === 4 && c.bytes === 1600 && [0, 1, 2].every((f) => c.frames.has(f)), [...c.frames.keys()].join());
  c.plan(1600, [5, 5]);
  assert.equal(c.frames.size, 0);
  c.plan(0, [5, 5]); c.put(0, frame());
  assert.equal(c.frames.size, 0);
});

test("the hidden reader fills faster than real time, and slower once it misses frames", () => {
  assert.deepEqual([24, 50, 12].map((fps) => viewerFrames.fillRate(fps)), [2.5, 1.2, 4]);
  assert.deepEqual([viewerFrames.fillRate(24, 1), viewerFrames.fillRate(24, 5)], [1.25, 1]);
});

test("playback statistics: frames on time on a 60 Hz screen are not late, a stall skips frames, a slow player is late", () => {
  const st = new viewerFrames.PlayStats(50, "memory");
  let last = -1, t = 0;
  for (; t < 2000; t += 1000 / 60) { st.tick(t); const f = Math.floor(t * 0.05 + 1e-6) % 121; if (f !== last) st.shown((last = f), t, 121); }
  let r = st.report();
  assert.deepEqual([r.frames, r.late, r.skipped, Math.round(r.screen), Math.round(r.fps)], [100, 0, 0, 60, 50]);
  t += 80; st.tick(t); st.shown(Math.floor(t * 0.05) % 121, t, 121); // the page stalled for 80 ms
  assert.equal(st.report().skipped, Math.floor(t * 0.05) - 100);
  st.time("draw", 2); st.time("draw", 4); st.time("look", 1);
  assert.match(viewerFrames.statsLine(st.report(), "1371 x 771"), /^Played 101 frames in 2\.\d\d s: \d+\.\d fps of 50, 0 late, \d skipped; from memory at 1371 x 771, screen 60 Hz; draw 3\.0 ms, median \(look 1\.0\)$/);
  const slow = new viewerFrames.PlayStats(50, "video");
  for (let f = 0; f < 60; f++) { slow.tick(f * 25); slow.shown(f, f * 25, 121); } // 25 ms a frame where 20 are due
  r = slow.report();
  assert.ok(Math.round(r.fps) === 40 && r.late > 5 && r.skipped === 0, JSON.stringify(r));
  assert.match(viewerFrames.statsLine(r), /from the video, screen 40 Hz/);
});
