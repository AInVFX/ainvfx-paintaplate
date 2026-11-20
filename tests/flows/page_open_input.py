"""Open plate: after a plate opened from a folder typed by its full path, the dialog opens again on Input, with its Input
and Output buttons and its filter, not on the machine's folder typed before."""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from page_open import mock_input  # noqa: E402


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    page.click("#open-btn"); page.click("#open [data-tab=files]")
    page.fill("#path", os.path.join(mock_input(), "plates")); page.click("#open-go")
    page.wait_for_function("[...document.querySelectorAll('#crumbs button')].some((b) => b.textContent === 'plates')", timeout=10000)
    page.click("#browse .item:has-text('desk')"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.includes('fps')", timeout=60000)
    page.click("#open-btn"); page.click("#open [data-tab=files]")
    on_input = U.until(page, "document.querySelector('#open [data-root=\"\"]').classList.contains('on')", 5000)
    trail = page.eval_on_selector_all("#crumbs button", "els => els.map((e) => e.textContent)")
    U.check(on_input and trail == ["Input"], f"the dialog opens again on Input, not on the folder typed before: {trail}")
    U.check(page.is_visible('#open [data-root="output:"]') and page.is_visible("#browse-find"), "its Input and Output buttons and its filter are there")
    U.no_errors([e for e in errors if "/paintaplate/stat" not in e and "Failed to load resource" not in e],  # a folder of plates: its stat answers 404, then the dialog lists it
                "after the dialog opens again")
    page.close()
