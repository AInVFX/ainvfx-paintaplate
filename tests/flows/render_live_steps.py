"""The live preview at every step, in the player. On Latent preview, a render starts with the full-size shot. Its pass asks
for a live preview at every step, and the player shows each one over the frame: a looping picture of the whole shot.
The mock's previews keep frame 1 the same at every step, as a real shot does, since it starts from the edited first frame."""
import re

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
WATCH_LIVE = """(() => { window.__live = []; window.__shown = false; const box = document.querySelector('#live'), img = box.querySelector('img');
  new MutationObserver(() => window.__live.push([img.getAttribute('src'), box.querySelector('figcaption').textContent]))
    .observe(img, { attributes: true, attributeFilter: ['src'] });
  new MutationObserver(() => { if (!box.hidden) window.__shown = true; }).observe(box, { attributes: true, attributeFilter: ['hidden'] }); })()"""


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, "?blank=0", errors=errors)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    page.select_option("#preview-size", "latent")
    page.evaluate(U.WATCH)
    page.evaluate(WATCH_LIVE)
    page.keyboard.press("p")
    U.paint_once(page, "a lantern", [(0.3, 0.5), (0.34, 0.56)])
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Shot, full size: done in"), 240000, "the full-size shot")
    shot = [(src, int(m[1]), int(m[2])) for src, caption in page.evaluate("window.__live")
            if (m := re.search(r"Shot, full size: step (\d+) of (\d+)", caption))]
    total = shot[0][2] if shot else 0
    U.check(total > 1 and sorted({step for _, step, _ in shot}) == list(range(1, total + 1)),
            f"the full-size shot shows a live preview at every step: steps {[step for _, step, _ in shot]} of {total}")
    U.check(len({src for src, _, _ in shot}) == total, "each step shows its own picture")
    U.check(page.evaluate("window.__shown") and page.is_hidden("#live"), "the live preview shows in the player, and goes when the pass ends")
    U.no_errors(errors, "with the live preview at every step")
    page.close()
