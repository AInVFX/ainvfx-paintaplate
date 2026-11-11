// Decoded frames of a video, cached as OpenRV's FBCache does (src/lib/ip/IPCore/FBCache.cpp): within a memory budget,
// ranked by use (logic.frameUse), filled from the in point to the out point like RV's region cache. A hidden reader
// video plays the clip once, faster than real time while it presents every frame, and keeps each frame at the size it
// is shown; frames it skipped are fetched by seeking. Stepping and scrubbing then draw from memory, with no seek, and
// once every frame between the in and out points is in, the page plays from memory as RV does (app.mjs, tick).

import { frameUse } from "./logic.mjs";

const bytes = (frame) => frame.bytes ?? frame.width * frame.height * 4; // an ImageBitmap holds 4 bytes a pixel

let reading = null; // one hidden reader decodes at a time, so the source on show fills first
const waiting = new Set();
function release(cache) { // its reader ended: the next cache that waits starts
  if (reading !== cache) return;
  reading = null;
  const next = waiting.values().next().value;
  if (next) { waiting.delete(next); next.fill(); }
}

export class FrameCache {
  // video: the <video> shown; view(): { fps, frame, inPt, outPt } or null without a plate; changed(): after any change;
  // budget: bytes; behind: a frame behind the playhead counts as this many frames ahead, so about a quarter of a cache
  // that cannot hold the whole range stays behind it, as RV's lookback. Frames are ImageBitmaps, or anything with width,
  // height and close() (the tests use plain objects).
  constructor(video, { view, changed = () => {}, budget = 384e6, behind = 3 }) {
    Object.assign(this, { video, view, changed, budget, behind, frames: new Map(), bytes: 0, src: "", reader: null, token: 0, size: null, missed: 0 });
  }

  reset() {
    for (const b of this.frames.values()) b.close();
    this.frames.clear();
    this.bytes = 0;
    this.token++;
    this.missed = 0;
    this.stopReader();
    this.src = this.video.getAttribute("src") || "";
    this.changed();
  }

  stopReader() {
    const r = this.reader;
    this.reader = null;
    waiting.delete(this);
    if (r) { r.pause(); r.removeAttribute("src"); r.load(); }
    release(this);
  }

  // This cache's share of the budget, in bytes, and the size its frames are kept at ([width, height]; null: the video's
  // own). Another size starts the cache again; a smaller share frees the frames of least use. Then it reads what is missing.
  plan(budget, size = null) {
    const same = String(size) === String(this.size);
    Object.assign(this, { budget, size });
    if (same) this.trim(); else this.reset();
    this.fill();
  }

  get(f) { return this.src === (this.video.getAttribute("src") || "") ? this.frames.get(f) : undefined; }

  use(f) { const v = this.view(); return v ? frameUse(f, v, this.behind) : 0; }

  least() { // the frame of least use, and its use
    let worst, low = Infinity;
    for (const k of this.frames.keys()) { const u = this.use(k); if (worst === undefined || u < low) { low = u; worst = k; } }
    return [worst, low];
  }

  drop(f) {
    const old = this.frames.get(f);
    this.bytes -= bytes(old); // the frame's own size, read before close() zeroes it
    old.close();
    this.frames.delete(f);
  }

  trim() { // a smaller budget: the frames of least use go
    while (this.bytes > this.budget && this.frames.size) this.drop(this.least()[0]);
    this.changed();
  }

  missing() { // the frames between the in and out points that are not in
    const v = this.view(), out = [];
    if (v) for (let f = v.inPt; f <= v.outPt; f++) if (!this.frames.has(f)) out.push(f);
    return out;
  }

  put(f, bitmap) { // kept if the budget allows, freeing frames of less use, never one of more use than this one
    const size = bytes(bitmap), want = this.use(f);
    if (this.frames.has(f) || !this.budget) return void bitmap.close();
    while (this.bytes + size > this.budget && this.frames.size) {
      const [worst, low] = this.least();
      if (low >= want) return void bitmap.close();
      this.drop(worst);
    }
    this.frames.set(f, bitmap);
    this.bytes += size;
    this.changed();
  }

  async grab(v, f) { // the frame video `v` shows now, as frame f, at the size this cache keeps
    if (v.readyState < 2 || this.frames.has(f) || !this.budget) return;
    const token = this.token, [w, h] = this.size ?? [0, 0], smaller = w && h && (w < v.videoWidth || h < v.videoHeight);
    try {
      const bitmap = await (smaller ? createImageBitmap(v, { resizeWidth: w, resizeHeight: h, resizeQuality: "medium" }) : createImageBitmap(v));
      if (token === this.token) this.put(f, bitmap); else bitmap.close(); // the cache started again meanwhile
    } catch { /* the video changed meanwhile */ }
  }

  fill() { // read what is missing between the in and out points: a hidden reader plays the clip, then seeks for the gaps
    const src = this.video.getAttribute("src"), view = this.view();
    if (!src || !view || typeof HTMLVideoElement === "undefined" || !("requestVideoFrameCallback" in HTMLVideoElement.prototype)) return;
    if (this.src !== src) this.reset();
    const first = this.missing()[0];
    if (this.reader || !this.budget || first === undefined) return;
    if (reading && reading !== this) return void waiting.add(this);
    reading = this;
    const token = this.token, r = (this.reader = document.createElement("video"));
    Object.assign(r, { muted: true, playsInline: true, preload: "auto", src });
    const live = () => token === this.token && this.reader === r && this.view();
    let last = -1, seeking = false;
    const gaps = async () => {
      if (seeking) return;
      seeking = true;
      r.pause();
      for (const f of this.missing().sort((a, b) => this.use(b) - this.use(a))) {
        if (!live()) return;
        if (this.bytes > this.budget * 0.98) break; // the budget holds the frames of most use
        r.currentTime = (f + 0.5) / this.view().fps;
        await new Promise((ok) => r.addEventListener("seeked", ok, { once: true }));
        await this.grab(r, f);
      }
      if (live()) this.stopReader();
    };
    const onFrame = (_, meta) => {
      if (!live()) return;
      const v = this.view(), f = Math.round(meta.mediaTime * v.fps);
      if (last >= 0 && f > last + 1) this.missed += f - last - 1; // frames the reader did not present: it reads slower from here
      last = f;
      this.grab(r, f);
      r.playbackRate = fillRate(v.fps, this.missed);
      if (f >= v.outPt || r.ended) return gaps();
      r.requestVideoFrameCallback(onFrame);
    };
    r.addEventListener("loadeddata", () => {
      if (!live()) return;
      const v = this.view();
      r.currentTime = (first + 0.5) / v.fps;
      r.playbackRate = fillRate(v.fps, this.missed);
      r.requestVideoFrameCallback(onFrame);
      r.play().catch(gaps);
    }, { once: true });
    r.addEventListener("ended", () => { if (live()) gaps(); }, { once: true });
    r.addEventListener("error", () => { if (live()) this.stopReader(); }, { once: true });
  }
}

// Frames at full precision, as OpenRV's cache keeps an EXR's half floats: fetched from the server's frame route with
// their own values (above 1.0 and below 0 included), never through an 8-bit video. A frame is { width, height, data,
// bytes }, with data a Uint16Array of RGB half floats. Same budget and ranking as above; the video only names the plate.
export class DeepFrames extends FrameCache {
  reset() { super.reset(); Object.assign(this, { filling: false, failed: false, frameBytes: 0 }); }

  fill() {} // its frames come from the frames route (fillDeep), never from a hidden reader

  roomFor(f) { // a frame of f's use fits the budget, or a frame of less use can make room
    if (!this.frameBytes || this.bytes + this.frameBytes <= this.budget) return true;
    const want = this.use(f);
    for (const k of this.frames.keys()) if (this.use(k) < want) return true;
    return false;
  }

  // Fill from `path` (a plate, or an export folder): fetchFrames(first, count) resolves to { width, height, data } holding
  // `count` frames from `first`. Another path, or another video, starts again; the same one resumes, never twice at once,
  // never after a failed fetch, and never for a frame the budget cannot keep. Returns true when it starts on a new path.
  fillDeep(fetchFrames, path, chunk = 4) {
    const src = this.video.getAttribute("src");
    if (!src || !this.view()) return false;
    const fresh = this.src !== src || this.path !== path;
    if (fresh) { this.reset(); this.path = path; }
    if (this.filling || this.failed || !this.budget) return fresh;
    this.filling = true;
    const token = this.token, live = () => token === this.token && this.view();
    (async () => {
      try {
        while (live()) {
          const { inPt, outPt } = this.view(), todo = [];
          for (let f = inPt; f <= outPt; f++) if (!this.frames.has(f)) todo.push(f);
          if (!todo.length) return;
          todo.sort((a, b) => this.use(b) - this.use(a));
          const first = todo[0];
          if (!this.roomFor(first)) return; // the budget holds frames of more use
          let count = 1;
          while (count < chunk && todo.includes(first + count)) count++; // the missing run after the frame of most use
          let got;
          try { got = await fetchFrames(first, count); } catch { if (token === this.token) this.failed = true; return; }
          if (!live()) return;
          const per = got.width * got.height * 3;
          this.frameBytes = per * 2;
          for (let i = 0; i < count; i++) {
            const data = got.data.slice(i * per, (i + 1) * per);
            this.put(first + i, { width: got.width, height: got.height, data, bytes: data.byteLength, close() {} });
          }
          if (!this.frames.has(first)) return;
        }
      } finally { if (token === this.token) this.filling = false; }
    })();
    return fresh;
  }
}

// ---------- One memory budget for every cache of decoded frames ----------
// OpenRV keeps its frames in system memory within a budget the person can set: 1 GB by default for its look-ahead cache,
// with a quarter kept behind the playhead (Options.cpp: maxlram, lookback). Here the 8-bit frames are ImageBitmaps, which
// Chrome can keep on the GPU, next to ComfyUI's models when ComfyUI runs on this machine.
export const CACHE_CHOICES = [0, 512e6, 1e9, 2e9, 4e9, 8e9]; // bytes, for View > Cache memory; 0 is Auto
export const CACHE_FLOOR = 960; // px on the long side: frames are never kept smaller than this to make more of them fit
const LOCAL = ["localhost", "127.0.0.1", "::1", "[::1]"];
export const sameMachine = (host) => LOCAL.includes(host); // ComfyUI serves the page: this host is its machine

// The budget when the setting is Auto. With ComfyUI on this machine: 1 GB, as RV's look-ahead cache, and 512 MB on the
// small memory profile (its borders live in logic.MEMORY_FROM; the page starts on it until the card is known), because the
// models need that memory. With ComfyUI on another machine: a
// quarter of the device's memory as the browser reports it (navigator.deviceMemory, 8 GB at most), from 512 MB to 2 GB;
// 1 GB where the browser does not say (Firefox, Safari).
export function autoBudget({ host = "", profile = "small", deviceMemory = 0 }) {
  if (sameMachine(host)) return profile === "small" ? 512e6 : 1e9;
  return deviceMemory ? Math.min(2e9, Math.max(512e6, (deviceMemory * 1e9) / 4)) : 1e9;
}

// The frame cache's line of the log: the budget and where it comes from, then what fits. A size appears once, and one
// source needs no name. `sources`: [{ name, fits, frames, width, height }].
export const cacheLine = (budget, why, sources) =>
  `Frame cache: ${budget} (${why}), ${sources.map((s) => `${s.fits} of ${s.frames} frames${sources.length > 1 ? ` of ${s.name}` : ""} at ${s.width} x ${s.height}`).join("; ")}`;

// The size a source's frames are kept at, and how many fit. `movie`: the movie's own size; `fit`: the size the frame is
// shown at, in device pixels; `bytes`: per pixel (4 for an ImageBitmap). Frames are kept at the size on show (its width
// rounded up to 64 px, so a small change of layout keeps the cache), at most the movie's. When the frames between the in
// and out points do not fit `budget` at that size, the size goes down, to CACHE_FLOOR on the long side at the least.
// Under that the cache keeps the frames round the playhead: `fits` is then less than `frames`.
export function cacheSize({ budget, frames, movie: [mw, mh], fit: [fw, fh], bytes: per = 4, floor = CACHE_FLOOR }) {
  const shown = Math.min(mw, Math.ceil((mw * Math.min(1, fw / mw, fh / mh)) / 64) * 64) / mw, least = Math.min(shown, floor / Math.max(mw, mh));
  const cost = (w, h) => frames * w * h * per;
  let k = shown;
  if (cost(Math.round(mw * k), Math.round(mh * k)) > budget) k = Math.max(least, Math.sqrt(budget / cost(mw, mh)));
  let width = Math.max(2, Math.round(mw * k)), height = Math.max(2, Math.round(mh * k));
  while (k > least && width > mw * least && cost(width, height) > budget) { width -= 1; height = Math.max(2, Math.round((width * mh) / mw)); } // the rounding went over
  return { width, height, fits: Math.min(frames, Math.floor(budget / (width * height * per))) };
}

// One budget shared by the caches. The sources on show come first, in equal shares, each at the size it is shown. The
// others share what is left, at the floor size. `sources`: [{ id, movie: [w, h], show, bytes }]. Returns, per id,
// { width, height, fits, budget }: the size of its frames, how many fit, and its share in bytes.
export function cachePlan({ budget, frames, fit, sources }) {
  const plan = {};
  let left = budget;
  for (const show of [true, false]) {
    const tier = sources.filter((s) => !!s.show === show);
    tier.forEach((s, i) => {
      const size = cacheSize({ budget: Math.max(0, left) / (tier.length - i), frames, movie: s.movie, fit: show ? fit : [CACHE_FLOOR, CACHE_FLOOR], bytes: s.bytes });
      plan[s.id] = { ...size, budget: size.fits * size.width * size.height * (s.bytes ?? 4) };
      left -= plan[s.id].budget;
    });
  }
  return plan;
}

// The hidden reader's speed while it fills a cache. A 60 Hz screen presents 60 frames a second, so a 24 fps clip is read
// 2.5 times faster than it plays, 4 times at most. Each frame the reader did not present halves the gain, down to 1.
export const fillRate = (fps, missed = 0, refresh = 60) => Math.max(1, Math.min(4, refresh / fps) / 2 ** Math.min(missed, 8));

// ---------- Playback statistics (?stats=1, View > Playback statistics) ----------
const median = (a) => { if (!a.length) return 0; const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };

// One stretch of playback along one path: "memory" or "video". tick(now): an animation frame, which gives the screen's
// refresh. shown(f, now, span): frame f was drawn at `now` (ms); `span` is the number of frames between the in and out
// points, so a loop counts on. The first frame drawn starts the clock. A frame is late when it shows more than half a
// frame after its time, or more than one screen refresh after it where the screen is slower than that (a 50 fps clip
// on a 60 Hz screen). After a late frame the clock starts again from it, so one stall counts once. A frame is skipped
// when the next frame drawn is not the one after it. time(part, ms): what a part of a frame cost on the main thread.
export class PlayStats {
  constructor(fps, path) { Object.assign(this, { fps, path, drawn: 0, late: 0, skipped: 0, start: null, origin: 0, at: 0, last: 0, n: 0, beats: [], beat: null, parts: {} }); }

  tick(now) { if (this.beat !== null) this.beats.push(now - this.beat); this.beat = now; }

  shown(f, now, span) {
    if (this.start === null) return void Object.assign(this, { start: now, origin: now, at: now, last: f, drawn: 1 });
    const step = (((f - this.last) % span) + span) % span, frame = 1000 / this.fps;
    if (!step) return; // the same frame drawn again
    Object.assign(this, { n: this.n + step, last: f, at: now, drawn: this.drawn + 1, skipped: this.skipped + step - 1 });
    if (now - (this.origin + this.n * frame) > Math.max(frame / 2, median(this.beats)) + 1) { this.late++; this.origin = now - this.n * frame; }
  }

  time(part, ms) { (this.parts[part] ??= []).push(ms); }

  report() {
    const seconds = (this.at - this.start) / 1000 || 0, beat = median(this.beats);
    return { path: this.path, frames: this.drawn, seconds, fps: seconds ? (this.drawn - 1) / seconds : 0, of: this.fps, late: this.late, skipped: this.skipped,
      screen: beat ? 1000 / beat : 0, parts: Object.fromEntries(Object.entries(this.parts).map(([k, v]) => [k, median(v)])) };
  }
}

const ms = (v) => (v >= 10 ? v.toFixed(0) : v.toFixed(1));
export function statsLine(r, size = "") { // a report as one line for the log: "Played 121 frames in 2.42 s: 49.6 fps of 50, 0 late, 0 skipped; from memory at 1371 x 771, screen 60 Hz; draw 2.1 ms, median (look 0.4, copy 0.3)"
  const parts = Object.entries(r.parts).filter(([k]) => k !== "draw").map(([k, v]) => `${k} ${ms(v)}`).join(", ");
  return `Played ${r.frames} frames in ${r.seconds.toFixed(2)} s: ${r.fps.toFixed(1)} fps of ${Math.round(r.of * 100) / 100}, ${r.late} late, ${r.skipped} skipped; ` +
    `from ${r.path === "memory" ? "memory" : "the video"}${size ? ` at ${size}` : ""}${r.screen ? `, screen ${Math.round(r.screen)} Hz` : ""}; ` +
    `draw ${ms(r.parts.draw ?? 0)} ms, median${parts ? ` (${parts})` : ""}`;
}
