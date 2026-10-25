"""AInVFX PaintAPlate: paint edits onto a moving plate, get the shot back in its own format.

The app is a page served by ComfyUI from ./web: open it from the Extensions menu,
or at /extensions/ainvfx-paintaplate/paintaplate.html. Every step runs as a
workflow from ./web/workflows; the nodes in nodes.py only fill gaps in core.
"""
from comfy_api.v0_0_2 import ComfyExtension, io

from .nodes import NODES

WEB_DIRECTORY = "./web"


class PaintAPlate(ComfyExtension):
    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return NODES


async def comfy_entrypoint() -> PaintAPlate:
    return PaintAPlate()
