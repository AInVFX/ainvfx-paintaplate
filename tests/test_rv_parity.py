"""The viewer's colour against OpenRV, value for value.

The reference is OpenRV's colour math, written here from its source (OpenRV at 0bd9675, main on 2 Nov 2026):
ColorIPNode.cpp builds RVColor's 4 x 4 matrix (invert, exposure, contrast, hue, saturation, each multiplied on the left)
and its shader applies gamma before that matrix (ColorMatrix(ColorGamma(source))); OCIOIPNode.cpp makes the OCIO
functions from getOptimizedGPUProcessor(OPTIMIZATION_DEFAULT) and floods the channel after the display. PyOpenColorIO's
CPU processor stands in for RV's GPU one. `reference` gives the 8-bit values on screen; tests/flows/viewer.py reads the
page's canvas for the same pixels and settings and compares them within 1 code value.
"""
import json
import shutil
import subprocess
import sys
import unittest

import numpy as np

from _env import ROOT, require
require("PyOpenColorIO")
sys.path.insert(0, ROOT)
import ocio  # noqa: E402
import PyOpenColorIO as OCIO  # noqa: E402

LUMA = np.array([0.2126, 0.7152, 0.0722])
# black, a near black, 18% grey, 1.0, 4.0, 16.0, saturated red, green and blue, a negative value, two colours
PIXELS = [[0, 0, 0], [0.002, 0.002, 0.002], [0.18, 0.18, 0.18], [1, 1, 1], [4, 4, 4], [16, 16, 16], [1, 0, 0], [0, 1, 0],
          [0, 0, 1], [-0.05, 0.1, 0.2], [0.5, 0.25, 0.1], [0.05, 0.3, 0.8]]
REST = {"exposure": 0, "contrast": 0, "gamma": 1, "saturation": 1, "hue": 0, "channel": "rgb", "invert": False}
CONFIG, SPACE = ocio.BUILTIN, "ACEScg"


def cases() -> list[dict]:
    """Each view of sRGB - Display and Display P3 - Display, one look, and every colour tool on the first view."""
    info = ocio.describe(CONFIG)
    views = [{"config": CONFIG, "display": d["name"], "view": v, "look": ""} for d in info["displays"]
             if d["name"] in ("sRGB - Display", "Display P3 - Display") for v in d["views"]]
    base = {"config": CONFIG, "display": info["display"], "view": info["view"], "look": ""}
    tools = [{"exposure": -2}, {"exposure": 2}, {"contrast": 0.3}, {"gamma": 2.2}, {"saturation": 0}, {"saturation": 2},
             {"hue": 60}, {"channel": "r"}, {"channel": "g"}, {"channel": "b"}, {"channel": "l"}, {"invert": True},
             {"invert": True, "contrast": 0.3}, {"exposure": 1, "gamma": 2.2, "saturation": 1.5, "hue": -30}]
    out = [{"view": v, "d": REST, "name": f"{v['display']} / {v['view']}"} for v in views]
    out += [{"view": base, "d": {**REST, **t}, "name": ", ".join(f"{k} {v}" for k, v in t.items())} for t in tools]
    if info["looks"]:
        out.append({"view": {**base, "look": info["looks"][0]}, "d": REST, "name": f"look {info['looks'][0]}"})
    return [{**c, "space": SPACE} for c in out]


def _rot(axis, angle):  # Rodrigues, for column vectors (TwkMath's makeRotation)
    x, y, z = np.asarray(axis, float) / np.linalg.norm(axis)
    c, s, t = np.cos(angle), np.sin(angle), 1 - np.cos(angle)
    m = np.eye(4)
    m[:3, :3] = [[t * x * x + c, t * x * y - s * z, t * x * z + s * y], [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
                 [t * x * z - s * y, t * y * z + s * x, t * z * z + c]]
    return m


def rv_matrix(d) -> np.ndarray:
    """RVColor's C, as ColorIPNode::evaluate builds it (Mat44f's constructor is row-major)."""
    C = np.eye(4)
    if d["invert"]:
        C = np.array([[-1, 0, 0, 1], [0, -1, 0, 1], [0, 0, -1, 1], [1, 1, 1, 0]], float) @ C
    if d["exposure"]:
        C = np.diag([2.0 ** d["exposure"]] * 3 + [1]) @ C
    c = d["contrast"]
    C = np.array([[1 + c, 0, 0, -c / 2], [0, 1 + c, 0, -c / 2], [0, 0, 1 + c, -c / 2], [0, 0, 0, 1]]) @ C
    if d["hue"]:
        R = _rot(np.cross([1, 1, 1], [0, 0, 1]), np.arccos(1 / np.sqrt(3)))
        lx, ly, lz, _ = R @ np.append(LUMA, 0)
        Z, iZ = np.eye(4), np.eye(4)
        Z[2, :2], iZ[2, :2] = [lx / lz, ly / lz], [-lx / lz, -ly / lz]
        C = np.linalg.inv(R) @ iZ @ _rot([0, 0, 1], np.radians(d["hue"])) @ Z @ R @ C
    s = d["saturation"]
    if s != 1:
        S = np.eye(4)
        S[:3, :3] = (1 - s) * np.tile(LUMA, (3, 1)) + s * np.eye(3)
        C = S @ C
    return C


def reference(case: dict, pixels=PIXELS) -> np.ndarray:
    """The 8-bit values OpenRV shows for `pixels` (file values in the case's colour space) with the case's settings."""
    cfg, v, d = ocio.config(case["view"]["config"]), case["view"], case["d"]
    rgb = np.array(pixels, np.float32)
    cfg.getProcessor(OCIO.ColorSpaceTransform(src=ocio.real(cfg, case["space"]), dst=OCIO.ROLE_SCENE_LINEAR)).getDefaultCPUProcessor().applyRGB(rgb)
    x = rgb.astype(np.float64)
    if d["gamma"] != 1:
        x = np.maximum(x, 0) ** (1 / d["gamma"])
    C = rv_matrix(d)
    x = (x @ C[:3, :3].T + C[:3, 3]).astype(np.float32)
    lin = OCIO.ROLE_SCENE_LINEAR
    out = OCIO.DisplayViewTransform(src=lin, display=v["display"], view=v["view"])
    if v["look"]:
        out = OCIO.GroupTransform([OCIO.LookTransform(src=lin, dst=lin, looks=v["look"]), out])
    x = np.ascontiguousarray(x)
    cfg.getProcessor(out).getDefaultCPUProcessor().applyRGB(x)
    pick = {"r": [1, 0, 0], "g": [0, 1, 0], "b": [0, 0, 1], "l": LUMA}.get(d["channel"])
    if pick is not None:
        x = np.repeat((x @ np.asarray(pick, np.float32))[:, None], 3, 1)
    return np.rint(np.clip(x, 0, 1) * 255).astype(int)


class RVParity(unittest.TestCase):
    def test_reference_follows_rv(self):
        c = {"view": {"config": CONFIG, "display": "sRGB - Display", "view": "Raw", "look": ""}, "space": "ACEScg"}
        lin = ocio.real(ocio.config(CONFIG), OCIO.ROLE_SCENE_LINEAR)
        self.assertEqual(lin, "ACEScg")
        pivot = reference({**c, "d": {**REST, "contrast": 1}}, [[0.5, 0.5, 0.5], [0.75, 0.75, 0.75]])
        self.assertEqual(pivot.tolist(), [[128] * 3, [255] * 3])  # Raw: 0.5 stays, 0.75 goes to 1.0
        first = reference({**c, "d": {**REST, "gamma": 2, "exposure": 1}}, [[0.0625, 0, 0]])  # (0.0625 ** 0.5) * 2 = 0.5
        self.assertEqual(first[0, 0], 128)

    @unittest.skipUnless(shutil.which("node"), "needs Node")
    def test_page_matrix_is_rvs(self):
        ds = [c["d"] for c in cases()]
        js = ("import { displayUniforms } from './web/display.mjs';"
              f"console.log(JSON.stringify({json.dumps(ds)}.map(displayUniforms)));")
        got = json.loads(subprocess.run(["node", "--input-type=module", "-e", js], cwd=ROOT, capture_output=True, text=True, check=True).stdout)
        for d, u in zip(ds, got):
            C = rv_matrix(d)
            np.testing.assert_allclose(u["matrix"], C[:3, :3], atol=1e-6, err_msg=str(d))
            np.testing.assert_allclose(u["offset"], C[:3, 3], atol=1e-6, err_msg=str(d))
            self.assertAlmostEqual(u["exponent"], 1 / d["gamma"])

    def test_table_covers_the_handover(self):
        cs = cases()
        names = " ".join(c["name"] for c in cs)
        for want in ("exposure -2", "exposure 2", "contrast", "gamma 2.2", "saturation 0", "saturation 2", "hue", "channel r",
                     "channel g", "channel b", "channel l", "invert", "sRGB - Display /", "Display P3 - Display /", "look "):
            self.assertIn(want, names)
        for c in cs:
            self.assertEqual(reference(c).shape, (len(PIXELS), 3))


if __name__ == "__main__":
    print(json.dumps([c["name"] for c in cases()], indent=1))
