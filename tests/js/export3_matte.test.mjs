// The upscaled matte's frames (logic.matteWindow): each window saves the matte frames the window before did not, each
// numbered by its frame in the shot, so all windows together number every frame of the shot once, from 1.
import assert from "node:assert/strict";
import test from "node:test";
import { matteWindow, upscaleWindows } from "../../web/logic.mjs";

test("the windows' matte frames number every frame of the shot once, from 1", () => {
  for (const [frames, size] of [[121, 21], [121, 42], [49, 49], [97, 33], [200, 64], [17, 17]]) { // windows larger than the frames two of them share
    const windows = upscaleWindows(frames, size), numbers = [];
    windows.forEach(([, count], i) => { const { share, first } = matteWindow(windows, i); for (let j = 0; j < count - share; j++) numbers.push(first + j); });
    assert.deepEqual(numbers, Array.from({ length: frames }, (_, k) => k + 1), `${frames} frames in windows of ${size}`);
  }
});
