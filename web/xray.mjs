// The X-ray (W), as PlateLock's: where the edits on show change the plate, tinted over the picture. Its mattes: the
// export's once Export has made one, else the tracking mattes of the size on show; a light edit changes every pixel, so
// it tints the whole frame. Pure functions, tested in tests/js/xray.test.mjs; app.mjs draws them on the #xray overlay,
// above the canvas, so the colour inspector and the colour picker read the picture without the tint.

export const XRAY_TINT = [255, 0, 200]; // magenta, rare in plates
export const XRAY_ALPHA = 0.5; // the tint's opacity where a matte is white
export const XRAY_SIDE = 512; // px on the long side of the mattes it reads: where the model touched, not a measure

// Which mattes: `tools` of the edits on show, the render `r`, its preview size `pv`, and whether the pass on show is full size
export function xrayPlan({ tools = [], r, pv, full = false }) {
  if (!tools.length) return { from: "none", urls: [] };
  if (tools.includes("light")) return { from: "light", urls: [] };
  if (r?.exported?.matte) return { from: "export", urls: [r.exported.matte] };
  const size = full && r?.full ? "full" : "preview", found = { ...r?.erased?.found, ...(size === "full" ? r.full : pv?.mattes)?.found };
  const urls = [found.movie_a, found.movie_b].filter(Boolean); // the erase matte, the paint matte
  return { from: urls.length ? size : "none", urls };
}

export const XRAY_TEXT = { none: "X-ray: no matte yet for the edits on show", light: "X-ray: a light edit changes the whole frame",
  export: "X-ray: where the edits change the plate, from the export's matte", full: "X-ray: where the edits change the plate, from the full-size tracking mattes",
  preview: "X-ray: where the edits change the plate, from the preview's tracking mattes" };

export function halfToFloat(h) { // IEEE 754 half precision, as the frames route sends it
  const s = h & 0x8000 ? -1 : 1, e = (h >> 10) & 31, m = h & 1023;
  if (e === 0) return s * m * 2 ** -24;
  return e === 31 ? (m ? NaN : s * Infinity) : s * (1 + m / 1024) * 2 ** (e - 15);
}
const HALF = Float32Array.from({ length: 65536 }, (_, h) => halfToFloat(h));

export function alphaFromHalfs(halfs) { // a grey matte's RGB half floats (the frames route): 0 to 255 by its Rec. 709 luma
  const n = halfs.length / 3, out = new Uint8ClampedArray(n);
  for (let i = 0; i < n; i++) out[i] = 255 * (0.2126 * HALF[halfs[3 * i]] + 0.7152 * HALF[halfs[3 * i + 1]] + 0.0722 * HALF[halfs[3 * i + 2]]);
  return out;
}

export function alphaFromBytes(rgba) { // a grey matte drawn from its movie: 0 to 255 by its Rec. 709 luma
  const n = rgba.length / 4, out = new Uint8ClampedArray(n);
  for (let i = 0; i < n; i++) out[i] = 0.2126 * rgba[4 * i] + 0.7152 * rgba[4 * i + 1] + 0.0722 * rgba[4 * i + 2];
  return out;
}

export function tintPixels(layers, n, tint = XRAY_TINT, k = XRAY_ALPHA) { // RGBA: the tint, its opacity the union of the mattes
  const out = new Uint8ClampedArray(n * 4);
  for (let i = 0; i < n; i++) {
    let a = 0;
    for (const l of layers) if (l[i] > a) a = l[i];
    out[4 * i] = tint[0]; out[4 * i + 1] = tint[1]; out[4 * i + 2] = tint[2]; out[4 * i + 3] = a * k;
  }
  return out;
}
