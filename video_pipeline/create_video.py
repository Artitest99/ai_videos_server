import os
import json
import re
import random
import sys
import subprocess
import math
import numpy as np
from helper import get_array_type, to_float
from moviepy.editor import (
    ImageClip, AudioFileClip, CompositeVideoClip,
    CompositeAudioClip, VideoFileClip, vfx
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
    CAPTION_Y = int(VIDEO_HEIGHT * 0.61)
    ADD_VIGNETTE = True

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

    # ----------------------------- media loading / motion -----------------------------
    def _load_media_clip(self, media_path, duration):
        is_video = self.is_video_file(media_path)

        if is_video:
            try:
                clip = VideoFileClip(media_path).without_audio()
                if clip.duration < duration:
                    clip = clip.fx(vfx.loop, duration=duration)
                else:
                    clip = clip.subclip(0, duration)
                return clip.set_duration(duration), True
            except Exception as e:
                print(f"Error loading video {media_path}: {e}")
                return ColorClip((self.VIDEO_WIDTH, self.VIDEO_HEIGHT), color=(0, 0, 0)).set_duration(duration), False

        try:
            return ImageClip(media_path).set_duration(duration), False
        except Exception as e:
            print(f"Error loading image {media_path}: {e}")
            return ColorClip((self.VIDEO_WIDTH, self.VIDEO_HEIGHT), color=(0, 0, 0)).set_duration(duration), False

    def _resize_to_cover(self, clip, extra_scale=None):
        """Resize media so that it covers the full 9:16 canvas with extra room for motion."""
        if extra_scale is None:
            extra_scale = self.MEDIA_EXTRA_SCALE
        scale = max(self.VIDEO_WIDTH / max(1, clip.w), self.VIDEO_HEIGHT / max(1, clip.h))
        return clip.resize(scale * extra_scale)

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

    def _motion_clip(self, clip, animation, duration):
        """Apply professional Ken Burns style motion.

        The returned clip always remains larger than the canvas and CompositeVideoClip
        crops it automatically to 1080x1920. This avoids black borders.
        """
        animation = self._normalize_animation_name(animation)
        base_w, base_h = clip.w, clip.h
        W, H = self.VIDEO_WIDTH, self.VIDEO_HEIGHT

        # z_start/z_end are relative to the already-covering base clip.
        presets = {
            "static":          (1.020, 1.020,  0.00,  0.00,  0.00,  0.00),
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

        def position_at(t):
            p = self._ease_in_out_cubic(t / max(duration, 0.001))
            z = z_at(t)
            w = base_w * z
            h = base_h * z
            max_x = max(0, (w - W) / 2.0)
            max_y = max(0, (h - H) / 2.0)

            x_factor = self._lerp(xf0, xf1, p)
            y_factor = self._lerp(yf0, yf1, p)

            # Micro shake is deterministic and decays quickly. It is intentionally tiny.
            if animation == "micro_shake":
                decay = max(0.0, 1.0 - t / 0.45)
                x_factor += 0.06 * math.sin(2 * math.pi * 12 * t) * decay
                y_factor += 0.04 * math.sin(2 * math.pi * 15 * t + 0.7) * decay

            x = (W - w) / 2.0 + x_factor * max_x
            y = (H - h) / 2.0 + y_factor * max_y
            return (x, y)

        return clip.resize(z_at).set_position(position_at)

    def create_media_effect(self, media_path, start_time, end_time, animation, clip_index=0):
        """Create a media clip with professional Shorts motion."""
        raw_duration = max(0.01, end_time - start_time)
        overlap = min(self.MEDIA_CROSSFADE, raw_duration * 0.25)
        actual_start = max(0.0, start_time - (overlap if clip_index > 0 else 0.0))
        duration = max(0.01, end_time - actual_start)

        media_clip, is_video = self._load_media_clip(media_path, duration)
        # Videos usually already have motion; use a slightly smaller extra scale for them.
        cover_extra = 1.06 if is_video else self.MEDIA_EXTRA_SCALE
        media_clip = self._resize_to_cover(media_clip, extra_scale=cover_extra)
        media_clip = self._motion_clip(media_clip, animation, duration)
        media_clip = media_clip.set_start(actual_start).set_duration(duration).set_end(end_time)

        if clip_index == 0:
            media_clip = media_clip.fadein(min(self.FIRST_MEDIA_FADE, raw_duration * 0.2))
        else:
            media_clip = media_clip.crossfadein(overlap)

        return media_clip

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

    def _load_audio(self):
        audio = AudioFileClip(self.VOICEOVER_PATH)
        bg_music = AudioFileClip(self.BACKGROUND_MUSIC_PATH)

        try:
            if bg_music.duration < audio.duration:
                bg_music = bg_music.fx(audio_loop, duration=audio.duration)
            else:
                bg_music = bg_music.subclip(0, audio.duration)
        except Exception:
            # Compatibility fallback: set_duration gives silence after the source ends on many MoviePy versions.
            bg_music = bg_music.set_duration(audio.duration)

        try:
            bg_music = bg_music.volumex(self.DEFAULT_BG_MUSIC_VOLUME).audio_fadein(0.8).audio_fadeout(1.2)
        except Exception:
            bg_music = bg_music.volumex(self.DEFAULT_BG_MUSIC_VOLUME)

        return audio, bg_music

    # ----------------------------- main generation -----------------------------
    def generate_video(self):
        os.makedirs(os.path.dirname(self.OUTPUT_PATH), exist_ok=True)

        captions = self.parse_captions_json(self.CAPTIONS_PATH)
        if not captions:
            print("No captions found. Check the captions JSON path/content.")
            return

        try:
            media_files = [
                f for f in os.listdir(self.MEDIA_FOLDER)
                if self.is_image_file(f) or self.is_video_file(f)
            ]
            media_files = sorted(
                media_files,
                key=lambda x: int(''.join(filter(str.isdigit, os.path.splitext(x)[0])) or 0)
            )

            print(f"Found {len(media_files)} media files")
            print(f"Images: {sum(1 for f in media_files if self.is_image_file(f))}")
            print(f"Videos: {sum(1 for f in media_files if self.is_video_file(f))}")
        except Exception as e:
            print(f"Error loading media files: {e}")
            return

        if not media_files:
            print("No media files found. Check MEDIA_FOLDER.")
            return

        try:
            audio, bg_music = self._load_audio()
        except Exception as e:
            print(f"Error loading audio files: {e}")
            return

        clips = []
        caption_clips = []
        media_index = 0
        segment = []

        image_effects = [
            "slow_push", "slow_pull", "pan_zoom_left", "pan_zoom_right",
            "drift_up", "drift_down", "cinematic_pull"
        ]
        video_effects = ["static", "slow_push", "slow_pull"]

        for i, cap in enumerate(captions):
            segment.append(cap)
            is_last_caption = i == len(captions) - 1

            if cap.get("media_transition", False) or is_last_caption:
                if media_index >= len(media_files):
                    print("Warning: more caption media transitions than media files. Stopping media assignment.")
                    break

                media_start = segment[0]["start"]
                media_end = segment[-1]["end"]
                media_path = os.path.join(self.MEDIA_FOLDER, media_files[media_index])

                is_video = self.is_video_file(media_files[media_index])
                media_type = "video" if is_video else "image"

                if cap.get('effect') is not None:
                    animation = cap['effect']
                else:
                    animation = random.choice(video_effects if is_video else image_effects)
                    if media_index == 0:
                        animation = "slow_push"
                    elif media_index >= len(media_files) - 1:
                        animation = "cinematic_pull"

                print(
                    f"\n-- Adding {media_type}: {media_files[media_index]} "
                    f"from {media_start:.2f}s to {media_end:.2f}s | effect: {animation}"
                )

                media_clip = self.create_media_effect(
                    media_path,
                    media_start,
                    media_end,
                    animation,
                    clip_index=media_index
                )
                clips.append(media_clip)

                for seg in segment:
                    if seg["text"].strip():
                        img_array = self.create_caption_image(
                            seg["text"],
                            seg.get("text_bold"),
                            seg.get("bold_color", "yellow"),
                            seg.get("border_color", "black")
                        )
                        cap_clip = self.create_caption_animation(seg, img_array, seg.get("caption_effect"))
                        if cap_clip:
                            caption_clips.append(cap_clip)

                media_index += 1
                segment = []

        if not clips:
            print("No clips were created. Check your input files and captions.")
            return

        try:
            total_duration = max(audio.duration, max(c.end for c in clips))
            overlay_clips = [self.create_vignette_clip(total_duration)] if self.ADD_VIGNETTE else []

            full_video = CompositeVideoClip(
                clips + overlay_clips + caption_clips,
                size=(self.VIDEO_WIDTH, self.VIDEO_HEIGHT)
            ).set_duration(total_duration)

            full_audio = CompositeAudioClip([audio, bg_music.set_duration(audio.duration)]).set_duration(audio.duration)
            final_video = full_video.set_audio(full_audio).set_duration(audio.duration)

            print(f"Rendering video to {self.OUTPUT_PATH}...")
            final_video.write_videofile(
                self.OUTPUT_PATH,
                fps=to_float(FPS),
                codec="libx264",
                audio_codec="aac",
                preset="medium",
                bitrate="9000k",
                audio_bitrate="192k",
                threads=4,
                ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
                logger='bar'
            )

            try:
                final_video.close()
                full_video.close()
                audio.close()
                bg_music.close()
            except Exception:
                pass

            print("Video generation complete!")
        except Exception as e:
            print(f"Error creating video: {e}")


def main():
    video_generator = VideoGenerator()
    video_generator.generate_video()


if __name__ == "__main__":
    main()
