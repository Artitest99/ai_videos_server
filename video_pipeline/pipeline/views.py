from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, FileResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from .models import VideoJob
from .tasks import run_video_pipeline
import threading
import os

def index(request):
    if request.method == 'POST':
        file_name = request.POST.get('file_name')
        fps = request.POST.get('fps', '30')  # Default to 30 if not provided
        text_content = request.POST.get('text_content')
        json_content = request.POST.get('json_content')
        
        # Create directories if they don't exist
        os.makedirs('scripts', exist_ok=True)
        os.makedirs('prompts', exist_ok=True)
        
        # Save text content to scripts folder
        if text_content:
            text_file_path = os.path.join('scripts', f'{file_name}.txt')
            with open(text_file_path, 'w', encoding='utf-8') as f:
                f.write(text_content)
        
        # Save JSON content to prompts folder
        if json_content:
            json_file_path = os.path.join('prompts', f'{file_name}.json')
            with open(json_file_path, 'w', encoding='utf-8') as f:
                f.write(json_content)
        
        # Handle media uploads
        media_dir = os.path.join('assets', 'media', file_name)
        os.makedirs(media_dir, exist_ok=True)
        
        # Save all uploaded media files
        for key in request.FILES:
            if key.startswith('media_'):
                media_file = request.FILES[key]
                media_index = key.split('_')[1]
                
                # Get file extension
                file_ext = os.path.splitext(media_file.name)[1]
                
                # Save with numbered filename
                media_path = os.path.join(media_dir, f'{media_index}{file_ext}')
                with open(media_path, 'wb+') as f:
                    for chunk in media_file.chunks():
                        f.write(chunk)
        
        # Create new job
        job = VideoJob.objects.create(
            file_name=file_name,
            status='pending'
        )
        
        # Start pipeline in background thread, passing FPS
        thread = threading.Thread(target=run_video_pipeline, args=(job.id, fps))
        thread.daemon = True
        thread.start()
        
        return redirect('job_status', job_id=job.id)
    
    # Show recent jobs
    recent_jobs = VideoJob.objects.all().order_by('-created_at')[:10]
    return render(request, 'pipeline/index.html', {'recent_jobs': recent_jobs})

def job_status(request, job_id):
    job = get_object_or_404(VideoJob, id=job_id)
    return render(request, 'pipeline/status.html', {'job': job})

def job_status_api(request, job_id):
    job = get_object_or_404(VideoJob, id=job_id)
    return JsonResponse({
        'status': job.status,
        'current_script': job.current_script,
        'progress': job.progress,
        'log': job.log,
    })

def download_video(request, job_id):
    job = get_object_or_404(VideoJob, id=job_id)
    
    # Check if job is completed
    if job.status != 'completed':
        raise Http404("Video not ready yet")
    
    # Path to the video file
    video_path = os.path.join('output', f'{job.file_name}.mp4')
    
    if not os.path.exists(video_path):
        raise Http404("Video file not found")
    
    # Serve the file for download
    response = FileResponse(open(video_path, 'rb'), content_type='video/mp4')
    response['Content-Disposition'] = f'attachment; filename="{job.file_name}.mp4"'
    return response

def job_status(request, job_id):
    job = get_object_or_404(VideoJob, id=job_id)
    return render(request, 'pipeline/status.html', {'job': job})

def job_status_api(request, job_id):
    job = get_object_or_404(VideoJob, id=job_id)
    return JsonResponse({
        'status': job.status,
        'current_script': job.current_script,
        'progress': job.progress,
        'log': job.log,
    })