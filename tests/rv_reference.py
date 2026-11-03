"""The reference EXR for reading OpenRV's Color Inspector, and the sheet of what to read.

    python tests/rv_reference.py OUT_FOLDER [--config ocio://studio-config-v4.0.0_aces-v2.0_ocio-v2.5]

Writes rv_parity_reference.exr: the 12 pixels of tests/test_rv_parity.py as 64 x 64 patches in one row (768 x 64, RGB half
float, ACEScg values, AP1 chromaticities), and rv_parity_readings.md: for each setting, the patch centres to read and the
8-bit values Paint a plate shows there (RV's math through PyOpenColorIO), with a column for OpenRV's Final Color. Use a
config both have: OpenRV 0bd9675 builds OCIO 2.4.2 by default and 2.5.0 with CY2026; the default here is the ACES 2.0
studio config of OCIO 2.5, which OCIO 2.6 also ships.
"""
import argparse
import os
import sys

import numpy as np
import OpenEXR

sys.path.insert(0, os.path.dirname(__file__))
import test_rv_parity as P  # noqa: E402

SIDE = 64
AP1 = (0.713, 0.293, 0.165, 0.830, 0.128, 0.044, 0.32168, 0.33767)  # ACEScg primaries and white (SMPTE ST 2065-1, AP1)


def write_exr(path):
    img = np.zeros((SIDE, SIDE * len(P.PIXELS), 3), np.float16)
    for i, px in enumerate(P.PIXELS):
        img[:, i * SIDE:(i + 1) * SIDE] = px
    header = {"compression": OpenEXR.ZIP_COMPRESSION, "type": OpenEXR.scanlineimage, "chromaticities": AP1}
    OpenEXR.File(header, {"RGB": img}).write(path)


def sheet(config):
    rows = ["| Setting | Patch | Pixel (x, y) | Source (ACEScg) | Paint a plate, 8-bit | OpenRV Final Color x 255 |", "| --- | --- | --- | --- | --- | --- |"]
    info = P.ocio.describe(config)
    base = {"config": config, "display": "sRGB - Display", "view": info["displays"][0]["views"][0], "look": ""}
    cases = [{"view": {**base, "display": d["name"], "view": v}, "d": P.REST, "name": f"{d['name']} / {v}"}
             for d in info["displays"] if d["name"] in ("sRGB - Display", "Display P3 - Display") for v in d["views"]]
    for t in ({"exposure": -2}, {"exposure": 2}, {"contrast": 0.3}, {"gamma": 2.2}, {"saturation": 0}, {"saturation": 2},
              {"hue": 60}, {"channel": "l"}, {"invert": True}, {"invert": True, "contrast": 0.3}):
        cases.append({"view": base, "d": {**P.REST, **t}, "name": f"{base['view']}, " + ", ".join(
            f"{k} {v}" + (" (1.0472 rad in RV)" if k == "hue" else "") for k, v in t.items())})
    for c in cases:
        ref = P.reference({**c, "space": "ACEScg"})
        for i, px in enumerate(P.PIXELS):
            rows.append(f"| {c['name']} | {i + 1} | {i * SIDE + SIDE // 2}, {SIDE // 2} | {px} | {list(map(int, ref[i]))} | |")
    return "\n".join(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--config", default="ocio://studio-config-v4.0.0_aces-v2.0_ocio-v2.5")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    write_exr(os.path.join(a.out, "rv_parity_reference.exr"))
    with open(os.path.join(a.out, "rv_parity_readings.md"), "w", encoding="utf-8") as f:
        f.write(f"# OpenRV readings for the Paint a plate parity table\n\nConfig `{a.config}`, File Color Space ACEScg, "
                "every other colour setting at its default. In OpenRV, F5 shows the Color Inspector; click the pixel, "
                "switch it to Final Color, and write the three values times 255.\n\n" + sheet(a.config) + "\n")
