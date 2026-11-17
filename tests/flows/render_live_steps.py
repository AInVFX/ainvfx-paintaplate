"""The live preview at every step. With the Preview pass Off, a render starts with the full-size shot. Its pass asks for
a live preview at every step (LIVE.every), and the page shows each one in the inset: a looping picture of the whole shot.
The mock's previews keep frame 1 the same at every step, as a real shot does, since it starts from the edited first frame."""
import re

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
WATCH_INSET = """(() => { window.__inset = []; const box = document.querySelector('#live-inset'), img = box.querySelector('img');
  new MutationObserver(() => window.__inset.push([img.getAttribute('src'), box.querySelector('figcaption').textContent, box.hidden]))
    .observe(img, { attributes: true, attributeFilter: ['src'] }); })()"""


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, "?blank=0", errors=errors)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    page.select_option("#preview-size", "0")
    page.evaluate(U.WATCH)
    page.evaluate(WATCH_INSET)
    page.keyboard.press("p")
    U.paint_once(page, "a lantern", [(0.3, 0.5), (0.34, 0.56)])
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Shot, full size: done in"), 240000, "the full-size shot")
    shot = [(src, int(m[1]), int(m[2])) for src, caption, _ in page.evaluate("window.__inset")
            if (m := re.search(r"Shot, full size: step (\d+) of (\d+)", caption))]
    total = shot[0][2] if shot else 0
    U.check(total > 1 and sorted({step for _, step, _ in shot}) == list(range(1, total + 1)),
            f"the full-size shot shows a live preview at every step: steps {[step for _, step, _ in shot]} of {total}")
    U.check(len({src for src, _, _ in shot}) == total, "each step shows its own picture in the inset")
    U.no_errors(errors, "with the live preview at every step")
    page.close()
