// Tests of an erase's cast shadow (web/logic.mjs: shadowBox, shadowOf): the shadow row that the prompt writer's caption
// cites, and which of SAM 3.1's masks of « shadow » join the object's SAM mask.
import { test } from "node:test";
import assert from "node:assert/strict";
import { shadowBox, shadowOf } from "../../web/logic.mjs";

const W = 100, H = 60, all = [0, 0, 1000, 1000];
const rect = (x0, y0, x1, y1) => { const m = new Uint8Array(W * H); for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) m[y * W + x] = 1; return m; };
const car = rect(40, 20, 60, 40); // the object, 400 pixels

test("the shadow that the caption cites: its row's box, only when the caption cites the row", () => {
  const caption = "Remove the orange convertible <car_1>, the dark cast shadow <shadow_1> extending toward frame-left. " +
    '[{"id": "car_1", "from": "ref_image_0", "src_bbox": [310, 372, 613, 625], "tgt_bbox": null, "desc": "a car"}, ' +
    '{"id": "shadow_1", "from": "ref_image_0", "src_bbox": [470, 211, 638, 405], "tgt_bbox": null, "desc": "A broad dark vehicle shadow"}]';
  assert.deepEqual(shadowBox(caption), [470, 211, 638, 405]);
  assert.equal(shadowBox(caption.replace("<shadow_1>", "")), null);
  assert.equal(shadowBox('Remove the barn <barn_1> completely, with its shadow. [{"id": "barn_1", "from": "ref_image_0", "src_bbox": [1, 2, 30, 40], "tgt_bbox": null, "desc": "a barn"}]'), null);
  assert.equal(shadowBox(""), null);
});

test("a shadow that touches the object, or lies under it, joins it; one apart, outside the box, or too large, does not", () => {
  const touching = rect(25, 35, 41, 45), under = rect(45, 46, 58, 50), apart = rect(5, 5, 15, 12), huge = rect(0, 40, 100, 60);
  const got = shadowOf({ object: car, shadows: [touching, apart], box: all, w: W, h: H });
  assert.ok(got && got.bits[38 * W + 30] === 1 && got.bits[8 * W + 10] === 0, "the touching shadow joins, the one apart does not");
  assert.equal(got.share, (160 - 5) / 400, "the share counts the shadow's pixels outside the object");
  assert.ok(shadowOf({ object: car, shadows: [under], box: all, w: W, h: H }), "a shadow under the object joins, though apart from it");
  assert.equal(shadowOf({ object: car, shadows: [touching], box: [0, 0, 100, 100], w: W, h: H }), null, "outside the caption's box");
  assert.equal(shadowOf({ object: car, shadows: [huge], box: all, w: W, h: H }), null, "over three times the object's area: shade");
  assert.equal(shadowOf({ object: car, shadows: [], box: all, w: W, h: H }), null);
  assert.equal(shadowOf({ object: car, shadows: [touching], box: null, w: W, h: H }), null, "no shadow cited");
});
