"""Create empty model files with the names the workflows load, so ComfyUI validates them without the models.

    python tools/placeholders.py /path/to/ComfyUI

For tests only: a workflow that really runs a model needs the real file."""
import glob
import json
import os
import sys

FOLDER = {"UNETLoader": ("unet_name", "diffusion_models"), "CLIPLoader": ("clip_name", "text_encoders"),
          "VAELoader": ("vae_name", "vae"), "LoraLoaderModelOnly": ("lora_name", "loras"),
          "CheckpointLoaderSimple": ("ckpt_name", "checkpoints")}


def main(comfy):
    made = []
    for path in glob.glob(os.path.join(os.path.dirname(__file__), "..", "web", "workflows", "*.json")):
        with open(path) as f:
            prompt = json.load(f)
        for node in prompt.values():
            field, folder = FOLDER.get(node["class_type"], (None, None))
            name = node["inputs"].get(field) if field else None
            target = os.path.join(comfy, "models", folder, name) if isinstance(name, str) else None
            if target and not os.path.exists(target):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                open(target, "wb").close()
                made.append(os.path.relpath(target, comfy))
    print("\n".join(made) or "all model files present")


if __name__ == "__main__":
    main(sys.argv[1])
