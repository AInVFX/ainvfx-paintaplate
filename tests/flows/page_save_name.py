"""Save scene names a blank plate's scene: its first save asks for a name, as the question before replacing a scene does,
with « fluid_shot » to start from. Its next save keeps that name."""


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    U.paint_once(page, "thick white smoke", [(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)])
    page.keyboard.press("End")
    U.stroke(page, [(0.45, 0.3), (0.55, 0.2)])
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1) + " && document.querySelector('#fluid').hidden", timeout=120000)
    page.click("#save-btn")
    asked = U.until(page, "document.querySelector('#ask').open", 10000)
    U.check(asked and page.text_content("#ask-text") == "Name this scene." and page.input_value("#ask-field") == "fluid_shot",
            f"the first save of a blank plate's scene asks for its name: {page.text_content('#ask-text')!r}, {page.input_value('#ask-field') if asked else ''!r}")
    page.fill("#ask-field", "smoke giant")
    U.check(page.text_content("#ask-yes") == "Save as smoke_giant", f"the button says the name it saves under: {page.text_content('#ask-yes')!r}")
    page.click("#ask-yes")
    U.wait_log(page, "[...document.querySelectorAll('#log li span')].some((e) => e.textContent.startsWith('Scene smoke_giant saved'))", 20000, "the save")
    page.click("#save-btn")
    U.until(page, "document.querySelector('#ask').open", 10000)
    U.check(page.text_content("#ask-text") == "A scene named smoke_giant exists.", f"the next save keeps the name, and asks before it replaces the scene: {page.text_content('#ask-text')!r}")
    page.click("#ask-no")
    U.no_errors(errors, "after the two saves")
    page.close()
