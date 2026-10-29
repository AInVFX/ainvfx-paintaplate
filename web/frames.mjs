// Decoded frames of a video, cached as OpenRV's FBCache does (src/lib/ip/IPCore/FBCache.cpp): within a memory budget,
// ranked by use (logic.frameUse), filled from the in point to the out point like RV's region cache. A hidden reader
// video plays the clip once and keeps every frame it presents; frames it skipped are fetched by seeking. Stepping and
// scrubbing then draw from memory, with no seek. Playback itself stays with the browser's video pipeline.

import { frameUse } from "./logic.mjs";

const bytes = (frame) => frame.bytes ?? frame.width * frame.height * 4; // an ImageBitmap holds 4 bytes a pixel

export class FrameCache {
  // video: the <video> shown; view(): { fps, frame, inPt, outPt } or null without a plate; changed(): after any change;
  // budget: bytes. Frames are ImageBitmaps, or anything with width, height and close() (the tests use plain objects).
  constructor(video, { view, changed = () => {}, budget = 384e6, behind = 3 }) {
    Object.assign(this, { video, view, changed, budget, behind, frames: new Map(), bytes: 0, src: "", reader: null, token: 0 });
  }

  reset() {
    for (const b of this.frames.values()) b.close();
    this.frames.clear();
    this.bytes = 0;
    this.token++;
    if (this.reader) { this.reader.pause(); this.reader.removeAttribute("src"); this.reader.load(); this.reader = null; }
    this.src = this.video.getAttribute("src") || "";
    this.changed();
  }

  get(f) { return this.src === (this.video.getAttribute("src") || "") ? this.frames.get(f) : undefined; }

  use(f) { const v = this.view(); return v ? frameUse(f, v, this.behind) : 0; }

  put(f, bitmap) { // kept if the budget allows, freeing frames of less use, never one of more use than this one
    const size = bytes(bitmap), want = this.use(f);
    if (this.frames.has(f)) return void bitmap.close();
    while (this.bytes + size > this.budget && this.frames.size) {
      let worst = null, low = Infinity;
      for (const k of this.frames.keys()) { const u = this.use(k); if (u < low) { low = u; worst = k; } }
      if (low >= want) return void bitmap.close();
      const old = this.frames.get(worst);
      this.bytes -= bytes(old); // the evicted frame's own size, read before close() zeroes it
      old.close();
      this.frames.delete(worst);
    }
    this.frames.set(f, bitmap);
    this.bytes += size;
    this.changed();
  }

  async grab(v, f) { // the frame video `v` shows now, as frame f
    if (v.readyState < 2 || this.frames.has(f)) return;
    try { this.put(f, await createImageBitmap(v)); } catch { /* the video changed meanwhile */ }
  }

  fill() { // read from the in point to the out point at playing speed, in a hidden reader, then fetch the gaps
    const src = this.video.getAttribute("src"), view = this.view();
    if (!src || !view || !("requestVideoFrameCallback" in HTMLVideoElement.prototype)) return;
    if (this.src !== src) this.reset();
    const token = this.token, r = (this.reader = document.createElement("video"));
    Object.assign(r, { muted: true, playsInline: true, preload: "auto", src });
    const live = () => token === this.token && this.view();
    const gaps = async () => {
      r.pause();
      const { inPt, outPt, fps } = this.view();
      const todo = [];
      for (let f = inPt; f <= outPt; f++) if (!this.frames.has(f)) todo.push(f);
      todo.sort((a, b) => this.use(b) - this.use(a));
      for (const f of todo) {
        if (!live() || this.bytes > this.budget * 0.98) return;
        r.currentTime = (f + 0.5) / fps;
        await new Promise((ok) => r.addEventListener("seeked", ok, { once: true }));
        await this.grab(r, f);
      }
    };
    const onFrame = (_, meta) => {
      if (!live()) return;
      const f = Math.round(meta.mediaTime * this.view().fps);
      this.grab(r, f);
      if (f >= this.view().outPt || r.ended) return gaps();
      r.requestVideoFrameCallback(onFrame);
    };
    r.addEventListener("loadeddata", () => {
      if (!live()) return;
      r.currentTime = (this.view().inPt + 0.5) / this.view().fps;
      r.requestVideoFrameCallback(onFrame);
      r.play().catch(gaps);
    }, { once: true });
    r.addEventListener("error", () => { if (live()) this.reader = null; }, { once: true });
  }
}

// Frames at full precision, as OpenRV's cache keeps an EXR's half floats: fetched from the server's frame route with
// their own values (above 1.0 and below 0 included), never through an 8-bit video. A frame is { width, height, data,
// bytes }, with data a Uint16Array of RGB half floats. Same budget and ranking as above; the video only names the plate.
export class DeepFrames extends FrameCache {
  reset() { super.reset(); Object.assign(this, { filling: false, failed: false, frameBytes: 0 }); }

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
    if (this.filling || this.failed) return fresh;
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
