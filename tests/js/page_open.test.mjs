// The Open dialog's trail (logic.crumbs): Input or Output and the folders below, or for a
// full path the machine's own folders, each crumb with the path that browses it.
import assert from "node:assert/strict";
import { test } from "node:test";
import { crumbs, fullPath } from "../../web/logic.mjs";

test("a full path's trail names the machine's folders, each by its full path", () => {
  assert.deepEqual(crumbs("/data/plates"), [{ label: "This machine", path: "/" }, { label: "data", path: "/data" }, { label: "plates", path: "/data/plates" }]);
  assert.deepEqual(crumbs("C:\\shots\\sh010"), [{ label: "C:", path: "C:\\" }, { label: "shots", path: "C:\\shots" }, { label: "sh010", path: "C:\\shots\\sh010" }]);
  assert.deepEqual(crumbs("D:/shots"), [{ label: "D:", path: "D:/" }, { label: "shots", path: "D:/shots" }]);
});

test("a path in ComfyUI's folders keeps its root, Input or Output", () => {
  assert.deepEqual(crumbs("plates"), [{ label: "Input", path: "" }, { label: "plates", path: "plates" }]);
  assert.deepEqual(crumbs("output:paintaplate/scenes"), [{ label: "Output", path: "output:" }, { label: "paintaplate", path: "output:paintaplate" },
    { label: "scenes", path: "output:paintaplate/scenes" }]);
  assert.ok(fullPath("/x") && fullPath("D:/x") && fullPath("C:\\x") && !fullPath("plates") && !fullPath("output:x") && !fullPath(""));
});
