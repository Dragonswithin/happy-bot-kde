"""Current mascot cues, shared by the floating app and the Plasma widget.

The recorder publishes capture transitions. A sensor sampler can call
observe_sensors with CPU temperature and load, available memory and pressure,
and the active connection's receive/transmit rates. A slower local sampler reports
battery, disk, restart and update conditions. Dismissal applies to both views
until that condition clears. Unknown readings hide the cue without rearming it.
Both views long-poll the latest snapshot. Nothing is stored on disk.
"""

from __future__ import annotations

import math
import threading
import time

NUDGE_KINDS = ("battery", "disk", "restart", "updates")


class _Sustained:
    """A cue with distinct entry and recovery thresholds and dwell times."""

    def __init__(self, enter_seconds: float, clear_seconds: float) -> None:
        self.enter_seconds = enter_seconds
        self.clear_seconds = clear_seconds
        self.active = False
        self.since: float | None = None

    def observe(self, value: float | None, high: float, low: float, now: float) -> bool:
        if value is None or not math.isfinite(value):
            self.active = False
            self.since = None
        elif (value <= low if self.active else value >= high):
            if self.since is None:
                self.since = now
            elif now - self.since >= (self.clear_seconds if self.active else self.enter_seconds):
                self.active = not self.active
                self.since = None
        else:
            self.since = None
        return self.active


class IconActivity:
    def __init__(self) -> None:
        self._changed = threading.Condition()
        self._revision = time.monotonic_ns()
        self._state = dict(recording=False, hot=False, busy=False, low_memory=False, downloading=False, uploading=False,
                           nudges=[])
        self._dismissed_nudges: set[str] = set()
        self._hot = _Sustained(10, 20)
        self._busy = _Sustained(10, 8)
        self._memory = _Sustained(15, 20)
        self._down = _Sustained(3, 5)
        self._up = _Sustained(3, 5)

    def _update(self, **fields: bool | list[str]) -> None:
        if any(self._state[key] != value for key, value in fields.items()):
            self._state.update(fields)
            self._revision += 1
            self._changed.notify_all()

    def set_recording(self, active: bool) -> None:
        with self._changed:
            self._update(recording=active)

    def observe_nudges(self, **conditions: bool | None) -> None:
        """Publish a snapshot in display order. Only a known recovery ends dismissal."""
        with self._changed:
            for kind in NUDGE_KINDS:
                if conditions.get(kind) is False:
                    self._dismissed_nudges.discard(kind)
            self._update(nudges=[kind for kind in NUDGE_KINDS
                                 if conditions.get(kind) is True and kind not in self._dismissed_nudges])

    def dismiss_nudge(self, kind: str) -> bool:
        """Hide an active condition for everyone; repeating a supported dismissal succeeds."""
        if kind not in NUDGE_KINDS:
            return False
        with self._changed:
            active = self._state["nudges"]
            if kind in active:
                self._dismissed_nudges.add(kind)
                self._update(nudges=[item for item in active if item != kind])
            return True

    def observe_sensors(self, *, cpu_c: float | None, high_c: float | None,
                        receive_bytes_per_second: float | None, send_bytes_per_second: float | None,
                        cpu_percent: float | None = None, available_memory_percent: float | None = None,
                        memory_pressure: bool | None = None, threshold_bytes_per_second: float = 256 * 1024) -> None:
        """Rates are bytes/second. high_c is the sensor's or user's limit."""
        with self._changed:
            now = time.monotonic()
            if high_c is None or not math.isfinite(high_c):
                cpu_c, high_c = None, 0
            low_rate = threshold_bytes_per_second / 4
            used_percent = None
            if available_memory_percent is not None and memory_pressure is not None:
                used_percent = 100 - available_memory_percent if memory_pressure else 0
            self._update(
                busy=self._busy.observe(cpu_percent, 85, 65, now),
                low_memory=self._memory.observe(used_percent, 90, 85, now),
                hot=self._hot.observe(cpu_c, high_c, high_c - 5, now),
                downloading=self._down.observe(receive_bytes_per_second, threshold_bytes_per_second, low_rate, now),
                uploading=self._up.observe(send_bytes_per_second, threshold_bytes_per_second, low_rate, now),
            )

    def wait(self, seen: str, timeout: float = 25) -> dict:
        with self._changed:
            self._changed.wait_for(lambda: str(self._revision) != seen, timeout)
            return {"revision": str(self._revision), **self._state}
