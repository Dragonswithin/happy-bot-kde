"""User-initiated local speech, with cancellation scoped to Happy Bot's own request."""

import hashlib
import json
import os
import re
from urllib.request import urlopen
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import uuid


PIPER_REPOSITORY = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


def voice_folder():
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "happy-bot/voices"


def installed_voices():
    return sorted(str(path) for path in voice_folder().glob("*/*.onnx")
                  if path.is_file() and Path(str(path) + ".json").is_file())


def piper_catalog():
    with urlopen(f"{PIPER_REPOSITORY}/voices.json", timeout=15) as response:
        return json.load(response)


def download_voice(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("Choose a voice from the Piper catalog.")
    spec = piper_catalog().get(name)
    if not spec:
        raise ValueError("This voice is no longer listed.")
    folder = voice_folder()
    folder.mkdir(parents=True, exist_ok=True)
    model = folder / name / (name + ".onnx")
    if model.is_file() and Path(str(model) + ".json").is_file():
        return str(model)
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        staged = Path(tmp) / name
        staged.mkdir()
        for suffix in (".onnx", ".onnx.json"):
            filename = name + suffix
            remote, info = next(((path, info) for path, info in spec["files"].items()
                                 if Path(path).name == filename), ("", {}))
            if not remote:
                raise ValueError("The voice catalog has an incomplete file list.")
            checksum = hashlib.md5(usedforsecurity=False)
            with urlopen(f"{PIPER_REPOSITORY}/{remote}", timeout=60) as response, (staged / filename).open("wb") as dest:
                while chunk := response.read(128 * 1024):
                    checksum.update(chunk)
                    dest.write(chunk)
            if checksum.hexdigest() != info["md5_digest"]:
                raise ValueError("The downloaded voice is incomplete. Try the download again.")
        try:
            staged.rename(model.parent)
        except OSError:
            if not (model.is_file() and Path(str(model) + ".json").is_file()):
                raise
    return str(model)


def dispatcher():
    try:
        import speechd
    except ImportError as error:
        raise RuntimeError("Install Speech Dispatcher and its Python bindings to use this voice.") from error
    try:
        return speechd.SSIPClient("happy-bot")
    except (speechd.SSIPCommunicationError, OSError) as error:
        raise RuntimeError("Could not connect to Speech Dispatcher. Check its output configuration or choose Piper.") from error


def voices():
    client = dispatcher()
    try:
        return sorted({row[0] for row in client.list_synthesis_voices()})
    finally:
        client.close()


def _dispatch(text, settings, stop):
    client = dispatcher()
    try:
        if client.get_output_module() == "dummy":
            raise RuntimeError("Speech Dispatcher has no synthesizer configured. Set up a speech output module or choose Piper.")
        if settings["dispatcher_voice"]:
            client.set_synthesis_voice(settings["dispatcher_voice"])
        done = threading.Event()
        if stop.is_set():
            return
        client.speak(text, callback=lambda *_, **kw: done.set(), event_types=("end", "cancel"))
        deadline = time.monotonic() + max(60, len(text) / 3)
        while not done.wait(0.1):
            if stop.is_set():
                client.cancel()
                return
            if time.monotonic() > deadline:
                client.cancel()
                raise RuntimeError("Speech Dispatcher stopped responding. Check its output module and try again.")
    finally:
        client.close()


def _command(args, stop, stdin=None):
    with subprocess.Popen(args, stdin=stdin or subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL) as process:
        while process.poll() is None:
            if stop.wait(0.1):
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                return
        if process.returncode:
            raise RuntimeError(f"{Path(args[0]).name} failed. Check the voice and audio settings.")


def _piper(text, settings, stop, runtime):
    model = Path(settings["piper_model"]).expanduser()
    if model.suffix != ".onnx" or not model.is_file() or not Path(str(model) + ".json").is_file():
        raise ValueError("Choose a Piper .onnx voice with its companion .onnx.json configuration.")
    engine = shutil.which("piper")
    player = shutil.which("pw-play") or shutil.which("paplay") or shutil.which("aplay")
    if not engine or not player:
        raise RuntimeError("Install the Piper speech engine and a PipeWire, PulseAudio, or ALSA player.")
    with tempfile.TemporaryDirectory(dir=runtime) as directory, tempfile.TemporaryFile(dir=directory) as source:
        audio = os.path.join(directory, "reply.wav")
        source.write(text.encode("utf-8"))
        source.seek(0)
        _command([engine, "--model", str(model), "--output_file", audio], stop, source)
        if not stop.is_set():
            _command([player, audio], stop)


class Reader:
    def __init__(self, runtime):
        self.runtime = runtime
        self.lock = threading.Lock()
        self.current = ""
        self.stop_event = threading.Event()
        self.result = {"playing": False}

    def start(self, text, settings):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Choose a reply to read.")
        with self.lock:
            if self.result["playing"]:
                raise ValueError("Stop the current reading before starting another.")
            self.current = uuid.uuid4().hex
            self.stop_event = threading.Event()
            self.result = {"playing": True}
            threading.Thread(target=self._run, args=(text, settings, self.stop_event), daemon=True).start()
            return self.current

    def _run(self, text, settings, stop):
        result = {"playing": False}
        try:
            if settings["speech_engine"] == "piper":
                _piper(text, settings, stop, self.runtime)
            else:
                _dispatch(text, settings, stop)
        except Exception as error:
            result["error"] = str(error) or "Could not read aloud."
        finally:
            with self.lock:
                self.result = result

    def status(self, job):
        with self.lock:
            return self.result.copy() if job == self.current else {"playing": False}

    def stop(self, job=None):
        with self.lock:
            if job is None or job == self.current:
                self.stop_event.set()
