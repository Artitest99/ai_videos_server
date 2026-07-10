# AI Video Platform — Code Assignments

## Document purpose

This document translates the product vision into an implementation plan for evolving the current Django script runner into an editable AI-video platform.

## Implementation progress

## Active first priority — Edit existing videos

The next implementation priority is an editor for existing generated projects. Work on remaining creation-wizard enhancements should not delay this editing path.

The approved approach is a hybrid editing model:

1. Replacing scene images or videos preserves voiceover, subtitles, and timing.
2. Subtitle-only corrections change displayed text without regenerating audio.
3. Spoken narration changes initially regenerate the complete voiceover and rebuild dependent timing.
4. Scene-level voiceover clips will then be introduced so later versions can regenerate only the affected scene.

The interface must clearly distinguish **subtitle text** from **spoken narration** so a non-technical user understands whether an edit will affect audio, timing, cost, or later scenes.

### Foundation slice 1 — implemented July 10, 2026

- Removed hard-coded ElevenLabs, Runware, and Django secrets from active source.
- Added environment-backed configuration and `.env.example`.
- Anchored the active five-stage pipeline, Django uploads/downloads, and subprocess runner to absolute application paths.
- Changed subprocess execution to use the current Python interpreter explicitly.
- Removed automatic opening of the rendered MP4 on the server/desktop host.
- Added pinned dependency metadata, `.gitignore`, and local setup instructions.
- Added five passing regression tests covering job defaults, environment updates, and shared helpers.

External action still required: rotate the previously exposed ElevenLabs and Runware keys in their provider dashboards, then add the replacement values to the local `.env`. This cannot be completed through source changes alone.

### Foundation slice 2 — implemented July 10, 2026

- Added server-side validation for safe project names and FPS bounds.
- Added JSON parsing with line/column errors and prompt schema validation.
- Enforced one image prompt per script scene.
- Added upload index, extension, and 500 MB size validation.
- Prevented reuse of an existing legacy project name to avoid stale asset collisions.
- Preserved submitted values and displayed actionable form errors in the browser.
- Canonicalized validated prompt JSON before saving it.
- Removed duplicate Django status view definitions.
- Expanded the regression suite from five to eleven passing tests.

The validated raw JSON field remains a temporary compatibility interface for the current legacy pipeline. It must be removed from the user-facing product during the guided project-creation stage below.

### Guided creation slice 1 — implemented July 10, 2026

- Replaced the user-facing script and raw prompt JSON fields with friendly scene cards.
- Added per-scene narration, plain-language visual description, and optional image/video upload controls.
- Added scene creation, removal, reordering, automatic numbering, and a `Use narration` prompt helper.
- Hid `###`, `.txt`, `.json`, filesystem paths, and numbered media concepts from the user.
- Added backend validation for the structured scene payload and a 100-scene safety limit.
- Added backend compatibility generation of legacy script and prompt files so the existing pipeline still runs.
- Preserved scene-card content after validation errors.
- Added UI and compatibility tests, increasing the suite from eleven to thirteen passing tests.
- Verified the rendered creator and dynamic scene interactions in a browser with no console errors.

Still pending within Assignment 2.0: AI-assisted script generation, AI-assisted prompt generation, scene splitting/merging, and draft autosave. The current `Use narration` helper is intentionally local and does not call an AI provider.

### Job recovery and output slice — implemented July 10, 2026

- Added an inline video player to successful job pages while retaining MP4 download.
- Added a protected inline video-serving endpoint for completed jobs.
- Persisted the requested FPS on each job through a database migration.
- Added a failed-job action to re-run from the recorded failed pipeline script.
- Retry preserves earlier successful artifacts, appends a visible retry marker to the log, and continues through remaining stages.
- Restricted retry to failed jobs with a known step; completed jobs cannot be retried through this action.
- Added regression coverage for inline output, retry state, saved FPS, and starting the pipeline at a requested script.
- Expanded the automated suite from fourteen to nineteen passing tests.
- Verified successful and failed job-detail states in a browser without triggering a real retry.

### Existing-video editor slice 1 — implemented July 10, 2026

- Added `Edit Video` to completed job pages.
- Added a scene editor that reconstructs legacy projects from script, prompt, caption, and media artifacts.
- Displays current media, locked spoken narration, editable visual prompts, and editable on-screen subtitles per scene.
- Added non-destructive image/video replacement with the previous asset copied into revision history.
- Added subtitle word correction while preserving cue timestamps and the original voiceover.
- Added explicit word-count validation so this first version cannot accidentally desynchronize captions from audio.
- Added `VideoEditRevision` snapshots and job-level current/rendered revision tracking.
- Marks saved edits as requiring render and exposes `Render updated video` only after changes are saved.
- Archives the previous successful MP4 before starting a renderer-only update.
- Renderer-only updates start at `create_video.py`; successful completion marks the edited revision current.
- Expanded automated coverage from nineteen to twenty-four passing tests.
- Verified the existing `R9` project in a browser as twelve editable scenes with media previews and no console errors.

Current limitation: subtitle corrections must keep the same number of words within each scene. Splitting/merging cues and changing spoken narration remain later priority assignments because they require timing or voiceover regeneration.

### Prompt-driven image regeneration fix — implemented July 10, 2026

- Detects visual prompt changes per scene instead of treating them as metadata-only edits.
- Archives stale active and AI-generated images in revision history.
- Starts the next update at `generate_images_runaware.py` when a new AI image is required.
- Promotes regenerated images by missing scene index without overwriting unrelated uploaded media.
- Keeps scene/media mapping stable while a changed scene temporarily has no active image.
- Makes a same-scene manual upload authoritative when prompt and media are changed together.
- Adds clear editor messaging and a `Generate new images and render` action.
- Expanded the automated suite from twenty-four to twenty-seven passing tests.

The target experience is:

1. A user creates a video project from a script.
2. AI generates the voiceover, word timing, subtitles, and suggested scene media.
3. The user opens an editor that shows every scene on a timeline.
4. The user previews and edits scenes, subtitles, transitions, subtitle effects, voiceover, and background music.
5. Uploaded videos can be trimmed in time and cropped/repositioned within the output frame.
6. The final server render matches the editor preview closely.

The assignments are ordered to build a stable foundation before implementing the visual editor.

---

## Accepted product and architecture decisions

The following decisions are approved and are requirements for implementation. They should be used to resolve ambiguity throughout the assignments in this document.

### Output formats

The first supported editing and rendering format is vertical 1080x1920. Aspect ratio and output dimensions must still be stored on the project so landscape and square formats can be added later without redesigning the data model.

### Editing model

The product is a guided, scene-based editor with a timeline, not a completely free-form professional NLE. Each scene has one primary visual, timing, crop, motion/effect, and outgoing transition. This boundary should be preserved unless a later product decision deliberately expands the scope.

### Non-technical creation experience

The product interface is designed for a non-technical person. Users must never need to create, upload, paste, or understand `script.txt`, `prompt.json`, raw JSON, filesystem paths, numbered media files, or `###` marker syntax.

Project creation happens through friendly UI workflows:

- Write or paste a topic/script into a normal text editor, or ask AI to generate the script.
- Let the application suggest scene boundaries, or add/remove/reorder scenes using scene cards.
- Generate an image prompt for every scene automatically from its narration and context.
- View and edit each prompt as ordinary text on the corresponding scene card.
- Regenerate a single prompt or all prompts without editing JSON.
- Generate scene media from the prompt with a clear button and visible progress.
- Upload or select replacement media without dealing with asset filenames.

The frontend sends structured project, scene, and prompt data to the backend API. Any legacy `.txt` or `.json` files required during migration are generated internally by backend compatibility code and remain invisible to the user.

### Master timeline

The generated voiceover is the authoritative master clock. Scene boundaries, subtitle cues, music playback, editor seeking, preview playback, and final rendering must all synchronize against the voiceover timeline. Replacing or regenerating voiceover is therefore an explicit revision operation that may require dependent timings to be regenerated.

### Preview strategy

Use lightweight browser previews for interactive editing and keep the server renderer authoritative for exported video. Every edit setting must be represented in a versioned shared render specification consumed by both browser preview and final rendering. No editor control is complete until preview and final render both support it.

### Non-destructive editing

All editing is non-destructive. Trimming, cropping, positioning, motion, subtitle correction, volume changes, and effects are stored as project settings. Original uploads, generated images, voiceovers, and music files remain immutable source assets. Regeneration creates a new asset revision or alternative rather than overwriting the original.

### Media alternatives

Generated images and uploaded replacements remain available in the project's asset library. Replacing scene media changes the scene-to-asset relationship; it does not delete or overwrite earlier alternatives.

### Creative controls

Subtitle styles, subtitle animation, scene motion, and transitions begin as a curated set of polished presets. Advanced parameters may be added where they materially improve control, but the first editor will not expose an unrestricted professional keyframe or typography system.

### Rendering workflow

The editor must support low-resolution draft renders and selected-scene or selected-range renders. Full-resolution rendering is an explicit export action, not the feedback mechanism for every edit.

### Editor device scope

Detailed timeline editing is desktop-first. Mobile initially supports viewing projects and renders, playback, status monitoring, and limited simple corrections; full mobile timeline parity is not required for the first release.

### Concurrency and background work

The first-stage product assumes one local desktop user. It does not need multi-user concurrency or distributed workers. However, the shared `.env` job context and in-process daemon threads must still be removed so a restart, retry, or accidentally overlapping local job cannot corrupt another project. Long-running generation and rendering should use one durable local worker with a default concurrency of one, and each project/job must have isolated configuration and storage.

### Security priority

The currently embedded ElevenLabs, Runware, and Django credentials are treated as exposed. Rotating them and moving all secrets to environment-backed configuration is the first implementation task, before further feature development.

### User accounts

The first-stage application is a local, single-user desktop app. Do not build login, account management, ownership checks, user quotas, teams, or sharing in the initial implementation. Avoid unnecessarily coupling project models to this assumption so ownership can be added in a later hosted edition, but do not carry an unused owner field through the first-stage UI or workflows.

### Local desktop operation

The initial distribution runs entirely on the user's computer: local Django/API process, local frontend, local database, local media storage, and a local background worker. External network access is needed only for configured AI providers. The product should provide a simple launcher and should not require the user to manage web-server or worker terminals manually.

---

# Priority Phase — Edit existing generated videos

## Assignment E1 — Open an existing project in edit mode

### Goal

Let a user move from a completed job to a friendly scene-based editing workspace.

### Work

- Add an `Edit video` action to successful job pages.
- Load the project's narration, prompts, media, caption timing, voiceover, music choice, and output settings.
- Convert legacy `.txt`, prompt JSON, caption JSON, and numbered media into one normalized editor payload.
- Display ordered scene cards with thumbnails, narration, subtitle text, visual prompt, and scene timing.
- Preserve original generated files and create a new editable revision rather than changing source assets destructively.
- Warn clearly when an older legacy project is missing data required for a particular edit.

### Acceptance criteria

- A non-technical user can open a completed video and understand its scenes without seeing paths, JSON, filenames, or marker syntax.
- Opening edit mode does not modify the existing video or its source assets.
- Returning to the job page still allows playback of the last successful render.

## Assignment E2 — Replace a scene image or video

### Goal

Allow the visual content of one scene to change without touching narration or timing.

### Work

- Show the current media preview on each scene card.
- Add `Replace media`, `Generate another image`, and `Choose existing asset` actions.
- Accept image/video upload through the existing validated media pipeline.
- Preserve the scene's start/end time, subtitle cues, voiceover, crop defaults, effect, and transition.
- Store replacement assets non-destructively and keep earlier alternatives available.
- Mark the project as changed and require a new render to update the MP4.

### Acceptance criteria

- Replacing media changes only the selected scene's visual asset.
- Voiceover and subtitle timing remain byte-for-byte/data-for-data unchanged.
- The user can return to an earlier visual alternative.
- A new render uses the replacement while the previous successful MP4 remains playable.

## Assignment E3 — Correct displayed subtitle text

### Goal

Let users fix spelling, punctuation, capitalization, and subtitle wording without regenerating voiceover.

### Work

- Add inline subtitle cue editing in the scene editor.
- Label the field `On-screen subtitles` and explain that it does not change spoken audio.
- Preserve cue start/end timing by default.
- Add split/merge operations later; the first version edits text within existing cues.
- Show a soft warning when edited subtitles differ substantially from aligned spoken words.
- Save manual-edit metadata so automatic alignment refresh does not silently overwrite corrections.

### Acceptance criteria

- Subtitle corrections appear in preview and the next render.
- Voiceover audio and all scene timings remain unchanged.
- Manual subtitle edits survive page refresh and project re-rendering.

## Assignment E4 — Edit spoken narration with full regeneration

### Goal

Support spoken-text changes safely before localized scene audio generation exists.

### Work

- Add a separate `Spoken narration` editor; do not combine it with subtitle editing.
- Before saving, explain that changing narration regenerates the complete voiceover and may change timing for every scene.
- Require explicit confirmation before starting the paid regeneration operation.
- Create a new voiceover asset rather than overwriting the previous one.
- Regenerate word alignment and subtitle timing from the new voiceover.
- Recalculate scene boundaries while preserving scene order, selected media, prompts, crop settings, and effects.
- Keep manually edited subtitles where they can be mapped safely; surface conflicts for user review.
- Preserve the previous project revision and rendered MP4 for rollback.

### Acceptance criteria

- The user understands the scope and cost before regeneration begins.
- New audio, timings, and subtitles belong to the same voiceover revision.
- Selected scene visuals and creative settings are retained.
- Failed regeneration leaves the previous working revision intact.

## Assignment E5 — Add edit revisions and re-render workflow

### Goal

Make edits reversible and clearly separate saved changes from exported video.

### Work

- Track an edit revision number or immutable edit snapshot.
- Show `Unsaved`, `Saved — render required`, `Rendering`, and `Up to date` states.
- Add `Render updated video` without replacing previous successful output.
- Add revision history with restore for at least the previous working version.
- Associate each render with the exact edit snapshot it used.

### Acceptance criteria

- Users cannot mistake saved editor changes for an already-updated MP4.
- A failed render does not remove the last playable output.
- The system can identify which revision produced each output.

## Assignment E6 — Move to scene-level voiceover clips

### Goal

Allow one scene's spoken narration to change without regenerating the entire voiceover.

### Work

- Store an immutable voiceover clip and alignment data per scene.
- Generate new projects scene by scene while retaining consistent provider voice/settings metadata.
- Concatenate scene clips into a combined narration track during rendering.
- Add short configurable pauses/crossfades at scene boundaries.
- When one scene changes, regenerate only its clip and alignment.
- Support two timing policies:
  - `Keep scene duration`: fit or pad the new clip within safe limits and warn when speech would sound unnatural.
  - `Adjust following scenes`: change the scene duration and ripple later timeline timestamps.
- Provide a legacy conversion path that references ranges of an existing continuous voiceover until scenes are individually regenerated.
- Detect voice/pacing discontinuities and allow full voiceover regeneration as a quality fallback.

### Acceptance criteria

- Editing spoken narration in one scene does not regenerate unrelated scene audio.
- Subtitle timing is rebuilt only for the affected scene unless ripple timing is selected.
- The user chooses timing behavior in plain language before generation.
- The combined output has clean, natural scene boundaries.

## Assignment E7 — Hybrid edit decision rules

### Goal

Automatically guide users to the least disruptive valid workflow.

### Rules

| User action | System behavior |
| --- | --- |
| Replace an image/video | Preserve all audio and timing |
| Correct spelling/punctuation on screen | Subtitle-only edit |
| Change subtitle wording without changing speech | Allow after a mismatch warning |
| Change spoken words before E6 | Regenerate complete voiceover |
| Change spoken words after E6 | Regenerate affected scene clip |
| Make large structural/script changes | Recommend complete voiceover regeneration |
| Reorder scenes after E6 | Reorder scene audio clips with the scenes |

### Acceptance criteria

- Every edit action states whether it changes audio, timing, later scenes, or provider cost.
- The UI never silently regenerates voiceover.
- Image and subtitle-only edits never invoke a paid TTS request.

## Priority delivery order

1. E1 — Open existing projects in edit mode.
2. E2 — Replace scene images/videos.
3. E3 — Correct on-screen subtitles.
4. E5 — Save revisions and re-render safely.
5. E4 — Full voiceover regeneration for spoken-text changes.
6. E6 — Scene-level voiceover architecture.
7. E7 — Complete hybrid guidance and timing policies.

The first useful release of editing is E1–E3 plus the minimum safe revision/re-render behavior from E5.

---

# Phase 0 — Stabilize the current application

## Assignment 0.1 — Secure configuration and create dependency metadata

### Goal

Make the application reproducible and prevent secrets from living in source code.

### Work

- Move ElevenLabs, Runware, and Django secrets to environment variables.
- Remove API keys from Python files and rotate the exposed credentials.
- Add `.env.example` containing names and safe example values only.
- Add `.gitignore` rules for `.env`, generated media, output files, SQLite, caches, and the virtual environment.
- Generate a pinned dependency file from the working environment.
- Document Python and FFmpeg requirements.
- Add configuration validation that reports missing variables at startup.

### Acceptance criteria

- No API credential or production secret is present in tracked source.
- A clean environment can be installed from the dependency manifest.
- Startup fails with a clear message when required configuration is missing.

## Assignment 0.2 — Introduce absolute project paths

### Goal

Remove the requirement that every command run from one specific working directory.

### Work

- Define a single application base path using `pathlib.Path`.
- Replace relative paths in views, tasks, and processing scripts.
- Stop manually parsing `.env` in `config.py`; use environment-backed Django/application settings.
- Pass project/job identifiers explicitly to pipeline commands.

### Acceptance criteria

- The server and pipeline work regardless of the shell's current directory.
- Pipeline scripts do not discover the active project through a shared `FILE_NAME` variable.

## Assignment 0.3 — Validate all input

### Goal

Reject invalid projects before starting expensive generation work.

### Work

- Create Django forms or request schemas for project creation.
- Restrict project names to safe identifiers and generate an internal UUID.
- Parse and validate prompt JSON before saving it.
- Validate upload type, size, and media readability.
- Validate scene count, prompt count, and script marker count.
- Display actionable validation messages in the UI.

### Acceptance criteria

- Invalid JSON, unsafe filenames, unsupported files, and mismatched inputs never start a job.
- User-visible errors explain what must be fixed.

## Assignment 0.4 — Establish automated tests

### Goal

Protect existing behavior while the architecture changes.

### Work

- Add unit tests for script marker parsing and caption preparation.
- Add model and view tests for project submission and job status.
- Mock external ElevenLabs and Runware requests.
- Add a small fixture project for renderer tests.
- Add a smoke test that produces a short low-resolution video.

### Acceptance criteria

- Core parsing, orchestration, and API behavior can be tested without paid API calls.
- Tests detect incorrect scene timing and invalid artifact paths.

---

# Phase 1 — Replace file-based state with a project data model

## Assignment 1.1 — Create the project and asset models

### Goal

Represent a video as editable database records rather than a collection of implicitly related files.

### Proposed models

#### `VideoProject`

- UUID and display title
- status and generation stage
- original script and cleaned narration text
- aspect ratio, width, height, and FPS
- total duration
- selected voice and voice settings
- selected background track and volume
- created/updated timestamps
- no owner field in the first-stage local schema; keep the model easy to extend for a future hosted edition

#### `MediaAsset`

- owning project
- asset type: image, video, voiceover, music, generated image, or render
- original filename and storage path
- MIME type, duration, width, and height
- source: upload, Runware, ElevenLabs, built-in library, or generated output
- generation metadata and prompt

#### `Scene`

- owning project and order
- start and end time on the project timeline
- narration/script section
- primary media asset
- source trim start and end for video assets
- crop/transform values
- scene motion effect and effect parameters
- outgoing transition and transition duration

#### `SubtitleCue`

- owning project and optional scene
- text, start time, and end time
- highlighted word/range information
- style preset and effect
- manual-edit flag

#### `RenderJob`

- project and immutable project revision/snapshot
- status, progress, log, error details, and output asset
- created, started, and completed timestamps

### Work

- Add models, migrations, admin registration, and indexes.
- Create service methods for project duration and ordered timeline retrieval.
- Keep old `VideoJob` temporarily for migration compatibility.

### Acceptance criteria

- A complete editable project can be loaded from database records.
- Multiple projects can generate concurrently without sharing mutable configuration.

## Assignment 1.2 — Add per-project media storage

### Goal

Isolate every project's source files, generated files, previews, and renders.

### Work

- Create a storage layout based on project UUID rather than user-entered names.
- Store original uploads separately from derived proxy/preview files.
- Add asset deletion and cleanup rules.
- Compute metadata and checksums when assets are ingested.
- Avoid overwriting old assets when a project is regenerated.

### Acceptance criteria

- Two projects with the same title cannot collide.
- Every file is traceable to a `MediaAsset` record.
- Regeneration creates a new asset or revision rather than silently reusing stale output.

## Assignment 1.3 — Convert scripts into callable services

### Goal

Make pipeline stages reusable from the editor, API, tests, and background worker.

### Work

- Refactor voice generation, alignment parsing, caption preparation, image generation, and video rendering into Python service modules.
- Give each service typed input and output objects.
- Remove import-time execution and global `FILE_NAME` constants.
- Return structured progress events and errors rather than relying on printed text.
- Keep thin CLI wrappers for manual operation and debugging.

### Acceptance criteria

- Each pipeline stage can be invoked for a specified project without editing `.env`.
- Services can be unit-tested independently.

## Assignment 1.4 — Add project revisions and render snapshots

### Goal

Ensure a render uses one consistent version even if the user keeps editing.

### Work

- Add a project revision number incremented after timeline changes.
- Serialize the complete render configuration into an immutable snapshot when rendering starts.
- Associate output and errors with that snapshot.
- Show when an existing render is older than the current edit revision.

### Acceptance criteria

- An in-progress render cannot change because of later edits.
- Users can tell whether the preview/editor has changes not present in the latest MP4.

---

# Phase 2 — Build a durable generation pipeline

## Assignment 2.0 — Replace raw file inputs with guided project creation

### Goal

Let a non-technical user create the complete initial video structure from the UI without providing script files, prompt files, JSON, or marker syntax.

### Work

- Replace the current filename/script/JSON form with a short project-creation wizard.
- Step 1: ask for a project title and either a topic/idea or existing narration text.
- Step 2: offer `Generate script with AI`, `Improve my script`, and `Use my text` actions.
- Step 3: show proposed scene cards containing each scene's narration; allow add, remove, split, merge, edit, and reorder.
- Step 4: generate a suggested visual prompt for every scene from the scene narration plus nearby context.
- Show prompts as editable ordinary text, never JSON.
- Add `Regenerate prompt` per scene and `Regenerate all prompts` with confirmation.
- Step 5: let the user generate AI media, upload media, or continue with placeholders on each scene.
- Save wizard progress automatically so the user can leave and continue later.
- Generate any temporary legacy `.txt` and `.json` compatibility artifacts on the backend until the old scripts have been fully replaced.

### Acceptance criteria

- A first-time user can create scenes, prompts, and generated media without seeing or entering JSON, filenames, paths, or `###`.
- Every scene can be created and edited independently through visible controls.
- AI script and prompt generation are optional; users can write or correct all text manually.
- The backend receives validated structured data rather than trusting frontend-generated files.
- The wizard can resume after a page refresh without losing completed work.

## Assignment 2.1 — Add a real background job queue

### Goal

Make long-running generation and rendering survive web-server restarts.

### Work

- Introduce a durable local job mechanism. Prefer the simplest solution that can persist jobs without requiring the desktop user to install or operate a separate Redis service; use a database-backed queue or supervised local worker unless testing proves it inadequate.
- Split generation into retryable jobs: voiceover, alignment, subtitles/scenes, images, proxies, and render.
- Persist stage progress and structured error messages.
- Add cancellation and retry actions.
- Default local worker concurrency to one. Prevent duplicate active render/generation jobs for the same project and make any future concurrency an explicit setting.

### Acceptance criteria

- Restarting Django does not lose queued/running job records.
- Failed stages can be retried without repeating successful paid stages.
- Accidentally overlapping or retried projects never exchange configuration or assets.

## Assignment 2.2 — Make voiceover and timing reliable

### Goal

Generate stable narration and word timings that can drive scenes and subtitles.

### Work

- Use an ElevenLabs endpoint/response that directly corresponds to the generation request and returns alignment when available.
- Never infer alignment from the account's newest history item.
- Store provider response IDs and raw alignment as asset metadata.
- Normalize character/word timings through a tested adapter.
- Support voice selection and configurable stability/similarity settings.
- Add a regenerate action with confirmation because it can invalidate timings.

### Acceptance criteria

- Timings always belong to the saved voiceover asset.
- Concurrent voice generations cannot cross-associate alignment.
- Regeneration produces a new voiceover revision and updates dependent data intentionally.

## Assignment 2.3 — Generate initial scenes and subtitles

### Goal

Turn narration into a useful editable first draft.

### Work

- Accept ordered scene records created by the guided UI as the normal input.
- Retain `###` parsing only as a temporary legacy-import compatibility path, not as a user-facing workflow.
- Add automatic scene segmentation for users who enter one continuous script.
- Let users review and modify proposed scene boundaries before paid generation starts.
- Map word alignment to subtitle cues and scene timing.
- Preserve punctuation and original wording.
- Create default subtitle groups based on readable line length and duration, not a fixed two words only.
- Store every result in `Scene` and `SubtitleCue` records.

### Acceptance criteria

- Every point on the narration timeline belongs to a scene.
- Subtitles are readable, editable, and synchronized to narration.
- User-approved scene cards remain authoritative unless the user explicitly requests automatic re-segmentation.

## Assignment 2.4 — Generate and attach scene media

### Goal

Create one suggested visual per scene while allowing replacement.

### Work

- Store an editable plain-text prompt per scene.
- Generate a default prompt from scene narration/context through a provider adapter.
- Generate images through a provider adapter interface.
- Attach generated assets directly to their scene instead of copying numbered files.
- Show generation state and errors on individual scenes.
- Add regenerate, upload replacement, reuse existing asset, and remove actions.
- Preserve earlier generated alternatives in an asset library.

### Acceptance criteria

- Scene-to-media relationships do not depend on filenames or directory ordering.
- Replacing one scene does not regenerate or reorder other scenes.
- No prompt workflow requires raw JSON input or knowledge of prompt files.

## Assignment 2.5 — Add proxy generation and media inspection

### Goal

Make uploaded media fast and safe to preview in the browser.

### Work

- Inspect files with FFprobe and store duration/dimensions/codecs.
- Create browser-compatible proxy videos and thumbnails.
- Normalize rotation metadata.
- Reject corrupt or unsupported media with useful errors.
- Generate low-resolution preview images for AI images and uploads.

### Acceptance criteria

- All accepted video uploads play in supported browsers.
- The editor can load thumbnails quickly without downloading full source videos.

---

# Phase 3 — Create the editor API

## Assignment 3.1 — Add project editor endpoints

### Goal

Expose project state and focused update operations to a rich frontend.

### Suggested endpoints

- `GET /api/projects/<id>/editor/` — complete editor payload
- `PATCH /api/projects/<id>/` — project settings
- `POST /api/projects/<id>/scenes/` — create/split a scene
- `PATCH /api/scenes/<id>/` — timing, media, crop, effect, transition
- `DELETE /api/scenes/<id>/` — remove/merge a scene
- `POST /api/projects/<id>/scenes/reorder/` — reorder scenes
- `PATCH /api/subtitles/<id>/` — subtitle text, timing, style, effect
- `POST /api/projects/<id>/assets/` — upload media
- `POST /api/projects/<id>/render/` — render current revision
- `GET /api/render-jobs/<id>/` — render status

### Work

- Use Django REST Framework or typed Django JSON views.
- Add schema validation, authorization, and optimistic revision checks.
- Return normalized URLs and media metadata.
- Add transactional timeline updates.

### Acceptance criteria

- The full editor can operate without direct filesystem assumptions.
- Stale concurrent edits receive a conflict response instead of overwriting newer data.

## Assignment 3.2 — Define the shared render specification

### Goal

Create one JSON-compatible schema used by editor preview and final renderer.

### Specification contents

- Canvas dimensions, aspect ratio, FPS, and duration
- Voiceover and background music assets with volume/envelope
- Ordered scene timing
- Media trim range
- Crop rectangle or normalized transform (`x`, `y`, `scale`)
- Motion/effect preset and parameters
- Transition type and duration
- Subtitle cues, typography, position, colors, and animation

### Work

- Define schema and validation rules.
- Add versioning for future compatibility.
- Export it from project database records.
- Save the exact specification on each `RenderJob`.

### Acceptance criteria

- One complete render can be reproduced from the snapshot alone plus referenced assets.
- Preview and final render interpret the same units and defaults.

## Assignment 3.3 — Add autosave and edit history

### Goal

Prevent users from losing timeline work.

### Work

- Debounce frontend changes and save small patches.
- Show saving, saved, offline/error, and conflict states.
- Add undo/redo in the client for the current editing session.
- Store important server-side revisions or an edit-event log.

### Acceptance criteria

- Refreshing the editor restores the latest saved state.
- Temporary network failures do not silently discard changes.
- Common edits can be undone and redone.

---

# Phase 4 — Build the visual scene editor

## Assignment 4.1 — Introduce a frontend application shell

### Goal

Create a maintainable interactive editor while keeping Django as the backend.

### Work

- Add a React or Vue application, preferably TypeScript-based.
- Create routes for project list, project creation, generation progress, and editor.
- Establish an API client, query cache, editor state store, and component test setup.
- Keep existing Django pages available until feature parity is reached.

### Acceptance criteria

- The new editor loads an existing project from the API.
- Backend and frontend development/build commands are documented.

## Assignment 4.2 — Build the editor layout

### Goal

Provide the basic editing workspace.

### Layout

- Center: video preview canvas
- Bottom: timeline with scene blocks, audio tracks, and subtitle cues
- Left: ordered scene/media browser
- Right: inspector for the selected scene, subtitle, transition, or audio track
- Top: project controls, undo/redo, preview quality, save state, and render action

### Acceptance criteria

- Selecting an item in any panel selects the same entity everywhere.
- The layout remains usable on common laptop and desktop resolutions.

## Assignment 4.3 — Implement timeline playback and seeking

### Goal

Make voiceover the master clock for a synchronized preview.

### Work

- Add play/pause, seek, current time, duration, and frame stepping.
- Draw scene boundaries, narration waveform, music track, and subtitle cues.
- Keep preview media and subtitles synchronized to the audio clock.
- Add timeline zoom and horizontal scrolling.
- Pause or degrade expensive preview effects when necessary for responsiveness.

### Acceptance criteria

- Clicking the timeline seeks audio, scene preview, and subtitles together.
- Playback does not drift noticeably over the length of a normal project.

## Assignment 4.4 — Implement scene operations

### Goal

Let users organize and retime video structure.

### Work

- Select, reorder, split, duplicate, and delete scenes.
- Adjust a scene boundary while maintaining a valid continuous timeline.
- Replace scene media from upload, generated alternatives, or the asset library.
- Show each scene's narration and visual prompt in friendly labeled fields.
- Edit the prompt as ordinary text and regenerate a single prompt or scene image.
- Generate a missing prompt directly from the scene narration.
- Provide clear empty states and primary actions such as `Generate visual`, `Upload media`, and `Choose from library`.
- Show scene duration and warnings for insufficient video source duration.

### Acceptance criteria

- Reordering updates timeline order without losing scene settings.
- No edit creates overlaps, negative duration, or uncovered narration time unless explicitly supported.
- Scene creation and media generation require no knowledge of internal files or data formats.

---

# Phase 5 — Video upload trimming and physical cropping

## Assignment 5.1 — Build the video source trimmer

### Goal

Allow a scene to use a selected time range from an uploaded video.

### Work

- Display the source video with thumbnails or a filmstrip.
- Add draggable in/out handles and numeric time inputs.
- Constrain trim values to the source duration.
- Preview the selected range looped within the scene.
- Define behavior when scene duration differs from selected source duration: trim, loop, freeze last frame, or playback-rate adjustment. Start with trim/loop options.

### Acceptance criteria

- The user can accurately select source start and end times.
- The renderer uses the same trim range shown in preview.
- Invalid or too-short ranges are prevented or clearly flagged.

## Assignment 5.2 — Build the crop and positioning editor

### Goal

Let the user choose the physical portion of an image/video visible in the output frame.

### Work

- Display the output aspect-ratio frame over the source.
- Support drag-to-position and zoom/scale controls.
- Store normalized transform coordinates independent of preview resolution.
- Provide `cover`, `contain`, `fit face`, and reset presets where practical.
- Show safe-area overlays for subtitle and platform UI regions.

### Acceptance criteria

- Crop/position settings remain correct at different browser sizes and final render resolution.
- No black borders appear in `cover` mode.
- Preview and output framing match within an agreed tolerance.

## Assignment 5.3 — Add optional scene motion/keyframes

### Goal

Extend static crop values into simple pan-and-zoom motion without becoming a full professional keyframe editor.

### Work

- Support start and end transforms for scale and position.
- Offer named presets such as slow push, pull, pan left, and pan right.
- Preview easing and expose a small set of easing options.
- Allow users to reset to a static crop.

### Acceptance criteria

- Users can customize a preset without exposing blank canvas edges.
- Renderer interpolation matches the browser preview.

---

# Phase 6 — Subtitle editing and styling

## Assignment 6.1 — Build subtitle text and timing editing

### Goal

Allow correction of generated subtitles without regenerating voiceover.

### Work

- Show subtitle cues in a list and on the timeline.
- Edit text inline while retaining timing.
- Adjust start/end times with drag handles and numeric inputs.
- Split and merge cues.
- Prevent unintended overlaps and out-of-range timing.
- Add a restore-from-alignment action.

### Acceptance criteria

- Text corrections do not change voiceover audio.
- Timing changes update preview immediately and persist after refresh.

## Assignment 6.2 — Add subtitle style presets

### Goal

Provide consistent, reusable subtitle styling rather than unrestricted low-level controls initially.

### Work

- Create project-level style presets for font, size, weight, case, color, highlight color, stroke, background, maximum width, and position.
- Allow a cue to inherit the project style or override selected values.
- Include mobile safe-area guides.
- Load fonts consistently in browser and renderer.

### Acceptance criteria

- Changing the project subtitle preset updates all inheriting cues.
- Line wrapping and placement are acceptably close between preview and render.

## Assignment 6.3 — Add subtitle animation effects

### Goal

Let users choose and preview caption motion.

### Work

- Implement a controlled preset set: static, fade, pop, rise, word highlight, and karaoke highlight.
- Define effect parameters in the shared render specification.
- Add per-project default and per-cue override.
- Respect reduced-motion preferences in the editor UI.

### Acceptance criteria

- Every exposed effect works in both preview and final rendering.
- Effects do not alter cue timing or cause text to leave the safe area.

---

# Phase 7 — Scene transitions and effects

## Assignment 7.1 — Define transition presets

### Goal

Replace random transitions with explicit user-controlled settings.

### Work

- Start with cut, crossfade, fade through black, slide, and zoom transition presets.
- Store transition on the outgoing scene with a validated duration.
- Define how transitions overlap adjacent scenes and affect total duration.
- Remove random effect selection from final rendering when a project specification exists.

### Acceptance criteria

- Every scene boundary has a deterministic transition.
- Transition timing cannot exceed safe limits based on neighboring scene durations.

## Assignment 7.2 — Build transition selection and preview

### Goal

Let users evaluate effects at the exact scene boundary.

### Work

- Add transition handles/icons between scene blocks.
- Open an inspector/gallery with effect previews and duration control.
- Loop preview around the selected boundary.
- Add apply-to-all and reset actions.

### Acceptance criteria

- Selecting a transition updates the boundary preview immediately.
- The rendered transition matches the selected type and duration.

---

# Phase 8 — Voiceover and background music controls

## Assignment 8.1 — Add voiceover track controls

### Goal

Use the generated voiceover as a visible, controllable, but timing-authoritative track.

### Work

- Display waveform, duration, mute, and volume.
- Keep original generated audio immutable and store non-destructive track settings.
- Add voiceover replacement/regeneration as a separate workflow.
- Warn that replacing narration may require rebuilding subtitle and scene timing.

### Acceptance criteria

- Voiceover plays in sync throughout editor preview.
- Track settings change the final mix without modifying the source file.

## Assignment 8.2 — Build the background music library

### Goal

Expose already-uploaded background tracks as a reusable library.

### Work

- Import existing numbered music files into `MediaAsset` records.
- Display track name, duration, preview/play control, and selection state.
- Allow uploading additional background music.
- Add search/tags later if the library grows.

### Acceptance criteria

- Users can audition and select any available track without knowing filenames.
- Selected music persists with the project.

## Assignment 8.3 — Add music trim, looping, volume, and fades

### Goal

Provide a basic usable audio mix.

### Work

- Add music source offset, loop toggle, volume, fade-in, and fade-out.
- Show the music region on the project timeline.
- Add optional automatic ducking under voiceover as a later enhancement.
- Prevent clipping in the final mix.

### Acceptance criteria

- Editor preview reflects selection, volume, trim/offset, and looping.
- Final MP4 has the same mix behavior and no obvious clipping.

---

# Phase 9 — Rendering parity and delivery

## Assignment 9.1 — Rewrite rendering around the shared specification

### Goal

Make the final renderer deterministic and independent of filenames, caption markers, and random choices.

### Work

- Load a render snapshot rather than global config and directories.
- Resolve assets by database/storage identifiers.
- Render explicit scene timing, source trim, crop transforms, motion, transitions, subtitles, and audio controls.
- Consider migrating heavy composition from MoviePy to generated FFmpeg filter graphs if performance or reliability becomes limiting.
- Remove server-side auto-opening of output files.

### Acceptance criteria

- Re-rendering the same snapshot produces visually equivalent output.
- All editor-supported controls are honored.
- Missing assets produce structured errors that identify the affected scene.

## Assignment 9.2 — Add draft preview renders

### Goal

Give users fast confirmation before committing to a full-quality render.

### Work

- Add low-resolution/low-bitrate draft render mode.
- Allow rendering a selected scene or short timeline range.
- Cache draft output by revision and range.
- Show estimated render status and make cancellation available.

### Acceptance criteria

- A user can validate one scene or transition without rendering the entire full-resolution project.
- Draft and final modes use the same render specification.

## Assignment 9.3 — Add final render history and download

### Goal

Keep outputs traceable and accessible.

### Work

- Show render history with revision, settings, creation time, duration, size, and status.
- Support download and deletion.
- Mark the newest render matching the current project revision.
- Add configurable retention/cleanup policy.

### Acceptance criteria

- Older renders are not silently overwritten.
- Users can distinguish current and outdated outputs.

---

# Phase 10 — Local desktop product readiness

## Assignment 10.1 — Desktop launcher and lifecycle management

### Goal

Let a non-technical user start and stop the complete local application safely.

### Work

- Add one desktop launcher that starts the local API/web process, frontend, and background worker.
- Ensure only one application instance uses the local database and job queue at a time.
- Open the editor automatically in the desktop shell or local browser.
- Shut down child processes cleanly without abandoning job state.
- Show clear startup errors for missing dependencies, ports, FFmpeg, or provider configuration.
- Decide on packaging after the development workflow is stable: a lightweight local launcher first, followed by an installer or desktop wrapper such as Tauri/Electron only if it improves distribution.

### Acceptance criteria

- The full application starts from one user-facing action without manually opening terminals.
- Closing the application leaves queued/running work in a recoverable state.
- A second instance cannot corrupt the first instance's local state.

## Assignment 10.2 — Observability and usage accounting

### Goal

Understand failures, performance, and paid API usage.

### Work

- Add structured application and worker logs.
- Record provider request IDs, latency, retries, and cost when available.
- Track render time, queue time, and output size.
- Add error reporting and an operational job dashboard.

### Acceptance criteria

- A failed generation can be diagnosed without reading an unbounded text field.
- API and rendering costs can be attributed to projects/users.

## Assignment 10.3 — Local packaging, storage, and recovery

### Goal

Make the local application reliable to install, update, back up, and recover.

### Work

- Bind the local service to loopback only and reject remote network access by default.
- Disable debug mode in packaged builds and use an application-generated local secret.
- Bundle or verify required runtimes such as Python dependencies and FFmpeg.
- Keep SQLite and filesystem media storage for the first stage.
- Store user data in a documented application-data directory rather than beside packaged application code.
- Add database migrations and safe in-place application upgrades.
- Add export/import or backup/restore for projects and media.
- Add local health checks and a repair/recovery path for interrupted jobs.

### Acceptance criteria

- Projects and outputs survive application restarts and upgrades.
- User data can be backed up and restored on the same or another computer.
- Packaged services are accessible only from the local machine by default.

## Assignment 10.4 — Accessibility and responsive editor behavior

### Goal

Make the product usable beyond a single desktop configuration.

### Work

- Add keyboard controls for playback, seeking, selection, deletion, and undo/redo.
- Add accessible names, focus states, and color contrast.
- Provide reduced-motion behavior.
- Create a read-only or simplified mobile view; keep detailed editing desktop-first initially.

### Acceptance criteria

- Core editor actions are keyboard accessible.
- The project remains viewable on mobile even if full timeline editing is desktop-only.

---

# Recommended implementation milestones

## Milestone A — Reliable editable backend

Complete Phases 0–2. A user can create multiple isolated projects, generate voiceover/scenes/subtitles/media, retry failed stages, and persist everything as editable records. The old form can still be used.

## Milestone B — First useful editor

Complete Assignment 2.0, Phase 3, Assignments 4.1–4.4, 6.1, 7.1, 8.1, 8.2, and 9.1. A non-technical user can create or generate a script, approve scene cards, generate/edit prompts, generate or replace media, correct subtitle text, select deterministic transitions, choose music, and render without seeing raw JSON or internal files.

## Milestone C — Uploaded video editing

Complete Phase 5 plus audio mix controls. Users can trim uploaded video sources, reposition/crop them, apply basic motion, and get matching final output.

## Milestone D — Polished creative controls

Complete subtitle styling/animation, transition preview, draft renders, render history, autosave refinement, and undo/redo.

## Milestone E — Local desktop release readiness

Complete Phase 10, local packaging, launcher/lifecycle management, backup and recovery, monitoring, and a local security review.

---

# Deferred hosted-platform work

The following work is intentionally outside the first-stage desktop scope and must not block the local editor:

- Authentication, user accounts, ownership, teams, and sharing
- Multi-tenant authorization and private asset delivery
- User storage/generation quotas and billing
- Public internet deployment, HTTPS termination, and hosted-domain configuration
- PostgreSQL migration for multi-user scale
- Redis or distributed worker infrastructure solely for horizontal scaling
- Cloud object storage and CDN delivery
- Multi-machine rendering

If a hosted edition is approved later, create a separate roadmap phase for these capabilities rather than adding speculative complexity to the local application.

---

# Suggested first development sprint

The first sprint should avoid starting the visual timeline prematurely. Implement these assignments first:

1. Secure and rotate credentials.
2. Add dependency metadata and tests around marker/caption parsing.
3. Add `VideoProject`, `MediaAsset`, `Scene`, `SubtitleCue`, and `RenderJob` models.
4. Create UUID-based per-project storage.
5. Refactor `config.py` and one pipeline stage to accept an explicit project context.
6. Refactor the remaining stages into services.
7. Add the shared render specification and generate it for an existing sample project.

At the end of this sprint, the visible UI may look similar, but the platform will have the foundation required for safe editing, concurrency, retries, and preview/render consistency.

---

# Definition of done for editor features

Every editor control should be considered complete only when:

- It has a persisted database representation.
- It is validated by the backend.
- It appears correctly in interactive preview.
- It is honored by final rendering.
- It has at least one automated test.
- It handles missing/corrupt media gracefully.
- It can be restored after refreshing the editor.
- It does not mutate original uploaded or generated source assets.
