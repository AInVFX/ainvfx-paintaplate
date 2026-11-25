"""A switch of the sources on show keeps a cache's frames when its new size is near its own. With a budget that holds the
shot alone at the size on show, the wipe shares it with the plate and plans the shot a few pixels smaller: the shot keeps
its size and the frames that still fit. With the wipe off, its own size comes back with its frames: the green stripe never
falls below where it was."""
import re

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
SHOT = re.compile(r"(all|\d+) of the shot's (\d+) frames at (\d+) x (\d+)")
STRIPE = """(() => { const c = document.querySelector('#tl-cache'), d = c.getContext('2d').getImageData(0, 0, c.width, 1).data;
  let lit = 0; for (let i = 0; i < c.width; i++) if (d[i * 4 + 1] > 120) lit++; return lit / c.width; })()"""
WATCH = """(() => { window.__least = 1; const c = document.querySelector('#tl-cache');
  const look = () => { const d = c.getContext('2d').getImageData(0, 0, c.width, 1).data; let lit = 0;
    for (let i = 0; i < c.width; i++) if (d[i * 4 + 1] > 120) lit++; window.__least = Math.min(window.__least, lit / c.width); requestAnimationFrame(look); };
  requestAnimationFrame(look); })()"""


def shot_lines(page, U):  # the shot's part of every « Frame cache » line: (frames in, frames in all, width, height)
    return [tuple(int(m[2] if x == "all" else x) for x in m.groups()) for t in U.log_lines(page) if t.startswith("Frame cache, ") and (m := SHOT.search(t))]


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    page.click("#view", button="right")
    for label in ("View", "Cache memory"):
        page.locator("#ctx li.group > span:first-child", has_text=re.compile(f"^{label}$")).first.hover()
    page.locator("#ctx [role=menuitemcheckbox]", has_text="Custom…").click()
    page.wait_for_function("document.querySelector('#ask').open", timeout=5000)
    page.fill("#ask-field", "220 MB"); page.keyboard.press("Enter")
    page.keyboard.press("p")
    U.paint_once(page, "a red lantern", [(0.3, 0.5), (0.34, 0.56)])
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelector('#render-left').textContent === 'full size ready'", timeout=180000)
    U.check(U.poll(page, lambda: bool(shot_lines(page, U)) and page.evaluate(STRIPE) > 0.95, 20), f"the shot plays from memory: {shot_lines(page, U)[-1:]}")
    alone = shot_lines(page, U)[-1]
    page.keyboard.press("F6")
    U.check(U.poll(page, lambda: shot_lines(page, U)[-1] != alone, 10), f"the wipe plans the caches again: {shot_lines(page, U)[-2:]}")
    wiped = shot_lines(page, U)[-1]
    U.check(wiped[2:] == alone[2:] and alone[1] - 4 <= wiped[0] < alone[1], f"the shot keeps its size, {alone[2]} x {alone[3]}, and the frames that fit: {wiped} after {alone}")
    page.wait_for_timeout(1500)
    before = page.evaluate(STRIPE)
    page.keyboard.press("F6")
    page.evaluate(WATCH)
    page.wait_for_timeout(1000)
    U.check(shot_lines(page, U)[-1] == wiped, f"the wipe off brings back a plan the log said already: no new line: {shot_lines(page, U)[-2:]}")
    page.wait_for_timeout(1000)
    U.check(page.evaluate("window.__least") >= before - 0.05, f"its frames stayed: the stripe never fell below {page.evaluate('window.__least'):.2f}, from {before:.2f}")
    page.close()
