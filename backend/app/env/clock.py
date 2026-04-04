from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StepClock:
    start_ts_ms: int
    step_ms: int = 120

    def ts(self, step: int, offset_ms: int = 0) -> int:
        return self.start_ts_ms + (step * self.step_ms) + offset_ms
