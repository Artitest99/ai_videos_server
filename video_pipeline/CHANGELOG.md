# Change Log

## 2026-07-24 — Narration audio fix

- Fixed inaudible narration when prepared caption timing begins at the intentional `-0.05s` offset.
- The narration builder now inserts a 50 ms silent lead-in and clamps MP3 extraction to non-negative timestamps instead of passing a negative start to MoviePy.
- Verified against the real `my_narration.mp3`; the repaired track contains audible stereo speech, and seven focused audio/timing tests passed.

## 2026-07-24 — Video source ranges

- Added per-video start and end timestamps in guided creation and edit mode.
- New uploads default to the complete source duration, rounded down to two decimal places.
- The browser video player seeks to the selected start immediately and loops only the selected range during preview.
- Changing a range updates the default narration-free scene duration to the range length.
- Rendering trims video and original source audio before looping them to the scene timeline.
- Render-cache filenames include the selected range, preventing a cached trim from being reused for different timestamps.
- Django checks, migration consistency, and 33 focused range/form/editor/renderer tests passed.

## 2026-07-24 — Voice selection

- Added Eddie (`VsQmyFHffusQDewmHB5v`) to the available ElevenLabs voices.
- Added playable samples to both voice pickers using the constant script “Hi, This is my voice. Do you find it fitting?”.
- Voice samples are generated lazily on first play and cached in `assets/voice_samples`, avoiding repeat API usage.
- Added a voiceover dropdown to new narrated video creation using the existing ElevenLabs voice registry.
- Stored the selected voice on each `VideoJob` and passed it to the render scripts through `VOICE` in `.env`.
- Extracted voice names and ElevenLabs IDs into the shared, side-effect-free `voice_config.py` module.
- Added voice selection to edit mode for narrated projects.
- Changing an existing project's voice removes its stale narration/timing assets and restarts rendering from `generate_voiceover_with_timing.py` so both audio and subtitle timing are regenerated.
- Narration-free projects retain a voice setting for consistency, but no voice API call is made while their script is empty.
- Django checks, migration consistency, and 31 focused creation/editor/pipeline tests passed.

## 2026-07-22

### Scene timing and audio

- Added optional narration and narration-free project support.
- Added per-scene time after a scene; the current visual continues with no narration or captions.
- Added per-video-scene original sound.
- Background music ducks while original video sound plays.
- Corrected synthetic silence to stereo for reliable MoviePy audio composition.

### Existing-video editor

- Made on-screen subtitles optional per scene.
- Blank subtitles hide that scene's caption display without changing timing.
- Added immediate preview for selected replacement images and videos.
- Added scene creation, deletion, and reordering for narration-free projects.
- New narration-free scenes accept uploaded media or an AI visual prompt and require a positive duration.
- Structural edits preserve revision history and archive replaced/reordered assets.

### Rendering performance

- Added duration-limited portrait H.264 working-video caches.
- Added early source cropping and bounded intermediate frame sizes.
- Replaced double resizing with one cover-and-motion resize pass.
- Added a static-scene fast path.
- Removed the expensive full-frame vignette composite.
- Added AMD AMF H.264 encoding with automatic `libx264/veryfast` fallback for Intel and unsupported systems.
- Increased CPU encoding thread utilization.
- Measured static uploaded-video processing improving from 1.65 to 5.92 fps; static images reached 34.49 fps.

### Verification

- Verified AMD encoding through MoviePy with a temporary MP4.
- Focused suites passed for audio mixing, scene timing, optional subtitles, revisions, narration-free scene restructuring, upload previews, and existing narrated-editor restrictions.
## 2026-07-24

### Precise scene duration

- Scene duration fields now use `0.01`-second increments and display two decimal places.
- Persisted scene durations are normalized to two decimal places.
- Selecting a video automatically sets the scene duration to the video's complete metadata duration, rounded down to hundredths (for example, `5.559` becomes `5.55`).
- Automatic duration detection is available in both guided creation and existing-video editing, including newly added narration-free scenes.

### Preserve complete 16:9 media

- Added a per-scene `fit_with_borders` setting for media detected as approximately 16:9.
- Creator and editor controls appear after browser metadata confirms a 16:9 image or video; existing editor media is also detected server-side.
- Fit mode uses contain scaling on a black 1080x1920 canvas. It never stretches or center-crops the source.
- Fit-aware video preprocessing uses FFmpeg `scale` plus black `pad` and a distinct render-cache key.
- Verified with the real `My_test` 16:9 video: the cached frame was 1080x1920, the top border was black, and center content remained visible.
- Nineteen focused Django tests passed.
