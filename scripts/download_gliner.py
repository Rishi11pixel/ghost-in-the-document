"""Download the open GLiNER model once, then point the app at the local directory.
Run only while online: python scripts/download_gliner.py
"""
from pathlib import Path

from gliner import GLiNER

MODEL_ID = "urchade/gliner_small-v2.1"
DESTINATION = Path(__file__).resolve().parents[1] / ".models" / "gliner-small-v2.1"
DESTINATION.mkdir(parents=True, exist_ok=True)
print(f"Downloading {MODEL_ID} into {DESTINATION} ...")
model = GLiNER.from_pretrained(MODEL_ID)
model.save_pretrained(DESTINATION)
print("Done. Set GHOST_GLINER_MODEL_PATH to this directory before launching the app.")
