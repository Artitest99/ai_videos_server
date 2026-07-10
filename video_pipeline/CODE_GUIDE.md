# AI Videos Server: Current Code Guide

## 1. Purpose

`ai_videos_server` is a small Django web application that turns a written script into a narrated, captioned AI video. The browser UI collects a project name, frame rate, narration text, image prompts, and optional uploaded media. The server stores those inputs, starts a background Python thread, runs a fixed sequence of standalone scripts, tracks progress in SQLite, and serves the resulting MP4 for download.

The active output format is a vertical 1080x1920 video intended for Shorts, TikTok, or Reels. A separate landscape renderer exists, but the web application does not currently call it.

## 2. High-level flow

```text
Browser form
  -> Django index view saves script, prompts, and uploads
  -> VideoJob row is created in SQLite
  -> daemon thread calls run_video_pipeline()
       1. generate_voiceover_with_timing.py
       2. prepare_captions.py
       3. generate_images_runaware.py
       4. prepare_images.py
       5. create_video.py
  -> output/<FILE_NAME>.mp4
  -> status page polls the job API
  -> completed video becomes downloadable
```

The scripts communicate primarily through files and the shared `.env` file rather than through Python function arguments. `FILE_NAME` selects the current project's files, `MUSIC` selects a numbered background track, and `FPS` controls rendering frame rate.

## 3. Project layout

The actual application root is `Y:\ai_videos_server\video_pipeline`.

| Path | Role |
| --- | --- |
| `manage.py` | Standard Django command entry point. |
| `video_pipeline/` | Django project configuration: settings, root URLs, WSGI, and ASGI. |
| `pipeline/` | Django application containing the job model, views, task runner, routes, migration, and HTML templates. |
| `scripts/<name>.txt` | Narration text. `###` markers also define scene boundaries. |
| `prompts/<name>.json` | Ordered image-generation prompt records. |
| `assets/voiceovers/` | Generated narration MP3 and raw timing JSON. |
| `captions/` | Caption segments prepared for MoviePy. |
| `assets/media/<name>/ai/` | AI-generated or selected source images. |
| `assets/media/<name>/` | Final ordered media used by the renderer, including user uploads. |
| `assets/background_music_<n>.mp3` | Selectable background music. |
| `assets/fonts/` | Fonts used to rasterize captions. |
| `output/<name>.mp4` | Final rendered video. |
| `db.sqlite3` | Django job/status database. |
| `.env` | Shared current-job configuration (`FILE_NAME`, `MUSIC`, `FPS`). |

There is no dependency manifest or project README in the current tree. A populated `.venv` exists one level above the Django application.

## 4. Web application

### Django configuration

`video_pipeline/settings.py` is mostly the default Django 5.2 configuration. It enables the standard Django applications plus `pipeline`, uses SQLite, discovers templates inside installed applications, and exposes static files at `static/`. The root URL configuration includes `pipeline.urls` at `/` and Django admin at `/admin/`.

The current configuration is development-oriented: `DEBUG` is enabled, `ALLOWED_HOSTS` is empty, and the Django secret key is stored directly in source.

### `pipeline/models.py`

`VideoJob` is the only application model. It stores:

- `file_name`: project identifier and base filename.
- `status`: `pending`, `running`, `completed`, or `failed`.
- `current_script`: pipeline step currently running.
- `progress`: integer percentage.
- `log`: accumulated subprocess output.
- `created_at` and `completed_at`: timestamps.

The initial migration creates this table.

### `pipeline/views.py`

`index()` handles both the home page and form submission.

On `GET`, it loads the ten newest jobs and renders `index.html`. On `POST`, it:

1. Reads `file_name`, `fps`, script text, and raw JSON text.
2. Writes the script to `scripts/<file_name>.txt`.
3. Writes prompts to `prompts/<file_name>.json` without parsing or validating the JSON.
4. Saves uploaded media as sequential names such as `assets/media/<file_name>/0.png`.
5. Creates a pending `VideoJob`.
6. Starts `run_video_pipeline()` in a daemon thread.
7. Redirects to the job status page.

`job_status()` renders a single job. `job_status_api()` returns status, step, progress, and log as JSON. `download_video()` only serves `output/<file_name>.mp4` when the job is marked completed.

`job_status()` and `job_status_api()` are each defined twice at the bottom of the file. The later definitions replace the earlier identical definitions at import time; this is redundant but does not change current behavior.

### Templates / frontend

`pipeline/templates/pipeline/index.html` is a server-rendered form with inline CSS and JavaScript. JavaScript counts `###` markers and creates one optional media upload control per scene (`marker count + 1`). The page also lists recent jobs.

`status.html` displays a status badge, progress bar, current script, and subprocess log. While a job is pending or running, JavaScript polls `/api/job/<id>/` every two seconds. When the API reports completion or failure, the page reloads; completed jobs show a download button.

There is no separate frontend framework, build system, or API client. The frontend is Django templates plus browser JavaScript.

## 5. Pipeline orchestration

### `pipeline/tasks.py`

`run_video_pipeline(job_id, fps)` is the central orchestrator.

It marks the job running, rewrites `FILE_NAME` and `FPS` in the shared `.env`, then invokes five scripts using the executable named `python` and the application directory as the assumed working directory. The first four use `subprocess.run()` with a ten-minute timeout. The renderer uses `subprocess.Popen()` so stdout and stderr can be read concurrently and appended to the job log.

Percent strings printed by MoviePy/FFmpeg are extracted with a regular expression and mapped into the renderer's portion of overall progress. A non-zero return code, timeout, or exception marks the job failed. If all steps return zero, the job is marked completed with 100% progress.

This is a process pipeline, not a Django/Celery task queue. Work exists only in an in-process daemon thread, so restarting the Django process can abandon active jobs.

## 6. Active processing scripts

### `config.py`

This module manually parses `.env` from the current working directory and exports `FILE_NAME`, `MUSIC`, and `FPS`. Importing it prints `FILE_NAME`. Paths throughout the project are relative, so commands must be launched from `Y:\ai_videos_server\video_pipeline`.

### `generate_voiceover_with_timing.py`

This script reads `scripts/<FILE_NAME>.txt`, removes Markdown-like `###`, `**`, and `*` markers, and sends the cleaned text to ElevenLabs text-to-speech using a selected voice. If the output MP3 already exists, the entire step exits early.

After generating audio, it waits three seconds, requests the latest ElevenLabs history item, attempts to locate character-level alignment data, and groups characters into word records:

```json
{"text": "word", "start": 1.23, "end": 1.48}
```

It writes these records to `assets/voiceovers/captions_<FILE_NAME>.json`. The script assumes the newest account history item is the audio it just created.

### `prepare_captions.py`

This script combines the original marked-up script with the voice timing JSON. It:

1. Interprets each timing record's `end` value as a duration and converts it to an absolute end time, applying a 0.05-second offset.
2. Finds `###` markers in the original script and records the preceding word as a media transition.
3. Builds one caption segment per spoken word.
4. Displays words in groups of two while highlighting the currently spoken word.
5. Makes each segment end exactly when the next one starts.
6. Marks relevant segments with `media_transition: true`.

The result is written to `captions/captions_<FILE_NAME>.json`. This file provides both caption timing and scene boundaries to the renderer.

### `generate_images_runaware.py`

This is the active image generator. It loads the ordered list from `prompts/<FILE_NAME>.json`, reads each record's `prompt`, submits it to Runware image inference, downloads the returned image, and saves it as `assets/media/<FILE_NAME>/ai/<index>.png`.

Existing numbered output files are skipped, allowing partial reruns. The request currently uses fixed 1024x1024 settings and a hard-coded Runware model in the payload.

### `prepare_images.py`

This reconciles generated images with uploaded media. If `assets/media/<FILE_NAME>/` already contains any media directly, it does nothing. Otherwise, it copies everything from the nested `ai/` directory into the parent media directory.

Consequently, any uploaded media prevents all generated images from being copied into the renderer's input directory. Generated files still remain under `ai/`.

### `create_video.py`

`VideoGenerator` is the active vertical renderer. It targets 1080x1920 and uses MoviePy, Pillow, and NumPy.

The renderer:

- Loads and sorts caption records by start time.
- Loads top-level image/video files from `assets/media/<FILE_NAME>/` and sorts them by digits in each filename.
- Groups captions until a `media_transition` flag, assigning one media file to that time span.
- Loads images as `ImageClip` and videos as silent `VideoFileClip`; short video clips are looped.
- Resizes media to cover the vertical canvas with extra scale for motion.
- Normalizes older animation names into a smaller set of cinematic pan, push, pull, reveal, drift, pop, shake, or static effects.
- Slightly overlaps scenes and crossfades them to avoid black gaps.
- Rasterizes two-word captions using Montserrat Bold, white text, a dark stroke, and a yellow highlighted current word.
- Applies caption `pop`, `rise`, or `static` motion.
- Optionally overlays a vignette.
- Loads narration and the selected background music, loops music to video length, lowers its volume, and mixes both tracks.
- writes H.264/AAC MP4 at the configured FPS.

The file contains a Pillow compatibility shim for MoviePy 1.0.3. Animation randomness is seeded, so automatic effect choices are repeatable. After rendering it attempts to open the output video using the operating system.

## 7. Alternate and currently unused scripts

### `generate_images_online.py`

This alternative media-acquisition path is not called by `tasks.py`. It uses Playwright to scrape DuckDuckGo Images for each prompt, downloads candidates, encodes the prompt and images with OpenCLIP, ranks candidates by similarity, and saves the best result per prompt under the project's AI media folder. It is substantially heavier than the Runware path because it requires a browser, PyTorch, and OpenCLIP.

### `create_video_landscape.py`

This is an older/alternate landscape renderer targeting 1920x1080. It supports images and videos, many transition styles, optional hidden captions, and equal media partitioning when captions are hidden. Its `main()` constructs the generator with captions hidden. It is not selected by the current web UI or task runner.

### `helper.py`

`get_array_type()` distinguishes all-integer from all-string lists and is used when deciding whether caption bolding refers to word indexes or word values. `to_float()` performs float conversion with an optional default.

## 8. Input and output contracts

### Script input

The narration is ordinary text with `###` embedded between scenes. For example:

```text
Opening narration for scene one. ### Narration for scene two.
```

The marker is removed before speech generation. Caption preparation treats the word immediately before each marker as the scene-ending transition point. With `N` markers, the UI offers `N + 1` media uploads.

### Prompt input

Both image-generation scripts expect a top-level JSON list whose entries contain at least a `prompt` field:

```json
[
  {"prompt": "Cinematic portrait of a footballer in a stadium"},
  {"prompt": "Crowd celebrating under stadium lights"}
]
```

The online selector also supports/anticipates filename information, but the active Runware generator numbers results by list position.

### Artifact lifecycle

For a job named `demo`, the important files are:

```text
scripts/demo.txt
prompts/demo.json
assets/voiceovers/demo.mp3
assets/voiceovers/captions_demo.json
captions/captions_demo.json
assets/media/demo/ai/0.png ...
assets/media/demo/0.png ...
output/demo.mp4
```

Several steps deliberately skip existing files. Reusing a project name can therefore reuse old narration, images, media, or output-related inputs rather than fully regenerating them.

## 9. Important current constraints and risks

These observations explain the current design; they are not changes made to the project.

- API credentials for ElevenLabs and Runware are hard-coded in source. The Django secret is also committed in settings. These credentials should be considered exposed and rotated before wider use.
- `.env` is global mutable state. Two simultaneous jobs can overwrite each other's `FILE_NAME` and `FPS`, causing cross-job files or settings.
- All paths depend on the process working directory.
- The form does not validate project names or JSON before writing files. A crafted filename can affect paths, and invalid JSON fails later in a subprocess.
- Job execution uses daemon threads inside the web server rather than a durable queue.
- Existing-file skipping makes retries fast but can silently retain stale assets.
- Voice timing retrieval assumes the newest ElevenLabs history item belongs to the current request, which is unsafe under concurrent account activity.
- The caption timing conversion assumes the provider's `end` value is a duration. If it is already an absolute end timestamp, captions will be too long.
- Mixing user uploads and AI images is effectively all-or-nothing because `prepare_images.py` copies AI images only when no top-level media exists.
- Media count, prompt count, and scene count are not validated against each other. The renderer stops assigning scenes once it runs out of media.
- Database log text is rewritten on nearly every output line during rendering, which can become expensive.
- The renderer attempts to open the MP4 on the server machine, which is unusual for a server process.
- There are no meaningful automated tests, no dependency lock/requirements file, and no repository metadata at `Y:\ai_videos_server`.
- Templates show signs of character-encoding corruption in some icons/arrows.
- Django is configured for development rather than deployment (`DEBUG=True`, embedded secret, empty `ALLOWED_HOSTS`).

## 10. Mental model for future work

The system has three layers:

1. **Django control layer:** accepts inputs, records a job, starts work, reports status, and serves output.
2. **File-based generation pipeline:** narration -> raw word timing -> display captions/scene timing -> generated or uploaded media.
3. **MoviePy renderer:** maps timed scenes to media, applies movement/captions, mixes audio, and encodes MP4.

The most important architectural characteristic is that the layers are coupled through shared relative paths and a single mutable `.env`. Improvements to reliability, concurrency, retry behavior, validation, and extensibility will likely start by replacing that global implicit context with an explicit per-job configuration and workspace.
