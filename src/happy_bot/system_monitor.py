"""System info for Happy Bot's System info view: live readings, short history, programs, stopping one.

The start screen's optional "System info" button opens a view meant to replace System Monitor for
everyday use (SystemInfoView.qml). This module gives it its data, read from ``/proc``, ``/sys`` and,
for NVIDIA graphics, ``nvidia-smi``, all with the user's own permissions:

- ``History`` keeps the last ``HISTORY_SAMPLES`` seconds of the readings the mascot's sampler
  already takes once a second (``system_sensors.SensorSampler``: CPU load and temperature, available
  memory, network speeds); the daemon feeds it from the same tick, so the graphs cost no extra
  sampling. It lives in memory only.
- ``overview(history)``: the processor (model, cores, load now and over time, temperature, load
  averages), memory and swap, each graphics card (AMD/Intel through sysfs: busy share, video and
  shared memory, temperature; NVIDIA through ``nvidia-smi``), each real disk's space, the network
  link carrying the default route and its speeds, the battery (charge, charging, time left), and
  how long the computer has been on. A part that cannot be read is left out or ``None``.
- ``Programs.top(sort)``: the running programs using the most CPU (their share of all cores between
  this look and the previous one, like System Monitor) or memory (resident), with name, pid, user and
  whether they are the user's own. The first look after a pause has no CPU share yet (0).
- ``stop(pid)``: asks one of the user's own programs to quit (``SIGTERM``, as closing it would),
  refusing other users' programs, Happy Bot's own daemon, and the desktop's shell and window manager
  (``PROTECTED``), whose loss would take the desktop down.

Every function is quick (milliseconds) and safe to call from request threads.
"""

from __future__ import annotations

import collections
import os
import pwd
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Iterator

from . import system_sensors

HISTORY_SAMPLES = 300  # seconds of graph
REAL_FILESYSTEMS = {"ext2", "ext3", "ext4", "btrfs", "xfs", "f2fs", "vfat", "exfat", "ntfs", "ntfs3", "zfs", "bcachefs"}
PROTECTED = {"plasmashell", "kwin_wayland", "kwin_x11", "ksmserver", "systemd", "Xwayland", "startplasma-wayland",
             "plasma_session", "kded6", "dbus-daemon", "pipewire", "wireplumber"}
PROGRAMS_LISTED = 25


class StopError(RuntimeError):
    """The program was not stopped; the message says why."""


class History:
    """The last ``HISTORY_SAMPLES`` readings, fed once a second by the daemon's sensor sampler."""

    def __init__(self, size: int = HISTORY_SAMPLES) -> None:
        self._lock = threading.Lock()
        self._samples: collections.deque[dict[str, Any]] = collections.deque(maxlen=size)

    def add(self, readings: dict[str, Any]) -> None:
        sample = {key: readings.get(key) for key in ("cpu_percent", "cpu_c", "high_c", "available_memory_percent",
                                                     "receive_bytes_per_second", "send_bytes_per_second")}
        with self._lock:
            self._samples.append({"time": time.time(), **sample})

    def samples(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._samples)

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _number(path: Path) -> int | None:
    value = _text(path)
    return int(value) if re.fullmatch(r"-?\d+", value) else None


def _meminfo() -> dict[str, int]:
    values = {}
    for line in _text(Path("/proc/meminfo")).splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[key] = int(parts[0]) * 1024
    return values


def _cpu_model() -> str:
    for line in _text(Path("/proc/cpuinfo")).splitlines():
        if line.startswith("model name"):
            return line.partition(":")[2].strip()
    return ""


_gpu_names: dict[str, str] = {}


def _gpu_name(device: Path) -> str:
    slot = os.path.basename(os.path.realpath(device))
    if slot not in _gpu_names:
        name = ""
        if shutil.which("lspci"):
            try:
                out = subprocess.run(["lspci", "-mm", "-s", slot], capture_output=True, text=True, timeout=3).stdout
                fields = re.findall(r'"([^"]*)"', out)
                name = fields[2] if len(fields) > 2 else ""
            except (OSError, subprocess.TimeoutExpired):
                pass
        # "Strix Halo [Radeon Graphics / Radeon 8050S Graphics / Radeon 8060S Graphics]": the marketing name
        # is the last one in the brackets; the code name before them means little to people.
        marketed = re.search(r"\[([^\]]*)\]", name)
        _gpu_names[slot] = (marketed.group(1).split("/")[-1].strip() if marketed else name.strip()) or "Graphics"
    return _gpu_names[slot]


def _gpus(sys_root: Path = Path("/sys")) -> list[dict[str, Any]]:
    found = []
    for card in sorted((sys_root / "class/drm").glob("card[0-9]")):
        device = card / "device"
        busy = _number(device / "gpu_busy_percent")
        if busy is None:
            continue
        temperature = None
        for hwmon in (device / "hwmon").glob("hwmon*"):
            milli = _number(hwmon / "temp1_input")
            temperature = milli / 1000 if milli is not None else temperature
        found.append({"name": _gpu_name(device), "busy_percent": busy, "temp_c": temperature,
                      "memory_used": _number(device / "mem_info_vram_used"),
                      "memory_total": _number(device / "mem_info_vram_total"),
                      "shared_used": _number(device / "mem_info_gtt_used"),
                      "shared_total": _number(device / "mem_info_gtt_total")})
    if shutil.which("nvidia-smi"):
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,"
                                  "memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=3).stdout
        except (OSError, subprocess.TimeoutExpired):
            out = ""
        for line in out.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) == 5 and all(re.fullmatch(r"\d+(\.\d+)?", part) for part in parts[1:]):
                found.append({"name": parts[0], "busy_percent": float(parts[1]), "temp_c": float(parts[2]),
                              "memory_used": int(float(parts[3])) * 1024**2,
                              "memory_total": int(float(parts[4])) * 1024**2, "shared_used": None, "shared_total": None})
    return found


def _disks() -> list[dict[str, Any]]:
    disks, seen = [], set()
    for line in _text(Path("/proc/mounts")).splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[2] not in REAL_FILESYSTEMS or not parts[0].startswith("/dev/"):
            continue
        mount = parts[1].replace("\\040", " ")
        if parts[0] in seen or mount.startswith(("/snap", "/boot", "/efi", "/var/lib/docker")):
            continue
        try:
            usage = shutil.disk_usage(mount)
        except OSError:
            continue
        seen.add(parts[0])
        disks.append({"mount": mount, "device": parts[0], "total": usage.total, "used": usage.total - usage.free})
    return disks


def batteries(sys_root: Path = Path("/sys")) -> Iterator[dict[str, Any]]:
    """Present system batteries from sysfs; peripherals have their own charge indicator."""
    for supply in sorted((sys_root / "class/power_supply").glob("*")):
        if _text(supply / "type") != "Battery" or _text(supply / "scope") == "Device" or _number(supply / "present") == 0:
            continue
        percent = _number(supply / "capacity")
        if percent is not None and not 0 <= percent <= 100:
            percent = None
        status = _text(supply / "status")
        energy, power = _number(supply / "energy_now"), _number(supply / "power_now")
        full = _number(supply / "energy_full")
        hours = None
        if power and energy is not None:
            hours = (full - energy) / power if status == "Charging" and full else energy / power
        yield {"percent": percent, "status": status, "hours_left": round(hours, 1) if hours else None}


def _network() -> dict[str, Any]:
    interface = system_sensors.default_interface(_text(Path("/proc/net/route")) or None,
                                                 _text(Path("/proc/net/ipv6_route")) or None)
    return {"interface": interface or ""}


def overview(history: History) -> dict[str, Any]:
    """Everything the System info view shows at the top (see the module docstring)."""
    samples = history.samples()
    latest = samples[-1] if samples else {}
    memory = _meminfo()
    total, available = memory.get("MemTotal", 0), memory.get("MemAvailable", 0)
    load = _text(Path("/proc/loadavg")).split()[:3]
    uptime = _text(Path("/proc/uptime")).split()
    return {
        "cpu": {"model": _cpu_model(), "cores": os.cpu_count() or 0, "percent": latest.get("cpu_percent"),
                "temp_c": latest.get("cpu_c"), "high_c": latest.get("high_c"),
                "load": [float(value) for value in load] if len(load) == 3 else []},
        "memory": {"total": total, "used": total - available, "swap_total": memory.get("SwapTotal", 0),
                   "swap_used": memory.get("SwapTotal", 0) - memory.get("SwapFree", 0)},
        "gpus": _gpus(),
        "disks": _disks(),
        "network": {**_network(), "receive_bps": latest.get("receive_bytes_per_second"),
                    "send_bps": latest.get("send_bytes_per_second")},
        "battery": next((battery for battery in batteries() if battery["percent"] is not None), None),
        "uptime_seconds": float(uptime[0]) if uptime else None,
        "history": {
            "cpu": [sample["cpu_percent"] for sample in samples],
            "memory": [None if sample["available_memory_percent"] is None else 100 - sample["available_memory_percent"]
                       for sample in samples],
            "receive": [sample["receive_bytes_per_second"] for sample in samples],
            "send": [sample["send_bytes_per_second"] for sample in samples],
            "temp": [sample["cpu_c"] for sample in samples],
        },
    }


class Programs:
    """The busiest programs; remembers each one's CPU time from the previous look to work out its share."""

    def __init__(self, proc_root: Path = Path("/proc")) -> None:
        self.proc = proc_root
        self._lock = threading.Lock()
        self._previous: dict[int, int] = {}
        self._previous_time = 0.0
        self._ticks = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        self._page = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
        self._users: dict[int, str] = {}

    def _user(self, uid: int) -> str:
        if uid not in self._users:
            try:
                self._users[uid] = pwd.getpwuid(uid).pw_name
            except KeyError:
                self._users[uid] = str(uid)
        return self._users[uid]

    def _read(self) -> list[dict[str, Any]]:
        found = []
        for entry in self.proc.iterdir():
            if not entry.name.isdigit():
                continue
            stat = _text(entry / "stat")
            close = stat.rfind(")")
            if close < 0:
                continue
            fields = stat[close + 2:].split()
            if len(fields) < 22 or fields[0] == "Z":
                continue
            statm = _text(entry / "statm").split()
            uid = _owner(entry)
            if uid is None:
                continue
            cmdline = _text(entry / "cmdline").split("\0")[0]
            name = os.path.basename(cmdline) if cmdline and not cmdline.startswith("[") else stat[stat.find("(") + 1:close]
            found.append({"pid": int(entry.name), "name": name or stat[stat.find("(") + 1:close],
                          "cpu_ticks": int(fields[11]) + int(fields[12]),
                          "memory": int(statm[1]) * self._page if len(statm) > 1 else 0,
                          "uid": uid})
        return found

    def top(self, sort: str = "cpu", limit: int = PROGRAMS_LISTED) -> list[dict[str, Any]]:
        """The ``limit`` programs using the most CPU (``sort`` "cpu") or memory ("memory")."""
        now = time.monotonic()
        current = self._read()
        with self._lock:
            elapsed = now - self._previous_time
            cores = os.cpu_count() or 1
            fresh = 0 < elapsed < 30
            for item in current:
                before = self._previous.get(item["pid"])
                used = item["cpu_ticks"] - before if fresh and before is not None else 0
                item["cpu_percent"] = round(max(0, used) / self._ticks / elapsed / cores * 100, 1) if fresh else 0.0
            self._previous = {item["pid"]: item["cpu_ticks"] for item in current}
            self._previous_time = now
        mine = os.getuid()
        key = (lambda item: item["memory"]) if sort == "memory" else (lambda item: (item["cpu_percent"], item["memory"]))
        ranked = sorted(current, key=key, reverse=True)[:limit]
        return [{"pid": item["pid"], "name": item["name"], "cpu_percent": item["cpu_percent"], "memory": item["memory"],
                 "user": self._user(item["uid"]), "mine": item["uid"] == mine,
                 "protected": item["name"] in PROTECTED} for item in ranked]


def _owner(entry: Path) -> int | None:
    """The real user id of the process at ``entry`` (its status file's owner can be root for a program
    with extra capabilities, such as KWin)."""
    for line in _text(entry / "status").splitlines():
        if line.startswith("Uid:"):
            parts = line.split()
            return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    return None


def stop(pid: int, proc_root: Path = Path("/proc")) -> str:
    """Ask the user's own program ``pid`` to quit (see the module docstring); raises ``StopError``."""
    entry = proc_root / str(pid)
    uid = _owner(entry)
    if uid is None:
        raise StopError("That program is no longer running.")
    stat = _text(entry / "stat")
    name = stat[stat.find("(") + 1:stat.rfind(")")] if "(" in stat else str(pid)
    cmdline = _text(entry / "cmdline").split("\0")[0]
    shown = os.path.basename(cmdline) if cmdline else name
    if uid != os.getuid():
        raise StopError(f"{shown} belongs to another user ({uid}), so Happy Bot cannot stop it.")
    if pid == os.getpid() or name in PROTECTED or shown in PROTECTED:
        raise StopError(f"{shown} keeps the desktop or Happy Bot running, so it is not stopped from here.")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError as error:
        raise StopError(f"{shown} has already stopped.") from error
    except PermissionError as error:
        raise StopError(f"{shown} may not be stopped by you.") from error
    return f"Asked {shown} to quit."
