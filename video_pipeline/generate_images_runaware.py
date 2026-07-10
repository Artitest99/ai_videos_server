import os
import json
import requests

# Constants
from config import FILE_NAME
PROMPTS_PATH = f"prompts/{FILE_NAME}.json"
OUTPUT_DIR = f"assets/media/{FILE_NAME}/ai"
MODEL_ID = "civitai:102438@133677"
IMAGE_WIDTH = 1024
IMAGE_HEIGHT = 1024
API_KEY = "hTCMRc48PAmGzKRg5tcfquiQAYUAcUpb"  # Replace with your actual key
API_URL = "https://api.runware.ai/v1/inference"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

def load_prompts(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def generate_image(prompt, output_path):
    
    payload = [
  {
    "taskType": "imageInference",
    "taskUUID": "a31ab30e-1e5f-48e6-bdeb-3f73a9875e73",
    "positivePrompt": prompt,
    "model": "runware:101@1",
    "width": 1024,
    "height": 1024,
    "numberResults": 1,
    "outputFormat": "JPEG",
    "steps": 28,
    "CFGScale": 3.5,
    "scheduler": "FlowMatchEulerDiscreteScheduler",
    "outputType": [],
    "includeCost": True
  }
]
    response = requests.post(API_URL, headers=headers, json=payload)

    if response.status_code == 200:
        data = response.json()
        print(data)
        image_url = data.get("data", [{}])[0].get("imageURL")
        if image_url:
            img_data = requests.get(image_url).content
            with open(output_path, "wb") as f:
                f.write(img_data)
            print(f"OK Saved: {output_path}")
        else:
            print("FAIL No image URL found in response.")
    else:
        print(f"FAIL Error {response.status_code}: {response.text}")

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    prompts = load_prompts(PROMPTS_PATH)
    for i, entry in enumerate(prompts):
        prompt = entry.get("prompt")
        if not prompt:
            print(f"Skipping entry {i}, no prompt found.")
            continue
        output_path = os.path.join(OUTPUT_DIR, f"{i}.png")
        if os.path.exists(output_path):
            print(f"File {output_path} already exists. Skipping the generation process.")
            continue  
        generate_image(prompt, output_path)
if __name__ == "__main__":
    main()
