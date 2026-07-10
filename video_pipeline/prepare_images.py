"""Promote generated scene media into the renderer's active media directory.

The legacy implementation copied AI files only when the entire media directory
was empty. That prevented one regenerated scene from replacing its stale image.
This version fills missing scene indexes individually, allowing uploaded media
and newly generated media to coexist.
"""

import shutil
from pathlib import Path

from config import BASE_DIR, FILE_NAME


OUTPUT_DIR = BASE_DIR / "assets" / "media" / FILE_NAME
AI_OUTPUT_DIR = OUTPUT_DIR / "ai"
MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".mp4", ".mov", ".avi", ".mkv", ".webm"}


def scene_index(path: Path):
    digits = "".join(filter(str.isdigit, path.stem))
    return int(digits) if digits else None


def promote_missing_generated_media():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if not AI_OUTPUT_DIR.exists():
        print(f"AI output directory '{AI_OUTPUT_DIR}' does not exist.")
        return

    active_indexes = {
        scene_index(path)
        for path in OUTPUT_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS
    }
    copied = 0
    for source in sorted(AI_OUTPUT_DIR.iterdir()):
        index = scene_index(source)
        if not source.is_file() or source.suffix.lower() not in MEDIA_EXTENSIONS or index is None:
            continue
        if index in active_indexes:
            continue
        shutil.copy2(source, OUTPUT_DIR / source.name)
        active_indexes.add(index)
        copied += 1
        print(f"Promoted generated scene {index}: {source.name}")

    if copied == 0:
        print("All generated scene indexes already have active media.")


if __name__ == "__main__":
    promote_missing_generated_media()
