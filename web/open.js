// Adds "Open PaintAPlate" to ComfyUI's Extensions menu. The app itself lives in paintaplate.html.
import { app } from "../../scripts/app.js";

app.registerExtension({
  name: "AInVFX.PaintAPlate",
  commands: [{
    id: "AInVFX.PaintAPlate.Open",
    label: "Open PaintAPlate",
    function: () => window.open(new URL("paintaplate.html", import.meta.url), "_blank"),
  }],
  menuCommands: [{ path: ["Extensions"], commands: ["AInVFX.PaintAPlate.Open"] }],
});
