// The edit workstream's tests of an erase that Klein's prompt writer takes for another object (web/logic.mjs: asksName).
import { test } from "node:test";
import assert from "node:assert/strict";
import { asksName, erasesPaint, reconcile } from "../../web/logic.mjs";

test("the laptop's answer of 12 November 2026 is refused, and an erase with no words then asks for its object's name", () => {
  // a stroke on the barn of horse.mp4, with no words: the prompt writer removed the horse, which holds none of the paint
  const locked = [{ id: "obj_1", from: "ref_image_0", src_bbox: [362, 721, 490, 1000], tgt_bbox: null, desc: "the object to remove" }];
  const answer = "Remove the horse <horse_1> completely, including its bridle, tack, cast shadow. " +
    '[{"id": "horse_1", "from": "ref_image_0", "src_bbox": [150, 120, 950, 715], "tgt_bbox": null, "desc": "a brown horse"}]';
  const w = 96, h = 54, bits = new Uint8Array(w * h);
  for (let y = 21; y <= 25; y++) for (let x = 80; x <= 93; x++) bits[y * w + x] = 1; // the barn: x 0.83 to 0.975, y 0.39 to 0.47
  assert.equal(erasesPaint(reconcile(answer, locked), locked, { bits, w, h }), false);
  assert.equal(asksName("erase", ""), true);
  assert.equal(asksName("erase", "   "), true);
  assert.equal(asksName("erase", undefined), true);
});

test("with words, or for paint and light, the page goes on with its own caption", () => {
  assert.equal(asksName("erase", "the barn"), false); // the page's own caption carries the name
  assert.equal(asksName("paint", ""), false);
  assert.equal(asksName("light", ""), false);
});
