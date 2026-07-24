"""Supported ElevenLabs voices shared by the web UI and render pipeline."""

DEFAULT_VOICE_KEY = "Rachel_other"

VOICES = {
    "rachel": "EXAVITQu4vr4xnSDxMaL",
    "adam": "pNInz6obpgDQGcFmaJgB",
    "josh": "TxGEqnHWrfWFTfGW9XjX",
    "antoni": "ErXwobaYiN019PkySvjV",
    "Dave": "CYw3kZ02Hs0563khs1Fj",
    "Charlie": "IKne3meq5aSn9XLyUdCD",
    "George": "JBFqnCBsd6RMkjVDRZzb",
    "Charlotte": "XB0fDUnXU5powFXDhCwa",
    "Vincent": "S9WrLrqYPJzmQyWPWbZ5",
    "Peter": "ZthjuvLPty3kTMaNKVKb",
    "Brad": "gWaDC0oXAheKoZfljzuI",
    "David": "asDeXBMC8hUkhqqL7agO",
    "Michael": "uju3wxzG5OhpWcoi3SMy",
    "Liam": "TX3LPaxmHKxFdv7VOQHJ",
    "Mike_Adams": "wgKk07zoxxDRH18KKNOf",
    "Daniel_R": "ZMK5OD2jmsdse3EKE4W5",
    "Rachel_other": "ZT9u07TYPVl83ejeLakq",
    "Adam": "ookcfIYgQDpBT5ueX6gr",
    "Eddie": "VsQmyFHffusQDewmHB5v",
}

VOICE_LABELS = {
    "rachel": "Rachel",
    "adam": "Adam (legacy)",
    "josh": "Josh",
    "antoni": "Antoni",
    "Rachel_other": "Rachel (alternate)",
    "Adam": "Adam (alternate)",
}

VOICE_CHOICES = tuple(
    (key, VOICE_LABELS.get(key, key.replace("_", " ")))
    for key in VOICES
)


def resolve_voice_id(voice_key):
    """Return the ElevenLabs ID for a validated stored voice key."""
    try:
        return VOICES[voice_key]
    except KeyError as exc:
        available = ", ".join(VOICES)
        raise ValueError(f"Unknown voice '{voice_key}'. Available voices: {available}") from exc
