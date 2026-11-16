"""An erase where Clean takes the whole object and the prompt writer cites the object's cast shadow (tests/flows/README.md):
once the caption is written, SAM 3.1 looks for « shadow », and the shadow that touches the object and meets the caption's
box for it joins the SAM mask. The mock's prompt writer answers with a caption that cites <shadow_1> (/mock/writer), and
the mock's SAM finds one shadow by that word (/mock/named): an ellipse just under the object that it finds around the
stroke."""
SHADOW = [0.6, 0.62, 0.06, 0.04]  # x, y and the two radii, in fractions of the frame
CAPTION = ('Remove the object <obj_1> completely, with its dark cast shadow <shadow_1>, and continue the ground behind them. '
           '[{"id": "obj_1", "from": "ref_image_0", "src_bbox": [250, 540, 600, 680], "tgt_bbox": null, "desc": "the object to remove"}, '
           '{"id": "shadow_1", "from": "ref_image_0", "src_bbox": [570, 530, 670, 670], "tgt_bbox": null, "desc": "its dark cast shadow"}]')


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    U.mock_route(port, "/mock/writer", {"times": 1, "text": CAPTION})
    U.mock_route(port, "/mock/named", {"times": 1, "ellipse": SHADOW})
    page.click('.tools [data-tool="erase"]')
    U.paint_once(page, "", [(0.6, 0.4), (0.62, 0.45)])  # one stroke, with no words: Clean takes the whole object
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Render v1"), 120000, "render of the erase with its shadow")
    lines = page.evaluate("window.__lines")
    said = [t for t in lines if "shadow" in t and t.startswith("Edit 1: ")]
    U.check(any(t.startswith("Edit 1: SAM 3.1 looking for the shadow of the object.") for t in lines), f"SAM 3.1 looks for the shadow ({said[:2]})")
    U.check(any(t.startswith("Edit 1: the object's shadow joins its SAM mask (") for t in lines), f"the shadow joins the SAM mask ({said[:3]})")
    U.no_errors(errors, "after an erase whose caption cites the object's shadow")
    page.close()
