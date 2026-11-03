"""The viewer workstream's page checks: the colour on the canvas against OpenRV (tests/test_rv_parity.py), and the colour
inspector. Each colour check draws fixed half-float pixels through the real shader (display.mjs) and reads the canvas:
a pixel sampled from a playing shot depends on the browser."""
import json
import sys
import urllib.request
import uuid

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


def upload_4k(port):
    """A 3840 x 2160 EXR plate of 3 frames with known values: [4.0, 0.5, -0.1] at (20, 10), [0.25, 0.75, 16.0] at
    (3800, 2000), a one-pixel checker of 4.0 and 0.0 at (100, 100) to (131, 131), 0.18 elsewhere."""
    import OpenEXR
    img = np.full((2160, 3840, 3), 0.18, np.float32)
    img[10, 20], img[2000, 3800] = [4.0, 0.5, -0.1], [0.25, 0.75, 16.0]
    yy, xx = np.mgrid[100:132, 100:132]
    img[100:132, 100:132] = (((yy + xx) % 2) * 4.0)[..., None]
    for n in range(3):
        path = f"/tmp/native4k.{1001 + n}.exr"
        OpenEXR.File({"compression": OpenEXR.PIZ_COMPRESSION, "type": OpenEXR.scanlineimage}, {"RGB": img.astype(np.float16)}).write(path)
        b = uuid.uuid4().hex
        body = (f'--{b}\r\nContent-Disposition: form-data; name="subfolder"\r\n\r\npaintaplate/native4k\r\n'
                f'--{b}\r\nContent-Disposition: form-data; name="image"; filename="native4k.{1001 + n}.exr"\r\n'
                'Content-Type: application/octet-stream\r\n\r\n').encode() + open(path, "rb").read() + f"\r\n--{b}--\r\n".encode()
        urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/upload/image", data=body,
                                                      headers={"Content-Type": f"multipart/form-data; boundary={b}"})).read()


def native_and_inspector(page, port, U):
    """A 4K EXR plate shows at its own size, paused, at full precision; the inspector reads its stored values; 1:1."""
    upload_4k(port)
    U.open_path(page, "paintaplate/native4k")
    page.wait_for_function("document.querySelector('#spec').textContent.includes('EXR') && document.querySelector('#opening').hidden", timeout=120000)
    page.wait_for_function("document.querySelector('#view').dataset.native === 'true'", timeout=120000)
    size = page.evaluate("(() => { const v = document.querySelector('#view'); return [v.width, v.height, v.dataset.precision]; })()")
    U.check(size == [3840, 2160, "float"], f"paused, a 4K EXR plate shows at its own size and in its own values: {size}")
    checker = page.evaluate("[...document.querySelector('#view').getContext('2d').getImageData(100, 100, 32, 1).data].filter((_, i) => i % 4 === 0)")
    U.check(all(abs(a - b) > 200 for a, b in zip(checker, checker[1:])),
            f"one source pixel per canvas pixel: a one-pixel checker of 4.0 and 0.0 alternates on the canvas: {checker[:8]}")
    page.keyboard.press("F5")
    U.check(page.is_visible("#inspector"), "F5 shows the Color Inspector")

    def inspect(x, y):
        r = page.evaluate("(() => { const r = document.querySelector('#view').getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; })()")
        page.mouse.move(r[0] + (x + 0.5) / 3840 * r[2], r[1] + (y + 0.5) / 2160 * r[3])
        page.wait_for_function(f"document.querySelector('#inspector').dataset.pixel === '{x},{y}' && !!document.querySelector('#inspector').dataset.value", timeout=20000)
        return [float(v) for v in page.evaluate("document.querySelector('#inspector').dataset.value").split(",")]
    got = inspect(20, 10)
    U.check(got == [4.0, 0.5, float(np.float16(-0.1))], f"the inspector reads the EXR's half floats as stored, at native pixel 20, 10: {got}")
    got = inspect(3800, 2000)
    U.check(got == [0.25, 0.75, 16.0], f"and at 3800, 2000, values above 1.0: {got}")
    page.keyboard.press("F5")
    page.keyboard.press("1")
    page.wait_for_timeout(300)
    dev = page.evaluate("document.querySelector('#view').getBoundingClientRect().width * devicePixelRatio")
    U.check(abs(dev - 3840) < 1, f"1 shows the plate 1:1: 3840 plate pixels over {dev:.1f} device pixels")
    page.keyboard.press("f")


PIXEL = "(([x, y]) => [...document.querySelector('#view').getContext('2d').getImageData(x, y, 1, 1).data].slice(0, 3))"
TO_CANVAS = """(([cx, cy]) => { const v = document.querySelector('#view'), r = v.getBoundingClientRect();
  return [Math.floor((cx - r.left) / r.width * v.width), Math.floor((cy - r.top) / r.height * v.height)]; })"""


def zoom_and_paint(page, U):
    """RV's zoom keys, and a stroke lands under the pointer at 4:1 and at 1:2 (the plate on show is 4K, the edits 1920)."""
    page.keyboard.press("Home"); page.keyboard.press("b"); page.click(".sw[data-color='#d32f2f']")
    box = page.eval_on_selector("#viewport", "e => { const r = e.getBoundingClientRect(); return [r.x, r.y, r.width, r.height]; }")
    for key, n, at in (("4", 4, (0.5, 0.5)), ("Shift+2", 0.5, (0.45, 0.5))):
        page.keyboard.press(key); page.wait_for_timeout(300)
        dev = page.evaluate("document.querySelector('#view').getBoundingClientRect().width * devicePixelRatio")
        U.check(abs(dev - 3840 * n) < 2, f"{key} shows {n}:1 as RV: 3840 plate pixels over {dev:.0f} device pixels")
        cx, cy = box[0] + at[0] * box[2], box[1] + at[1] * box[3]
        xy = page.evaluate(TO_CANVAS, [cx, cy]); before = page.evaluate(PIXEL, xy)
        page.mouse.move(cx - 3, cy); page.mouse.down(); page.mouse.move(cx + 3, cy, steps=4); page.mouse.up(); page.wait_for_timeout(300)
        after = page.evaluate(PIXEL, xy)
        U.check(after[0] - after[1] > 60 and sum(abs(a - b) for a, b in zip(before, after)) > 60,
                f"at {key}, the red stroke lands under the pointer: canvas {xy} goes from {before} to {after}")
        page.keyboard.press("Control+z"); page.wait_for_timeout(200)
    page.keyboard.press("f")


def run(browser, port, U):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    rows = parity_table(page)
    with open("/tmp/rv_parity.json", "w") as f:
        json.dump(rows, f)
    bad = [(r["case"], r["max_diff"]) for r in rows if r["max_diff"] is None or r["max_diff"] > 1]
    U.check(not bad, f"the canvas matches OpenRV within 1 code value: {len(rows)} cases, 12 pixels each; over 1: {bad}")
    # F5 shows the Color Inspector and the browser does not reload
    page.evaluate("window.__alive = 1")
    page.keyboard.press("F5")
    U.check(page.evaluate("window.__alive") == 1, "F5 is the page's: it does not reload")
    native_and_inspector(page, port, U)
    zoom_and_paint(page, U)
    page.close()
