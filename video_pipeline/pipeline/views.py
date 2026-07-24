import json
import math
import mimetypes
import shutil
import threading
from pathlib import Path

import requests

from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from voice_config import DEFAULT_VOICE_KEY, VOICE_CHOICES, VOICES

from .editor import MEDIA_EXTENSIONS, is_media_16_9, load_editor_project, update_caption_words
from .forms import MAX_SCENES, MAX_UPLOAD_SIZE, MAX_VIDEO_TIMESTAMP_SECONDS, VideoProjectSubmissionForm
from .models import BackgroundMusicAsset, VideoEditRevision, VideoJob
from .tasks import run_video_pipeline
from .voice_samples import ensure_voice_sample


def available_music_tracks():
    labels = {
        str(asset.track_id): asset.display_name
        for asset in BackgroundMusicAsset.objects.all()
    }
    tracks = []
    for path in (settings.BASE_DIR / "assets").glob("background_music_*.mp3"):
        track_id = path.stem.removeprefix("background_music_")
        if track_id.isdigit():
            tracks.append({"id": track_id, "label": labels.get(track_id, f"Music {track_id}")})
    return sorted(tracks, key=lambda track: int(track["id"]))


def parse_scene_video_range(request, suffix, scene_number, errors):
    """Parse an optional [start, end] range while retaining old full-video projects."""
    raw_start = request.POST.get(f"video_start_seconds_{suffix}", "0").strip()
    raw_end = request.POST.get(f"video_end_seconds_{suffix}", "").strip()
    try:
        start = float(raw_start or 0)
        end = float(raw_end) if raw_end else None
    except ValueError:
        errors.append(f"Scene {scene_number} has an invalid video range.")
        return 0.0, None
    if not math.isfinite(start) or not 0 <= start <= MAX_VIDEO_TIMESTAMP_SECONDS:
        errors.append(f"Scene {scene_number} video start time is invalid.")
    if end is not None and (not math.isfinite(end) or end > MAX_VIDEO_TIMESTAMP_SECONDS or end <= start):
        errors.append(f"Scene {scene_number} video end time must be after its start time.")
    if end is None and start > 0:
        errors.append(f"Scene {scene_number} needs a video end time after its start time.")
    return round(max(0, start), 2), round(end, 2) if end is not None else None


def index(request):
    form = VideoProjectSubmissionForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        file_name = form.cleaned_data["file_name"]
        fps = str(form.cleaned_data["fps"])
        music_track = form.cleaned_data["music_track"]
        voice_key = form.cleaned_data["voice_key"]
        scenes = form.cleaned_data["scenes_json"]

        scripts_dir = settings.BASE_DIR / "scripts"
        prompts_dir = settings.BASE_DIR / "prompts"
        media_dir = settings.BASE_DIR / "assets" / "media" / file_name
        scripts_dir.mkdir(parents=True, exist_ok=True)
        prompts_dir.mkdir(parents=True, exist_ok=True)
        media_dir.mkdir(parents=True, exist_ok=True)

        legacy_script = " ### ".join(scene["narration"] for scene in scenes)
        prompts = [
            {
                "filename": f"scene_{index:02d}.png",
                "prompt": scene["prompt"],
                "narration": scene["narration"],
                "use_original_audio": scene["use_original_audio"],
                "fit_with_borders": scene["fit_with_borders"],
                "hold_after_seconds": scene["hold_after_seconds"],
                "video_start_seconds": scene["video_start_seconds"],
                "video_end_seconds": scene["video_end_seconds"],
            }
            for index, scene in enumerate(scenes, start=1)
        ]
        (scripts_dir / f"{file_name}.txt").write_text(legacy_script, encoding="utf-8")
        (prompts_dir / f"{file_name}.json").write_text(
            json.dumps(prompts, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        for field_name, media_file in request.FILES.items():
            media_index = int(field_name.removeprefix("media_"))
            extension = Path(media_file.name).suffix.lower()
            media_path = media_dir / f"{media_index}{extension}"
            with media_path.open("wb") as destination:
                for chunk in media_file.chunks():
                    destination.write(chunk)

        job = VideoJob.objects.create(
            file_name=file_name,
            fps=int(fps),
            music_track=music_track,
            voice_key=voice_key,
            status="pending",
        )
        thread = threading.Thread(target=run_video_pipeline, args=(job.id, fps), daemon=True)
        thread.start()
        return redirect("job_status", job_id=job.id)

    recent_jobs = VideoJob.objects.all().order_by("-created_at")[:10]
    initial_scenes = [{
        "narration": "", "prompt": "", "use_original_audio": False,
        "fit_with_borders": False, "hold_after_seconds": 0,
        "video_start_seconds": 0, "video_end_seconds": None,
    }]
    if request.method == "POST":
        try:
            submitted_scenes = json.loads(request.POST.get("scenes_json", "[]"))
            if isinstance(submitted_scenes, list) and submitted_scenes:
                initial_scenes = submitted_scenes
        except json.JSONDecodeError:
            pass
    return render(
        request,
        "pipeline/index.html",
        {
            "form": form,
            "recent_jobs": recent_jobs,
            "initial_scenes": initial_scenes,
            "music_tracks": available_music_tracks(),
            "selected_music": request.POST.get("music_track", "1"),
            "voice_choices": VOICE_CHOICES,
            "selected_voice": request.POST.get("voice_key", DEFAULT_VOICE_KEY),
        },
    )


def job_status(request, job_id):
    job = get_object_or_404(VideoJob, id=job_id)
    return render(request, "pipeline/status.html", {"job": job})


def job_status_api(request, job_id):
    job = get_object_or_404(VideoJob, id=job_id)
    return JsonResponse(
        {
            "status": job.status,
            "current_script": job.current_script,
            "progress": job.progress,
            "log": job.log,
        }
    )


def download_video(request, job_id):
    job = get_object_or_404(VideoJob, id=job_id)
    if job.status != "completed":
        raise Http404("Video not ready yet")

    video_path = settings.BASE_DIR / "output" / f"{job.file_name}.mp4"
    if not video_path.exists():
        raise Http404("Video file not found")

    response = FileResponse(video_path.open("rb"), content_type="video/mp4")
    response["Content-Disposition"] = f'attachment; filename="{job.file_name}.mp4"'
    return response


def watch_video(request, job_id):
    job = get_object_or_404(VideoJob, id=job_id)
    if job.status != "completed":
        raise Http404("Video not ready yet")

    video_path = settings.BASE_DIR / "output" / f"{job.file_name}.mp4"
    if not video_path.exists():
        raise Http404("Video file not found")

    response = FileResponse(video_path.open("rb"), content_type="video/mp4")
    response["Content-Disposition"] = f'inline; filename="{job.file_name}.mp4"'
    return response


def retry_job(request, job_id):
    if request.method != "POST":
        raise Http404

    job = get_object_or_404(VideoJob, id=job_id)
    if job.status != "failed" or not job.current_script:
        raise Http404("This job cannot be retried")

    failed_script = job.current_script
    job.status = "pending"
    job.completed_at = None
    job.log += f"\n--- Re-running from {failed_script} ---\n"
    job.save(update_fields=["status", "completed_at", "log"])

    thread = threading.Thread(
        target=run_video_pipeline,
        args=(job.id, str(job.fps), failed_script),
        daemon=True,
    )
    thread.start()
    return redirect("job_status", job_id=job.id)


def save_silent_scene_structure(request, job, editor_project, selected_music, selected_voice):
    """Save add/remove/reorder operations for a project with no narration."""
    errors = []
    try:
        order = json.loads(request.POST.get("scene_order", "[]"))
    except json.JSONDecodeError:
        order = []
    if not isinstance(order, list) or not order:
        return ["Keep at least one scene."], None
    if len(order) > MAX_SCENES or any(not isinstance(token, str) for token in order):
        return [f"A project can contain up to {MAX_SCENES} valid scenes."], None
    if len(set(order)) != len(order):
        return [f"A project can contain up to {MAX_SCENES} unique scenes."], None

    existing = {str(scene["index"]): scene for scene in editor_project["scenes"]}
    submitted = []
    for position, token in enumerate(order, start=1):
        if not isinstance(token, str):
            errors.append(f"Scene {position} is invalid.")
            continue
        source = existing.get(token)
        suffix = token
        prompt = request.POST.get(f"prompt_{suffix}", "").strip()
        upload = request.FILES.get(f"media_{suffix}")
        video_start, video_end = parse_scene_video_range(request, suffix, position, errors)
        try:
            hold = float(request.POST.get(f"hold_after_seconds_{suffix}", "0") or 0)
        except ValueError:
            hold = -1
        if not 0 < hold <= 300:
            errors.append(f"Scene {position} needs a time between 0 and 300 seconds.")
        if not prompt and not upload and not (source and source["media_path"]):
            errors.append(f"Scene {position} needs a visual description or uploaded media.")
        if upload:
            extension = Path(upload.name).suffix.lower()
            if extension not in MEDIA_EXTENSIONS:
                errors.append(f"{upload.name} is not a supported image or video format.")
            if upload.size > MAX_UPLOAD_SIZE:
                errors.append(f"{upload.name} exceeds the 500 MB upload limit.")
        submitted.append({
            "token": token, "source": source, "prompt": prompt, "upload": upload,
            "hold": round(max(0, hold), 2),
            "use_original_audio": request.POST.get(f"use_original_audio_{suffix}") == "on",
            "fit_with_borders": request.POST.get(f"fit_with_borders_{suffix}") == "on",
            "video_start_seconds": video_start,
            "video_end_seconds": video_end,
        })
    if errors:
        return errors, None

    new_revision = job.current_revision + 1
    media_dir = editor_project["paths"]["media"]
    history_dir = media_dir / "history" / f"revision_{new_revision:03d}"
    history_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = media_dir / f".scene_edit_{new_revision:03d}"
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(parents=True)
    needs_image_generation = False
    prompts = []
    media_names = []
    try:
        for new_index, item in enumerate(submitted):
            source = item["source"]
            upload = item["upload"]
            source_path = source["media_path"] if source else None
            prompt_changed = bool(source and item["prompt"] != source["prompt"])
            staged_path = None
            if upload:
                extension = Path(upload.name).suffix.lower()
                staged_path = staging_dir / f"{new_index}{extension}"
                with staged_path.open("wb") as destination:
                    for chunk in upload.chunks():
                        destination.write(chunk)
            elif source_path and source_path.exists() and not prompt_changed:
                staged_path = staging_dir / f"{new_index}{source_path.suffix.lower()}"
                shutil.copy2(source_path, staged_path)
            elif item["prompt"]:
                needs_image_generation = True

            is_video = bool(staged_path and staged_path.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv", ".webm"})
            prompts.append({
                "filename": f"scene_{new_index + 1:02d}.png",
                "prompt": item["prompt"],
                "narration": "",
                "use_original_audio": bool(item["use_original_audio"] and is_video),
                "fit_with_borders": bool(item["fit_with_borders"] and staged_path and is_media_16_9(staged_path)),
                "hold_after_seconds": item["hold"],
                "video_start_seconds": item["video_start_seconds"] if is_video else 0.0,
                "video_end_seconds": item["video_end_seconds"] if is_video else None,
            })
            media_names.append(staged_path.name if staged_path else None)

        for path in media_dir.iterdir():
            if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
                shutil.copy2(path, history_dir / path.name)
                path.unlink()
        ai_dir = media_dir / "ai"
        if ai_dir.exists():
            ai_history = history_dir / "ai"
            shutil.copytree(ai_dir, ai_history, dirs_exist_ok=True)
            shutil.rmtree(ai_dir)
        for staged_path in staging_dir.iterdir():
            shutil.move(str(staged_path), media_dir / staged_path.name)
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)

    editor_project["paths"]["script"].write_text(" ### ".join("" for _ in prompts), encoding="utf-8")
    editor_project["paths"]["prompts"].write_text(
        json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    editor_project["paths"]["captions"].write_text("[]", encoding="utf-8")
    snapshot = {
        "prompts": prompts,
        "captions": [],
        "media": media_names,
        "scene_order": order,
        "voice_key": selected_voice,
    }
    VideoEditRevision.objects.create(job=job, number=new_revision, snapshot=snapshot)
    job.current_revision = new_revision
    job.render_required = True
    job.music_track = selected_music
    job.voice_key = selected_voice
    job.render_start_script = "generate_images_runaware.py" if needs_image_generation else "create_video.py"
    job.save(update_fields=[
        "current_revision", "render_required", "render_start_script", "music_track", "voice_key"
    ])
    return [], new_revision

def edit_job(request, job_id):
    job = get_object_or_404(VideoJob, id=job_id)
    if job.status != "completed":
        raise Http404("Only completed jobs can be edited")

    try:
        editor_project = load_editor_project(settings.BASE_DIR, job.file_name)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return render(request, "pipeline/edit.html", {
            "job": job,
            "load_error": str(exc),
            "scenes": [],
            "voice_choices": VOICE_CHOICES,
            "selected_voice": job.voice_key,
        }, status=422)

    errors = []
    if request.method == "POST":
        scene_word_lists = []
        selected_music = request.POST.get("music_track", job.music_track).strip()
        selected_voice = request.POST.get("voice_key", job.voice_key).strip()
        valid_music_ids = {track["id"] for track in available_music_tracks()}
        if selected_music not in valid_music_ids:
            errors.append("Choose one of the available background tracks.")
        if selected_voice not in VOICES:
            errors.append("Choose one of the available voiceover voices.")
        narration_free = all(not scene["narration"].strip() for scene in editor_project["scenes"])
        if narration_free and request.POST.get("scene_order"):
            if errors:
                return render(request, "pipeline/edit.html", {
                    "job": job, "scenes": editor_project["scenes"], "errors": errors,
                    "saved": False, "music_tracks": available_music_tracks(), "narration_free": True,
                    "voice_choices": VOICE_CHOICES, "selected_voice": selected_voice,
                })
            structure_errors, revision = save_silent_scene_structure(
                request, job, editor_project, selected_music, selected_voice
            )
            if not structure_errors:
                return redirect(f"{request.path}?saved=1")
            errors.extend(structure_errors)
            return render(request, "pipeline/edit.html", {
                "job": job, "scenes": editor_project["scenes"], "errors": errors,
                "saved": False, "music_tracks": available_music_tracks(), "narration_free": True,
                "voice_choices": VOICE_CHOICES, "selected_voice": selected_voice,
            })
        for scene in editor_project["scenes"]:
            index = scene["index"]
            prompt = request.POST.get(f"prompt_{index}", "").strip()
            subtitle_text = request.POST.get(f"subtitle_{index}", "").strip()
            words = subtitle_text.split()
            upload = request.FILES.get(f"media_{index}")
            video_start, video_end = parse_scene_video_range(request, index, index + 1, errors)
            try:
                hold_after_seconds = float(request.POST.get(f"hold_after_seconds_{index}", "0") or 0)
            except ValueError:
                hold_after_seconds = -1
            if not 0 <= hold_after_seconds <= 300:
                errors.append(f"Scene {index + 1} time after scene must be between 0 and 300 seconds.")
            use_original_audio = request.POST.get(f"use_original_audio_{index}") == "on"
            fit_with_borders = request.POST.get(f"fit_with_borders_{index}") == "on"
            if not prompt and not upload and not scene["media_path"]:
                errors.append(f"Scene {index + 1} needs a visual description or uploaded media.")
            if words and len(words) != scene["subtitle_word_count"]:
                errors.append(
                    f"Scene {index + 1} must keep {scene['subtitle_word_count']} subtitle words "
                    "in this first editor version so voiceover timing stays unchanged."
                )
            scene["prompt"] = prompt
            scene["prompt_changed"] = prompt != editor_project["prompts"][index].get("prompt", "")
            scene["subtitle_text"] = subtitle_text
            scene["hold_after_seconds"] = round(hold_after_seconds, 2) if hold_after_seconds >= 0 else 0
            scene["use_original_audio"] = use_original_audio
            scene["fit_with_borders"] = fit_with_borders
            scene["video_start_seconds"] = video_start
            scene["video_end_seconds"] = video_end
            scene_word_lists.append(words)
            if upload:
                extension = Path(upload.name).suffix.lower()
                if extension not in MEDIA_EXTENSIONS:
                    errors.append(f"{upload.name} is not a supported image or video format.")
                if upload.size > MAX_UPLOAD_SIZE:
                    errors.append(f"{upload.name} exceeds the 500 MB upload limit.")

        if not errors:
            voice_changed = selected_voice != job.voice_key
            new_revision = job.current_revision + 1
            history_dir = editor_project["paths"]["media"] / "history" / f"revision_{new_revision:03d}"
            history_dir.mkdir(parents=True, exist_ok=True)
            needs_image_generation = False
            for scene in editor_project["scenes"]:
                index = scene["index"]
                editor_project["prompts"][index]["prompt"] = scene["prompt"]
                editor_project["prompts"][index]["narration"] = scene["narration"]
                editor_project["prompts"][index]["hold_after_seconds"] = scene["hold_after_seconds"]
                editor_project["prompts"][index]["fit_with_borders"] = scene["fit_with_borders"]
                upload = request.FILES.get(f"media_{index}")
                old_path = scene["media_path"]
                if scene["prompt_changed"] and scene["prompt"] and not upload:
                    needs_image_generation = True
                    if old_path and old_path.exists():
                        shutil.copy2(old_path, history_dir / old_path.name)
                        old_path.unlink()
                        scene["media_name"] = None
                        scene["media_path"] = None
                    ai_dir = editor_project["paths"]["media"] / "ai"
                    ai_history_dir = history_dir / "ai"
                    if ai_dir.exists():
                        for ai_path in ai_dir.iterdir():
                            if ai_path.is_file() and ai_path.stem == str(index):
                                ai_history_dir.mkdir(parents=True, exist_ok=True)
                                shutil.copy2(ai_path, ai_history_dir / ai_path.name)
                                ai_path.unlink()
                if upload:
                    if old_path and old_path.exists():
                        shutil.copy2(old_path, history_dir / old_path.name)
                    extension = Path(upload.name).suffix.lower()
                    stem = old_path.stem if old_path else str(index)
                    new_path = editor_project["paths"]["media"] / f"{stem}{extension}"
                    with new_path.open("wb") as destination:
                        for chunk in upload.chunks():
                            destination.write(chunk)
                    if old_path and old_path != new_path and old_path.exists():
                        old_path.unlink()
                    scene["media_name"] = new_path.name
                    scene["media_path"] = new_path
                active_path = scene["media_path"]
                is_video = bool(active_path and active_path.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv", ".webm"})
                editor_project["prompts"][index]["use_original_audio"] = bool(
                    scene["use_original_audio"] and is_video
                )
                editor_project["prompts"][index]["fit_with_borders"] = bool(
                    scene["fit_with_borders"] and active_path and is_media_16_9(active_path)
                )
                editor_project["prompts"][index]["video_start_seconds"] = (
                    scene["video_start_seconds"] if is_video else 0.0
                )
                editor_project["prompts"][index]["video_end_seconds"] = (
                    scene["video_end_seconds"] if is_video else None
                )
            captions = update_caption_words(editor_project["captions"], editor_project["caption_ranges"], scene_word_lists)
            editor_project["paths"]["prompts"].write_text(
                json.dumps(editor_project["prompts"], ensure_ascii=False, indent=2), encoding="utf-8"
            )
            editor_project["paths"]["captions"].write_text(
                json.dumps(captions, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            snapshot = {
                "prompts": editor_project["prompts"],
                "captions": captions,
                "media": [scene["media_name"] for scene in editor_project["scenes"]],
                "scene_settings": [
                    {
                        "use_original_audio": prompt.get("use_original_audio", False),
                        "fit_with_borders": prompt.get("fit_with_borders", False),
                        "hold_after_seconds": prompt.get("hold_after_seconds", 0),
                        "video_start_seconds": prompt.get("video_start_seconds", 0),
                        "video_end_seconds": prompt.get("video_end_seconds"),
                    }
                    for prompt in editor_project["prompts"]
                ],
                "voice_key": selected_voice,
            }
            VideoEditRevision.objects.create(job=job, number=new_revision, snapshot=snapshot)
            job.current_revision = new_revision
            job.render_required = True
            job.music_track = selected_music
            job.voice_key = selected_voice
            if voice_changed:
                voiceover_dir = settings.BASE_DIR / "assets" / "voiceovers"
                for stale_path in (
                    voiceover_dir / f"{job.file_name}.mp3",
                    voiceover_dir / f"captions_{job.file_name}.json",
                ):
                    stale_path.unlink(missing_ok=True)
                job.render_start_script = "generate_voiceover_with_timing.py"
            elif needs_image_generation:
                job.render_start_script = "generate_images_runaware.py"
            else:
                job.render_start_script = "create_video.py"
            job.save(update_fields=[
                "current_revision", "render_required", "render_start_script", "music_track", "voice_key"
            ])
            return redirect(f"{request.path}?saved=1")

    return render(request, "pipeline/edit.html", {
        "job": job,
        "scenes": editor_project["scenes"],
        "errors": errors,
        "saved": request.GET.get("saved") == "1",
        "music_tracks": available_music_tracks(),
        "voice_choices": VOICE_CHOICES,
        "selected_voice": request.POST.get("voice_key", job.voice_key),
        "narration_free": all(not scene["narration"].strip() for scene in editor_project["scenes"]),
    })


def scene_media(request, job_id, scene_index):
    job = get_object_or_404(VideoJob, id=job_id)
    try:
        editor_project = load_editor_project(settings.BASE_DIR, job.file_name)
        media_path = editor_project["scenes"][scene_index]["media_path"]
    except (FileNotFoundError, json.JSONDecodeError, IndexError):
        raise Http404("Scene media not found")
    if not media_path or not media_path.exists():
        raise Http404("Scene media not found")
    content_type = mimetypes.guess_type(media_path.name)[0] or "application/octet-stream"
    return FileResponse(media_path.open("rb"), content_type=content_type)


def render_edits(request, job_id):
    if request.method != "POST":
        raise Http404
    job = get_object_or_404(VideoJob, id=job_id)
    if job.status != "completed" or not job.render_required:
        raise Http404("This project has no saved edits to render")
    output_path = settings.BASE_DIR / "output" / f"{job.file_name}.mp4"
    if output_path.exists():
        history_dir = settings.BASE_DIR / "output" / "history" / str(job.id)
        history_dir.mkdir(parents=True, exist_ok=True)
        history_path = history_dir / f"revision_{job.rendered_revision:03d}.mp4"
        if not history_path.exists():
            shutil.copy2(output_path, history_path)
    job.status = "pending"
    start_script = job.render_start_script or "create_video.py"
    job.current_script = start_script
    pipeline_steps = [
        "generate_voiceover_with_timing.py", "prepare_captions.py",
        "generate_images_runaware.py", "prepare_images.py", "create_video.py",
    ]
    job.progress = int((pipeline_steps.index(start_script) / len(pipeline_steps)) * 100)
    job.log += f"\n--- Rendering saved edit revision {job.current_revision} ---\n"
    job.save(update_fields=["status", "current_script", "progress", "log"])
    thread = threading.Thread(
        target=run_video_pipeline,
        args=(job.id, str(job.fps), start_script),
        daemon=True,
    )
    thread.start()
    return redirect("job_status", job_id=job.id)


def preview_music(request, track_id):
    if not track_id.isdigit():
        raise Http404("Music track not found")
    music_path = settings.BASE_DIR / "assets" / f"background_music_{track_id}.mp3"
    if not music_path.exists():
        raise Http404("Music track not found")
    response = FileResponse(music_path.open("rb"), content_type="audio/mpeg")
    response["Content-Disposition"] = f'inline; filename="{music_path.name}"'
    return response


def preview_voice(request, voice_key):
    if voice_key not in VOICES:
        raise Http404("Voice not found")
    try:
        sample_path = ensure_voice_sample(settings.BASE_DIR, voice_key)
    except (OSError, RuntimeError, ValueError, requests.RequestException) as exc:
        return JsonResponse({"error": f"Voice sample could not be generated: {exc}"}, status=502)
    response = FileResponse(sample_path.open("rb"), content_type="audio/mpeg")
    response["Content-Disposition"] = f'inline; filename="{sample_path.name}"'
    return response


def upload_music(request):
    if request.method != "POST":
        raise Http404

    display_name = request.POST.get("music_name", "").strip()
    uploaded_file = request.FILES.get("music_file")
    if not display_name:
        return JsonResponse({"error": "Enter a name for this music track."}, status=400)
    if len(display_name) > 120:
        return JsonResponse({"error": "Music names can contain up to 120 characters."}, status=400)
    if not uploaded_file:
        return JsonResponse({"error": "Choose an MP3 file to upload."}, status=400)
    if Path(uploaded_file.name).suffix.lower() != ".mp3":
        return JsonResponse({"error": "Only MP3 music files are supported."}, status=400)
    if uploaded_file.size > 50 * 1024 * 1024:
        return JsonResponse({"error": "Music files must be 50 MB or smaller."}, status=400)

    assets_dir = settings.BASE_DIR / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    existing_ids = {
        int(path.stem.removeprefix("background_music_"))
        for path in assets_dir.glob("background_music_*.mp3")
        if path.stem.removeprefix("background_music_").isdigit()
    }
    existing_ids.update(BackgroundMusicAsset.objects.values_list("track_id", flat=True))
    track_id = max(existing_ids, default=0) + 1
    destination = assets_dir / f"background_music_{track_id}.mp3"
    temporary = assets_dir / f".background_music_{track_id}.uploading"
    try:
        with temporary.open("wb") as output:
            for chunk in uploaded_file.chunks():
                output.write(chunk)
        temporary.replace(destination)
        BackgroundMusicAsset.objects.create(
            track_id=track_id,
            display_name=display_name,
            original_filename=Path(uploaded_file.name).name,
        )
    except Exception:
        temporary.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise

    return JsonResponse({
        "track": {
            "id": str(track_id),
            "label": display_name,
            "preview_url": reverse("preview_music", args=[track_id]),
        }
    })
