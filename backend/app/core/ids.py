from __future__ import annotations

import re
from datetime import datetime, timezone


def prefixed_id(prefix: str, counter: int) -> str:
    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{now}_{counter:03d}"


def parse_sequential_suffix(value: str, *, prefix: str) -> int | None:
    match = re.fullmatch(rf"{re.escape(prefix)}_(\d+)", value)
    if not match:
        return None
    return int(match.group(1))


def format_sequential_id(prefix: str, number: int, *, min_width: int = 3) -> str:
    width = max(min_width, len(str(number)))
    return f"{prefix}_{number:0{width}d}"


def next_sequential_id(existing_ids: list[str], *, prefix: str, min_start: int = 1) -> str:
    max_seen = min_start - 1
    for value in existing_ids:
        suffix = parse_sequential_suffix(value, prefix=prefix)
        if suffix is not None:
            max_seen = max(max_seen, suffix)
    return format_sequential_id(prefix, max_seen + 1)
