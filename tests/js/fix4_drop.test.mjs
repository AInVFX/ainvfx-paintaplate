// What a drop may open (logic.dropRefusal): one movie, or the frames of one sequence, from files or from one folder. Anything
// else is refused before any upload, with the reason. The extensions are those of the Open dialog's Upload tab.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { dropRefusal, plateFile } from "../../web/logic.mjs";

test("a drop opens one movie, or the frames of one sequence, as files or as one folder", () => {
  assert.equal(dropRefusal(["take.mov"]), null);
  assert.equal(dropRefusal(["shot.0001.exr", "shot.0002.exr"]), null);
  assert.equal(dropRefusal(["shot.0001.exr", "shot.0002.exr"], 1), null);
});

test("several movies, a movie with frames, several folders or a folder with files open nothing, and say why", () => {
  assert.equal(dropRefusal(["take_1.mp4", "take_2.mp4"]), "this drop holds 2 movies");
  assert.equal(dropRefusal(["take.mp4", "shot.0001.png"]), "this drop holds a movie and frames");
  assert.equal(dropRefusal(["shot.0001.png"], 2), "this drop holds 2 folders");
  assert.equal(dropRefusal(["shot.0001.png", "still.png"], 1, 1), "this drop holds a folder and files");
  assert.equal(dropRefusal([], 1), "the folder holds no EXR, PNG, TIFF or DPX frames");
  assert.equal(dropRefusal([]), "this drop holds no movie and no frames");
});

test("a drop takes the extensions of the Open dialog's Upload tab, and no other", () => {
  const html = readFileSync(new URL("../../web/paintaplate.html", import.meta.url), "utf8");
  const accept = html.match(/id="files"[^>]*accept="([^"]+)"/)[1].split(",");
  assert.deepEqual(accept.filter((ext) => !plateFile(`take${ext}`)), []);
  assert.deepEqual([".txt", ".jpg", ".DS_Store", ".json"].filter((ext) => plateFile(`take${ext}`)), []);
});
