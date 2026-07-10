import json
import mimetypes
import shutil
import threading
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .editor import MEDIA_EXTENSIONS, load_editor_project, update_caption_words
from .forms import MAX_UPLOAD_SIZE, VideoProjectSubmissionForm
from .models import VideoEditRevision, VideoJob
from .tasks import run_video_pipeline


def index(request):
    form = VideoProjectSubmissionForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        file_name = form.cleaned_data["file_name"]
        fps = str(form.cleaned_data["fps"])
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

        job = VideoJob.objects.create(file_name=file_name, fps=int(fps), status="pending")
        thread = threading.Thread(target=run_video_pipeline, args=(job.id, fps), daemon=True)
        thread.start()
        return redirect("job_status", job_id=job.id)

    recent_jobs = VideoJob.objects.all().order_by("-created_at")[:10]
    initial_scenes = [{"narration": "", "prompt": ""}]
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
        {"form": form, "recent_jobs": recent_jobs, "initial_scenes": initial_scenes},
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


def edit_job(request, job_id):
    job = get_object_or_404(VideoJob, id=job_id)
    if job.status != "completed":
        raise Http404("Only completed jobs can be edited")

    try:
        editor_project = load_editor_project(settings.BASE_DIR, job.file_name)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        return render(request, "pipeline/edit.html", {"job": job, "load_error": str(exc), "scenes": []}, status=422)

    errors = []
    if request.method == "POST":
        scene_word_lists = []
        for scene in editor_project["scenes"]:
            index = scene["index"]
            prompt = request.POST.get(f"prompt_{index}", "").strip()
            subtitle_text = request.POST.get(f"subtitle_{index}", "").strip()
            words = subtitle_text.split()
            if not prompt:
                errors.append(f"Scene {index + 1} needs a visual description.")
            if len(words) != scene["subtitle_word_count"]:
                errors.append(
                    f"Scene {index + 1} must keep {scene['subtitle_word_count']} subtitle words "
                    "in this first editor version so voiceover timing stays unchanged."
                )
            scene["prompt"] = prompt
            scene["prompt_changed"] = prompt != editor_project["prompts"][index].get("prompt", "")
            scene["subtitle_text"] = subtitle_text
            scene_word_lists.append(words)
            upload = request.FILES.get(f"media_{index}")
            if upload:
                extension = Path(upload.name).suffix.lower()
                if extension not in MEDIA_EXTENSIONS:
                    errors.append(f"{upload.name} is not a supported image or video format.")
                if upload.size > MAX_UPLOAD_SIZE:
                    errors.append(f"{upload.name} exceeds the 500 MB upload limit.")

        if not errors:
            new_revision = job.current_revision + 1
            history_dir = editor_project["paths"]["media"] / "history" / f"revision_{new_revision:03d}"
            history_dir.mkdir(parents=True, exist_ok=True)
            needs_image_generation = False
            for scene in editor_project["scenes"]:
                index = scene["index"]
                editor_project["prompts"][index]["prompt"] = scene["prompt"]
                upload = request.FILES.get(f"media_{index}")
                old_path = scene["media_path"]
                if scene["prompt_changed"] and not upload:
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
                if not upload:
                    continue
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
            }
            VideoEditRevision.objects.create(job=job, number=new_revision, snapshot=snapshot)
            job.current_revision = new_revision
            job.render_required = True
            if needs_image_generation:
                job.render_start_script = "generate_images_runaware.py"
            job.save(update_fields=["current_revision", "render_required", "render_start_script"])
            return redirect(f"{request.path}?saved=1")

    return render(request, "pipeline/edit.html", {
        "job": job,
        "scenes": editor_project["scenes"],
        "errors": errors,
        "saved": request.GET.get("saved") == "1",
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
