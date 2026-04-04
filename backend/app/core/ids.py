from __future__ import annotations

from datetime import datetime, timezone


def prefixed_id(prefix: str, counter: int) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{now}_{counter:03d}"
