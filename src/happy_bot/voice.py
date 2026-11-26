"""Talking to Happy Bot: the microphone, listening until the user pauses, and speech to text.

The user clicks the microphone in Happy Bot's field (or presses the "Talk to Happy Bot" shortcut,
``happy-bot app talk``) and speaks; the words are sent to the assistant as a request. This module
is the daemon's side of that:

- ``VOICE_DEFAULTS`` / ``validate_voice``: the ``voice`` settings group (kept in the daemon's
  settings, ``settings.py``)::

      "voice": {
        "enabled": false,     # show the microphone button and let the shortcut listen
        "base_url": "",       # the speech-to-text service: any server with an OpenAI-style
                              #   POST <base_url>/audio/transcriptions (Whisper in FastFlowLM,
                              #   whisper.cpp's server, ...), e.g. "http://127.0.0.1:52625/v1"
        "model": "",          # model name sent with the audio; "" sends none (services that
                              #   serve one speech model ignore it)
        "language": "en"      # what the user speaks, as a two- or three-letter code; "" lets the
      }                       #   service guess, which Whisper does poorly on short requests

- ``Listener.listen``: records the default microphone through PipeWire (``pw-record``, else
  ``parecord`` or ``arecord``) as 16 kHz mono 16-bit sound, the format Whisper wants, and watches
  its loudness in tenths of a second. It stops when the user has spoken and then been quiet for
  ``QUIET_SECONDS``, when nobody spoke within ``WAIT_FOR_SPEECH_SECONDS``, after
  ``MAX_SECONDS``, or when ``stop`` is called (the microphone clicked again). Only audio in which
  speech was heard is sent: Whisper "hears" words such as "you" in silence. Before sending, the
  recording is loudness-normalized (``normalize``): the chunks heard as speech are brought to
  ``TARGET_SPEECH_RMS`` on average, with the loudest sample kept under ``PEAK_LIMIT``, since
  Whisper needs loudness-normalized 16 kHz mono (with ``language`` set) to hear a quiet or distant
  voice correctly. The recording is encoded and sent from memory.
- ``transcribe`` sends one recording (multipart ``file``, ``model``, ``language``) and returns the
  service's ``text``; ``check_service`` sends half a second of silence to see that a service
  answers like one, for the settings page's Test button, and ``find_service`` tries the model
  services on this computer the same way, for its "Find on this computer" button.

Speech is judged by loudness, not by a model: a chunk counts as speech when it is clearly louder
(``SPEECH_FACTOR`` times) than the quietest chunk so far and above ``SPEECH_FLOOR``. One listener
runs at a time (``Listener.active``); ``listen`` blocks its caller (an HTTP request thread) until
the recording ends and the text is back. Privacy: the voice goes only to the configured service;
an online one is refused while the user's "local only" setting is on.
"""

from __future__ import annotations

import array
import io
import json
import re
import shutil
import subprocess
import threading
import time
import uuid
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import sounds
from .redaction import is_local_address
from .runtime_paths import clear_cache_files

VOICE_DEFAULTS: dict[str, Any] = {"enabled": False, "base_url": "", "model": "", "language": "en"}

RATE = 16000                    # samples per second, mono, 16-bit
CHUNK_SECONDS = 0.1
QUIET_SECONDS = 1.6             # quiet after speech that ends the recording
WAIT_FOR_SPEECH_SECONDS = 8.0   # how long to wait for the user to start talking
MAX_SECONDS = 60.0
MIN_SPEECH_SECONDS = 0.3        # louder chunks needed before it counts as speech
SPEECH_FLOOR = 500              # RMS of 16-bit samples; quieter is never speech
SPEECH_FACTOR = 4.0             # louder than the quietest chunk by this much
TRANSCRIBE_TIMEOUT = 90.0
TARGET_SPEECH_RMS = 3277        # -20 dBFS: the average level speech is brought to
PEAK_LIMIT = 29205              # -1 dBFS: no sample is made louder than this


class VoiceSettingsError(ValueError):
    """A ``voice`` value is not acceptable; the message says which and why."""


class VoiceError(RuntimeError):
    """Listening or speech to text failed; ``code`` is "not_set_up", "busy", "no_microphone",
    "no_speech", "local_only" or "service", and the message is for the user."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_voice(raw: Any) -> dict[str, Any]:
    """A complete, checked ``voice`` group: missing keys get their defaults, unknown ones are refused."""
    if not isinstance(raw, dict):
        raise VoiceSettingsError("'voice' must be an object")
    unknown = sorted(set(raw) - set(VOICE_DEFAULTS))
    if unknown:
        raise VoiceSettingsError(f"'voice': unknown setting '{unknown[0]}'")
    voice = {**VOICE_DEFAULTS, **raw}
    if not isinstance(voice["enabled"], bool):
        raise VoiceSettingsError("'voice': 'enabled' must be true or false")
    for key in ("base_url", "model", "language"):
        if not isinstance(voice[key], str):
            raise VoiceSettingsError(f"'voice': '{key}' must be text")
        voice[key] = voice[key].strip()
    voice["base_url"] = voice["base_url"].rstrip("/")
    if voice["base_url"] and not voice["base_url"].startswith(("http://", "https://")):
        raise VoiceSettingsError("'voice': 'base_url' must start with http:// or https://")
    if voice["language"] and not re.fullmatch(r"[a-z]{2,3}", voice["language"]):
        raise VoiceSettingsError("'voice': 'language' must be a two- or three-letter code such as en")
    return voice


def _recorder() -> list[str]:
    """The command that streams raw 16 kHz mono 16-bit microphone sound to stdout."""
    if shutil.which("pw-record"):
        return ["pw-record", "--raw", "--rate", str(RATE), "--channels", "1", "--format", "s16",
                "--media-category", "Capture", "--media-role", "Communication", "-"]
    if shutil.which("parecord"):
        return ["parecord", "--raw", f"--rate={RATE}", "--channels=1", "--format=s16le"]
    if shutil.which("arecord"):
        return ["arecord", "-q", "-t", "raw", "-r", str(RATE), "-c", "1", "-f", "S16_LE"]
    raise VoiceError("no_microphone", "No recording program was found (pw-record, parecord or arecord).")


def _loudness(chunk: bytes) -> float:
    samples = array.array("h", chunk[: len(chunk) // 2 * 2])
    return (sum(sample * sample for sample in samples) / len(samples)) ** 0.5 if samples else 0.0


def normalize(frames: bytes, speech_power: float) -> bytes:
    """``frames`` scaled so speech (mean square ``speech_power``) reaches ``TARGET_SPEECH_RMS``, peaks under ``PEAK_LIMIT``."""
    samples = array.array("h", frames[: len(frames) // 2 * 2])
    peak = max((abs(sample) for sample in samples), default=0)
    if not samples or speech_power <= 0 or peak == 0:
        return frames
    gain = min(TARGET_SPEECH_RMS / speech_power ** 0.5, PEAK_LIMIT / peak)
    return array.array("h", (int(sample * gain) for sample in samples)).tobytes()


def _wav(frames: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(frames)
    return buffer.getvalue()


def _multipart(fields: dict[str, str], audio: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
             for name, value in fields.items() if value]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="speech.wav"\r\n'
                 f"Content-Type: audio/wav\r\n\r\n".encode() + audio + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def transcribe(voice: dict[str, Any], audio: bytes, timeout: float = TRANSCRIBE_TIMEOUT) -> str:
    """The text the service hears in ``audio`` (a WAV file's bytes); raises ``VoiceError``."""
    body, content_type = _multipart({"model": voice["model"], "language": voice["language"],
                                     "response_format": "json"}, audio)
    request = Request(f"{voice['base_url']}/audio/transcriptions", data=body, method="POST",
                      headers={"Content-Type": content_type})
    try:
        with urlopen(request, timeout=timeout) as response:
            document = json.loads(response.read().decode("utf-8", errors="replace"))
    except HTTPError as error:
        with error:
            raise VoiceError("service", f"The speech service refused the recording (HTTP {error.code}).") from error
    except (URLError, TimeoutError, OSError, ValueError) as error:
        raise VoiceError("service", f"The speech service at {voice['base_url']} did not answer: "
                                    f"{getattr(error, 'reason', error)}") from error
    if not isinstance(document, dict) or not isinstance(document.get("text"), str):
        raise VoiceError("service", "The speech service did not answer with text.")
    return document["text"].strip()


def _usable(voice: dict[str, Any], local_only: bool) -> None:
    if not voice["base_url"]:
        raise VoiceError("not_set_up", "Speech to text is not set up yet (AI Model settings, Voice).")
    if local_only and not is_local_address(voice["base_url"]):
        raise VoiceError("local_only", "Your speech service is online, and \"Local only\" is on.")


def check_service(voice: dict[str, Any], local_only: bool = False) -> dict[str, Any]:
    """Send half a second of silence; ``{"ok": True}`` when the service answers with text."""
    _usable(voice, local_only)
    transcribe(voice, _wav(b"\0\0" * (RATE // 2)), timeout=30.0)
    return {"ok": True}


def find_service(base_urls: list[str]) -> str:
    """The first of ``base_urls`` on this computer that answers like a speech-to-text service, or ""."""
    for base_url in dict.fromkeys(url.rstrip("/") for url in base_urls):
        if not is_local_address(base_url):
            continue
        try:
            check_service({**VOICE_DEFAULTS, "base_url": base_url})
        except VoiceError:
            continue
        return base_url
    return ""


class Listener:
    """Records one request at a time; ``stop`` ends it early (see the module docstring)."""

    def __init__(self, runtime_dir: Path, capture_changed: Callable[[bool], None] | None = None) -> None:
        self._capture_changed = capture_changed
        self._folder = runtime_dir / "voice"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._discard = False
        self.active = False

    def clear_cache(self) -> None:
        """Remove temporary voice clips left by an interrupted older version."""
        clear_cache_files(self._folder, r"[0-9a-f]{32}\.wav")

    def stop(self, discard: bool = False) -> bool:
        """Ends the recording now; with ``discard`` nothing is sent. False when none was running."""
        self._discard = discard
        self._stop.set()
        return self.active

    def listen(self, voice: dict[str, Any], local_only: bool, ui: dict[str, Any] | None = None) -> dict[str, Any]:
        """Record until a pause and return ``{"text"}``; raises ``VoiceError``."""
        _usable(voice, local_only)
        if not self._lock.acquire(blocking=False):
            raise VoiceError("busy", "Happy Bot is already listening.")
        try:
            self.active, self._discard = True, False
            self._stop.clear()
            command = _recorder()
            with sounds.audio_lock:
                if not self._stop.is_set():
                    sounds.play(ui or {}, "mic_ready", wait=True)
                if self._stop.is_set():
                    return {"text": "", "discarded": True}
                frames, speech_power = self._record(command)
            if self._discard:
                return {"text": "", "discarded": True}
            sounds.play(ui or {}, "mic_done")
            return {"text": transcribe(voice, _wav(normalize(frames, speech_power)))}
        finally:
            self.active = False
            self._lock.release()

    def _record(self, command: list[str]) -> tuple[bytes, float]:
        """Raw sound from the microphone until the user pauses (or the limits), and the mean square of
        the chunks heard as speech; raises when no speech was heard."""
        chunk_bytes = int(RATE * CHUNK_SECONDS) * 2
        try:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                       stdin=subprocess.DEVNULL)
        except OSError as error:
            raise VoiceError("no_microphone", f"The microphone could not be opened: {error}") from error
        frames, quietest, spoken, quiet, started = bytearray(), float("inf"), 0, 0, time.monotonic()
        speech_power = 0.0
        try:
            while not self._stop.is_set():
                chunk = process.stdout.read(chunk_bytes) if process.stdout else b""
                if not chunk:
                    break
                # First audio confirms that the device opened, even in a silent room.
                if not frames and self._capture_changed:
                    self._capture_changed(True)
                frames += chunk
                level = _loudness(chunk)
                quietest = min(quietest, level)
                if level > max(SPEECH_FLOOR, quietest * SPEECH_FACTOR):
                    spoken, quiet = spoken + 1, 0
                    speech_power += level * level
                else:
                    quiet += 1
                elapsed = time.monotonic() - started
                heard = spoken * CHUNK_SECONDS >= MIN_SPEECH_SECONDS
                if (heard and quiet * CHUNK_SECONDS >= QUIET_SECONDS) or elapsed >= MAX_SECONDS \
                        or (not heard and elapsed >= WAIT_FOR_SPEECH_SECONDS):
                    break
        finally:
            try:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            finally:
                if self._capture_changed and frames:
                    self._capture_changed(False)
                if process.stdout:
                    process.stdout.close()
        if not frames and not self._discard:
            raise VoiceError("no_microphone", "No sound came from the microphone.")
        if spoken * CHUNK_SECONDS < MIN_SPEECH_SECONDS and not self._discard:
            raise VoiceError("no_speech", "Happy Bot did not hear anything.")
        return bytes(frames), speech_power / max(spoken, 1)
