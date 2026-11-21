"""The X-ray shows the matte the composite uses. The mock's shot drifts against the plate by 6% of the frame, as an LTX
shot can, and its tracking matte follows the drift; the composite moves both back onto the plate, as Fit to Plate does.
On a frame where the shot drifted, the X-ray's tint covers where the composite differs from the plate. Each picture is
read once the viewer says it drew its own frame (`#view` data-picture and data-native), not after a fixed time."""
import json
import urllib.request

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
GRID = """(sel) => { const src = document.querySelector(sel), c = document.createElement('canvas'); c.width = 64; c.height = 36;
  const x = c.getContext('2d'); x.drawImage(src, 0, 0, 64, 36); return Array.from(x.getImageData(0, 0, 64, 36).data); }"""
SHOWS = "(want) => { const v = document.querySelector('#view'); return v.dataset.picture === want && v.dataset.native === 'true'; }"
DRAWN = """(() => { const x = document.querySelector('#xray'); if (x.hidden || x.dataset.from !== 'full') return false;
  const d = x.getContext('2d').getImageData(0, 0, x.width, x.height).data; for (let i = 3; i < d.length; i += 4) if (d[i] > 8) return true; return false; })()"""


def shift(port, dx):  # the mock's drift, as a fraction of the frame's width
    request = urllib.request.Request(f"http://127.0.0.1:{port}/mock/shift", data=json.dumps({"dx": dx}).encode(), headers={"Content-Type": "application/json"})
    urllib.request.urlopen(request, timeout=5).read()


def centre(cells):
    return (sum(x for x, _ in cells) / len(cells) / 64, sum(y for _, y in cells) / len(cells) / 36) if cells else None


def run(browser, port, U):
    errors = []
    shift(port, 0.06)
    page = U.load(browser, port, errors=errors)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    page.keyboard.press("p")
    U.paint_once(page, "a red lantern", [(0.3, 0.5), (0.34, 0.56)])
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelector('#render-left').textContent === 'full size ready'", timeout=180000)
    page.keyboard.press("End"); page.wait_for_function(SHOWS, arg="shot", timeout=30000)
    shot = page.evaluate(GRID, "#view")
    page.keyboard.down("o"); page.wait_for_function(SHOWS, arg="plate", timeout=30000)  # the plate's own frame: it can still be on its way
    plate = page.evaluate(GRID, "#view")
    page.keyboard.up("o"); page.wait_for_function(SHOWS, arg="shot", timeout=30000)
    changed = [(i % 64, i // 64) for i in range(64 * 36) if sum(abs(shot[4 * i + k] - plate[4 * i + k]) for k in range(3)) > 60]
    page.keyboard.press("x")
    page.wait_for_function(DRAWN, timeout=30000)
    tint = page.evaluate(GRID, "#xray")
    tinted = {(i % 64, i // 64) for i in range(64 * 36) if tint[4 * i + 3] > 8}
    covered = sum(c in tinted for c in changed) / max(1, len(changed))
    a, b = centre(changed), centre(sorted(tinted))
    U.check(len(changed) >= 4 and covered >= 0.8 and abs(a[0] - b[0]) < 0.03 and abs(a[1] - b[1]) < 0.03,
            f"on the last frame, the tint covers {covered:.0%} of where the composite differs from the plate, centred at {b} against {a}, though the shot drifted 6%")
    U.check(page.text_content("#hud") == "X-ray: the full-size composite's matte.", f"the HUD names the matte: {page.text_content('#hud')!r}")
    U.no_errors(errors, "with a shot that drifts against the plate")
    page.close()
