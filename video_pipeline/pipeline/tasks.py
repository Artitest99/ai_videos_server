import os
import subprocess
from .models import VideoJob
from django.utils import timezone

def run_video_pipeline(job_id, fps='30'):
    job = VideoJob.objects.get(id=job_id)
    job.status = 'running'
    job.save()
    
    # Path to .env file
    env_path = ".env"
    
    # Update .env file with FILE_NAME and FPS
    try:
        update_env_variable("FILE_NAME", job.file_name, env_path)
        update_env_variable("FPS", fps, env_path)
        job.log += f"Updated FILE_NAME in {env_path}\n"
        job.log += f"Updated FPS to {fps} in {env_path}\n"
        job.save()
    except Exception as e:
        job.status = 'failed'
        job.log += f"Failed to update .env: {str(e)}\n"
        job.save()
        return
    
    # List of scripts to run
    scripts = [
        "generate_voiceover_with_timing.py",
        "prepare_captions.py",
        "generate_images_runaware.py",
        "prepare_images.py",
        "create_video.py"
    ]
    
    total_scripts = len(scripts)
    
    # Run each script
    for idx, script in enumerate(scripts):
        job.current_script = script
        job.progress = int((idx / total_scripts) * 100)
        job.save()
        
        job.log += f"Running {script}...\n"
        job.save()
        
        try:
            # Special handling for create_video.py to track progress
            if script == "create_video.py":
                import sys
                import select
                process = subprocess.Popen(
                    ["python", "-u", script],  # -u flag for unbuffered output
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    bufsize=0,
                    universal_newlines=True
                )
                
                # Read from both stdout and stderr in real-time
                import threading
                
                def read_output(pipe, log_prefix=""):
                    for line in iter(pipe.readline, ''):
                        if line:
                            job.log += line
                            
                            # Try to extract percentage from output
                            import re
                            percentage_match = re.search(r'(\d+)%', line)
                            if percentage_match:
                                video_progress = int(percentage_match.group(1))
                                base_progress = int((idx / total_scripts) * 100)
                                script_weight = int((1 / total_scripts) * 100)
                                job.progress = base_progress + int((video_progress / 100) * script_weight)
                            
                            job.save()
                
                # Create threads to read stdout and stderr simultaneously
                stdout_thread = threading.Thread(target=read_output, args=(process.stdout, "OUT"))
                stderr_thread = threading.Thread(target=read_output, args=(process.stderr, "ERR"))
                
                stdout_thread.daemon = True
                stderr_thread.daemon = True
                
                stdout_thread.start()
                stderr_thread.start()
                
                # Wait for process to complete
                return_code = process.wait()
                
                # Wait for threads to finish reading
                stdout_thread.join(timeout=2)
                stderr_thread.join(timeout=2)
                
                if return_code != 0:
                    job.status = 'failed'
                    job.log += f"X {script} failed with return code {return_code}.\n"
                    job.save()
                    return
                else:
                    job.log += f"✓ {script} completed.\n"
                    job.save()
            else:
                # Normal subprocess handling for other scripts
                result = subprocess.run(
                    ["python", script],
                    capture_output=True,
                    text=True,
                    timeout=600,
                    encoding='utf-8',
                    errors='replace'
                )
                
                if result.returncode != 0:
                    job.status = 'failed'
                    job.log += f"X {script} failed.\n"
                    job.log += f"Error: {result.stderr}\n"
                    job.save()
                    return
                else:
                    job.log += f"✓ {script} completed.\n"
                    job.log += f"Output: {result.stdout}\n"
                    job.save()
        
        except subprocess.TimeoutExpired:
            job.status = 'failed'
            job.log += f"X {script} timed out.\n"
            job.save()
            return
        except Exception as e:
            job.status = 'failed'
            job.log += f"X {script} error: {str(e)}\n"
            job.save()
            return
    
    # All scripts completed
    job.status = 'completed'
    job.progress = 100
    job.completed_at = timezone.now()
    job.log += "\n✓ All scripts completed successfully!\n"
    job.save()

def update_env_variable(key, value, env_path):
    lines = []
    found = False
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                if line.startswith(f"{key}="):
                    lines.append(f"{key}={value}\n")
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(f"{key}={value}\n")
    
    with open(env_path, "w") as f:
        f.writelines(lines)