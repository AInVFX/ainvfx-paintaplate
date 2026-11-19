"""« Text prompt » names the edit's text: the field's label, its dialog, the right-click menu and the Help's Keys tab.
In full screen, T opens the dialog and Enter applies its text; W does nothing."""

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
ALONE = "document.body.classList.contains('plate-alone')"
MENU = "[...document.querySelectorAll('#ctx button')].map((b) => b.textContent.trim())"
KEYS = "[...document.querySelectorAll('#help dt')].map((dt) => [dt.textContent, dt.nextElementSibling.textContent])"


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    U.check(page.text_content(".prompt-label") == "Text prompt" and page.get_attribute("#prompt", "aria-label") == "Text prompt",
            "the field over the frame is labelled Text prompt, for the eye and for a screen reader")

    page.keyboard.press("`")
    page.wait_for_function(ALONE, timeout=5000)
    v = page.locator("#view").bounding_box()
    page.mouse.click(v["x"] + v["width"] / 2, v["y"] + v["height"] / 2, button="right")
    items = page.evaluate(MENU)
    U.check(any(t.startswith("Text prompt…") and t.endswith("T") for t in items) and not any("Words" in t for t in items),
            f"full screen: the right-click menu has Text prompt… (T), and no Words…: {items}")
    page.keyboard.press("Escape")

    page.keyboard.press("w")
    U.check(page.is_hidden("#words") and page.is_hidden("#colours") and page.is_hidden("#help"), "W does nothing: no dialog opens")
    page.keyboard.press("t")
    U.check(page.is_visible("#words") and page.text_content("#words h2") == "Text prompt" and page.get_attribute("#words", "aria-label") == "Text prompt",
            "T opens the dialog Text prompt")
    page.fill("#words-field", "a brass lantern")
    page.keyboard.press("Enter")
    U.check(page.is_hidden("#words") and page.input_value("#prompt") == "a brass lantern",
            f"Enter applies the dialog's text to the text prompt: {page.input_value('#prompt')!r}")

    page.keyboard.press("?")
    keys = dict(page.evaluate(KEYS))
    U.check(keys.get("S, T") == "Colours, text prompt: in a dialog over the frame." and "S, W" not in keys,
            f"the Help's Keys tab gives T for the text prompt: {keys.get('S, T')!r}")
    page.keyboard.press("?")
    page.keyboard.press("`")
    U.no_errors(errors, "with T, W and the dialog Text prompt in full screen")
    page.close()
