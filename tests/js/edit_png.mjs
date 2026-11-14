// The edit workstream's PNG reader for its Node tests: the frames and masks of its fixture, as PIL writes them.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { inflateSync } from "node:zlib";

export function png(path) { // a PNG as RGBA: 8-bit grey, RGB or RGBA, not interlaced (what PIL writes)
  const b = readFileSync(path), idat = [];
  let o = 8, w = 0, h = 0, n = 0;
  while (o < b.length) {
    const len = b.readUInt32BE(o), kind = b.toString("latin1", o + 4, o + 8), d = b.subarray(o + 8, o + 8 + len);
    if (kind === "IHDR") {
      [w, h, n] = [d.readUInt32BE(0), d.readUInt32BE(4), { 0: 1, 2: 3, 6: 4 }[d[9]]];
      assert.ok(d[8] === 8 && d[12] === 0 && n, `${path}: an 8-bit grey, RGB or RGBA PNG, not interlaced`);
    } else if (kind === "IDAT") idat.push(d);
    o += 12 + len;
  }
  const raw = inflateSync(Buffer.concat(idat)), row = w * n, px = new Uint8Array(w * h * n); // wraps at 256, as PNG's filters do
  for (let y = 0; y < h; y++) {
    const f = raw[y * (row + 1)], src = y * (row + 1) + 1, at = y * row;
    for (let x = 0; x < row; x++) {
      const a = x >= n ? px[at + x - n] : 0, up = y ? px[at - row + x] : 0, c = x >= n && y ? px[at - row + x - n] : 0;
      const p = a + up - c, pa = Math.abs(p - a), pb = Math.abs(p - up), pc = Math.abs(p - c);
      px[at + x] = raw[src + x] + [0, a, up, (a + up) >> 1, pa <= pb && pa <= pc ? a : pb <= pc ? up : c][f];
    }
  }
  const data = new Uint8ClampedArray(w * h * 4);
  for (let i = 0, j = 0; i < w * h; i++, j += n) data.set(n === 1 ? [px[j], px[j], px[j], 255] : [px[j], px[j + 1], px[j + 2], n === 4 ? px[j + 3] : 255], i * 4);
  return { w, h, data };
}
