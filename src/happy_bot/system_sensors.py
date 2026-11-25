"""Live system readings for the mascot: one snapshot a second into ``IconActivity.observe_sensors``.

The mascot reacts to heat, sustained CPU load, memory pressure and network transfers
(``icon_activity``, which owns the thresholds, dwell and recovery times). This module only
measures: ``SystemReadings.snapshot`` reads the machine and returns every argument of
``observe_sensors`` at once, and ``SensorSampler`` calls it about once per ``SAMPLE_SECONDS`` on
its own thread, through quiet periods too, so active poses can clear. ``daemon_http.serve``
starts it with the daemon and stops it on shutdown. Everything is read from ``/proc`` and
``/sys`` with ordinary user permissions; nothing is written and nothing is kept on disk.

Readings (``None`` whenever one cannot be read, and for anything measured as a change until a
baseline exists):

- ``cpu_c``, ``high_c``: a CPU temperature and the high threshold of that same sensor, in °C.
  The sensor is discovered once (``find_cpu_temperature``), looked for again every
  ``REDISCOVER_SECONDS`` while none works: hwmon channels of CPU drivers (``CPU_DRIVERS``) or
  labelled as the CPU (Tctl, Tdie, "Package id", cpu...), preferring one that carries its own
  ``_max`` (else ``_crit``) threshold; then thermal zones whose type names the CPU, with their
  "hot", else "passive", else "critical" trip point. A reading is never paired with another
  sensor's threshold: a CPU sensor without one gives ``high_c`` None.
- ``cpu_percent``: busy share of all cores between two ``/proc/stat`` samples (idle and iowait
  count as idle), 0 to 100.
- ``available_memory_percent``: 100 × MemAvailable / MemTotal from ``/proc/meminfo``.
- ``memory_pressure``: Linux pressure stall information, ``/proc/pressure/memory``. Its ``some
  avg10`` is the share of the last 10 seconds in which at least one task waited for memory;
  True when that is at least ``PRESSURE_STALL_PERCENT``, False below, None when the kernel
  does not offer PSI (file missing or switched off) or the line cannot be parsed.
- ``receive_bytes_per_second``, ``send_bytes_per_second``: the byte counters of the interface
  carrying the default route (IPv4 ``/proc/net/route``, else IPv6 ``/proc/net/ipv6_route``,
  lowest metric), divided by the actually elapsed time. The baseline restarts (rates None for
  that tick) when the interface changes, a counter goes backwards (reset or wrap), there is no
  default route, or the computer was suspended between samples, seen as ``CLOCK_BOOTTIME``
  running ahead of ``CLOCK_MONOTONIC`` (which stops during suspend) by ``RESUME_GAP_SECONDS``.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

SAMPLE_SECONDS = 1.0
PRESSURE_STALL_PERCENT = 10.0
RESUME_GAP_SECONDS = 1.0
REDISCOVER_SECONDS = 60.0
CPU_DRIVERS = ("k10temp", "zenpower", "coretemp", "cpu_thermal", "cpu-thermal", "soc_thermal")
_CPU_LABEL = re.compile(r"^(tctl|tdie|package id \d+|cpu)", re.IGNORECASE)
_CPU_ZONE = re.compile(r"^(x86_pkg_temp|cpu)", re.IGNORECASE)
_TRIP_ORDER = ("hot", "passive", "critical")


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _milli(path: Path | None) -> float | None:
    text = _read(path) if path else None
    try:
        return int(text) / 1000 if text is not None else None
    except ValueError:
        return None


@dataclass(frozen=True)
class TemperatureSource:
    """Where one CPU temperature and its own threshold are read (millidegrees)."""
    reading: Path
    threshold: Path | None
    name: str


def find_cpu_temperature(sys_root: Path = Path("/sys")) -> TemperatureSource | None:
    """The CPU temperature sensor to use (see the module docstring), or None when there is none."""
    found: list[tuple[int, TemperatureSource]] = []
    hwmon = sys_root / "class" / "hwmon"
    for device in sorted(hwmon.glob("hwmon*"), key=lambda path: int(re.sub(r"\D", "", path.name) or 0)):
        driver = _read(device / "name") or ""
        for reading in sorted(device.glob("temp*_input"), key=lambda path: int(re.sub(r"\D", "", path.name) or 0)):
            prefix = reading.name[: -len("_input")]
            label = _read(device / f"{prefix}_label") or ""
            by_driver = driver in CPU_DRIVERS
            if not by_driver and not _CPU_LABEL.match(label):
                continue
            threshold = next((device / f"{prefix}_{kind}" for kind in ("max", "crit")
                              if (device / f"{prefix}_{kind}").exists()), None)
            rank = (0 if threshold else 2) + (0 if by_driver else 1)
            found.append((rank, TemperatureSource(reading, threshold, f"{driver} {label}".strip())))
    for zone in sorted((sys_root / "class" / "thermal").glob("thermal_zone*")):
        kind = _read(zone / "type") or ""
        if not _CPU_ZONE.match(kind):
            continue
        trips = {(_read(trip) or ""): trip.with_name(trip.name.replace("_type", "_temp"))
                 for trip in zone.glob("trip_point_*_type")}
        threshold = next((trips[name] for name in _TRIP_ORDER if name in trips), None)
        found.append((4 if threshold else 5, TemperatureSource(zone / "temp", threshold, kind)))
    return min(found, key=lambda item: item[0])[1] if found else None


def cpu_times(stat_text: str) -> tuple[int, int] | None:
    """``(idle, total)`` jiffies of all cores from ``/proc/stat`` text."""
    for line in stat_text.splitlines():
        fields = line.split()
        if fields and fields[0] == "cpu" and len(fields) >= 5:
            try:
                values = [int(value) for value in fields[1:9]]
            except ValueError:
                return None
            return values[3] + (values[4] if len(values) > 4 else 0), sum(values)
    return None


def available_memory_percent(meminfo_text: str) -> float | None:
    fields = dict(re.findall(r"^(MemTotal|MemAvailable):\s+(\d+)", meminfo_text, re.MULTILINE))
    try:
        total, available = int(fields["MemTotal"]), int(fields["MemAvailable"])
    except (KeyError, ValueError):
        return None
    return 100 * available / total if total > 0 else None


def memory_pressure(psi_text: str | None) -> bool | None:
    """True when ``some avg10`` ≥ ``PRESSURE_STALL_PERCENT`` (see the module docstring)."""
    match = re.search(r"^some\s.*\bavg10=([\d.]+)", psi_text or "", re.MULTILINE)
    return float(match.group(1)) >= PRESSURE_STALL_PERCENT if match else None


def default_interface(route_text: str | None, ipv6_route_text: str | None) -> str | None:
    """The interface of the lowest-metric default route, IPv4 first, else IPv6."""
    best: tuple[int, str] | None = None
    for line in (route_text or "").splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 7 and fields[1] == "00000000" and fields[0] != "lo":
            try:
                up, metric = int(fields[3], 16) & 1, int(fields[6])
            except ValueError:
                continue
            if up and (best is None or metric < best[0]):
                best = (metric, fields[0])
    if best:
        return best[1]
    for line in (ipv6_route_text or "").splitlines():
        fields = line.split()
        if len(fields) >= 10 and fields[0] == "0" * 32 and fields[1] == "00" and fields[9] != "lo":
            try:
                metric = int(fields[5], 16)
            except ValueError:
                continue
            if best is None or metric < best[0]:
                best = (metric, fields[9])
    return best[1] if best else None


def _boottime() -> float:
    return time.clock_gettime(time.CLOCK_BOOTTIME)


class SystemReadings:
    """Reads the machine; keeps only the previous counters it needs for rates."""

    def __init__(self, proc_root: Path = Path("/proc"), sys_root: Path = Path("/sys"),
                 monotonic: Callable[[], float] = time.monotonic, boottime: Callable[[], float] = _boottime) -> None:
        self.proc, self.sys = proc_root, sys_root
        self._monotonic, self._boottime = monotonic, boottime
        self._temperature: TemperatureSource | None = None
        self._looked_for_temperature: float | None = None
        self._cpu: tuple[int, int] | None = None
        self._traffic: tuple[str, int, int, float, float] | None = None  # interface, rx, tx, monotonic, boottime

    def _temperatures(self, now: float) -> tuple[float | None, float | None]:
        if self._temperature is None and (self._looked_for_temperature is None
                                          or now - self._looked_for_temperature >= REDISCOVER_SECONDS):
            self._looked_for_temperature = now
            self._temperature = find_cpu_temperature(self.sys)
        if self._temperature is None:
            return None, None
        reading = _milli(self._temperature.reading)
        if reading is None:
            self._temperature = None  # gone (a module unloaded): look again later
            return None, None
        return reading, _milli(self._temperature.threshold)

    def _cpu_percent(self) -> float | None:
        times = cpu_times(_read(self.proc / "stat") or "")
        previous, self._cpu = self._cpu, times
        if times is None or previous is None or times[1] <= previous[1]:
            return None
        idle, total = times[0] - previous[0], times[1] - previous[1]
        return max(0.0, min(100.0, 100 * (total - idle) / total))

    def _rates(self) -> tuple[float | None, float | None]:
        interface = default_interface(_read(self.proc / "net" / "route"), _read(self.proc / "net" / "ipv6_route"))
        statistics = self.sys / "class" / "net" / (interface or "-") / "statistics"
        received, sent = _read(statistics / "rx_bytes"), _read(statistics / "tx_bytes")
        mono, boot = self._monotonic(), self._boottime()
        try:
            current = (str(interface), int(received or ""), int(sent or ""), mono, boot) if interface else None
        except ValueError:
            current = None
        previous, self._traffic = self._traffic, current
        if current is None or previous is None or current[0] != previous[0]:
            return None, None
        elapsed = mono - previous[3]
        suspended = (boot - previous[4]) - elapsed >= RESUME_GAP_SECONDS
        if elapsed <= 0 or suspended or current[1] < previous[1] or current[2] < previous[2]:
            return None, None
        return (current[1] - previous[1]) / elapsed, (current[2] - previous[2]) / elapsed

    def snapshot(self) -> dict[str, Any]:
        """Every argument of ``IconActivity.observe_sensors`` for this moment."""
        cpu_c, high_c = self._temperatures(self._monotonic())
        receive, send = self._rates()
        return {
            "cpu_c": cpu_c, "high_c": high_c,
            "cpu_percent": self._cpu_percent(),
            "available_memory_percent": available_memory_percent(_read(self.proc / "meminfo") or ""),
            "memory_pressure": memory_pressure(_read(self.proc / "pressure" / "memory")),
            "receive_bytes_per_second": receive, "send_bytes_per_second": send,
        }


class SensorSampler:
    """Feeds one snapshot per tick to ``observe`` (``IconActivity.observe_sensors``) on its own thread."""

    def __init__(self, observe: Callable[..., None], readings: SystemReadings | None = None,
                 interval: float = SAMPLE_SECONDS) -> None:
        self._observe, self._interval = observe, interval
        self._readings = readings or SystemReadings()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="sensor-sampler", daemon=True)
            self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def _run(self) -> None:
        next_tick = time.monotonic()
        while not self._stop.is_set():
            try:
                self._observe(**self._readings.snapshot())
            except Exception:  # noqa: BLE001 - one bad reading must not end the mascot's sensors
                pass
            next_tick += self._interval
            delay = next_tick - time.monotonic()
            if delay < 0:  # fell behind (the computer slept): start the rhythm again from now
                next_tick, delay = time.monotonic(), 0
            self._stop.wait(delay)
