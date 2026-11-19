"""A new budget in View > Cache memory keeps every cache's frame size. A smaller budget drops only the frames that no
longer fit, and a larger one drops no decoded frame: the green stripe of the frames in memory never empties, and the
« Frame cache » line gives the same frame size each time."""
import re

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
LINE = re.compile(r"^Frame cache: (.+?) \(set in View > Cache memory\), (\d+) of (\d+) frames at (\d+) x (\d+)\.$")
STRIPE = """(() => { const c = document.querySelector('#tl-cache'), d = c.getContext('2d').getImageData(0, 0, c.width, 1).data;
  let lit = 0; for (let i = 0; i < c.width; i++) if (d[i * 4 + 1] > 120) lit++; return lit / c.width; })()"""
WATCH = """(() => { window.__least = 1; const c = document.querySelector('#tl-cache');
  const look = () => { const d = c.getContext('2d').getImageData(0, 0, c.width, 1).data; let lit = 0;
    for (let i = 0; i < c.width; i++) if (d[i * 4 + 1] > 120) lit++; window.__least = Math.min(window.__least, lit / c.width); requestAnimationFrame(look); };
  requestAnimationFrame(look); })()"""


def budget(page, U, size):  # View > Cache memory > Custom…, the row found by its text: a ticked row's name holds its tick
    page.click("#view", button="right")
    for label in ("View", "Cache memory"):
        page.locator("#ctx li.group > span:first-child", has_text=re.compile(f"^{label}$")).first.hover()
    page.locator("#ctx [role=menuitemcheckbox]", has_text="Custom…").click()
    page.wait_for_function("document.querySelector('#ask').open", timeout=5000)
    page.fill("#ask-field", size)
    page.keyboard.press("Enter")


def line(page, U, size):  # the newest « Frame cache » line for this budget: (frames in, frames in all, width, height)
    def newest():
        found = [m for t in U.log_lines(page) if (m := LINE.match(t)) and m[1] == size]
        return tuple(int(x) for x in found[-1].groups()[1:]) if found else None
    U.poll(page, lambda: newest() is not None, 10)
    return newest()


def run(browser, port, U):
    page = U.load(browser, port, device_scale_factor=2)  # the frames at the plate's own size: 128 MB, the least budget, then holds part of them
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    budget(page, U, "2 GB")
    big = line(page, U, "2 GB")
    U.check(big is not None and big[0] == big[1], f"2 GB holds every frame: {big}")
    U.check(U.poll(page, lambda: page.evaluate(STRIPE) > 0.95, 20), f"the stripe fills: {page.evaluate(STRIPE):.2f}")
    budget(page, U, "128 MB")
    small = line(page, U, "128 MB")
    fits = min(big[1], 128_000_000 // (big[2] * big[3] * 4))
    U.check(fits < big[1] and small == (fits, big[1], big[2], big[3]), f"128 MB keeps the frame size and the {fits} frames that fit: {small} after {big}")
    U.check(U.poll(page, lambda: 0.2 < page.evaluate(STRIPE) < 0.9, 5), f"the stripe shows the frames kept: {page.evaluate(STRIPE):.2f}")
    kept = page.evaluate(STRIPE)
    page.evaluate(WATCH)
    budget(page, U, "4 GB")
    again = line(page, U, "4 GB")
    U.check(again == (big[1], big[1], big[2], big[3]), f"4 GB keeps the frame size and plans every frame: {again}")
    U.check(U.poll(page, lambda: page.evaluate(STRIPE) > 0.95, 20) and page.evaluate("window.__least") >= kept - 0.05,
            f"a larger budget drops no decoded frame: the stripe stayed at {page.evaluate('window.__least'):.2f} or more, from {kept:.2f}, and filled")
    page.close()
