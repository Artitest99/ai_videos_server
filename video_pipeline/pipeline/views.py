import json
import threading
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import VideoProjectSubmissionForm
from .models import VideoJob
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
