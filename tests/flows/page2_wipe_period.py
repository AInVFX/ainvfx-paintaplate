"""With the wipe on, the period key steps the right side through the Render panel's finished steps, and from the last one
back to the first: every press displays another step. The latest result is passed over when it is the picture of the step
displayed, so no press leaves the picture as it was."""

ROWS = "[...document.querySelectorAll('#stages li[data-pass] .name')].map((e) => e.textContent)"


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    page.click('.tools [data-tool="paint"]')
    U.paint_once(page, "a red ball", [(0.4, 0.5), (0.45, 0.52), (0.5, 0.5)])
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    U.settled(page)
    rows = page.evaluate(ROWS)
    U.check(len(rows) >= 3, f"the Render panel's finished steps: {rows}")
    page.keyboard.press("F6")
    seen = [page.text_content("#wipe .label.right")]
    for _ in range(len(rows) + 1):
        page.keyboard.press(".")
        page.wait_for_timeout(250)
        seen.append(page.text_content("#wipe .label.right"))
    same = [seen[i] for i in range(1, len(seen)) if seen[i] == seen[i - 1]]
    U.check(not same and seen[-1] == seen[1], f"every press of « . » displays another step, and the last step leads back to the first: {seen}")
    U.no_errors(errors, "after the presses")
    page.close()
