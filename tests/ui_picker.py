"""The colour picker in one browser, against the mock ComfyUI or a real one.

    python tests/ui_picker.py [--browser chromium|firefox|webkit] [--no-eyedropper] [--url http://127.0.0.1:8188 --path plates/lighthouse.mp4]

Chrome and Edge have the browser's eyedropper (the EyeDropper API): the pipette by the swatches stays hidden and I opens it
(a stand-in here: automation cannot drive the browser's own). Firefox and Safari have none, nor has a page loaded with
--no-eyedropper: the pipette shows, it or I arms the in-frame picker, a click on the frame gives the brush the colour the
viewer shows there, and Esc leaves the picker. The plate opens with no page error. Without --url the mock ComfyUI starts
with its test plate.
"""
import argparse, os, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ui_mock import check, open_path  # noqa: E402

SPOT = (0.5, 0.5)  # where the frame is clicked, as fractions of its width and height
AVERAGE = """([fx, fy]) => { const v = document.querySelector('#view'), n = 5;  // the 5 x 5 pixels the page averages
  const d = v.getContext('2d').getImageData(Math.round(fx * v.width) - 2, Math.round(fy * v.height) - 2, n, n).data;
  let r = 0, g = 0, b = 0; for (let i = 0; i < d.length; i += 4) { r += d[i]; g += d[i + 1]; b += d[i + 2]; }
  return [r, g, b].map((c) => Math.round(c / (n * n))); }"""


def picker(page, name):
    picking = lambda: page.evaluate("document.querySelector('#view').classList.contains('picking')")  # noqa: E731
    if page.evaluate("window.isSecureContext && 'EyeDropper' in window"):
        check(page.is_hidden("#pick"), f"{name}: the browser's eyedropper is there, so the pipette stays hidden")
        page.evaluate("() => { window.EyeDropper = class { open() { return Promise.resolve({ sRGBHex: '#2E7D32' }); } }; }")
        page.keyboard.press("i")
        page.wait_for_function("document.querySelector('#color').value === '#2e7d32'", timeout=5000)
        check(True, f"{name}: I opens the eyedropper (a stand-in) and the brush takes its colour")
        return
    check(page.is_visible("#pick"), f"{name}: no eyedropper, so the pipette shows by the swatches")
    page.click("#pick")
    check(picking(), f"{name}: the pipette arms the in-frame picker")
    want = page.evaluate(AVERAGE, list(SPOT))
    box = page.locator("#view").bounding_box()
    page.mouse.click(box["x"] + box["width"] * SPOT[0], box["y"] + box["height"] * SPOT[1])
    got = page.input_value("#color")
    rgb = [int(got[i:i + 2], 16) for i in (1, 3, 5)]
    check(all(abs(p - q) <= 6 for p, q in zip(rgb, want)) and not picking(),
          f"{name}: a click on the frame picks the colour on show there: {got} against {want}")
    page.keyboard.press("i")
    armed = picking()
    page.keyboard.press("Escape")
    check(armed and not picking(), f"{name}: I arms the picker again, and Esc leaves it")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", default="chromium", choices=["chromium", "firefox", "webkit"])
    ap.add_argument("--channel", default="", help="a browser channel, such as chrome")
    ap.add_argument("--no-eyedropper", action="store_true", help="remove the EyeDropper API before the page loads")
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
    name = a.channel or a.browser + (" without an eyedropper" if a.no_eyedropper else "")
    try:
        with sync_playwright() as p:
            browser = getattr(p, a.browser).launch(channel=a.channel or None)
            context = browser.new_context(viewport={"width": 1400, "height": 900})
            if a.no_eyedropper:
                context.add_init_script("delete window.EyeDropper;")
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            page.goto(f"{url}/extensions/ainvfx-paintaplate/paintaplate.html")
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
