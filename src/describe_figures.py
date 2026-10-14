import json
import re
import time
from pathlib import Path

from ollama import chat
from PIL import Image

ROOT = Path.cwd()
IMAGE_DIR = ROOT / "data/processed/figure_crops"
OUT = ROOT / "data/processed/figure_descriptions.jsonl"
MODEL = "qwen2.5vl:7b"

def image_size(path):
    try:
        with Image.open(path) as im:
            return im.size
    except Exception:
        return (0, 0)

def page_number(path):
    match = re.search(r"page_(\d+)", path.name)
    return int(match.group(1)) if match else None

done = set()
if OUT.exists():
    with OUT.open() as f:
        for line in f:
            try:
                done.add(json.loads(line)["image"])
            except Exception:
                pass

files = sorted(IMAGE_DIR.glob("*.png"))
processed = 0
skipped = 0
errors = 0

with OUT.open("a") as out:
    for i, path in enumerate(files, 1):
        if str(path.relative_to(ROOT)) in done:
            continue

        width, height = image_size(path)

        # Skip tiny crops likely to be icons or decorative fragments.
        if width < 250 or height < 180:
            skipped += 1
            continue

        try:
            response = chat(
                model=MODEL,
                messages=[{
                    "role": "user",
                    "content": (
                        "Describe only what is visibly supported by this image "
                        "from a corporate annual report. Classify it as a chart, "
                        "table, diagram, photograph, logo, or decoration. "
                        "Transcribe readable labels and summarize meaningful "
                        "relationships or data. If it is a logo or decoration, "
                        "say so briefly. Mark unreadable text as unclear. "
                        "Do not guess facts or infer unseen context. "
                        "Return a concise description in 2-5 sentences."
                    ),
                    "images": [str(path)],
                }],
                options={"temperature": 0},
            )

            record = {
                "image": str(path.relative_to(ROOT)),
                "page_number": page_number(path),
                "width": width,
                "height": height,
                "description": response.message.content.strip(),
                "model": MODEL,
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            processed += 1

            if processed % 10 == 0:
                print(f"Described {processed}; skipped {skipped}; errors {errors}")

        except Exception as exc:
            errors += 1
            print(f"ERROR {path.name}: {exc}")

print(f"\nFinished. New descriptions: {processed}")
print(f"Skipped small crops: {skipped}")
print(f"Errors: {errors}")
print(f"Dataset: {OUT}")
