"""The text prompt's placeholder follows the plate: a blank plate shows the fluid's, and a plate opened after it shows the
tool's own, as picking the tool does."""


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "33")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    fluid = page.get_attribute("#prompt", "placeholder")
    U.open_plate(page)
    shown = page.get_attribute("#prompt", "placeholder")
    page.click('.tools [data-tool="paint"]')
    tool = page.get_attribute("#prompt", "placeholder")
    U.check(bool(fluid) and shown == tool and shown != fluid,
            f"a blank plate shows the fluid's placeholder, then a plate shows the tool's: {fluid!r}, then {shown!r}, Paint's {tool!r}")
    U.no_errors(errors, "after the two plates")
    page.close()
