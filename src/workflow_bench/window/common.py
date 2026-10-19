"""Limits and filesystem/value checks shared by observation-window modules."""

import math
import sys
from datetime import datetime
from pathlib import Path

SCHEMA_VERSION = 1
MAX_SCHEDULE_BYTES = 64 * 1024
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
MAX_ENTRIES = 4096
MAX_SAMPLES = 128
MAX_SKIPPED = 1024
MAX_ACTIONS = 128
MAX_WATCH = 32
MAX_PATH_LENGTH = 256
MAX_DURATION_SEC = 3600
MAX_TAIL_SEC = 600
CHUNK_BYTES = 64 * 1024


def _nonnegative_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0 <= value <= sys.float_info.max
        and math.isfinite(value)
    )


def _absolute_path(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= MAX_PATH_LENGTH
        and value.startswith("/")
        and ".." not in Path(value).parts
        and "\x00" not in value
    )


def _has_symlink_component(path: Path) -> bool:
    """Reject links in the path itself or any existing parent."""
    return any(part.is_symlink() for part in (path, *path.parents))


def _relative_path(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and bool(Path(value).parts)
        and not Path(value).is_absolute()
        and ".." not in Path(value).parts
    )


def _optional_str(value: object) -> bool:
    return value is None or isinstance(value, str)


def _utc_time(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    try:
        observed = datetime.fromisoformat(value)
    except ValueError:
        return False
    offset = observed.utcoffset()
    return offset is not None and offset.total_seconds() == 0


def _digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )
