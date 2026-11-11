"""The colour picker in one browser, against the mock ComfyUI or a real one.

    python tests/ui_picker.py [--browser chromium|firefox|webkit] [--url http://127.0.0.1:8188 --path plates/lighthouse.mp4]

The pipette by the swatches, or I, arms the in-frame picker in every browser. A click on the first frame gives the brush the
frame's own colour there, and Esc leaves the picker. A stroke shows its own colour, through OCIO and the colour tools as the
picture does: the picked colour painted elsewhere reads as that colour, and with the exposure up one stop the pick still
gives the frame's own value and a dab of it there shows as the picture did. The plate opens with no page error. Without
--url the mock ComfyUI starts with its test plate.
"""
import argparse, os, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ui_mock import check, open_path, stroke  # noqa: E402

SPOT = (0.5, 0.5)  # where the frame is clicked, as fractions of its width and height
AVERAGE = """([fx, fy]) => { const v = document.querySelector('#view'), n = 5;  // the 5 x 5 pixels the page averages
  const d = v.getContext('2d').getImageData(Math.round(fx * v.width) - 2, Math.round(fy * v.height) - 2, n, n).data;
  let r = 0, g = 0, b = 0; for (let i = 0; i < d.length; i += 4) { r += d[i]; g += d[i + 1]; b += d[i + 2]; }
  return [r, g, b].map((c) => Math.round(c / (n * n))); }"""


def picker(page, name):
    picking = lambda: page.evaluate("document.querySelector('#view').classList.contains('picking')")  # noqa: E731
    box = page.locator("#view").bounding_box()
    at = lambda f: (box["x"] + box["width"] * f[0], box["y"] + box["height"] * f[1])  # noqa: E731
    seen = lambda f: page.evaluate(AVERAGE, list(f))  # noqa: E731
    hexed = lambda: [int(page.input_value("#color")[i:i + 2], 16) for i in (1, 3, 5)]  # noqa: E731
    near = lambda p, q, by: all(abs(a - b) <= by for a, b in zip(p, q))  # noqa: E731

    def pick(f):
        page.keyboard.press("i")
        page.mouse.click(*at(f))
        return hexed()

    def dab(f):  # one dot of the brush, then the pointer away, so the brush outline is not read
        stroke(page, [f, (f[0] + 0.01, f[1])])
        page.mouse.move(box["x"] + 4, box["y"] + 4)
        page.wait_for_timeout(300)
        return seen(f)

    check(page.is_visible("#pick"), f"{name}: the pipette shows by the swatches")
    page.click("#pick")
    check(picking(), f"{name}: the pipette arms the in-frame picker")
    want = seen(SPOT)
    page.mouse.click(*at(SPOT))
    own = hexed()
    check(near(own, want, 6) and not picking(), f"{name}: a click on the frame picks the frame's colour there: {own} against {want}")
    page.keyboard.press("i")
    armed = picking()
    page.keyboard.press("Escape")
    check(armed and not picking(), f"{name}: I arms the picker again, and Esc leaves it")

    # A stroke shows its own colour: the picked colour painted over the place that differs most from it reads as that colour
    grid = [(x / 10, y / 10) for x in range(1, 10) for y in range(1, 10) if abs(x / 10 - SPOT[0]) + abs(y / 10 - SPOT[1]) >= 0.3]
    far = max(grid, key=lambda f: sum(abs(a - b) for a, b in zip(seen(f), own)))
    under = seen(far)
    page.keyboard.press("b")
    over = dab(far)
    check(near(over, own, 2) and not near(under, own, 20), f"{name}: a stroke shows its own colour: {own} painted over {under} reads {over}")

    # With the exposure up one stop, the pick still gives the frame's own value, and a dab of it there shows as the picture did
    page.evaluate("document.activeElement.blur()")
    page.mouse.move(*at((0.5, 0.9)))
    page.keyboard.press("Shift+E")
    page.mouse.down(); page.mouse.move(at((0.5, 0.9))[0] + 100, at((0.5, 0.9))[1], steps=5); page.mouse.up()
    label, lit = page.text_content("#display-state"), seen(SPOT)
    again = pick(SPOT)
    there = dab(SPOT)
    check(label.startswith("E +1.0") and not near(lit, want, 3) and near(again, own, 1) and near(there, lit, 2),
          f"{name}: under {label}, the pick gives the frame's own {again} (first {own}), and a dab of it shows as the picture did: {there} against {lit}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", default="chromium", choices=["chromium", "firefox", "webkit"])
    ap.add_argument("--channel", default="", help="a browser channel, such as chrome")
    ap.add_argument("--url", default="", help="a running ComfyUI; without it, the mock ComfyUI starts")
    ap.add_argument("--path", default="plates/desk.mp4", help="the plate to open, in that ComfyUI's input folder")
    ap.add_argument("--port", type=int, default=8196)
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright
    mock, url = None, a.url.rstrip("/")
    if not url:
        root, url = "/tmp/paintaplate_mock_picker", f"http://127.0.0.1:{a.port}"
        mock = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_comfy.py"), "--plate", "--port", str(a.port), "--root", root],
                                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        for _ in range(60):
            try:
                urllib.request.urlopen(f"{url}/system_stats", timeout=1)
                break
            except Exception:
                time.sleep(0.5)
    name = a.channel or a.browser
    try:
        with sync_playwright() as p:
            browser = getattr(p, a.browser).launch(channel=a.channel or None)
            context = browser.new_context(viewport={"width": 1400, "height": 900})
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.goto(f"{url}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
            page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=120000)
            open_path(page, a.path)
            page.wait_for_function("document.querySelector('#spec').textContent.includes('frames') && document.querySelector('#opening').hidden",
                                   timeout=180000)
            page.wait_for_timeout(1500)  # the first frame on show
            picker(page, name)
            check(not errors, f"{name}: no page error: {errors[:3]}")
            browser.close()
    finally:
        if mock:
            mock.terminate()
    print(f"UI PICKER PASSED ({name})")


if __name__ == "__main__":
    main()
