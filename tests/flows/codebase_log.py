"""The codebase workstream's page checks for the log (tests/flows/README.md). The status line says what to do next and the
log records what happened: a hint shows in the status line only, and a fact is written to the log once. A plate that
opens writes two lines, and a blank plate keeps its fluid hint."""
import re

HINT = "Ready. Open a plate to start."
SAID = """() => { window.__said = []; const line = document.querySelector('#status');
  new MutationObserver(() => window.__said.push(line.textContent)).observe(line, { childList: true, characterData: true, subtree: true }); }"""  # every sentence the status line shows from now on: a later one cannot hide it
PLAYABLE = "() => { window.__playable = 0; document.addEventListener('canplaythrough', () => { window.__playable += 1; }, true); }"  # counts each time a video can play through: the open's last sentence comes then
NEXT = "Describe the edit at the top, paint on the frame, then Generate."
FLUID = "Paint a fluid keyframe, describe it at the top, then Generate."
OPENED = re.compile(r"^Plate \S+ opened in [\d.]+ s: (\d+) x (\d+), (\d+) frames, (\d+-bit|float), (.+)$")  # the plate's line: the open's time, the size, the frames, the bit depth, the colour space
SIZES = re.compile(r"^Working sizes: edits at \d+ x \d+, edit preview at \d+ x \d+, shot preview at \d+ x \d+, tracking at \d+ x \d+\.$")


def run(browser, port, U):
    page = U.load(browser, port)  # ?blank=0: no plate opens at start
    status, lines = page.text_content("#status"), U.log_lines(page)
    U.check(status == HINT and not any("Open a plate" in t for t in lines) and any(t.startswith("Page ready in") for t in lines),
            f"at start the status line holds the hint, and the log holds what happened, without the hint: {status!r} {lines}")
    page.evaluate(PLAYABLE)
    U.open_plate(page)
    page.wait_for_function("window.__playable > 0", timeout=60000)  # the playback video is loaded: every sentence of the open is said
    status, lines = page.text_content("#status"), U.log_lines(page)
    plate, sizes = [OPENED.match(t) for t in lines if t.startswith("Plate ")], [t for t in lines if t.startswith("Working sizes")]
    U.check(len(plate) == 1 and plate[0] is not None and plate[0].group(1, 2, 4) == ("1280", "704", "8-bit") and plate[0].group(5).endswith("(from file)")
            and len(sizes) == 1 and SIZES.match(sizes[0]) is not None,
            f"a plate that opens writes two lines, one with the open's time, the size, the frames, the bit depth and the colour space, one with the working sizes: {[t for t in lines if t.startswith(('Plate ', 'Working sizes'))]}")
    told = [t for t in lines if "Describe the edit" in t or "Ready to play" in t or "OCIO > Colour space" in t]
    U.check(status == f"Ready to play. {NEXT}" and not told, f"what to do next shows in the status line only: {status!r}, and in the log: {told}")
    page.evaluate(SAID)
    name, _ = U.save_scene(page)
    said, lines = page.evaluate("window.__said"), U.log_lines(page)
    fact, then = f"Scene {name} saved on this ComfyUI", "Open plate > Scenes opens it again, or downloads it."
    U.check(f"{fact}. {then}" in said and [t for t in lines if "saved on this ComfyUI" in t] == [fact] and not any(then in t for t in lines),
            f"a save is one fact in the log, and the status line adds what to do next: {said} {[t for t in lines if 'Scene' in t]}")
    page.select_option("#preview-size", index=1)
    page.wait_for_function("window.__said.some((t) => t.startsWith('Previews at'))", timeout=10000)
    fact = next(t for t in page.evaluate("window.__said") if t.startswith("Previews at"))
    U.check(U.log_lines(page).count(fact) == 1, f"a fact with no instruction still shows in the status line and goes to the log, once: {fact!r}")
    page.evaluate("window.__playable = 0")
    page.click("#open-btn"); page.click("#open [data-tab=blank]"); page.click("#open-go")  # a blank plate, at the Blank tab's settings
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    page.wait_for_function("window.__playable > 0", timeout=60000)
    status, lines = page.text_content("#status"), U.log_lines(page)
    blank = [OPENED.match(t) for t in lines if t.startswith("Plate ")][-1]
    U.check(status == FLUID and blank is not None and blank.group(1, 2, 3, 4) == ("960", "512", "121", "16-bit") and not any("Ready to play" in t for t in lines),
            f"a blank plate keeps its fluid hint once its playback video is loaded, and its line gives the bit depth asked for its fluid shot: {status!r}, {[t for t in lines if t.startswith('Plate ')][-1:]}")
    page.close()
