# Bug Register

This file tracks confirmed bugs in the AI video application. It includes both resolved bugs and known bugs that have not been fixed yet.

## Status definitions

- **Known:** Confirmed but not yet being addressed.
- **In progress:** A fix is currently being implemented or tested.
- **Blocked:** The fix requires information, access, or another change first.
- **Resolved:** The fix has been implemented and verified.

---

# Known unresolved bugs

No unresolved bugs have been formally recorded yet.

When adding an unresolved bug, use this structure:

```text
## BUG-XXX — Short descriptive title

- Status: Known
- Reported: YYYY-MM-DD
- Area: UI / pipeline / voiceover / subtitles / images / rendering / storage
- Severity: Low / Medium / High / Critical

### Symptom

What the user sees and how to reproduce it.

### Suspected cause

Known technical information, or “Not yet diagnosed.”

### Workaround

Temporary steps the user can take, or “None known.”

### Planned resolution

The intended fix or next investigation step.
```

---

# Resolved bugs

## BUG-001 — Generated prompt JSON omitted `filename`

- **Status:** Resolved
- **Reported:** 2026-07-10
- **Resolved:** 2026-07-10
- **Area:** Guided creator / prompt compatibility output
- **Severity:** High

### Symptom

The guided creator generated prompt JSON entries containing only `prompt`:

```json
{
  "prompt": "The scene's visual description"
}
```

Existing prompt consumers and the established project format expect every entry to contain both `filename` and `prompt`.

### Cause

The new scene-card compatibility converter in `pipeline/views.py` generated prompt records directly from scene descriptions but did not include the legacy filename property.

### Fix

The converter now creates sequential, deterministic filenames:

```json
{
  "filename": "scene_01.png",
  "prompt": "The scene's visual description"
}
```

Following scenes use `scene_02.png`, `scene_03.png`, and so on.

### Verification

The guided-creator regression test now compares the complete saved prompt structure, including filenames for multiple scenes. The full test suite passed after the fix.

---

## BUG-002 — Voiceover pipeline failed because `sys` was treated as an uninitialized local variable

- **Status:** Resolved
- **Reported:** 2026-07-10
- **Resolved:** 2026-07-10
- **Area:** Pipeline orchestration / voiceover
- **Severity:** Critical

### Symptom

Starting a new project failed on the first pipeline stage with this message:

```text
X generate_voiceover_with_timing.py error: cannot access local variable 'sys' where it is not associated with a value
```

Voiceover generation never started.

### Cause

`pipeline/tasks.py` imported `sys` at module level but also contained another `import sys` inside the later `create_video.py` branch of `run_video_pipeline()`.

In Python, an import inside a function is an assignment. That inner import caused `sys` to be treated as a local variable throughout the whole function. Earlier stages attempted to evaluate `sys.executable` before the local import ran, causing `UnboundLocalError`.

### Fix

The redundant inner `import sys` was removed. All pipeline stages now use the module-level `sys` import and launch subprocesses using the active environment's `sys.executable`.

### Verification

A regression test now starts the pipeline runner with subprocess execution mocked, verifies that the first command uses `sys.executable`, and confirms the function reaches subprocess handling without the scoping error. All 14 tests passed after the fix.

---

## BUG-003 — Editing a visual prompt reused the old scene image

- **Status:** Resolved
- **Reported:** 2026-07-10
- **Resolved:** 2026-07-10
- **Area:** Existing-video editor / image generation
- **Severity:** High

### Symptom

After changing a scene's visual prompt in the existing-video editor, saving and rendering continued to show the same image. The changed prompt was saved, but no new image-generation request occurred.

### Cause

Edited projects always started their update pipeline at `create_video.py`. The existing active image and cached AI image were still present, so the renderer reused them. The legacy image generator also deliberately skipped an image when its numbered AI output already existed.

### Fix

- Prompt changes are now detected by comparing submitted text with the saved prompt.
- When a prompt changes without a manual media upload, the active scene image and cached AI image are copied into revision history and removed from the active generation paths.
- The job records `generate_images_runaware.py` as the required starting step.
- The editor explains that a new AI image will be generated and changes the action label to `Generate new images and render`.
- `prepare_images.py` now promotes missing generated scene indexes individually, allowing new AI media and manually uploaded media to coexist.
- Editor media loading maps files by their numeric scene index. Removing scene 1's stale image therefore cannot cause scene 2's image to appear in scene 1 while generation is pending.
- If the user uploads replacement media while also editing the prompt, the uploaded media remains authoritative and no unnecessary AI generation is scheduled for that scene.

### Verification

Regression tests verify that stale active/generated images are archived and removed, prompt changes start at image generation, missing generated indexes are promoted without overwriting uploaded media, and scene indexes remain stable. The full suite passed with 27 tests. The real `R9` editor also loaded all 12 scenes and media previews without browser errors after the fix.

---

# Bug entry requirements

Each future bug should include:

- A unique sequential ID.
- User-visible symptoms and reproduction information.
- Severity and affected area.
- Current status.
- Root cause when known.
- Workaround when available.
- Resolution details when fixed.
- How the fix was verified, preferably with an automated regression test.

When a known bug is fixed, move its complete entry from **Known unresolved bugs** to **Resolved bugs** instead of deleting its history.
