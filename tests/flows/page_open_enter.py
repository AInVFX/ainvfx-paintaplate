"""Open plate: Enter in the path field opens the path typed, as the Open button does."""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from page_open import mock_input  # noqa: E402


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    page.click("#open-btn"); page.click("#open [data-tab=files]")
    page.fill("#path", os.path.join(mock_input(), "plates", "desk.mp4"))
    page.press("#path", "Enter")
    U.check(U.until(page, "document.querySelector('#spec').textContent.includes('fps')", 60000),
            f"Enter in the path field opens the plate, as Open does: {page.text_content('#spec')!r}")
    U.no_errors(errors, "after Enter")
    page.close()
