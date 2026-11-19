"""Full-precision frames that get no answer. An image sequence's own values reach the viewer from the frames route; when
the browser gets no answer, the log says so once, in red, and the viewer keeps the 8-bit movie."""
import os
import sys
import tempfile

import numpy as np


def run(browser, port, U):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    import plateio
    folder = tempfile.mkdtemp(prefix="review_deep_error_")
    paths = [os.path.join(folder, f"lamp.{1001 + i}.exr") for i in range(4)]
    ramp = np.linspace(0.0, 2.0, 256, dtype=np.float32)  # values above 1.0, which only the full-precision frames keep
    plateio.write_exrs(lambda i: np.broadcast_to(ramp[None, :, None], (144, 256, 3)) * (1 + 0.1 * i), paths, fps=24)
    page = U.load(browser, port)
    page.route("**/paintaplate/frames?*", lambda route: route.abort())  # the frames route never answers
    page.click("#open-btn"); page.click("#open [data-tab=upload]"); page.set_input_files("#files", paths); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.includes('fps')", timeout=60000)
    red = "[...document.querySelectorAll('#log li.error span')].filter((e) => e.textContent.startsWith('Error: full-precision frames of lamp: stopped ('))"
    U.wait_log(page, f"{red}.length > 0", 60000, "the red line of the full-precision frames")
    line = page.evaluate(f"{red}[0].textContent")
    U.check(line.endswith("). Viewer: 8-bit movie."), f"a red line names the source and what the viewer shows: {line!r}")
    page.wait_for_timeout(2000)
    U.check(page.evaluate(f"{red}.length") == 1, "the failure is said once")
    page.close()
