import os
import json
import re
import random
import sys
import subprocess
import math
from pathlib import Path
import numpy as np
from helper import get_array_type, to_float
from moviepy.editor import (
    ImageClip, AudioFileClip, CompositeVideoClip,
    CompositeAudioClip, VideoFileClip, AudioClip, concatenate_audioclips, vfx
)
from moviepy.audio.fx.volumex import volumex
from moviepy.audio.fx.all import audio_loop
from moviepy.video.VideoClip import ColorClip
from PIL import Image, ImageDraw, ImageFont

# --- Pillow 11.x compatibility shim for MoviePy 1.0.3 ---
try:
    _Resampling = getattr(Image, "Resampling", None)
    if _Resampling:
        if not hasattr(Image, "ANTIALIAS"):
            Image.ANTIALIAS = _Resampling.LANCZOS
        for _name in ("BICUBIC", "BILINEAR", "NEAREST", "LANCZOS"):
            if not hasattr(Image, _name):
                setattr(Image, _name, getattr(_Resampling, _name))
except Exception:
    pass

from config import BASE_DIR, FILE_NAME, MUSIC, FPS
from moviepy.config import get_setting


class VideoGenerator:
    """
    Vertical Shorts/TikTok/Reels video generator with professional motion.

    Main changes compared with the older version:
    - all media is resized to safely cover 1080x1920 before animation;
    - effects use smooth easing instead of linear movement;
    - amateur-looking slide/spin/large shake effects are mapped to clean cinematic motion;
    - clips overlap slightly and crossfade, preventing black flicker between scenes;
    - Ken Burns movement is subtle, controlled, and never exposes empty edges;
    - captions use lower-third placement and cleaner pop/rise animation.
    """

    SCRIPT_PATH = str(BASE_DIR / "scripts" / f"{FILE_NAME}.txt")
    VOICEOVER_PATH = str(BASE_DIR / "assets" / "voiceovers" / f"{FILE_NAME}.mp3")
    CAPTIONS_PATH = str(BASE_DIR / "captions" / f"captions_{FILE_NAME}.json")
    PROMPTS_PATH = str(BASE_DIR / "prompts" / f"{FILE_NAME}.json")
    MEDIA_FOLDER = str(BASE_DIR / "assets" / "media" / FILE_NAME)
    BACKGROUND_MUSIC_PATH = str(BASE_DIR / "assets" / f"background_music_{MUSIC}.mp3")
    OUTPUT_PATH = str(BASE_DIR / "output" / f"{FILE_NAME}.mp4")
    FONT_PATH = str(BASE_DIR / "assets" / "fonts" / "Montserrat-Bold.ttf")

    VIDEO_WIDTH, VIDEO_HEIGHT = 1080, 1920

    # Professional motion defaults for Shorts.
    # Keep these subtle. Big movements look cheap and can make AI images feel unstable.
    MEDIA_EXTRA_SCALE = 1.10          # room for pans without showing borders
    MEDIA_CROSSFADE = 0.18           # clean scene overlap, not a visible fade-to-black
    FIRST_MEDIA_FADE = 0.10
    LAST_MEDIA_FADEOUT = 0.18
    DEFAULT_BG_MUSIC_VOLUME = 0.08
    DUCKED_BG_MUSIC_VOLUME = 0.015
    ORIGINAL_AUDIO_VOLUME = 1.0
    CAPTION_Y = int(VIDEO_HEIGHT * 0.61)
    ADD_VIGNETTE = False
    WORKING_OVERSCAN = 1.06
    MAX_SOURCE_ASPECT_MULTIPLIER = 1.22

    IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp')
    VIDEO_EXTENSIONS = ('.mp4', '.mov', '.avi', '.webm', '.mkv')

    def __init__(self):
        self.caption_image_cache = {}
        # Reproducible random animation choices.
        random.seed(17)

    # ----------------------------- basic helpers -----------------------------
    @staticmethod
    def _clamp(x, lo=0.0, hi=1.0):
        return max(lo, min(hi, x))

    @staticmethod
    def _lerp(a, b, p):
        return a + (b - a) * p

    @classmethod
    def _smoothstep(cls, p):
        p = cls._clamp(p)
        return p * p * (3.0 - 2.0 * p)

    @classmethod
    def _ease_in_out_cubic(cls, p):
        p = cls._clamp(p)
        if p < 0.5:
            return 4.0 * p * p * p
        return 1.0 - pow(-2.0 * p + 2.0, 3) / 2.0

    @classmethod
    def _ease_out_cubic(cls, p):
        p = cls._clamp(p)
        return 1.0 - pow(1.0 - p, 3)

    @classmethod
    def _ease_out_back(cls, p, c1=1.45):
        p = cls._clamp(p)
        c3 = c1 + 1.0
        return 1.0 + c3 * pow(p - 1.0, 3) + c1 * pow(p - 1.0, 2)

    @staticmethod
    def _safe_truetype(font_path: str, size: int) -> ImageFont.ImageFont:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            return ImageFont.load_default()

    @staticmethod
    def _line_height(draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont, extra: int = 10) -> int:
        bbox = draw.textbbox((0, 0), "Agjpqy", font=font, stroke_width=0)
        return (bbox[3] - bbox[1]) + extra

    @staticmethod
    def _text_width(draw: ImageDraw.ImageDraw, s: str, font: ImageFont.ImageFont) -> float:
        return draw.textlength(s, font=font)

    def split_text_with_hyphen(self, text):
        words = re.split(r'(\s+|-|\u2014)', text)
        return [word for word in words if word.strip() and word != ' ']

    def is_video_file(self, filename):
        return filename.lower().endswith(self.VIDEO_EXTENSIONS)

    def is_image_file(self, filename):
        return filename.lower().endswith(self.IMAGE_EXTENSIONS)

    # ----------------------------- captions -----------------------------
    def parse_captions_json(self, json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            captions = []
            for seg in data:
                text = seg.get("text", "").strip()
                captions.append({
                    "start": round(float(seg["start"]), 2),
                    "end": round(float(seg["end"]), 2),
                    "text": text,
                    "text_bold": seg.get("text_bold", []),
                    "bold_color": seg.get("bold_color", "yellow"),
                    "media_transition": seg.get("media_transition", False),
                    "border_color": seg.get("border_color", "black"),
                    "effect": seg.get("effect", None),
                    "caption_effect": seg.get("caption_effect", None)
                })

            return sorted(captions, key=lambda x: x["start"])
        except Exception as e:
            print(f"Error parsing captions file: {e}")
            return []

    def create_caption_image(self, text, text_bold=None, bold_color="yellow",
                             border_color="black", width=VIDEO_WIDTH, height=450):
        """Create a transparent caption image.

        Stroke is slightly smaller than the old version because huge strokes tend to
        look amateur on Shorts. The caption is still very readable on mobile.
        """
        cache_key = f"{text}_{str(text_bold)}_{bold_color}_{border_color}_{width}x{height}"
        if cache_key in self.caption_image_cache:
            return self.caption_image_cache[cache_key]

        img = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = self._safe_truetype(self.FONT_PATH, 82)

        words = self.split_text_with_hyphen(text)
        lines = []
        line = []
        line_width = 0
        space_width = self._text_width(draw, " ", font)
        max_line_width = width * 0.84

        for word in words:
            word_width = self._text_width(draw, word, font)
            if line and line_width + word_width + space_width >= max_line_width:
                lines.append(line)
                line = [word]
                line_width = word_width
            else:
                line.append(word)
                line_width += word_width + space_width

        if line:
            lines.append(line)

        line_height = self._line_height(draw, font, extra=8)
        y = (height - len(lines) * line_height) // 2

        global_idx = 0
        for line in lines:
            line_width = sum(self._text_width(draw, w, font) for w in line) + space_width * (len(line) - 1)
            x = (width - line_width) / 2

            for word in line:
                word_width = self._text_width(draw, word, font)

                if get_array_type(text_bold) == "integers":
                    is_bold = bool(text_bold) and global_idx in text_bold
                else:
                    key = word.strip(' ., -!?: \u2014')
                    is_bold = bool(text_bold) and key in (text_bold or [])

                fill_color = bold_color if is_bold else 'white'
                border_col = border_color if is_bold else 'black'
                stroke = 11 if is_bold else 9

                draw.text((x, y), word, font=font, fill=fill_color,
                          stroke_width=stroke, stroke_fill=border_col)
                x += word_width + space_width
                global_idx += 1

            y += line_height

        img_array = np.array(img)
        self.caption_image_cache[cache_key] = img_array
        return img_array

    def create_caption_animation(self, seg, img_array, caption_animation=None):
        duration = max(0.01, seg["end"] - seg["start"])

        if not caption_animation:
            # Avoid too many caption styles. Consistency looks more professional.
            caption_animation = random.choice(['pop', 'rise', 'static'])

        if caption_animation == 'static':
            # Static means no fade, scale, movement, or other transition.
            return (
                ImageClip(img_array, duration=duration)
                .set_start(seg["start"])
                .set_end(seg["end"])
                .set_position(("center", self.CAPTION_Y))
            )

        fadein_time = min(0.08, duration * 0.15)
        fadeout_time = min(0.08, duration * 0.15)
        base = (
            ImageClip(img_array, duration=duration)
            .set_start(seg["start"])
            .set_end(seg["end"])
            .fadein(fadein_time)
            .fadeout(fadeout_time)
        )

        if caption_animation in ('pop', 'pop-out'):
            def scale(t):
                p = self._ease_out_back(min(t / 0.22, 1.0), c1=1.15)
                return 0.90 + 0.10 * p

            return base.resize(scale).set_position(("center", self.CAPTION_Y))

        if caption_animation in ('rise', 'slide'):
            def pos(t):
                p = self._ease_out_cubic(min(t / 0.24, 1.0))
                return ("center", self.CAPTION_Y + (1.0 - p) * 42)

            def scale(t):
                p = self._ease_out_cubic(min(t / 0.24, 1.0))
                return 0.96 + 0.04 * p

            return base.resize(scale).set_position(pos)

        # Unknown effects fall back to a simple fade rather than movement.
        return base.set_position(("center", self.CAPTION_Y))

    def build_scene_timeline(self, captions):
        """Map legacy word timings to scenes, then insert each scene's requested hold."""
        with open(self.PROMPTS_PATH, "r", encoding="utf-8") as f:
            settings = json.load(f)
        try:
            with open(self.SCRIPT_PATH, "r", encoding="utf-8") as f:
                script_scenes = re.split(r"\s*###\s*", f.read())
        except OSError:
            script_scenes = []

        timeline = []
        caption_index = 0
        output_cursor = 0.0
        for index, setting in enumerate(settings):
            narration = setting.get("narration")
            if narration is None:
                narration = script_scenes[index] if index < len(script_scenes) else ""
            word_count = len(re.findall(r"\b[\w'-]+\b", narration))
            scene_captions = captions[caption_index:caption_index + word_count]
            caption_index += word_count
            hold = max(0.0, float(setting.get("hold_after_seconds", 0) or 0))

            if scene_captions:
                raw_start = scene_captions[0]["start"]
                raw_end = scene_captions[-1]["end"]
                narration_duration = max(0.01, raw_end - raw_start)
                shift = output_cursor - raw_start
                adjusted = []
                for cue in scene_captions:
                    shifted = dict(cue)
                    shifted["start"] = max(output_cursor, cue["start"] + shift)
                    shifted["end"] = max(shifted["start"] + 0.01, cue["end"] + shift)
                    adjusted.append(shifted)
            else:
                raw_start = raw_end = None
                narration_duration = 0.0
                adjusted = []

            # For a narration-free scene, the entered time is the scene's explicit duration.
            visual_duration = narration_duration + hold
            timeline.append({
                "index": index,
                "start": output_cursor,
                "narration_end": output_cursor + narration_duration,
                "end": output_cursor + visual_duration,
                "raw_start": raw_start,
                "raw_end": raw_end,
                "captions": adjusted,
                "use_original_audio": bool(setting.get("use_original_audio", False)),
                "fit_with_borders": bool(setting.get("fit_with_borders", False)),
                "hold_after_seconds": hold,
                "video_start_seconds": max(0.0, float(setting.get("video_start_seconds", 0) or 0)),
                "video_end_seconds": (
                    float(setting["video_end_seconds"])
                    if setting.get("video_end_seconds") not in (None, "") else None
                ),
            })
            output_cursor += visual_duration

        return timeline

    @staticmethod
    def _silence(duration, fps=44100):
        def make_silence(t):
            if isinstance(t, np.ndarray):
                return np.zeros((len(t), 2), dtype=float)
            return np.zeros(2, dtype=float)
        return AudioClip(make_silence, duration=duration, fps=fps)

    def build_narration_track(self, raw_audio, timeline):
        parts = []
        for scene in timeline:
            if raw_audio is not None and scene["raw_start"] is not None:
                # Caption preparation intentionally offsets the first cue by 50 ms.
                # MoviePy interprets a negative subclip start relative to the end of
                # the source, which can silently remove the narration. Preserve that
                # lead-in as silence and only address the MP3 with non-negative times.
                if scene["raw_start"] < 0:
                    parts.append(self._silence(-scene["raw_start"]))
                audio_start = max(0.0, scene["raw_start"])
                audio_end = min(scene["raw_end"], raw_audio.duration)
                if audio_end > audio_start:
                    parts.append(raw_audio.subclip(audio_start, audio_end))
            hold = scene["hold_after_seconds"]
            if hold > 0:
                parts.append(self._silence(hold))
        if not parts:
            return self._silence(max((scene["end"] for scene in timeline), default=0.01))
        return concatenate_audioclips(parts)

    def duck_background_music(self, music, intervals):
        normal = self.DEFAULT_BG_MUSIC_VOLUME
        ducked = self.DUCKED_BG_MUSIC_VOLUME
        def apply_gain(get_frame, t):
            frame = get_frame(t)
            if isinstance(t, np.ndarray):
                gain = np.full(t.shape, normal, dtype=float)
                for start, end in intervals:
                    gain[(t >= start) & (t < end)] = ducked
                if getattr(frame, "ndim", 1) > 1:
                    gain = gain[:, None]
                return frame * gain
            return frame * (ducked if any(start <= t < end for start, end in intervals) else normal)
        return music.fl(apply_gain, keep_duration=True)
    # ----------------------------- media loading / motion -----------------------------
    def _load_media_clip(self, media_path, duration, video_start_seconds=0.0, video_end_seconds=None):
        is_video = self.is_video_file(media_path)
        if is_video:
            try:
                clip = VideoFileClip(media_path)
                trim_start = min(max(0.0, float(video_start_seconds or 0)), max(0.0, clip.duration - 0.01))
                trim_end = clip.duration if video_end_seconds is None else min(float(video_end_seconds), clip.duration)
                if (trim_start > 0 or video_end_seconds is not None) and trim_end > trim_start:
                    clip = clip.subclip(trim_start, trim_end)
                if clip.duration < duration:
                    clip = clip.fx(vfx.loop, duration=duration)
                else:
                    clip = clip.subclip(0, duration)
                source_audio = clip.audio
                return clip.without_audio().set_duration(duration), True, source_audio
            except Exception as e:
                print(f"Error loading video {media_path}: {e}")
                fallback = ColorClip((self.VIDEO_WIDTH, self.VIDEO_HEIGHT), color=(0, 0, 0)).set_duration(duration)
                return fallback, False, None
        try:
            return ImageClip(media_path).set_duration(duration), False, None
        except Exception as e:
            print(f"Error loading image {media_path}: {e}")
            fallback = ColorClip((self.VIDEO_WIDTH, self.VIDEO_HEIGHT), color=(0, 0, 0)).set_duration(duration)
            return fallback, False, None
    def _crop_to_working_aspect(self, clip):
        """Crop very wide sources before resizing so discarded pixels are never processed."""
        target_aspect = self.VIDEO_WIDTH / self.VIDEO_HEIGHT
        max_aspect = target_aspect * self.MAX_SOURCE_ASPECT_MULTIPLIER
        if clip.w / max(1, clip.h) <= max_aspect:
            return clip
        crop_width = int(clip.h * max_aspect)
        x1 = max(0, int((clip.w - crop_width) / 2))
        return clip.crop(x1=x1, y1=0, width=crop_width, height=clip.h)

    def _resize_to_cover(self, clip, extra_scale=None):
        if extra_scale is None:
            extra_scale = self.MEDIA_EXTRA_SCALE
        scale = max(self.VIDEO_WIDTH / max(1, clip.w), self.VIDEO_HEIGHT / max(1, clip.h))
        return clip.resize(scale * extra_scale)

    @staticmethod
    def _encoder_available(encoder):
        ffmpeg_binary = get_setting("FFMPEG_BINARY")
        command = [
            ffmpeg_binary, "-v", "error", "-f", "lavfi", "-i",
            "color=c=black:s=64x64:d=0.05", "-c:v", encoder, "-f", "null", "NUL"
        ]
        try:
            return subprocess.run(command, capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def _encoding_settings(self):
        if not hasattr(self, "_cached_encoding_settings"):
            self._cached_encoding_settings = (
                ("h264_amf", "speed") if self._encoder_available("h264_amf")
                else ("libx264", "veryfast")
            )
        return self._cached_encoding_settings

    def _normalize_video_media(
        self, media_path, duration, fit_with_borders=False,
        video_start_seconds=0.0, video_end_seconds=None,
    ):
        """Cache a short portrait H.264 working copy for efficient MoviePy decoding."""
        source = Path(media_path)
        cache_dir = source.parent / ".render_cache"
        cache_dir.mkdir(exist_ok=True)
        width = int(math.ceil(self.VIDEO_WIDTH * self.WORKING_OVERSCAN / 2) * 2)
        height = int(math.ceil(self.VIDEO_HEIGHT * self.WORKING_OVERSCAN / 2) * 2)
        trim_start = max(0.0, float(video_start_seconds or 0))
        trim_end = float(video_end_seconds) if video_end_seconds is not None else None
        selected_duration = max(0.01, trim_end - trim_start) if trim_end is not None else duration
        working_duration = min(duration, selected_duration)
        duration_ms = max(1, int(math.ceil(working_duration * 1000)))
        start_ms = max(0, int(round(trim_start * 1000)))
        end_ms = "full" if trim_end is None else max(start_ms + 1, int(round(trim_end * 1000)))
        mode = "fit" if fit_with_borders else "cover"
        cache_name = (
            f"{source.stem}_{source.stat().st_mtime_ns}_{start_ms}-{end_ms}_"
            f"{duration_ms}_{width}x{height}_{mode}.mp4"
        )
        destination = cache_dir / cache_name
        if destination.exists() and destination.stat().st_size > 0:
            return str(destination)

        temporary = destination.with_suffix(".tmp.mp4")
        codec, preset = self._encoding_settings()
        ffmpeg_binary = get_setting("FFMPEG_BINARY")
        video_filter = (
            f"scale={self.VIDEO_WIDTH}:{self.VIDEO_HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={self.VIDEO_WIDTH}:{self.VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:black"
            if fit_with_borders else
            f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
        )
        command = [
            ffmpeg_binary, "-y", "-v", "error", "-ss", f"{trim_start:.3f}", "-i", str(source),
            "-t", f"{working_duration:.3f}",
            "-vf", video_filter,
            "-map", "0:v:0", "-map", "0:a?", "-c:v", codec,
            "-preset", preset, "-b:v", "8M", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(temporary),
        ]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0 and codec != "libx264":
            command[command.index(codec)] = "libx264"
            command[command.index(preset)] = "veryfast"
            result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            temporary.unlink(missing_ok=True)
            print(f"Warning: video normalization failed; using source media. {result.stderr[-500:]}")
            return str(source)
        temporary.replace(destination)
        print(f"Prepared render cache: {destination.name}")
        return str(destination)
    def _normalize_animation_name(self, animation):
        if not animation:
            return "slow_push"

        aliases = {
            # Old names kept for backward compatibility, but mapped to cleaner motion.
            "pan": "pan_zoom_left",
            "full-pan": "pan_zoom_left",
            "pan-from-center": "slow_push",
            "pan-from-right": "pan_zoom_right",
            "zoom": "slow_push",
            "zoomout": "slow_pull",
            "watermark": "slow_pull",
            "watermark_zoom": "slow_push",
            "super_zoomout": "cinematic_pull",
            "slide-right": "soft_reveal_right",
            "slide-left": "soft_reveal_left",
            "slide-top": "drift_down",
            "slide-bottom": "drift_up",
            "pop": "soft_pop",
            "whip": "fast_push",
            "spin": "slow_push",
            "shake": "micro_shake",
            "static": "static",
        }
        return aliases.get(animation, animation)

    def _motion_clip(self, clip, animation, duration, extra_scale=None, fit_with_borders=False):
        """Crop early and apply cover sizing plus motion in one resize operation."""
        animation = self._normalize_animation_name(animation)
        W, H = self.VIDEO_WIDTH, self.VIDEO_HEIGHT
        if fit_with_borders:
            contain_scale = min(W / max(1, clip.w), H / max(1, clip.h))
            fitted = clip.resize(contain_scale).set_position("center")
            return fitted.on_color(size=(W, H), color=(0, 0, 0), pos=("center", "center"))
        clip = self._crop_to_working_aspect(clip)
        base_w, base_h = clip.w, clip.h
        if extra_scale is None:
            extra_scale = self.MEDIA_EXTRA_SCALE
        cover_scale = max(W / max(1, base_w), H / max(1, base_h)) * extra_scale

        if animation == "static":
            return clip.resize(cover_scale).set_position("center")

        presets = {
            "slow_push":       (1.000, 1.060,  0.00,  0.00,  0.04, -0.04),
            "slow_pull":       (1.070, 1.000,  0.00,  0.00, -0.02,  0.03),
            "cinematic_pull":  (1.100, 1.015,  0.08, -0.08, -0.03,  0.03),
            "pan_zoom_left":   (1.015, 1.070,  0.45, -0.45,  0.03, -0.02),
            "pan_zoom_right":  (1.015, 1.070, -0.45,  0.45,  0.03, -0.02),
            "drift_up":        (1.030, 1.060,  0.00,  0.00,  0.35, -0.35),
            "drift_down":      (1.030, 1.060,  0.00,  0.00, -0.35,  0.35),
            "soft_reveal_left":  (1.035, 1.070,  0.22, -0.16,  0.00,  0.00),
            "soft_reveal_right": (1.035, 1.070, -0.22,  0.16,  0.00,  0.00),
            "soft_pop":        (1.050, 1.020,  0.00,  0.00,  0.00,  0.00),
            "fast_push":       (1.000, 1.080,  0.18, -0.18,  0.03, -0.03),
            "micro_shake":     (1.045, 1.060,  0.00,  0.00,  0.00,  0.00),
        }
        z0, z1, xf0, xf1, yf0, yf1 = presets.get(animation, presets["slow_push"])

        def z_at(t):
            p = self._ease_in_out_cubic(t / max(duration, 0.001))
            if animation == "soft_pop":
                p = self._ease_out_back(min(t / 0.28, 1.0), c1=0.9)
            return self._lerp(z0, z1, p)

        def scale_at(t):
            return cover_scale * z_at(t)

        def position_at(t):
            p = self._ease_in_out_cubic(t / max(duration, 0.001))
            scale = scale_at(t)
            width = base_w * scale
            height = base_h * scale
            max_x = max(0, (width - W) / 2.0)
            max_y = max(0, (height - H) / 2.0)
            x_factor = self._lerp(xf0, xf1, p)
            y_factor = self._lerp(yf0, yf1, p)
            if animation == "micro_shake":
                decay = max(0.0, 1.0 - t / 0.45)
                x_factor += 0.06 * math.sin(2 * math.pi * 12 * t) * decay
                y_factor += 0.04 * math.sin(2 * math.pi * 15 * t + 0.7) * decay
            return (
                (W - width) / 2.0 + x_factor * max_x,
                (H - height) / 2.0 + y_factor * max_y,
            )

        return clip.resize(scale_at).set_position(position_at)
    def create_media_effect(
        self, media_path, start_time, end_time, animation, clip_index=0,
        use_original_audio=False, fit_with_borders=False,
        video_start_seconds=0.0, video_end_seconds=None,
    ):
        """Create a media clip with professional Shorts motion."""
        raw_duration = max(0.01, end_time - start_time)
        overlap = min(self.MEDIA_CROSSFADE, raw_duration * 0.25)
        actual_start = max(0.0, start_time - (overlap if clip_index > 0 else 0.0))
        duration = max(0.01, end_time - actual_start)

        render_media_path = self._normalize_video_media(
            media_path, duration, fit_with_borders, video_start_seconds, video_end_seconds
        ) if self.is_video_file(media_path) else media_path
        normalized = Path(render_media_path).resolve() != Path(media_path).resolve()
        media_clip, is_video, source_audio = self._load_media_clip(
            render_media_path,
            duration,
            0.0 if normalized else video_start_seconds,
            None if normalized else video_end_seconds,
        )
        cover_extra = self.WORKING_OVERSCAN if is_video else self.MEDIA_EXTRA_SCALE
        media_clip = self._motion_clip(media_clip, animation, duration, extra_scale=cover_extra, fit_with_borders=fit_with_borders)
        media_clip = media_clip.set_start(actual_start).set_duration(duration).set_end(end_time)

        if clip_index == 0:
            media_clip = media_clip.fadein(min(self.FIRST_MEDIA_FADE, raw_duration * 0.2))
        else:
            media_clip = media_clip.crossfadein(overlap)

        original_audio = None
        if use_original_audio and is_video and source_audio is not None:
            source_offset = max(0.0, start_time - actual_start)
            source_end = min(source_offset + raw_duration, source_audio.duration)
            original_audio = source_audio.subclip(source_offset, source_end)
            if original_audio.duration < raw_duration:
                original_audio = original_audio.fx(audio_loop, duration=raw_duration)
            original_audio = original_audio.volumex(self.ORIGINAL_AUDIO_VOLUME).set_start(start_time).set_duration(raw_duration)
            try:
                original_audio = original_audio.audio_fadein(0.08).audio_fadeout(0.12)
            except Exception:
                pass
        elif use_original_audio and is_video:
            print(f"Warning: {media_path} has no usable original audio stream.")
        return media_clip, original_audio

    def create_vignette_clip(self, duration):
        """A subtle dark-edge overlay. It makes Shorts captions and subjects read better."""
        W, H = self.VIDEO_WIDTH, self.VIDEO_HEIGHT
        yy, xx = np.mgrid[0:H, 0:W]
        nx = (xx - W / 2) / (W / 2)
        ny = (yy - H / 2) / (H / 2)
        r = np.sqrt((nx / 0.88) ** 2 + (ny / 1.02) ** 2)
        alpha = np.clip((r - 0.50) / 0.58, 0, 1) ** 1.8
        alpha = (alpha * 95).astype(np.uint8)
        arr = np.zeros((H, W, 4), dtype=np.uint8)
        arr[..., 3] = alpha
        return ImageClip(arr).set_start(0).set_duration(duration)

    # ----------------------------- system helpers -----------------------------
    def open_video_file(self, file_path):
        try:
            if sys.platform.startswith('darwin'):
                subprocess.call(('open', file_path))
            elif os.name == 'nt':
                os.startfile(file_path)
            elif os.name == 'posix':
                subprocess.call(('xdg-open', file_path))
            print(f"Opening video file: {file_path}")
        except Exception as e:
            print(f"⚠️ Could not open video automatically: {e}")

    def _load_audio(self, duration, duck_intervals):
        raw_audio = AudioFileClip(self.VOICEOVER_PATH) if os.path.exists(self.VOICEOVER_PATH) else None
        bg_music = AudioFileClip(self.BACKGROUND_MUSIC_PATH)
        try:
            if bg_music.duration < duration:
                bg_music = bg_music.fx(audio_loop, duration=duration)
            else:
                bg_music = bg_music.subclip(0, duration)
        except Exception:
            bg_music = bg_music.set_duration(duration)
        bg_music = self.duck_background_music(bg_music, duck_intervals)
        try:
            bg_music = bg_music.audio_fadein(0.8).audio_fadeout(1.2)
        except Exception:
            pass
        return raw_audio, bg_music
    # ----------------------------- main generation -----------------------------
    def generate_video(self):
        os.makedirs(os.path.dirname(self.OUTPUT_PATH), exist_ok=True)
        captions = self.parse_captions_json(self.CAPTIONS_PATH)
        try:
            timeline = self.build_scene_timeline(captions)
        except Exception as e:
            print(f"Error building scene timeline: {e}")
            return
        if not timeline or timeline[-1]["end"] <= 0:
            print("No positive-duration scenes were found.")
            return

        try:
            media_files = sorted(
                [f for f in os.listdir(self.MEDIA_FOLDER) if self.is_image_file(f) or self.is_video_file(f)],
                key=lambda x: int(''.join(filter(str.isdigit, os.path.splitext(x)[0])) or 0)
            )
        except Exception as e:
            print(f"Error loading media files: {e}")
            return
        if len(media_files) < len(timeline):
            print(f"Not enough media files: found {len(media_files)} for {len(timeline)} scenes.")
            return

        clips = []
        caption_clips = []
        original_audio_clips = []
        duck_intervals = []
        image_effects = [
            "slow_push", "slow_pull", "pan_zoom_left", "pan_zoom_right",
            "drift_up", "drift_down", "cinematic_pull"
        ]
        video_effects = ["static", "slow_push", "slow_pull"]

        for scene in timeline:
            index = scene["index"]
            media_name = media_files[index]
            media_path = os.path.join(self.MEDIA_FOLDER, media_name)
            is_video = self.is_video_file(media_name)
            animation = random.choice(video_effects if is_video else image_effects)
            if index == 0:
                animation = "slow_push"
            elif index == len(timeline) - 1:
                animation = "cinematic_pull"
            print(
                f"\n-- Adding {'video' if is_video else 'image'}: {media_name} "
                f"from {scene['start']:.2f}s to {scene['end']:.2f}s | effect: {animation}"
            )
            media_clip, original_audio = self.create_media_effect(
                media_path,
                scene["start"],
                scene["end"],
                animation,
                clip_index=index,
                use_original_audio=scene["use_original_audio"],
                fit_with_borders=scene["fit_with_borders"],
                video_start_seconds=scene["video_start_seconds"],
                video_end_seconds=scene["video_end_seconds"],
            )
            clips.append(media_clip)
            if original_audio is not None:
                original_audio_clips.append(original_audio)
                duck_intervals.append((scene["start"], scene["end"]))

            for cue in scene["captions"]:
                if cue["text"].strip():
                    image = self.create_caption_image(
                        cue["text"], cue.get("text_bold"),
                        cue.get("bold_color", "yellow"), cue.get("border_color", "black")
                    )
                    caption_clip = self.create_caption_animation(cue, image, cue.get("caption_effect"))
                    if caption_clip:
                        caption_clips.append(caption_clip)

        total_duration = timeline[-1]["end"]
        try:
            raw_audio, bg_music = self._load_audio(total_duration, duck_intervals)
            narration = self.build_narration_track(raw_audio, timeline).set_duration(total_duration)
            overlay_clips = [self.create_vignette_clip(total_duration)] if self.ADD_VIGNETTE else []
            full_video = CompositeVideoClip(
                clips + overlay_clips + caption_clips,
                size=(self.VIDEO_WIDTH, self.VIDEO_HEIGHT)
            ).set_duration(total_duration)
            full_audio = CompositeAudioClip(
                [narration, bg_music.set_duration(total_duration)] + original_audio_clips
            ).set_duration(total_duration)
            final_video = full_video.set_audio(full_audio).set_duration(total_duration)

            video_codec, video_preset = self._encoding_settings()
            print(f"Rendering video to {self.OUTPUT_PATH} with {video_codec}/{video_preset}...")
            final_video.write_videofile(
                self.OUTPUT_PATH,
                fps=to_float(FPS),
                codec=video_codec,
                audio_codec="aac",
                preset=video_preset,
                bitrate="9000k",
                audio_bitrate="192k",
                threads=max(4, min(12, os.cpu_count() or 4)),
                ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
                logger='bar'
            )
            final_video.close()
            full_video.close()
            narration.close()
            if raw_audio is not None:
                raw_audio.close()
            bg_music.close()
            print("Video generation complete!")
        except Exception as e:
            print(f"Error creating video: {e}")
            raise
def main():
    video_generator = VideoGenerator()
    video_generator.generate_video()


if __name__ == "__main__":
    main()
