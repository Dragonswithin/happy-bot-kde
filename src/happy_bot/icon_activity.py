"""Current mascot cues, shared by the floating app and the Plasma widget.

The recorder publishes capture transitions. A sensor sampler can call
observe_sensors once per sample with the CPU temperature and the active
connection's receive/transmit rates. Unknown readings clear their own cue.
Both views long-poll the latest snapshot. Nothing is stored on disk.
"""

from __future__ import annotations

import math
import threading
import time


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
        self._state = dict(recording=False, hot=False, downloading=False, uploading=False)
        self._hot = _Sustained(10, 20)
        self._down = _Sustained(3, 5)
        self._up = _Sustained(3, 5)

    def _update(self, **fields: bool) -> None:
        if any(self._state[key] != value for key, value in fields.items()):
            self._state.update(fields)
            self._revision += 1
            self._changed.notify_all()

    def set_recording(self, active: bool) -> None:
        with self._changed:
            self._update(recording=active)

    def observe_sensors(self, *, cpu_c: float | None, high_c: float | None,
                        receive_bytes_per_second: float | None, send_bytes_per_second: float | None,
                        threshold_bytes_per_second: float = 256 * 1024) -> None:
        """Rates are bytes/second. high_c is the sensor's or user's limit."""
        with self._changed:
            now = time.monotonic()
            if high_c is None or not math.isfinite(high_c):
                cpu_c, high_c = None, 0
            low_rate = threshold_bytes_per_second / 4
            self._update(
                hot=self._hot.observe(cpu_c, high_c, high_c - 5, now),
                downloading=self._down.observe(receive_bytes_per_second, threshold_bytes_per_second, low_rate, now),
                uploading=self._up.observe(send_bytes_per_second, threshold_bytes_per_second, low_rate, now),
            )

    def wait(self, seen: str, timeout: float = 25) -> dict:
        with self._changed:
            self._changed.wait_for(lambda: str(self._revision) != seen, timeout)
            return {"revision": str(self._revision), **self._state}
