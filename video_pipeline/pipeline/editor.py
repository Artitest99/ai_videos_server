import json
import re
from pathlib import Path


MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".mp4", ".mov", ".avi", ".mkv", ".webm"}


def numeric_media_sort(path: Path):
    digits = "".join(filter(str.isdigit, path.stem))
    return (int(digits or 0), path.name.lower())


def project_paths(base_dir: Path, file_name: str):
    return {
        "script": base_dir / "scripts" / f"{file_name}.txt",
        "prompts": base_dir / "prompts" / f"{file_name}.json",
        "captions": base_dir / "captions" / f"captions_{file_name}.json",
        "media": base_dir / "assets" / "media" / file_name,
        "output": base_dir / "output" / f"{file_name}.mp4",
    }


def load_editor_project(base_dir: Path, file_name: str):
    paths = project_paths(base_dir, file_name)
    missing = [name for name in ("script", "prompts", "captions") if not paths[name].exists()]
    if missing:
        raise FileNotFoundError(f"Missing project data: {', '.join(missing)}")

    narrations = [part.strip() for part in re.split(r"\s*###\s*", paths["script"].read_text(encoding="utf-8"))]
    prompts = json.loads(paths["prompts"].read_text(encoding="utf-8"))
    captions = json.loads(paths["captions"].read_text(encoding="utf-8"))
    media_files = sorted(
        [path for path in paths["media"].iterdir() if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS],
        key=numeric_media_sort,
    ) if paths["media"].exists() else []
    media_by_index = {}
    for media_path in media_files:
        digits = "".join(filter(str.isdigit, media_path.stem))
        if digits:
            media_by_index[int(digits)] = media_path

    subtitle_scenes = []
    current_words = []
    caption_ranges = []
    range_start = 0
    for index, cue in enumerate(captions):
        bold = cue.get("text_bold") or []
        current_words.append(str(bold[0]) if bold else str(cue.get("text", "")).strip())
        if cue.get("media_transition") or index == len(captions) - 1:
            subtitle_scenes.append(current_words)
            caption_ranges.append((range_start, index + 1))
            current_words = []
            range_start = index + 1

    highest_media_count = max(media_by_index.keys(), default=-1) + 1
    scene_count = max(len(narrations), len(prompts), len(subtitle_scenes), highest_media_count)
    scenes = []
    for index in range(scene_count):
        prompt_entry = prompts[index] if index < len(prompts) else {}
        words = subtitle_scenes[index] if index < len(subtitle_scenes) else []
        media_path = media_by_index.get(index)
        scenes.append({
            "index": index,
            "number": index + 1,
            "narration": narrations[index] if index < len(narrations) else "",
            "prompt": prompt_entry.get("prompt", ""),
            "subtitle_text": " ".join(words),
            "subtitle_word_count": len(words),
            "media_name": media_path.name if media_path else None,
            "media_path": media_path,
        })

    return {"paths": paths, "scenes": scenes, "prompts": prompts, "captions": captions, "caption_ranges": caption_ranges}


def update_caption_words(captions, caption_ranges, scene_word_lists):
    all_words = []
    for scene_index, (start, end) in enumerate(caption_ranges):
        words = scene_word_lists[scene_index]
        if len(words) != end - start:
            raise ValueError(
                f"Scene {scene_index + 1} must keep {end - start} subtitle words to preserve timing."
            )
        all_words.extend(words)

    for index, cue in enumerate(captions):
        group_start = index - index % 2
        group_words = all_words[group_start:group_start + 2]
        cue["text"] = " ".join(group_words)
        cue["text_bold"] = [all_words[index]]
    return captions
