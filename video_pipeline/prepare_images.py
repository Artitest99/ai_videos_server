import os
import shutil
from config import FILE_NAME

# Define directories
OUTPUT_DIR = f"assets/media/{FILE_NAME}"
AI_OUTPUT_DIR = f"assets/media/{FILE_NAME}/ai"

# Define media file extensions to check for
MEDIA_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.mp4', '.mov', '.avi', '.mkv')

def contains_media_files(directory):
    """Check if there are any media files directly in the directory (not subdirectories)."""
    for file in os.listdir(directory):
        file_path = os.path.join(directory, file)
        if os.path.isfile(file_path) and file.lower().endswith(MEDIA_EXTENSIONS):
            return True
    return False

def copy_ai_output_to_output():
    """Copy all files and folders from AI_OUTPUT_DIR to OUTPUT_DIR."""
    if not os.path.exists(AI_OUTPUT_DIR):
        print(f"AI_OUTPUT_DIR '{AI_OUTPUT_DIR}' does not exist.")
        return
    
    for item in os.listdir(AI_OUTPUT_DIR):
        src_path = os.path.join(AI_OUTPUT_DIR, item)
        dst_path = os.path.join(OUTPUT_DIR, item)
        
        if os.path.isdir(src_path):
            shutil.copytree(src_path, dst_path, dirs_exist_ok=True)
        else:
            shutil.copy2(src_path, dst_path)
    print(f"Copied contents from '{AI_OUTPUT_DIR}' to '{OUTPUT_DIR}'.")

# Create OUTPUT_DIR if it doesn't exist
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Run the logic
if not contains_media_files(OUTPUT_DIR):
    copy_ai_output_to_output()
else:
    print(f"Media files already exist in '{OUTPUT_DIR}'. No action taken.")
