import os
import subprocess
from pathlib import Path
from typing import Dict, Any
from config.settings import settings

class AudioProcessorProvider:
    def extract_audio(self, media_path: str) -> str:
        """
        Extracts 16kHz mono WAV audio from video/media file for transcription & silence processing.
        """
        in_path = Path(media_path)
        out_path = settings.cache_dir / f"{in_path.stem}_audio.wav"
        
        # If a valid audio file already exists (not a stub), reuse it
        if out_path.exists() and out_path.stat().st_size > 1000:
            return str(out_path.resolve())
            
        try:
            # Command to extract 16kHz mono PCM WAV using ffmpeg
            cmd = [
                "ffmpeg", "-y", "-i", str(in_path),
                "-vn", "-acodec", "pcm_s16le",
                "-ar", "16000", "-ac", "1",
                str(out_path)
            ]
            result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
            # Verify output is valid
            if out_path.exists() and out_path.stat().st_size > 1000:
                return str(out_path.resolve())
        except FileNotFoundError:
            # ffmpeg not installed - log warning
            print("[WARN] ffmpeg not found. Install ffmpeg for audio extraction. Falling back to source file.")
        except subprocess.TimeoutExpired:
            print("[WARN] ffmpeg timed out during audio extraction.")
        except Exception:
            pass
        
        # Fallback: return original media path directly so Whisper can attempt to read it
        # Do NOT create fake stub WAV files — they break downstream processing
        return str(in_path.resolve())
