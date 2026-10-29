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
