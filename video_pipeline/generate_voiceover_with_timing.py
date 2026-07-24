import requests
import os
import json
import time
import numpy as np
from moviepy.audio.AudioClip import AudioClip
from config import BASE_DIR, FILE_NAME, VOICE, require_setting
from voice_config import resolve_voice_id

# === CONFIG ===
#pelegha2000:  sk_183570bf426a3dd0a30e06958314e3b4bf28ac1c5433b8c1 
#ali: sk_33ce6496023f05bb58f67185b5752387d1ca270c7efe7aa1
API_KEY = None
VOICE_ID = resolve_voice_id(VOICE)
TEXT_FILE = BASE_DIR / 'scripts' / f'{FILE_NAME}.txt'
OUTPUT_FILE = BASE_DIR / 'assets' / 'voiceovers' / f'{FILE_NAME}.mp3'
TIMING_FILE = BASE_DIR / 'assets' / 'voiceovers' / f'captions_{FILE_NAME}.json'
if OUTPUT_FILE.exists() and TIMING_FILE.exists():
    print(f"File {OUTPUT_FILE} already exists. Skipping the generation process.")
    exit()  # Exit the script if the file exists
# === LOAD SCRIPT ===
with open(TEXT_FILE, 'r', encoding='utf-8') as f:
    script = f.read()
    script = script.replace('###', '')
    script = script.replace('**', '')
    script = script.replace('*', '')

if not script.strip():
    prompts_path = BASE_DIR / 'prompts' / f'{FILE_NAME}.json'
    with open(prompts_path, 'r', encoding='utf-8') as f:
        scene_settings = json.load(f)
    duration = sum(max(0.0, float(scene.get('hold_after_seconds', 0) or 0)) for scene in scene_settings)
    if duration <= 0:
        raise ValueError('A narration-free project needs a positive scene duration.')
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    def make_silence(t):
        if isinstance(t, np.ndarray):
            return np.zeros((len(t), 2), dtype=float)
        return np.zeros(2, dtype=float)
    silence = AudioClip(make_silence, duration=duration, fps=44100)
    silence.write_audiofile(str(OUTPUT_FILE), fps=44100, codec='libmp3lame', logger=None)
    silence.close()
    TIMING_FILE.write_text('[]', encoding='utf-8')
    print(f"OK Silent voiceover saved to {OUTPUT_FILE}")
    raise SystemExit(0)

API_KEY = require_setting("ELEVENLABS_API_KEY")
print(f"Selected voice: {VOICE}")

# === APPROACH: REGULAR TTS + HISTORY RETRIEVAL ===
# Step 1: Generate the audio first
url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
headers = {
    "xi-api-key": API_KEY,
    "Content-Type": "application/json"
}
data = {
    "text": script,
    "voice_settings": {
        "stability": 0.75,
        "similarity_boost": 0.75
    },
    "model_id": "eleven_multilingual_v2",
    # Add to history so we can retrieve alignment later
    "generation_config": {
        "add_to_history": True
    }
}

print("Generating speech and adding to history...")
response = requests.post(url, headers=headers, json=data)

# Save the audio file if successful
if response.status_code == 200:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, 'wb') as f:
        f.write(response.content)
    print(f"OK Voiceover saved to {OUTPUT_FILE}")
    
    # Step 2: Wait a moment for history to be updated
    print("Waiting for history to be processed...")
    time.sleep(3)  # Wait longer to ensure the history is available
    
    # Step 3: Get the latest history item (should be the one we just created)
    history_url = "https://api.elevenlabs.io/v1/history"
    history_params = {"page_size": 1}  # Get only the most recent item
    history_response = requests.get(history_url, headers=headers, params=history_params)
    
    if history_response.status_code == 200:
        try:
            history_data = history_response.json()
            history_items = history_data.get('history', [])
            
            if history_items and len(history_items) > 0:
                # Get the most recent history item
                most_recent_item = history_items[0]
                item_id = most_recent_item.get('history_item_id')
                
                print(f"Found most recent history item with ID: {item_id}")
                
                # Step 4: Get the details of the history item with alignment data
                item_url = f"https://api.elevenlabs.io/v1/history/{item_id}"
                item_response = requests.get(item_url, headers=headers)
                
                if item_response.status_code == 200:
                    item_details = item_response.json()
                    
                    # Debug the structure
                    if 'alignments' in item_details:
                        words_info = item_details['alignments']
                        print("Found alignments data")
                    else:
                        # Try to navigate to the correct location based on debugging
                        print("Exploring alternative data structure...")
                        
                    # Based on your debugging output - the data structure is different
                    # Let's handle character-level timing data and convert to word level
                    character_data = None
                    
                    # Try multiple paths to find the character data based on debugging results
                    if 'alignments' in item_details and isinstance(item_details['alignments'], dict):
                        if 'alignment' in item_details['alignments']:
                            character_data = item_details['alignments']['alignment']
                            print("Found character data in alignments.alignment")
                    
                    # Try direct path based on debugging
                    if character_data is None and 'alignment' in item_details:
                        character_data = item_details['alignment']
                        print("Found character data in item_details.alignment")
                        
                    if character_data and 'characters' in character_data:
                        # We have character-level data, convert to word-level
                        print("Processing character-level data to word-level timing...")
                        
                        characters = character_data.get('characters', [])
                        char_start_times = character_data.get('character_start_times_seconds', [])
                        char_end_times = character_data.get('character_end_times_seconds', [])
                        
                        # Make sure all arrays are the same length
                        min_length = min(len(characters), len(char_start_times), len(char_end_times))
                        
                        # Process characters into words
                        timing_data = []
                        current_word = ""
                        word_start = None
                        word_end = None
                        
                        for i in range(min_length):
                            char = characters[i]
                            start_time = char_start_times[i]
                            end_time = char_end_times[i]
                            
                            # If character is a space or punctuation, it's the end of a word
                            if char in [' ', '\t', '\n', '.', ',', '!', '?', ';', ':', '-']:
                                if current_word:  # If we have a word accumulated
                                    timing_data.append({
                                        "text": current_word,
                                        "start": word_start,
                                        "end": word_end
                                    })
                                    current_word = ""
                                    word_start = None
                            else:
                                # Add character to current word
                                current_word += char
                                # Update word timing
                                if word_start is None:
                                    word_start = start_time
                                word_end = end_time
                        
                        # Add the last word if there is one
                        if current_word:
                            timing_data.append({
                                "text": current_word,
                                "start": word_start,
                                "end": word_end
                            })
                        
                        # Save timing data to JSON file
                        if timing_data:
                            TIMING_FILE.parent.mkdir(parents=True, exist_ok=True)
                            with open(TIMING_FILE, 'w', encoding='utf-8') as f:
                                json.dump(timing_data, f, indent=2)
                            print(f"OK Created word-level timing data with {len(timing_data)} words and saved to {TIMING_FILE}")
                        else:
                            print("FAIL Failed to create word-level timing data")
                    else:
                        print("FAIL Character-level data not found")
                        print(f"Available keys in item_details: {list(item_details.keys())}")
                        
                        # Print raw structure for debugging (limit output size)
                        print("\nRaw data structure preview:")
                        item_str = str(item_details)[:500]  # Limit to first 500 chars
                        print(f"{item_str}...")
                else:
                    print(f"FAIL Error getting history item details: {item_response.status_code}")
                    print(item_response.text)
            else:
                print("FAIL No history items found")
        except json.JSONDecodeError:
            print("FAIL Failed to parse history response as JSON")
            print(f"Response content: {history_response.content[:200]}...")  # Print first 200 chars
    else:
        print(f"FAIL Error getting history: {history_response.status_code}")
        print(history_response.text)
else:
    print(f"FAIL Error generating speech: {response.status_code}")
    print(response.text)
