"""Generate and cache short ElevenLabs voice-picker samples."""

import os
import threading
from pathlib import Path

import requests

from voice_config import resolve_voice_id


VOICE_SAMPLE_TEXT = "Hi, This is my voice. Do you find it fitting?"
_generation_lock = threading.Lock()


def _read_elevenlabs_api_key(base_dir: Path) -> str:
    environment_value = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if environment_value:
        return environment_value

    env_path = Path(base_dir) / ".env"
    if env_path.exists():
        with env_path.open(encoding="utf-8") as env_file:
            for raw_line in env_file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key.strip() == "ELEVENLABS_API_KEY":
                    value = value.strip().strip('"').strip("'")
                    if value:
                        return value
    raise RuntimeError("ELEVENLABS_API_KEY is not configured.")


def ensure_voice_sample(base_dir: Path, voice_key: str) -> Path:
    """Return a cached sample path, generating it atomically when absent."""
    samples_dir = Path(base_dir) / "assets" / "voice_samples"
    sample_path = samples_dir / f"{voice_key}.mp3"
    if sample_path.exists():
        return sample_path

    with _generation_lock:
        if sample_path.exists():
            return sample_path

        api_key = _read_elevenlabs_api_key(Path(base_dir))
        voice_id = resolve_voice_id(voice_key)
        response = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json={
                "text": VOICE_SAMPLE_TEXT,
                "voice_settings": {"stability": 0.75, "similarity_boost": 0.75},
                "model_id": "eleven_multilingual_v2",
            },
            timeout=90,
        )
        response.raise_for_status()

        samples_dir.mkdir(parents=True, exist_ok=True)
        temporary_path = samples_dir / f".{voice_key}.generating"
        try:
            temporary_path.write_bytes(response.content)
            temporary_path.replace(sample_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        return sample_path
