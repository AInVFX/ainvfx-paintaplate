"""The viewer's checks on a stop and what follows it. Esc or Stop on the edit being generated keeps the edit and its
strokes; nothing of a stopped pass stays in the frame; an edit being changed shows without its old result; strokes replay
in the order they were made. The mock holds a job open (/mock/hold), so every check meets the pass it stops."""
import base64
import io
import json
import re
import urllib.request

import numpy as np
from PIL import Image

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
PICTURE = "document.querySelector('#view').dataset.picture"
STATUS = "document.querySelector('#status').textContent"
PIXEL = """([x, y]) => { const v = document.querySelector('#view');
  return [...v.getContext('2d').getImageData(Math.round(x * v.width), Math.round(y * v.height), 1, 1).data.slice(0, 3)]; }"""
SPY = """() => { window.__uploads = [];  // every image the page uploads, as a data URL
  for (const how of ['append', 'set']) {
    const add = FormData.prototype[how];
    FormData.prototype[how] = function (name, value, ...rest) {
      if (value instanceof Blob) { const r = new FileReader(); r.onload = () => window.__uploads.push(r.result); r.readAsDataURL(value); }
      return add.call(this, name, value, ...rest);
    };
  } }"""


def hold(port, **what):  # the mock keeps the next job that writes `output`, or fills `slot`, open for `seconds`
    req = urllib.request.Request(f"http://127.0.0.1:{port}/mock/hold", json.dumps(what).encode(), {"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=5).read()


def enter_held(page, port, U, seconds=30, key="Enter"):
    """Generate, with the edit's first Klein pass kept open by the mock for `seconds`; `key` is Enter, or Control+Enter for
    another try. Returns once the mock runs that pass. The status line says « edit preview » before the pass is posted: a
    stop pressed in that gap cancels a pass that was never posted, and the hold stays armed for the next edit's pass,
    which then lasts `seconds`."""
    running = lambda: sum(e[0] == "held" for e in U.mock_route(port, "/mock/events"))  # noqa: E731
    before = running()
    hold(port, output="patch", seconds=seconds)
    page.keyboard.press(key)
    page.wait_for_function(f"/edit preview|first look/.test({STATUS})", timeout=30000)
    if not U.poll(page, lambda: running() > before, 30):
        raise AssertionError("the mock did not start the edit's first Klein pass within 30 s of Enter")


def masks(page):  # the black and white images among the uploads: the edit masks, as arrays
    out = []
    masks.seen = []
    for url in page.evaluate("window.__uploads"):
        im = np.asarray(Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).convert("RGB"), np.int16)
        grey = np.abs(im[..., 0] - im[..., 1]).max() < 3 and np.abs(im[..., 1] - im[..., 2]).max() < 3
        masks.seen.append((im.shape[1], im.shape[0], bool(grey), round(float(((im < 8) | (im > 247)).mean()), 3)))
        if grey and ((im < 8) | (im > 247)).mean() > 0.9:
            out.append(im[..., 0])
    return out


def run(browser, port, U):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
    page.wait_for_function(f"{STATUS}.startsWith('Ready')", timeout=60000)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    page.evaluate(SPY)
    rows = lambda: page.evaluate("document.querySelectorAll('#history li').length")
    status = lambda: page.text_content("#status")
    away = lambda: (page.mouse.move(5, 5), page.wait_for_timeout(250))
    pixel = lambda at: np.array(page.evaluate(PIXEL, list(at)))
    kept, gone = (0.31, 0.60), (0.39, 0.60)  # inside the first stroke: its left part, and the part rubbed out
    plate, plate_gone = pixel(kept), pixel(gone)

    # 1. Esc during the first Klein pass: the edit stays, with its strokes, as the strokes in progress
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.30, 0.60), (0.40, 0.60)])
    enter_held(page, port, U)
    page.keyboard.press("Escape"); away()
    U.check(rows() == 1 and status().startswith("Stopped. Edit 1 keeps") and "Ctrl+Enter" in status() and not page.is_disabled("#generate"),
            f"Esc during the first Klein pass keeps the edit: {rows()} row in History, Generate is live, and the status line says what Enter and Ctrl+Enter do ({status()[:60]})")
    U.check(page.text_content("#editing").startswith("Editing 1") and np.abs(pixel(kept) - plate).sum() > 60,
            f"the stopped edit stays the current edit, and its strokes stay on the frame: {pixel(kept).tolist()} on a plate of {plate.tolist()}")

    # 2. Half the stroke rubbed out, then Enter: a new result. The first LTX pass of its render is held for check 4
    page.keyboard.press("x"); U.paint_once(page, "a red fire", [(0.37, 0.60), (0.44, 0.60)]); page.keyboard.press("x")
    hold(port, slot="live", seconds=40)
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000); away()
    made = pixel(kept)
    U.check(np.abs(made - plate).sum() > 40 and np.abs(pixel(gone) - plate_gone).max() <= 16,
            f"Enter after the stop makes the edit from the changed strokes: its result shows at the stroke kept ({made.tolist()}), the plate where it was rubbed out ({pixel(gone).tolist()})")

    # 3. The made edit is changed: the first frame shows its strokes without its old result, so a rubbed stroke leaves no paint
    page.keyboard.press("x"); U.paint_once(page, "a red fire", [(0.28, 0.60), (0.36, 0.60)]); page.keyboard.press("x"); away()
    U.check(np.abs(pixel(kept) - plate).max() <= 16,
            f"rubbing a stroke of a made edit shows the plate there, not the old result: {pixel(kept).tolist()} against the plate's {plate.tolist()}")
    page.keyboard.press("Escape")  # the rub is dropped: the edit goes back to its result

    # 4. Stop during an LTX pass whose live preview is in the frame: nothing of it stays, not after a stroke, not after Generate
    page.wait_for_function(f"{PICTURE} === 'live'", timeout=60000)
    page.click("#stop"); page.wait_for_timeout(300)
    U.check(page.evaluate(PICTURE) != "live" and status().startswith("Stopped") and not page.is_disabled("#generate"),
            f"Stop during an LTX pass takes its live preview off the frame: it shows {page.evaluate(PICTURE)}")
    U.paint_once(page, "a red fire", [(0.30, 0.45), (0.34, 0.45)]); away()
    U.check(page.evaluate(PICTURE) != "live", "a stroke after the stop shows the first frame and the strokes")
    hold(port, output="patch", seconds=6)
    page.keyboard.press("Enter"); page.wait_for_function(f"/edit preview|first look/.test({STATUS})", timeout=30000); page.wait_for_timeout(1000)
    U.check(page.evaluate(PICTURE) != "live", "Generate after the stop never brings the stopped pass's preview back")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)

    # 5. Paint, rub, paint over the rubbed place: the last stroke is in the masks the page uploads
    page.keyboard.press("n")
    U.paint_once(page, "a blue vase", [(0.55, 0.30), (0.70, 0.30)])
    page.keyboard.press("x"); U.paint_once(page, "a blue vase", [(0.58, 0.30), (0.67, 0.30)]); page.keyboard.press("x")
    U.paint_once(page, "a blue vase", [(0.62, 0.30), (0.63, 0.30)])
    page.evaluate("window.__uploads = []")
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=2), timeout=120000)
    got = masks(page)
    last = [int(m[round(0.30 * m.shape[0]), round(0.625 * m.shape[1])]) for m in got]
    U.check(len(got) >= 2 and min(last) > 200, f"a stroke painted after a rub, over the rubbed place, is in the {len(got)} masks Klein receives: {last} (uploads: {masks.seen})")

    # 6. Ctrl+Enter after a stop: the edit runs again with another seed
    enter_held(page, port, U, key="Control+Enter")
    page.keyboard.press("Escape")
    U.check(rows() == 2 and status().startswith("Stopped. Edit 2 keeps"), f"Esc on an edit made again keeps it and its strokes: {status()[:40]}")
    page.keyboard.press("Control+Enter")
    page.wait_for_function(U.DONE.format(n=2), timeout=120000)
    seeds = [int(m.group(1)) for line in U.log_lines(page) for m in [re.search(r'Edit 2: Paint .* seed (\d+)', line)] if m]
    U.check(len(seeds) >= 3 and seeds[-1] != seeds[-2], f"Ctrl+Enter after the stop tries another seed: {seeds[-2:]}")
    page.close()
