"""An export's zip, read by its rows (routes.zipped). Every name starts with the export's stem, the plate's or the scene's
name, then its row's name, which the page takes from the Export dialog's rows (logic.zipNames). Frames sit in a folder of
the row's name; one movie, the graph and the models' list sit at the top, as <stem>_<row>.<ext>."""
import os

# The rows the page names, then the route's own names for a request that names none (its parts' ids)
ROWS = ("composite_full_size", "light_transfer_full_size", "shot_full_size", "matte", "comfyui_graph", "models", "sdr_to_hdr",
        "fluid_shot", "fluid_shot_preview", "composite_upscaled", "matte_upscaled", "plate_upscaled", "sdr_to_hdr_upscaled",
        "fluid_shot_upscaled", "export", "review", "shot", "graph", "preview")
# The composite's row: a Light-only render names it after its step, and the route names it export when a request names no
# row (tests/comfy_live.py), as in the zips of older runs
COMPOSITE = ("composite_full_size", "light_transfer_full_size", "export")


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
    """The composite's names: its frames in its folder, else its one movie at the top."""
    found = [n for row in COMPOSITE for n in files(names, row, ext)]
    return [n for n in found if "/" in n] or found
