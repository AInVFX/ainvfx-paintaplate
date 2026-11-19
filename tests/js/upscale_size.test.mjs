// Finish > Upscale's sizes: the menu's list for a plate, the size a person asks for, Custom…'s width or height, and what a
// saved scene asks for.
import { test } from "node:test";
import assert from "node:assert/strict";
import { UPSCALE, UPSCALE_ASK, upscaleAskOf, upscaleCustom, upscaleSizes, upscaleTarget, upscaleWhy } from "../../web/logic.mjs";

test("the default is 3840 px on the long side, within 3840 x 2160, the aspect kept; a plate that large keeps its size", () => {
  assert.deepEqual(upscaleTarget(1920, 1080), [3840, 2160]);
  assert.deepEqual(upscaleTarget(1080, 1920), [2160, 3840]);
  assert.deepEqual(upscaleTarget(1440, 1080), [2880, 2160]); // 4:3: the short side holds it at 2160
  assert.deepEqual(upscaleTarget(2048, 858), [3840, 1608]);
  assert.deepEqual(upscaleTarget(3840, 2160), [3840, 2160]);
  assert.deepEqual(upscaleTarget(4096, 2160), [4096, 2160]);
  assert.deepEqual(upscaleTarget(1920, 1080, 2560), [2560, 1440]); // a number is a long side
});

test("a width or a height asked for keeps its px, the other side follows the plate, both even", () => {
  assert.deepEqual(upscaleTarget(1920, 1080, { side: "width", px: 2000 }), [2000, 1124]); // no multiple of 16
  assert.deepEqual(upscaleTarget(1920, 1080, { side: "height", px: 1500 }), [2666, 1500]);
  assert.deepEqual(upscaleTarget(1920, 1080, { side: "width", px: 2001 }), [2000, 1126]);
  assert.deepEqual(upscaleTarget(1920, 1080, { side: "width", px: 1280 }), [1280, 720]); // under the plate's size
  assert.deepEqual(upscaleTarget(1920, 1080, { side: "width", px: 5000 }), [3840, 2160]); // held within 3840 x 2160
});

test("the menu lists the plate's own size, then each larger one", () => {
  const sizes = (w, h) => upscaleSizes(w, h).map((s) => s.size);
  assert.deepEqual(sizes(1920, 1080), [[1920, 1080], [2560, 1440], [3840, 2160]]);
  assert.deepEqual(sizes(2560, 1440), [[2560, 1440], [3840, 2160]]);
  assert.deepEqual(sizes(3840, 2160), [[3840, 2160]]);
  assert.deepEqual(sizes(1440, 1080), [[1440, 1080], [2560, 1920], [2880, 2160]]);
  for (const { ask, size } of upscaleSizes(1920, 1080)) assert.deepEqual(upscaleTarget(1920, 1080, ask), size);
});

test("Custom… takes one number, the long side, from the least long side to 3840 px", () => {
  assert.deepEqual(upscaleCustom("3000", 1920, 1080), { side: "width", px: 3000 });
  assert.deepEqual(upscaleCustom(" 3000 ", 1080, 1920), { side: "height", px: 3000 }); // a portrait plate's long side is its height
  assert.deepEqual(upscaleCustom(`${UPSCALE.least}`, 1920, 1080), { side: "width", px: UPSCALE.least });
  for (const no of ["", "abc", "3000 px", "1600p", "3000 x 1700", "5000", `${UPSCALE.least - 2}`]) assert.equal(upscaleCustom(no, 1920, 1080), null, no);
  assert.deepEqual(upscaleTarget(1440, 1080, upscaleCustom("3840", 1440, 1080)), [2880, 2160]); // the short side holds a 4:3 plate at 2160
  assert.deepEqual(upscaleTarget(1920, 1080, upscaleCustom("1280", 1920, 1080)), [1280, 720]); // under the plate's size
});

test("a scene's switch: true asks for the default, a size is kept, anything else is off", () => {
  assert.deepEqual(upscaleAskOf(true), UPSCALE_ASK);
  assert.deepEqual(upscaleAskOf({ side: "height", px: 1600 }), { side: "height", px: 1600 });
  for (const no of [false, undefined, null, 3840, { side: "diagonal", px: 3 }, { side: "width", px: -2 }]) assert.equal(upscaleAskOf(no), false);
});

test("the row says what a size no larger than the plate does, and nothing for a larger one", () => {
  assert.equal(upscaleWhy(1920, 1080), "");
  assert.match(upscaleWhy(3840, 2160), /^At the plate's own size, the result is brought down to (half|a third of) that size/);
  assert.match(upscaleWhy(1920, 1080, { side: "long", px: 1920 }), /^At the plate's own size/);
  assert.match(upscaleWhy(1920, 1080, { side: "width", px: 1280 }), /^This size is smaller than the plate, so the frames come out smaller/);
});
