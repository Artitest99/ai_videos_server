import json
import math
import re
from pathlib import Path

from django import forms
from django.conf import settings

from voice_config import DEFAULT_VOICE_KEY, VOICE_CHOICES

from .models import VideoJob


SAFE_PROJECT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
ALLOWED_MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
    ".mp4", ".mov", ".avi", ".mkv", ".webm",
}
MAX_UPLOAD_SIZE = 500 * 1024 * 1024
MAX_SCENES = 100
MAX_SCENE_HOLD_SECONDS = 300
MAX_VIDEO_TIMESTAMP_SECONDS = 24 * 60 * 60


class VideoProjectSubmissionForm(forms.Form):
    """Validate the guided creator payload without exposing legacy file formats."""

    file_name = forms.CharField(max_length=80)
    fps = forms.IntegerField(min_value=1, max_value=120, initial=30)
    music_track = forms.CharField(max_length=40)
    voice_key = forms.ChoiceField(
        choices=VOICE_CHOICES,
        initial=DEFAULT_VOICE_KEY,
        required=False,
    )
    scenes_json = forms.CharField(widget=forms.HiddenInput)

    def clean_voice_key(self):
        return self.cleaned_data.get("voice_key") or DEFAULT_VOICE_KEY

    def clean_file_name(self):
        file_name = self.cleaned_data["file_name"].strip()
        if not SAFE_PROJECT_NAME.fullmatch(file_name):
            raise forms.ValidationError(
                "Use 1-80 letters, numbers, underscores, or hyphens; start with a letter or number."
            )
        if VideoJob.objects.filter(file_name=file_name).exists():
            raise forms.ValidationError(
                "This project name already exists. Choose a new name to avoid reusing stale assets."
            )
        return file_name

    def clean_scenes_json(self):
        raw_json = self.cleaned_data["scenes_json"]
        try:
            scenes = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(
                "The scene editor data could not be read. Refresh the page and try again."
            ) from exc

        if not isinstance(scenes, list) or not scenes:
            raise forms.ValidationError("Add at least one scene.")
        if len(scenes) > MAX_SCENES:
            raise forms.ValidationError(f"A project can contain up to {MAX_SCENES} scenes.")

        cleaned_scenes = []
        for index, scene in enumerate(scenes, start=1):
            if not isinstance(scene, dict):
                raise forms.ValidationError(f"Scene {index} is invalid. Remove it and add it again.")

            narration = scene.get("narration", "")
            prompt = scene.get("prompt", "")
            if not isinstance(narration, str):
                raise forms.ValidationError(f"Scene {index} has invalid narration.")
            if not isinstance(prompt, str):
                raise forms.ValidationError(f"Scene {index} has an invalid visual description.")
            try:
                hold_after_seconds = float(scene.get("hold_after_seconds", 0) or 0)
            except (TypeError, ValueError) as exc:
                raise forms.ValidationError(f"Scene {index} has an invalid time after scene.") from exc
            if not math.isfinite(hold_after_seconds) or not 0 <= hold_after_seconds <= MAX_SCENE_HOLD_SECONDS:
                raise forms.ValidationError(
                    f"Scene {index} time after scene must be between 0 and {MAX_SCENE_HOLD_SECONDS} seconds."
                )
            fit_with_borders = scene.get("fit_with_borders", False)
            if not isinstance(fit_with_borders, bool):
                raise forms.ValidationError(f"Scene {index} has an invalid fit-with-borders setting.")
            use_original_audio = scene.get("use_original_audio", False)
            if not isinstance(use_original_audio, bool):
                raise forms.ValidationError(f"Scene {index} has an invalid original sound setting.")
            if not narration.strip() and hold_after_seconds <= 0:
                raise forms.ValidationError(f"Scene {index} needs narration or a positive time after scene.")
            try:
                video_start_seconds = float(scene.get("video_start_seconds", 0) or 0)
                raw_video_end = scene.get("video_end_seconds")
                video_end_seconds = None if raw_video_end in (None, "") else float(raw_video_end)
            except (TypeError, ValueError) as exc:
                raise forms.ValidationError(f"Scene {index} has an invalid video range.") from exc
            if not math.isfinite(video_start_seconds) or not 0 <= video_start_seconds <= MAX_VIDEO_TIMESTAMP_SECONDS:
                raise forms.ValidationError(f"Scene {index} video start time is invalid.")
            if video_end_seconds is not None:
                if not math.isfinite(video_end_seconds) or video_end_seconds > MAX_VIDEO_TIMESTAMP_SECONDS:
                    raise forms.ValidationError(f"Scene {index} video end time is invalid.")
                if video_end_seconds <= video_start_seconds:
                    raise forms.ValidationError(f"Scene {index} video end time must be after its start time.")
            elif video_start_seconds > 0:
                raise forms.ValidationError(f"Scene {index} needs a video end time after its start time.")

            cleaned_scenes.append(
                {
                    "narration": narration.strip(),
                    "prompt": prompt.strip(),
                    "use_original_audio": use_original_audio,
                    "fit_with_borders": fit_with_borders,
                    "hold_after_seconds": round(hold_after_seconds, 2),
                    "video_start_seconds": round(video_start_seconds, 2),
                    "video_end_seconds": round(video_end_seconds, 2) if video_end_seconds is not None else None,
                }
            )
        return cleaned_scenes

    def clean(self):
        cleaned = super().clean()
        scenes = cleaned.get("scenes_json") or []

        for index, scene in enumerate(scenes):
            if not scene["prompt"] and not self.files.get(f"media_{index}"):
                self.add_error(
                    "scenes_json",
                    f"Scene {index + 1} needs either a visual description or an uploaded image/video.",
                )

        for field_name, upload in self.files.items():
            if not field_name.startswith("media_"):
                raise forms.ValidationError("An unexpected upload was received. Refresh and try again.")
            try:
                media_index = int(field_name.removeprefix("media_"))
            except ValueError as exc:
                raise forms.ValidationError("A scene upload could not be matched. Refresh and try again.") from exc
            if media_index < 0 or media_index >= len(scenes):
                raise forms.ValidationError("An uploaded file does not match an existing scene.")

            extension = Path(upload.name).suffix.lower()
            if extension not in ALLOWED_MEDIA_EXTENSIONS:
                raise forms.ValidationError(
                    f"{upload.name} is not a supported image or video format."
                )
            if upload.size > MAX_UPLOAD_SIZE:
                raise forms.ValidationError(f"{upload.name} exceeds the 500 MB upload limit.")

        return cleaned

    def clean_music_track(self):
        track = self.cleaned_data["music_track"].strip()
        music_path = settings.BASE_DIR / "assets" / f"background_music_{track}.mp3"
        if not track.isdigit() or not music_path.exists():
            raise forms.ValidationError("Choose one of the available background tracks.")
        return track
