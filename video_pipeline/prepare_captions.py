import json
import re
import os
from config import FILE_NAME

# === CONFIG ===
TEXT_FILE = f'scripts/{FILE_NAME}.txt'
TIMING_FILE = f'assets/voiceovers/captions_{FILE_NAME}.json'
OUTPUT_FILE = f'captions/captions_{FILE_NAME}.json'
WORDS_PER_SENTENCE = 2

def process_script_with_timing():
    # Read the original script
    with open(TEXT_FILE, 'r', encoding='utf-8') as f:
        script = f.read()
    
    # Read the timing data
    with open(TIMING_FILE, 'r', encoding='utf-8') as f:
        timing_data = json.load(f)
    
    # Fix timing data: Convert durations to end times and apply offsets
    # Process this once at the beginning to avoid any inconsistencies
    for word_data in timing_data:
        # Store the original duration
        duration = word_data['end']
        # Calculate end time: start time + duration + offset
        offset = 0.05
        word_data['end'] = round(word_data['start'] + duration + offset, 2)
        # Apply offset to start time
        word_data['start'] = round(word_data['start'] - offset, 2)
    
    # Tokenize the script and extract transition markers
    plain_script = re.sub(r"\*\*(.+?)\*\*", r"\1", script)
    tokens = re.findall(r"\b[\w'-]+\b|###|\S", plain_script)
    
    # Track transition word indices
    transition_word_indices = []
    word_count = 0
    
    for token in tokens:
        if token == '###':
            if word_count > 0:
                transition_word_indices.append(word_count - 1)
        elif re.match(r"\b[\w'-]+\b", token):  # Count only actual words
            word_count += 1
    
    # Create segments for each word with surrounding context
    segments = []
    word_to_segment = {}  # Map each word index to its segment index
    
    # Process words with their surrounding context
    num_words = len(timing_data)
    
    for i in range(num_words):
        # Get the current word and its timing
        current_word = timing_data[i]['text']
        start_time = timing_data[i]['start']
        end_time = timing_data[i]['end']
        
        # Calculate the range for the group (making sure we don't go out of bounds)
        group_start = max(0, i - i % WORDS_PER_SENTENCE)
        group_end = min(num_words, group_start + WORDS_PER_SENTENCE)
        
        # Create the group text
        group_words = [timing_data[j]['text'] for j in range(group_start, group_end)]
        group_text = ' '.join(group_words)
        group_text = group_text.replace("\u2014", "\u2014 ")
        # Create segment with only the current word highlighted and add the static caption effect
        segment = {
            "text": group_text,
            "text_bold": [current_word],
            "start": start_time,
            "end": end_time,
            "media_transition": False,
            "caption_effect": "static"
        }
        
        segments.append(segment)
        word_to_segment[i] = len(segments) - 1
    
    # Adjust segment end times to match the start time of the next segment
    for i in range(len(segments) - 1):
        next_start = segments[i + 1]["start"]
        segments[i]["end"] = next_start
    
    # Apply image transitions
    for idx in transition_word_indices:
        if idx < num_words:
            segment_idx = word_to_segment[idx]
            if segment_idx < len(segments):
                segments[segment_idx]["media_transition"] = True
    
    # Save the segments
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(segments, f, indent=2)
    
    print(f"OK Word-by-word highlighting segments saved to {OUTPUT_FILE}")
    print(f" - Total segments: {len(segments)}")
    print(f" - Each segment shows {WORDS_PER_SENTENCE} words with single-word highlighting")
    print(f" - All segments have 'static' caption effect")
    print(f" - End time of each segment matches start time of the next segment")

if __name__ == "__main__":
    process_script_with_timing()