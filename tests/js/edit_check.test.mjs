// The edit workstream's tests of the check after an erase (web/logic.mjs: eraseCheck, objectLeft): a removed object
// passes; an object that stayed, or that Klein only recoloured as it did the barn on 12 November 2026, is left.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { inflateSync } from "node:zlib";
import { eraseCheck, objectLeft } from "../../web/logic.mjs";

const w = 64, h = 32;
const frame = (fn) => {
  const a = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) a.set([...fn(x, y), 255], (y * w + x) * 4);
  return a;
};
const inside = (x, y) => x >= 16 && x < 48 && y >= 8 && y < 24;
const sky = (x, y) => [150 + y, 140 + y, 130 + y];
const barn = (x, y) => (inside(x, y) ? ((x >> 2) % 2 ? [60, 70, 90] : [170, 180, 200]) : sky(x, y)); // planks on a sky
const mask = frame((x, y) => (inside(x, y) ? [255, 255, 255] : [0, 0, 0]));
const before = frame(barn);

test("an object that went passes; one that stayed, or that was only recoloured, is left", () => {
  const gone = eraseCheck(frame(sky), before, mask, w, h);
  assert.equal(gone.left, false, JSON.stringify(gone));
  assert.equal(eraseCheck(before, before, mask, w, h).left, true);
  // recoloured: every value 40 levels up, its planks in place. The rule of 12 Nov (2% at 12 levels) let it through
  const recoloured = eraseCheck(frame((x, y) => barn(x, y).map((v) => v + 40)), before, mask, w, h);
  assert.ok(recoloured.changed > 0.9 && recoloured.edges > 0.85, JSON.stringify(recoloured));
  assert.equal(recoloured.left, true);
  assert.deepEqual(eraseCheck(before, before, frame(() => [0, 0, 0]), w, h), { changed: null, edges: null, left: false }); // no mask
});

test("the probe's results on horse.mp4 (13 Nov 2026): what went passes; what stayed, and the half-changed tree, are left", () => {
  // [share of the object moved by more than 24 levels, correlation of its edges before and after]
  const went = [[0.53, 0.75], [0.78, 0.71], [0.77, -0.03], [0.58, 0.74], [0.74, 0.03], [0.73, 0.03], [0.74, 0.03]];
  const stayed = [[0, 0.98], [0.01, 0.98], [0, 0.93], [0, 0.97], [0.17, 0.62]];
  for (const [changed, edges] of went) assert.equal(objectLeft({ changed, edges }), false, `${changed}, ${edges}`);
  for (const [changed, edges] of stayed) assert.equal(objectLeft({ changed, edges }), true, `${changed}, ${edges}`);
});

// E5's fixture (12 and 13 November 2026, horse.mp4): real first frames at the page's quick-pass size, 768 x 432, against
// the check after an erase. The frames live with the test data, never in git: PAINTAPLATE_FIXTURES names the folder that
// holds edit_check/; without it this test is skipped. Each case is [the frame under the edit, the object's mask, left]:
// - the plate's first frame resized (horse_frame0, the same pixels as w6/horse_frame0.png at 768 x 432), with the page's mask
//   of the barn (1.11.13): the exports' first frames of 12 Nov (1.11.12) and 13 Nov (1.11.14), and the probe of 13 Nov
//   (tests/erase_probe.py, 1.11.13, seven requests);
// - the frame and the masks that the probe of 1.11.14 sent (probe14_*): the barn, the post and the tree, with no words and
//   with their names. Each probe's results are measured against its own frame: they give the probe's own figures exactly.
// The verdicts agree with the frames and with SAM 3.1 run again. Measured on 13 Nov, at 24 levels and for the edges: a
// kept object 0 to 3% and 0.91 to 0.98; a removed one 53 to 97% and -0.07 to 0.76, a thin post among them (73%, 0.05).
const CASES = {
  horse_erase: ["horse_frame0", "horse_barn_mask", true], // 12 Nov, no words: the barn kept
  horse_erase_barn: ["horse_frame0", "horse_barn_mask", false],
  probe_page: ["horse_frame0", "horse_barn_mask", false],
  probe_dimmed: ["horse_frame0", "horse_barn_mask", false],
  probe_crop: ["horse_frame0", "horse_barn_mask", false],
  probe_tight: ["horse_frame0", "horse_barn_mask", false],
  probe_named: ["horse_frame0", "horse_barn_mask", true],
  probe_as_words: ["horse_frame0", "horse_barn_mask", true],
  probe_own: ["horse_frame0", "horse_barn_mask", true],
  w6_horse_erase: ["horse_frame0", "horse_barn_mask", false], // 13 Nov, no words: the writer's box cut to the object (E3)
  w6_horse_erase_barn: ["horse_frame0", "horse_barn_mask", false],
  probe14_barn_page: ["probe14_frame", "probe14_barn_mask", false],
  probe14_barn_wide: ["probe14_frame", "probe14_barn_mask", true], // 1.11.13's request: the writer names the horse, refused
  probe14_post_page: ["probe14_frame", "probe14_post_mask", false],
  probe14_post_own: ["probe14_frame", "probe14_post_mask", true],
  probe14_tree_own: ["probe14_frame", "probe14_tree_mask", true],
  probe14_barn_words: ["probe14_frame", "probe14w_barn_mask", false], // with its name, SAM 3.1 finds the object by it
  probe14_post_words: ["probe14_frame", "probe14w_post_mask", false],
  probe14_tree_words: ["probe14_frame", "probe14_tree_mask", false],
};

function png(path) { // a PNG as RGBA: 8-bit grey, RGB or RGBA, not interlaced (what PIL writes)
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

test("real first frames: an object that stayed is left, one that went is gone", { skip: !process.env.PAINTAPLATE_FIXTURES && "PAINTAPLATE_FIXTURES is not set" }, () => {
  const dir = join(process.env.PAINTAPLATE_FIXTURES, "edit_check"), read = (name) => png(join(dir, `${name}.png`));
  for (const [name, [frame, object, left]] of Object.entries(CASES)) {
    const before = read(frame), mask = read(object), after = read(name);
    assert.deepEqual([before.w, before.h, mask.w, mask.h, after.w, after.h], [768, 432, 768, 432, 768, 432], name);
    const check = eraseCheck(after.data, before.data, mask.data, before.w, before.h);
    assert.equal(check.left, left, `${name}: ${JSON.stringify(check)}`);
  }
});
