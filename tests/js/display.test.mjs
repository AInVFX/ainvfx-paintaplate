// The viewer's colour tools against OpenRV's RVColor (ColorIPNode.cpp at 0bd9675): the shader's values, case by case.
import { test } from "node:test";
import assert from "node:assert/strict";
import { DISPLAY, LUMA, colorMatrix, displayActive, displayLabel, displayUniforms, hueMatrix } from "../../web/display.mjs";

const apply = (d, v) => { // what the shader does before the display: gamma, then the matrix and its offset
  const u = displayUniforms({ ...DISPLAY, ...d }), g = v.map((x) => (u.exponent !== 1 ? Math.max(x, 0) ** u.exponent : x));
  return u.matrix.map((row, i) => row.reduce((a, m, j) => a + m * g[j], 0) + u.offset[i]);
};
const near = (a, b, eps = 1e-6) => a.forEach((v, i) => assert.ok(Math.abs(v - b[i]) < eps, `${a} vs ${b}`));

test("at rest the colour tools change nothing", () => {
  assert.equal(displayActive(DISPLAY), false);
  near(apply({}, [0.18, 4, -0.1]), [0.18, 4, -0.1]);
});

test("contrast is RV's (1 + c) x - c / 2: it turns about 0.5, not 18% grey", () => {
  near(apply({ contrast: 1 }, [0.5, 1, 0]), [0.5, 1.5, -0.5]);
  assert.equal(displayLabel({ ...DISPLAY, contrast: 0.3 }), "C +0.30");
});

test("exposure is 2 to the stops; invert acts before it", () => {
  near(apply({ exposure: 2 }, [0.25, 1, 4]), [1, 4, 16]);
  near(apply({ invert: true, exposure: 1 }, [0.25, 0.5, 1]), [1.5, 1, 0]);
});

test("gamma acts first, on max(x, 0), then the matrix: ColorMatrix(ColorGamma(source))", () => {
  near(apply({ gamma: 2, exposure: 1 }, [0.25, -1, 4]), [1, 0, 4]);
});

test("after an invert, contrast scales its offset by r + g + b, as RV's homogeneous matrix does", () => {
  const c = 0.5, v = [0.2, 0.3, 0.4], w = v.reduce((a, b) => a + b);
  near(apply({ invert: true, contrast: c }, v), v.map((x) => (1 + c) * (1 - x) - (c / 2) * w));
});

test("hue turns about the grey axis and keeps Rec. 709 luma; saturation 0 gives luma", () => {
  const H = hueMatrix(1.1), grey = H.slice(0, 3).map((r) => r[0] + r[1] + r[2]);
  near(grey, [1, 1, 1]);
  const luma = [0, 1, 2].map((j) => LUMA.reduce((a, w, i) => a + w * H[i][j], 0));
  near(luma, LUMA);
  near(apply({ saturation: 0 }, [1, 0, 0]), [LUMA[0], LUMA[0], LUMA[0]]);
  assert.notDeepEqual(colorMatrix({ hue: 60 }), colorMatrix({}));
});

test("the channel is picked after the display, as OCIODisplay floods it; luminance with Rec. 709 weights", () => {
  assert.deepEqual(displayUniforms({ ...DISPLAY, channel: "r" }).pick, [[1, 0, 0], [1, 0, 0], [1, 0, 0]]);
  assert.deepEqual(displayUniforms({ ...DISPLAY, channel: "l" }).pick[2], LUMA);
});

import { nativeSize, oneToOne } from "../../web/display.mjs";

test("the canvas holds the plate at its own size, up to the frames route's 4096; 1:1 counts device pixels", () => {
  assert.deepEqual(nativeSize(3840, 2160, 4096), [3840, 2160]);
  assert.deepEqual(nativeSize(8192, 4320, 4096), [4096, 2160]);
  assert.equal(oneToOne(3840, 960, 2), 2);
  assert.equal(oneToOne(1920, 1920, 1), 1);
});

import { dragZoomScale, lockAxis, pixelScale, pointIn, zoomAbout } from "../../web/display.mjs";

test("zoom as RV: N:1 in device pixels, dragZoom's curve, the press point held, the pan locked to one axis", () => {
  assert.equal(pixelScale(4, 3840, 960, 1), 16);
  assert.equal(pixelScale(1 / 2, 1920, 960, 1), 1);
  const w = 1000, m = (100 / w) * 1 * 2; // RV: m = |dx| / width * k * 2
  assert.ok(Math.abs(dragZoomScale(1, 100, w) - (1 + 15 * m * m)) < 1e-12);
  assert.ok(Math.abs(dragZoomScale(1, -100, w) - (1 - 0.75 * m)) < 1e-12);
  const z = zoomAbout({ k: 1, x: 0, y: 0 }, 4, 300, 200); // the point at 300, 200 stays at 300, 200
  assert.deepEqual([z.x + 300 * 4, z.y + 200 * 4], [300, 200]);
  assert.deepEqual(lockAxis(10, -3), [10, 0]);
  assert.deepEqual(lockAxis(2, -9), [0, -9]);
});

test("a point on screen maps to the same working-size pixel at any zoom", () => {
  for (const k of [1 / 4, 1, 3.5, 16]) {
    const rect = { left: 50 - 200 * k, top: 30, width: 960 * k, height: 540 * k }; // the view's box, laid out at zoom k
    const [x, y] = pointIn(rect, rect.left + 480 * k, rect.top + 135 * k, 1920, 1088);
    assert.ok(Math.abs(x - 960) < 1e-9 && Math.abs(y - 272) < 1e-9);
  }
});

