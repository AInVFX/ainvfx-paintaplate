import urllib.request
import json
"""The viewer's checks on playback. The frame cache fills inside one memory budget, at the size the frame is shown. Once
every frame between the in and out points is in memory, the plate and the shot play from memory, on a clock, with the
videos paused. A pause writes one line of statistics. A budget too small for the range keeps a window of frames, and the
videos play. The mock serves VP9 and the sandbox draws WebGL in software: these checks prove the logic, a GPU the speed."""
import re

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
CACHE = "(() => { const c = document.querySelector('#tl-cache').dataset; return [+c.cached, +c.frames, c.size || '']; })()"
FULL = "(() => { const c = document.querySelector('#tl-cache').dataset; return +c.frames > 1 && c.cached === c.frames && !!c.size; })()"
VIEW = "document.querySelector('#view').dataset"
PAUSED = "[...document.querySelectorAll('video')].every((v) => v.paused)"


def opened(browser, port, U, query=""):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0&stats=1{query}")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    return page


def lines(page):
    return page.eval_on_selector_all("#log li span", "els => els.map(e => e.textContent)")


def plan_line(page):  # the last line of the log about the cache's plan
    return next((line for line in reversed(lines(page)) if "Frame cache: " in line), "")


def space(page):  # play or pause, whatever had the focus
    page.evaluate("document.activeElement.blur()")
    page.keyboard.press("Space")


def run(browser, port, U):
    page = opened(browser, port, U)

    # 1. The stripe fills: every frame of the plate, at the size it is shown, inside the Auto budget
    U.wait_log(page, FULL, 150000, "frame cache with every frame of the plate")
    cached, frames, size = page.evaluate(CACHE)
    w, h = (int(v) for v in size.split("x"))
    said = plan_line(page)
    U.check(cached == frames and 960 <= w <= 1280 and "1 GB (Auto), " in said and f"{frames} of {frames} frames at {w} x {h}" in said,
            f"the stripe fills: {cached} of {frames} frames in memory at {w} x {h}, the size the frame is shown, inside the Auto budget ({said[:60]})")

    # 2. With every frame in memory the plate plays from memory: the videos stay paused, a clock moves the playhead
    space(page)
    page.wait_for_function(f"{VIEW}.play === 'memory'", timeout=15000)
    start = page.text_content("#frame-now")
    page.wait_for_timeout(2000)
    U.check(page.evaluate(PAUSED) and page.text_content("#frame-now") != start,
            "with every frame in memory the plate plays from memory: the videos stay paused and the playhead moves on the clock")

    # 3. A pause writes one line of statistics
    space(page)
    page.wait_for_function(f"({VIEW}.stats || '').startsWith('Played')", timeout=10000)
    stats = page.evaluate(f"{VIEW}.stats")
    m = re.match(r"Played (\d+) frames in [\d.]+ s: [\d.]+ fps of 24, \d+ late, \d+ skipped; from memory at \d+ x \d+", stats)
    U.check(bool(m) and int(m.group(1)) >= 3 and "draw " in stats and any(stats in line for line in lines(page)) and page.evaluate(f"{VIEW}.play") == "",
            f"a pause writes one line of statistics in the log: {stats}")

    # 4. View > Cache memory sets the budget and keeps it; View > Playback statistics turns the line off
    U.menu(page, "View", "Cache memory", "512 MB")
    page.wait_for_function("localStorage.getItem('paintaplate.cache') === '512000000'", timeout=5000)
    page.wait_for_timeout(500)
    U.check("512 MB (set in View > Cache memory)" in plan_line(page), f"View > Cache memory sets the budget and keeps it for the next session: {plan_line(page)[:70]}")
    page.click("#view", button="right")  # a ticked entry: U.menu finds an entry by its exact name, without a tick
    page.locator("#ctx li.group > span:first-child", has_text=re.compile("^View$")).first.hover()
    page.locator("#ctx li", has_text="Playback statistics").last.click()
    U.check("Playback statistics off" in page.text_content("#hud"), "View > Playback statistics, ticked while the statistics are on, turns them off")

    # 5. A budget too small for the range: the cache keeps a window of frames at 960 px, never more than fit, and the videos play
    small = opened(browser, port, U, "&cache=8")
    small.wait_for_function("+document.querySelector('#tl-cache').dataset.cached > 0", timeout=60000)
    seen = []
    for _ in range(8):
        small.wait_for_timeout(500); seen.append(small.evaluate(CACHE)[0])
    cached, frames, size = small.evaluate(CACHE)
    said = plan_line(small)
    U.check(0 < max(seen) <= 3 and size == "960x528" and "8 MB (set in the address)" in said and f"3 of {frames} frames at 960 x 528" in said,
            f"a budget of 8 MB holds: at most {max(seen)} frames in memory at {size} ({said[:60]})")
    space(small)
    small.wait_for_function(f"{VIEW}.play === 'video'", timeout=15000)
    small.wait_for_timeout(1500)
    U.check(not small.evaluate(PAUSED), "without every frame in memory the videos play")
    space(small)
    small.wait_for_function(f"({VIEW}.stats || '').includes('from the video')", timeout=10000)
    U.check(True, f"and the statistics name the path: {small.evaluate(f'{VIEW}.stats')[:110]}")
    before = sum("Frame cache: " in line for line in lines(small))
    U.open_path(small, "plates/desk.mp4")
    U.wait_log(small, f"[...document.querySelectorAll('#log li span')].filter((e) => e.textContent.includes('Frame cache: ')).length > {before}", 60000, "cache plan of the plate opened again")
    U.check(plan_line(small).count(" frames at ") == 1, f"a plate that opens logs its cache's plan, the same plate again too: {plan_line(small)[:70]}")
    small.close()

    # 6. A shot on show: once its frames are in memory it plays from memory too
    page.keyboard.press("b"); U.paint_once(page, "a red fire", [(0.30, 0.60), (0.40, 0.60)]); page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    space(page)
    U.wait_log(page, f"{VIEW}.play === 'memory' && {VIEW}.picture === 'shot'", 150000, "shot playing from memory")
    U.wait_log(page, "[...document.querySelectorAll('#log li span')].filter((e) => e.textContent.includes('Frame cache: ')).pop()?.textContent.includes('frames of the shot at')",
               30000, "cache plan that names the shot")  # the plan is logged again each time the shot's movie changes: read it once it names the shot
    said = plan_line(page)
    U.check("frames of the shot at" in said and page.evaluate(PAUSED), f"the shot of the edits plays from memory once its frames are in ({said[-62:]})")
    space(page)
    page.close()

    # The reference laptop's card, 16 GB of VRAM: the small memory profile gives 512 MB, and the line names no card
    urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/mock/card", json.dumps({"vram": 17.2e9, "ram": 65.5e9}).encode(), {"Content-Type": "application/json"}), timeout=5).read()
    laptop = opened(browser, port, U)
    U.wait_log(laptop, FULL, 150000, "frame cache with every frame of the plate, on the small memory profile")
    said = plan_line(laptop)
    U.check(re.fullmatch(r"Frame cache: 512 MB \(Auto\), (\d+) of \1 frames at \d+ x \d+", said) is not None, f"on a 16 GB card beside ComfyUI the Auto budget is 512 MB, and the line names no card: {said}")
    laptop.close()
