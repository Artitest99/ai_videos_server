import os
import json
import re
import random
import sys
import subprocess
import numpy as np
from helper import get_array_type
from moviepy.editor import (
    ImageClip, AudioFileClip, CompositeVideoClip,
    CompositeAudioClip, vfx, VideoFileClip
)
from moviepy.audio.fx.volumex import volumex
from moviepy.video.VideoClip import ColorClip
from PIL import Image, ImageDraw, ImageFont
from moviepy.audio.fx.all import audio_loop
from config import FILE_NAME, MUSIC

class VideoGenerator:
    """
    Video generator class that creates short-form vertical videos with captions,
    images, video clips, voiceovers, and background music with various animation effects.
    Compatible with MoviePy 1.0.3 and Pillow 9.5.0.
    
    Features enhanced transitions suitable for short-form videos:
    - slide-right: Media slides in from the right edge
    - slide-left: Media slides in from the left edge
    - slide-top: Media slides in from the top edge
    - slide-bottom: Media slides in from the bottom edge
    - pop: Media starts small and pops to full size with subtle bounce
    - whip: Fast whip-pan transition with motion effect
    - spin: Media spins while fading in
    """
    
    # Constants
    SCRIPT_PATH = f"scripts/{FILE_NAME}.txt"
    VOICEOVER_PATH = f"assets/voiceovers/{FILE_NAME}.mp3"
    CAPTIONS_PATH = f"captions/captions_{FILE_NAME}.json"
    MEDIA_FOLDER = f"assets/media/{FILE_NAME}"  # Renamed from IMAGES_FOLDER to MEDIA_FOLDER
    BACKGROUND_MUSIC_PATH = f"assets/background_music_{MUSIC}.mp3"
    OUTPUT_PATH = f"output/final_video_{FILE_NAME}.mp4"
    FONT_PATH = "assets/fonts/Montserrat-Bold.ttf"
    VIDEO_WIDTH, VIDEO_HEIGHT = 1920, 1080
    FPS = 60
    
    # NEW: Caption visibility control
    HIDE_CAPTIONS = True  # Set to True to generate video without captions
    EQUAL_CLIP_PARTITION = False
   
    # Supported media extensions
    IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp')
    VIDEO_EXTENSIONS = ('.mp4', '.mov', '.avi', '.webm', '.mkv')
    
    def __init__(self, hide_captions=None):
        """Initialize the VideoGenerator with an empty caption image cache."""
        self.caption_image_cache = {}
        # Allow override of HIDE_CAPTIONS via constructor
        if hide_captions is not None:
            self.HIDE_CAPTIONS = hide_captions
        
    def split_text_with_hyphen(self, text):
        """Split text by spaces or hyphens as separate tokens."""
        words = re.split(r'(\s+|-|\u2014)', text)
        # Filter out empty strings and whitespace tokens
        return [word for word in words if word.strip() and word != ' ']
    
    def parse_captions_json(self, json_path):
        """Parse the captions JSON file and return a list of caption segments."""
        # Skip parsing if captions are hidden
        if self.HIDE_CAPTIONS and self.EQUAL_CLIP_PARTITION:
            print("Captions are hidden - skipping caption parsing")
            return []
            
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            captions = []
            
            for seg in data:
                text = seg["text"].strip()

                captions.append({
                    "start": round(float(seg["start"]), 2),
                    "end": round(float(seg["end"]), 2),
                    "text": text,
                    "text_bold": seg.get("text_bold", []),
                    "bold_color": seg.get("bold_color", "yellow"),
                    "media_transition": seg.get("media_transition", False),  # Renamed from image_transition
                    "border_color": seg.get("border_color", "black"),
                    "effect": seg.get("effect", None),
                    "caption_effect": seg.get("caption_effect", None)
                })
                
            return sorted(captions, key=lambda x: x["start"])
        except Exception as e:
            print(f"Error parsing captions file: {e}")
            return []
    
    def is_video_file(self, filename):
        """Check if the file is a video based on its extension."""
        return filename.lower().endswith(self.VIDEO_EXTENSIONS)
    
    def is_image_file(self, filename):
        """Check if the file is an image based on its extension."""
        return filename.lower().endswith(self.IMAGE_EXTENSIONS)
        
    def create_caption_image(self, text, text_bold=None, bold_color="yellow", 
                            border_color="black", width=1920, height=1080):
        """Create a caption image with the given text and styling - FIXED for memory issues."""
        # Skip caption image creation if captions are hidden
        if self.HIDE_CAPTIONS:
            return None
            
        # Check cache first
        cache_key = f"{text}_{text_bold}_{bold_color}_{border_color}"
        if cache_key in self.caption_image_cache:
            return self.caption_image_cache[cache_key]
        
        # CRITICAL FIX 1: Use much smaller height to reduce memory usage
        # Instead of 1800px height, use reasonable caption area
        caption_height = 400  # Much smaller, sufficient for captions
        
        # Create image with smaller dimensions
        img = Image.new('RGBA', (width, caption_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # CRITICAL FIX 2: Adjust font size proportionally
        font_size = int(caption_height * 0.15)  # 15% of caption height, not video height
        font = ImageFont.truetype(self.FONT_PATH, font_size)
        
        # Text wrapping (unchanged)
        lines = []
        words = self.split_text_with_hyphen(text)
        line = []
        line_width = 0
        space_width = draw.textlength(" ", font=font) * 1.4
        
        for word in words:
            word_width = draw.textlength(word, font=font)
            if line_width + word_width + space_width < width * 0.8:
                line.append(word)
                line_width += word_width + space_width
            else:
                lines.append(line)
                line = [word]
                line_width = word_width
                
        if line:
            lines.append(line)

        # CRITICAL FIX 3: Adjust line height and positioning
        line_height = font.getsize("A")[1] + 20  # Much smaller line spacing
        y = (caption_height - len(lines) * line_height) // 2
        border_color_default = "black"
        
        for line in lines:
            line_width = sum(draw.textlength(w, font=font) for w in line) + space_width * (len(line) - 1)
            x = (width - line_width) / 2
            
            for idx, word in enumerate(line):
                word_width = draw.textlength(word, font=font)
                
                if get_array_type(text_bold) == "integers":
                    fill_color = bold_color if text_bold and idx in text_bold else 'white'
                else:
                    fill_color = bold_color if text_bold and word.strip(' ., -!?: \u2014') in text_bold else 'white'
                    border_color_default = border_color if text_bold and word.strip(' ., -!?: \u2014') in text_bold else 'black'
                    
                # CRITICAL FIX 4: Reduce stroke width to save memory
                draw.text((x, y), word, font=font, fill=fill_color, stroke_width=5, stroke_fill=border_color_default)
                x += word_width + space_width
                
            y += line_height

        # CRITICAL FIX 5: Convert to proper numpy array with correct dtype
        img_array = np.array(img, dtype=np.uint8)  # Explicitly use uint8 instead of default float64
        
        # CRITICAL FIX 6: Limit cache size to prevent memory buildup
        if len(self.caption_image_cache) > 20:  # Clear cache if too many items
            self.caption_image_cache.clear()
            print("Caption cache cleared to free memory")
        
        # Store in cache
        self.caption_image_cache[cache_key] = img_array
        return img_array
    
    def create_media_effect(self, media_path, start_time, end_time, animation, final_width=None):
        """Create a media clip (image or video) with the specified animation effect."""
        # Determine if the media is an image or video
        is_video = self.is_video_file(media_path)
        
        # Create base clip
        if is_video:
            # Load video and set appropriate duration
            try:
                video_clip = VideoFileClip(media_path)
                # If video is shorter than needed duration, loop it
                if video_clip.duration < (end_time - start_time):
                    print(f"Video {media_path} is shorter than needed duration. Looping...")
                    # Calculate how many times we need to loop the video
                    loop_count = int(np.ceil((end_time - start_time) / video_clip.duration))
                    # Create a list of the same clip multiple times
                    video_segments = [video_clip] * loop_count
                    # Concatenate them into one longer clip
                    from moviepy.editor import concatenate_videoclips
                    video_clip = concatenate_videoclips(video_segments)
                
                # Trim to exact duration needed
                base_clip = video_clip.subclip(0, end_time - start_time)
                
                # Resize to fit vertical format while maintaining aspect ratio
                if base_clip.h != self.VIDEO_HEIGHT:
                    base_clip = base_clip.resize(height=self.VIDEO_HEIGHT)
                
                # Center the clip horizontally if it's not the full width
                if base_clip.w < self.VIDEO_WIDTH:
                    base_clip = base_clip.set_position("center")
                
            except Exception as e:
                print(f"Error loading video {media_path}: {e}")
                # Fall back to a solid color clip as placeholder
                base_clip = ColorClip((self.VIDEO_WIDTH, self.VIDEO_HEIGHT), color=(0, 0, 0))
                base_clip = base_clip.set_duration(end_time - start_time)
        else:
            # Handle image as before
            base_clip = ImageClip(media_path).resize(height=self.VIDEO_HEIGHT).set_duration(end_time - start_time)
        
        # Set timing for the clip
        base_clip = base_clip.set_start(start_time).set_end(end_time)
        
        # Calculate final dimensions for positioning
        if not final_width:
            if is_video:
                final_width = base_clip.w
            else:
                img = Image.open(media_path)
                img_w, img_h = img.size
                scale_factor = self.VIDEO_HEIGHT / img_h
                final_width = int(img_w * scale_factor)
        
        dur = end_time - start_time
        transition_duration = min(0.5, dur / 4)  # Transition duration
        
        # Position functions - now work for both videos and images
        def moving_position(t, total_movement=175):
            shift = int((t / dur) * total_movement)
            return (-shift, 0)
            
        def moving_position_r(t, total_movement=175):
            shift = int((t / dur) * total_movement)
            return (-0.9 * final_width + shift, 0)
        
        def slide_in_from_right(t):
            if t < transition_duration:
                progress = t / transition_duration
                start_x = self.VIDEO_WIDTH
                end_x = (self.VIDEO_WIDTH - final_width) / 2
                return (start_x - (start_x - end_x) * progress, 0)
            return ("center", 0)
            
        def slide_in_from_left(t):
            if t < transition_duration:
                progress = t / transition_duration
                start_x = -final_width
                end_x = (self.VIDEO_WIDTH - final_width) / 2
                return (start_x + (end_x - start_x) * progress, 0)
            return ("center", 0)
            
        def slide_in_from_top(t):
            if t < transition_duration:
                progress = t / transition_duration
                start_y = -self.VIDEO_HEIGHT
                end_y = 0
                return ("center", start_y + (end_y - start_y) * progress)
            return ("center", 0)
            
        def slide_in_from_bottom(t):
            if t < transition_duration:
                progress = t / transition_duration
                start_y = self.VIDEO_HEIGHT
                end_y = 0
                return ("center", start_y - (start_y - end_y) * progress)
            return ("center", 0)
            
        def pop_in(t):
            if t < transition_duration:
                progress = t / transition_duration
                # Elastic easing function for a nice bounce effect
                progress = max(0, min(1, progress))
                if progress < 0.7:
                    scale = 0.5 + (0.5 * (progress / 0.7))
                else:
                    try:
                        import math
                        overshoot = (progress - 0.7) / 0.3
                        bounce = 1.0 + 0.1 * math.sin(overshoot * math.pi)
                        scale = min(1.1, bounce)
                    except ImportError:
                        scale = 1.0
                return scale
            return 1.0
            
        def shaking_position(t, base_w, base_h):
            px = 2
            shake_x = random.randint(-px, px)
            shake_y = random.randint(-px, px)
            return (-(self.VIDEO_WIDTH) // 4 + shake_x, 0 + shake_y)
            
        def whip_pan(t):
            if t < transition_duration:
                progress = t / transition_duration
                # Accelerated movement
                progress = progress * progress  # Quadratic for acceleration
                start_x = self.VIDEO_WIDTH
                end_x = (self.VIDEO_WIDTH - final_width) / 2
                return (start_x - (start_x - end_x) * progress, 0)
            return ("center", 0)
            
        def spin_in(t):
            if t < transition_duration:
                return 360 * (1 - t / transition_duration)
            return 0
        
        try:
            import math  # Import math for advanced effects
        except ImportError:
            pass
            
        # Apply selected animation effect - now works for both videos and images
        if animation == "pan":
            clip = base_clip.set_position(lambda t: moving_position(t))
        if animation == 'pan-from-center':
            clip = base_clip.set_position("center")
            clip = base_clip.set_position(lambda t: moving_position(t))
        elif animation == 'full-pan':
            if is_video:
                # For videos, use the actual width
                clip = base_clip.set_position(lambda t: moving_position(t, base_clip.w * 0.7))
            else:
                img = Image.open(media_path)
                img_w, _ = img.size
                clip = base_clip.set_position(lambda t: moving_position(t, img_w * 0.8))
        elif animation == 'pan-from-right':
            clip = base_clip.set_position(lambda t: moving_position_r(t))
        elif animation == "zoom":
            clip = base_clip.resize(lambda t: 1.02 + 0.03 * t).set_position("center")
        elif animation == 'zoomout':
            clip = base_clip.resize(lambda t: 1.2 - 0.01 * t).set_position("center")
        elif animation == 'zoomout_last_image':
            clip = base_clip.resize(lambda t: 1.2 - 0.01 * t).set_position("center")
        elif animation == 'pan_zoom_right':
            clip = (base_clip.resize(lambda t: 1.0 + 0.02 * t).set_position(lambda t: ( -50 + 10 * t, "center")))
        elif animation == 'pan_zoom_left':
            clip = (base_clip.resize(lambda t: 1.0 + 0.02 * t).set_position(lambda t: ( 50 - 10 * t, "center")))
        elif animation == 'watermark':
            clip = base_clip.resize(lambda t: 1.2 - 0.01 * t).set_position("center")
        elif animation == 'watermark_zoom':
            clip = base_clip.resize(lambda t: 1.2 + 0.015 * t).set_position("center")
        elif animation == 'super_zoomout':
            clip = base_clip.resize(lambda t: 1.2 - 0.065 * t).set_position("center")
        elif animation == 'shake':
            clip = base_clip.set_position(
                lambda t: shaking_position(t, self.VIDEO_WIDTH, self.VIDEO_HEIGHT)
            )
        elif animation == 'slide-right':
            clip = base_clip.set_position(slide_in_from_right)
        elif animation == 'slide-left':
            clip = base_clip.set_position(slide_in_from_left)
        elif animation == 'slide-top':
            clip = base_clip.set_position(slide_in_from_top)
        elif animation == 'slide-bottom':
            clip = base_clip.set_position(slide_in_from_bottom)
        elif animation == 'pop':
            clip = base_clip.resize(pop_in).set_position("center")
        elif animation == 'whip':
            clip = base_clip.set_position(whip_pan)
            # Add motion blur effect if using MoviePy 1.0.3 which supports it
            try:
                from moviepy.video.fx.painting import painting
                clip = clip.fx(painting, saturation=1.2, black=0.001)
            except:
                pass
        elif animation == 'spin':
            try:
                from moviepy.video.fx.rotate import rotate
                clip = base_clip.set_position("center")
                clip = clip.fl(lambda gf, t: rotate(gf(t), angle=spin_in(t)))
            except:
                clip = base_clip.set_position("center")
        else:  # static
            clip = base_clip.set_position("center")
            
        # Add fade in/out for any transition type
        return clip.fadein(0.25).fadeout(0.25)    
    
    def create_caption_animation(self, seg, img_array, caption_animation=None):
        """Create a caption clip with the specified animation effect - FIXED for memory issues."""
        # Skip caption animation if captions are hidden
        if self.HIDE_CAPTIONS or img_array is None:
            return None
            
        duration = seg["end"] - seg["start"]
        
        if not caption_animation:
            # For MoviePy 1.0.3, prioritize effects with better compatibility
            caption_effects_styles = ['pop-out', 'slide', 'pop','static']
            caption_animation = random.choice(caption_effects_styles)

        # Basic animation calculations
        fadein_time = min(0.1, duration * 0.1)  # 10% of clip duration or max 0.15s
        fadeout_time = min(0.1, duration * 0.1)  # 10% of clip duration or max 0.15s
        
        # CRITICAL FIX 7: Adjust caption positioning for smaller image
        caption_y_position = self.VIDEO_HEIGHT - 500  # Adjusted for smaller caption area
        
        # Import necessary modules for MoviePy 1.0.3
        import numpy as np
        from moviepy.video.VideoClip import ColorClip
        try:
            from moviepy.video.fx.fadein import fadein
            from moviepy.video.fx.fadeout import fadeout
        except ImportError:
            # These should be available in MoviePy 1.0.3, but just in case
            pass
        
        if caption_animation == 'pop-out':
            return (
                ImageClip(img_array, duration=duration)
                .set_start(seg["start"])
                .set_end(seg["end"])
                .resize(lambda t: 1.25 - 0.2 * min(t / 0.3, 1))
                .fadein(fadein_time)
                .fadeout(fadeout_time)
                .set_position(("center", caption_y_position))
            )
        elif caption_animation == 'slide':
            # Safe implementation for MoviePy 1.0.3
            initial_y = caption_y_position + 100  # Start a bit lower
            target_y = caption_y_position  # Final position
            
            clip = (
                ImageClip(img_array, duration=duration)
                .set_start(seg["start"])
                .set_end(seg["end"])
                .fadein(fadein_time)
                .fadeout(fadeout_time)
            )
            
            # Define position function for the sliding effect
            def slide_position(t):
                progress = min(t / 0.3, 1)  # Complete slide in 0.3s
                current_y = initial_y - (initial_y - target_y) * progress
                return ("center", current_y)
                
            # Apply resize as a separate effect
            resize_func = lambda t: 1.2 - 0.2 * min(t / 0.3, 1)
            
            # First apply resize, then set the position
            return clip.fx(
                lambda c: c.resize(lambda t: resize_func(t))
            ).set_position(slide_position)
        elif caption_animation == 'pop': 
            # Safe implementation for MoviePy 1.0.3
            clip = (
                ImageClip(img_array, duration=duration)
                .set_start(seg["start"])
                .set_end(seg["end"])
                .fadein(fadein_time)
                .fadeout(fadeout_time)
                .set_position(("center", caption_y_position))
            )
            
            # Apply resize as a separate effect for better compatibility
            resize_func = lambda t: 0.88 + 0.12 * min(t / 0.3, 1)
            return clip.fx(
                lambda c: c.resize(lambda t: resize_func(t))
            )
        elif caption_animation == 'fade-blur':
            # Blur effect as caption fades out - adjusted for MoviePy 1.0.3
            try:
                # Create the basic clip
                clip = (
                    ImageClip(img_array, duration=duration)
                    .set_start(seg["start"])
                    .set_end(seg["end"])
                    .fadein(fadein_time)
                    .fadeout(fadeout_time)
                    .set_position(("center", caption_y_position))
                )
                
                # Use a simpler approach with fx.glow for a blur-like effect
                from moviepy.video.fx.painting import painting
                
                # Apply increasing blur/glow effect over time
                def get_frame_with_effect(t):
                    frame = clip.get_frame(t)
                    if t > duration * 0.7:  # Only apply effect during fadeout
                        progress = (t - duration * 0.7) / (duration * 0.3)
                        # Use painting effect as a substitute for blur in MoviePy 1.0.3
                        blur_amount = progress * 0.5  # Subtle effect
                        return painting(frame, blur_amount, 0.3)
                    return frame
                    
                # Create new clip with frame processor
                result_clip = clip.fl(lambda gf, t: get_frame_with_effect(t))
                return result_clip
                
            except ImportError:
                # Fallback if effects are not available
                return (
                    ImageClip(img_array, duration=duration)
                    .set_start(seg["start"])
                    .set_end(seg["end"])
                    .fadein(fadein_time)
                    .fadeout(fadeout_time)
                    .set_position(("center", caption_y_position))
                )
        else:  # static
            return (
                ImageClip(img_array, duration=duration)
                .set_start(seg["start"])
                .set_end(seg["end"])
                #.fadein(fadein_time)
                #.fadeout(fadeout_time)
                .set_position(("center", caption_y_position))
            )
    
    def get_media_timing_without_captions(self):
        """Get media timing based on audio duration when captions are hidden."""
        try:
            # Load the voiceover to get total duration
            audio = AudioFileClip(self.VOICEOVER_PATH)
            total_duration = audio.duration
            audio.close()
            
            # Get all media files
            media_files = []
            for f in os.listdir(self.MEDIA_FOLDER):
                if self.is_image_file(f) or self.is_video_file(f):
                    media_files.append(f)
            
            # Sort files numerically
            media_files = sorted(media_files, 
                key=lambda x: int(''.join(filter(str.isdigit, os.path.splitext(x)[0])) or 0))
            
            if not media_files:
                return []
            
            # Divide the total duration equally among media files
            duration_per_media = total_duration / len(media_files)
            
            media_segments = []
            for i, media_file in enumerate(media_files):
                start_time = i * duration_per_media
                end_time = (i + 1) * duration_per_media
                
                # Make sure the last segment ends exactly at total duration
                if i == len(media_files) - 1:
                    end_time = total_duration
                
                media_segments.append({
                    'file': media_file,
                    'start': start_time,
                    'end': end_time
                })
            
            return media_segments
            
        except Exception as e:
            print(f"Error calculating media timing: {e}")
            return []
    
    def open_video_file(self, file_path):
        """Open the video file with the default application."""
        try:
            if sys.platform.startswith('darwin'):  # macOS
                subprocess.call(('open', file_path))
            elif os.name == 'nt':  # Windows
                os.startfile(file_path)
            elif os.name == 'posix':  # Linux
                subprocess.call(('xdg-open', file_path))
            print(f"Opening video file: {file_path}")
        except Exception as e:
            print(f"⚠️ Could not open video automatically: {e}")
    
    def generate_video(self):
        """Main method to generate the video with captions, images and video clips."""
        # Ensure output directory exists
        os.makedirs(os.path.dirname(self.OUTPUT_PATH), exist_ok=True)
        
        # Load captions and media files
        captions = self.parse_captions_json(self.CAPTIONS_PATH)
        
        # Print caption status
        if self.HIDE_CAPTIONS:
            print("🚫 CAPTIONS ARE HIDDEN - Generating video without captions")
        else:
            print(f"📝 CAPTIONS ENABLED - Found {len(captions)} caption segments")
        
        try:
            # Get all media files (both images and videos)
            media_files = []
            for f in os.listdir(self.MEDIA_FOLDER):
                if self.is_image_file(f) or self.is_video_file(f):
                    media_files.append(f)
            
            # Sort files numerically (assuming filenames start with numbers)
            media_files = sorted(media_files, 
                key=lambda x: int(''.join(filter(str.isdigit, os.path.splitext(x)[0])) or 0))
            
            print(f"Found {len(media_files)} media files")
            print(f"Images: {sum(1 for f in media_files if self.is_image_file(f))}")
            print(f"Videos: {sum(1 for f in media_files if self.is_video_file(f))}")
        except Exception as e:
            print(f"Error loading media files: {e}")
            return
            
        # Load audio files
        try:
            audio = AudioFileClip(self.VOICEOVER_PATH)
            bg_music = AudioFileClip(self.BACKGROUND_MUSIC_PATH).volumex(0.1)
        except Exception as e:
            print(f"Error loading audio files: {e}")
            return

        clips = []
        caption_clips = []
        
        # Handle media timing based on whether captions are enabled
        if self.HIDE_CAPTIONS and self.EQUAL_CLIP_PARTITION:
            # No captions: divide time equally among media files
            media_segments = self.get_media_timing_without_captions()
            for i, segment in enumerate(media_segments):
                media_path = os.path.join(self.MEDIA_FOLDER, segment['file'])
                is_video = self.is_video_file(segment['file'])
                media_type = "video" if is_video else "image"
                
                print(f"\n-- Adding {media_type}: {segment['file']} from {segment['start']:.2f}s to {segment['end']:.2f}s")
                
                # Choose appropriate animation for media type
                if is_video:
                    transition_styles = ["static", "watermark", "zoom"]
                else:
                    transition_styles = ["pan", "zoom", "static", "pan_zoom_right","pan_zoom_left","watermark"]
                
                animation = random.choice(transition_styles)
                
                # Special cases for first and last media
                if i >= len(media_segments) - 1:
                    animation = 'zoomout_last_image'
                elif i == 0:
                    animation = 'zoom'
                
                # Create media clip
                media_clip = self.create_media_effect(media_path, segment['start'], segment['end'], animation)
                clips.append(media_clip)
        else:
            # With captions: use original logic
            media_index = 0
            segment = []

            # Process captions and create video segments
            for i, cap in enumerate(captions):
                segment.append(cap)
                is_last = i == len(captions) - 1
                
                if cap.get("media_transition", False) or is_last:
                    if media_index >= len(media_files):
                        break

                    media_start = segment[0]["start"]
                    media_end = segment[-1]["end"]
                    media_path = os.path.join(self.MEDIA_FOLDER, media_files[media_index])
                    
                    # Determine if this is an image or video
                    is_video = self.is_video_file(media_files[media_index])
                    media_type = "video" if is_video else "image"

                    print(f"\n-- Adding {media_type}: {media_files[media_index]} from {media_start:.2f}s to {media_end:.2f}s")

                    # Determine animation style
                    if cap.get('effect') is not None:
                        animation = cap['effect']
                    else:
                        # For videos, we might want different transition styles than for images
                        if is_video:
                            # Videos look best with simpler transitions
                            transition_styles = [
                                "static", "zoom","watermark"
                            ]
                        else:
                            # Images can have more varied transitions
                            transition_styles = [
                                "pan", "zoom", "static", "zoomout","watermark",
                            ]
                        
                        animation = random.choice(transition_styles)
                        
                        # Special case for first and last media
                        if media_index >= len(media_files) - 1:
                            # Last media gets a clean exit transition
                            animation = 'zoomout_last_image'
                        elif media_index == 0:
                            # First media gets an engaging entrance
                            animation = 'zoom'
                    
                    # Create media clip with effect        
                    media_clip = self.create_media_effect(media_path, media_start, media_end, animation)
                    clips.append(media_clip)
                    
                    # Process each caption segment only if captions are not hidden
                    if not self.HIDE_CAPTIONS:
                        for seg in segment:
                            if seg["text"].strip():
                                text_bold = seg.get("text_bold")
                                bold_color = seg.get("bold_color")
                                border_color = seg.get("border_color", "black")
                                caption_effect = seg.get("caption_effect")
                                
                                # Create caption image and animation
                                img_array = self.create_caption_image(
                                    seg["text"], text_bold, bold_color, border_color
                                )
                                cap_clip = self.create_caption_animation(seg, img_array, caption_effect)
                                
                                if cap_clip:
                                    caption_clips.append(cap_clip)
                    
                    media_index += 1
                    segment = []

        # Combine everything
        if not clips:
            print("No clips were created. Check your input files.")
            return
            
        try:
            # Only add caption clips if they exist
            all_clips = clips + caption_clips if caption_clips else clips
            full_video = CompositeVideoClip(all_clips, size=(self.VIDEO_WIDTH, self.VIDEO_HEIGHT))
            looped_bg = audio_loop(bg_music, duration=full_video.duration)
            full_audio = CompositeAudioClip([audio, looped_bg])    
            final_video = full_video.set_audio(full_audio)

            print(f"Rendering video to {self.OUTPUT_PATH}...")
            final_video.write_videofile(
                self.OUTPUT_PATH, 
                fps=self.FPS, 
                codec="libx264", 
                audio_codec="aac"
            )
            
            self.open_video_file(self.OUTPUT_PATH)             
            print("Video generation complete!")                      
        except Exception as e:             
            print(f"Error creating video: {e}")  

def main():     
    """Main function to create and run the video generator."""     
    video_generator = VideoGenerator(hide_captions=True)     
    video_generator.generate_video()  

if __name__ == "__main__":     
    main()