"""The viewer workstream's page checks: the colour on the canvas against OpenRV (tests/test_rv_parity.py), and the colour
inspector. Each colour check draws fixed half-float pixels through the real shader (display.mjs) and reads the canvas:
a pixel sampled from a playing shot depends on the browser."""
import json
import sys

import numpy as np

sys.path.insert(0, "tests")
import test_rv_parity as P  # noqa: E402

DRAW = """async ({ cases, halfs, w }) => {
  const { Display } = await import("/extensions/ainvfx-paintaplate/display.mjs");
  const D = new Display({ onerror: (m) => { throw new Error(m); } }), out = [];
  for (const c of cases) {
    D.setView(c.view);
    let img = null;
    for (let t = 0; t < 400 && !img; t++) { img = D.image({ width: w, height: 1, data: new Uint16Array(halfs) }, c.d, c.space); if (!img) await new Promise((ok) => setTimeout(ok, 25)); }
    if (!img) { out.push(null); continue; }
    const cv = document.createElement("canvas"); cv.width = w; cv.height = 1;
    const x = cv.getContext("2d"); x.drawImage(img, 0, 0);
    const p = x.getImageData(0, 0, w, 1).data, row = [];
    for (let i = 0; i < w; i++) row.push([p[4 * i], p[4 * i + 1], p[4 * i + 2]]);
    out.push(row);
  }
  return out;
}"""


def parity_table(page):
    """Every case of the parity table: the page's 8-bit values and OpenRV's, and the largest difference."""
    cases = P.cases()
    halfs = np.array(P.PIXELS, np.float16).view(np.uint16).ravel().tolist()
    got = page.evaluate(DRAW, {"cases": [{k: c[k] for k in ("view", "d", "space")} for c in cases], "halfs": halfs, "w": len(P.PIXELS)})
    rows = []
    for c, g in zip(cases, got):
        ref = P.reference(c)
        diff = None if g is None else int(np.abs(np.array(g) - ref).max())
        rows.append({"case": c["name"], "max_diff": diff, "page": g, "rv": ref.tolist()})
    return rows


def run(browser, port, U):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    rows = parity_table(page)
    with open("/tmp/rv_parity.json", "w") as f:
        json.dump(rows, f)
    bad = [(r["case"], r["max_diff"]) for r in rows if r["max_diff"] is None or r["max_diff"] > 1]
    print(f"parity: {len(rows)} cases x {len(P.PIXELS)} pixels, largest difference {max(r['max_diff'] or 0 for r in rows)} code values")
    assert not bad, f"the canvas differs from OpenRV by more than 1 code value: {bad}"
    # F5 shows the Color Inspector and the browser does not reload
    page.evaluate("window.__alive = 1")
    page.keyboard.press("F5")
    assert page.evaluate("window.__alive") == 1, "F5 reloaded the page"
    page.close()
