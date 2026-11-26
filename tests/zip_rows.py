"""An export's zip, read by its rows (routes.zip_entries). Every name starts with the export's stem, the plate's or the
scene's name, then its row's name, which the page takes from the Export dialog's ticks: an element at a stage (app.exportCells,
logic.zipName). Frames sit in a folder of the row's name; one movie, the graph and the models' list sit at the top, as
<stem>_<row>.<ext>; the source plate's files keep their own names in source_plate/."""
import os

ROWS = ("source_plate", "fluid_shot_preview", "fluid_shot_full_size", "plate_hdr", "plate_upscaled", "plate_hdr_upscaled", "fluid_shot_upscaled",
        "shot_preview", "clean_plate_pass_preview", "shot_full_size", "clean_plate_pass_full_size", "light_transfer_full_size", "shot_hdr",
        "layer_full_size", "layer_hdr", "layer_upscaled", "matte", "matte_preview", "matte_upscaled",
        "composite_preview", "composite_full_size", "composite_hdr", "composite_upscaled", "composite_hdr_upscaled", "comfyui_graph", "models",
        "hdr", "fluid_shot", "hdr_upscaled", "export", "review", "shot", "graph", "preview")  # the last: the names of zips from older runs
# The result's rows, the first the zip holds: the composite at full size (a Light-only render names it after its step), else in
# HDR; export, in the zips of older runs, whose route named a part by its id when the request named no row
COMPOSITE = ("composite_full_size", "light_transfer_full_size", "composite_hdr", "export")


def row_of(name: str) -> str:
    """The row of a name in the zip: its folder, or, for a file at the top, the longest row its name ends with."""
    if "/" in name:
        return name.split("/", 1)[0]
    base = os.path.splitext(name)[0]
    return max((r for r in ROWS if base.endswith(f"_{r}")), key=len, default="")


def files(names, row: str, ext=()) -> list:
    """The names of a row, those that end with one of `ext` when it is given."""
    return [n for n in names if row_of(n) == row and not n.endswith("/") and (not ext or n.lower().endswith(ext))]


def composite(names, ext=()) -> list:
    """The result's names, from the first row of COMPOSITE the zip holds: its frames in its folder, else its one movie."""
    for row in COMPOSITE:
        found = files(names, row, ext)
        if found:
            return [n for n in found if "/" in n] or found
    return []
