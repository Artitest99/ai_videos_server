# Change Log

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