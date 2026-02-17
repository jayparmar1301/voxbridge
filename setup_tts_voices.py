"""
Downloads Piper TTS voice models for offline text-to-speech.
Run this once before using the translator.

Confirmed available voices (as of 2025):
  - English: en_US-lessac-medium  (confirmed working)
  - Hindi:   hi_IN-rohan-medium   (added to piper-voices ~Aug 2025)
             hi_IN-pratham-medium  (fallback)
  - Japanese: NOT available in standard Piper voices repo.
              Japanese TTS will be disabled (subtitles still work).
"""

import os
import urllib.request
import sys

# Piper voice model base URLs
PIPER_BASE_V1 = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0"
PIPER_BASE_MAIN = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

VOICES = {
    "en": {
        "name": "en_US-lessac-medium",
        "base_url": PIPER_BASE_V1,
        "files": [
            "en/en_US/lessac/medium/en_US-lessac-medium.onnx",
            "en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
        ],
    },
    "hi": {
        "name": "hi_IN-rohan-medium",
        "base_url": PIPER_BASE_MAIN,  # rohan was added after v1.0.0
        "files": [
            "hi/hi_IN/rohan/medium/hi_IN-rohan-medium.onnx",
            "hi/hi_IN/rohan/medium/hi_IN-rohan-medium.onnx.json",
        ],
        "fallback": {
            "name": "hi_IN-pratham-medium",
            "base_url": PIPER_BASE_MAIN,
            "files": [
                "hi/hi_IN/pratham/medium/hi_IN-pratham-medium.onnx",
                "hi/hi_IN/pratham/medium/hi_IN-pratham-medium.onnx.json",
            ],
        },
    },
    # Japanese: Piper does NOT have official Japanese voices in the main repo.
    # We skip Japanese TTS and rely on subtitles only for Japanese output.
}


def download_file(url: str, dest: str) -> bool:
    """Download a file with progress indication."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        print(f"    Already exists: {os.path.basename(dest)}")
        return True

    print(f"    Downloading: {os.path.basename(dest)}...", end=" ", flush=True)
    try:
        urllib.request.urlretrieve(url, dest)
        size_mb = os.path.getsize(dest) / (1024 * 1024)
        print(f"OK ({size_mb:.1f} MB)")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        if os.path.exists(dest):
            os.remove(dest)  # Clean up partial downloads
        return False


def try_download_voice(voice_info: dict, voices_dir: str) -> bool:
    """Try downloading all files for a voice. Returns True if all succeeded."""
    base_url = voice_info["base_url"]
    all_ok = True
    for file_path in voice_info["files"]:
        url = f"{base_url}/{file_path}"
        filename = os.path.basename(file_path)
        dest = os.path.join(voices_dir, filename)
        if not download_file(url, dest):
            all_ok = False
    return all_ok


def setup():
    voices_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "piper_voices")
    os.makedirs(voices_dir, exist_ok=True)

    print("=" * 60)
    print("Piper TTS — Downloading Voice Models")
    print("=" * 60)
    print(f"Download directory: {os.path.abspath(voices_dir)}\n")

    success_count = 0
    fail_count = 0
    results = {}

    for lang_code, voice_info in VOICES.items():
        voice_name = voice_info["name"]
        print(f"[{lang_code}] Trying: {voice_name}")

        ok = try_download_voice(voice_info, voices_dir)

        # Try fallback if primary failed
        if not ok and "fallback" in voice_info:
            fb = voice_info["fallback"]
            print(f"    Primary failed. Trying fallback: {fb['name']}")
            ok = try_download_voice(fb, voices_dir)
            if ok:
                voice_name = fb["name"]

        if ok:
            success_count += 1
            results[lang_code] = voice_name
            print(f"    -> Ready! Voice: {voice_name}\n")
        else:
            fail_count += 1
            results[lang_code] = None
            print(f"    -> FAILED. TTS for '{lang_code}' will be disabled.\n")

    # Japanese notice
    print(f"[ja] Japanese")
    print(f"    Piper does NOT have official Japanese voices in the repo.")
    print(f"    Japanese TTS output will be disabled (subtitles still work).")
    print(f"    Alternative: install 'piper-tts-plus' (pip install piper-tts-plus)")
    print(f"    which has OpenJTalk-based Japanese support.\n")

    print("=" * 60)
    print(f"Results: {success_count}/{len(VOICES)} voices ready, {fail_count} failed")
    print()

    # Print config.py updates needed
    if any(v is not None for v in results.values()):
        print("Update PIPER_VOICE_MODELS in config.py:")
        print("PIPER_VOICE_MODELS = {")
        for lang, name in results.items():
            if name:
                print(f'    "{lang}": "{name}",')
        print('    # "ja": no Piper voice available')
        print("}")

    print("\nDone!")


if __name__ == "__main__":
    setup()
