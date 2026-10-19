"""Bounded copying and fingerprints of concurrently changing task paths."""

import errno
import hashlib
import itertools
import json
import os
import shutil
import stat
from contextlib import nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from workflow_bench.window.common import (
    CHUNK_BYTES,
    MAX_ENTRIES,
    MAX_EVIDENCE_BYTES,
    MAX_PATH_LENGTH,
    MAX_SKIPPED,
    _has_symlink_component,
)
from workflow_bench.window.evidence import Skipped


@dataclass
class _CopyBudget:
    """Count stored bytes/entries, or observed bytes/visits in an action."""

    bytes: int = 0
    entries: int = 0


@dataclass(frozen=True)
class _CopyResult:
    """Copied file count/bytes and observed identity, independent of storage limits.

    A missing digest means an incomplete or non-content observation; truncation
    also covers a complete observation whose stored copy could not fit.
    """

    entries: int = 0
    bytes: int = 0
    truncated: bool = False
    kind: str = "missing"
    sha256: str | None = None
    file_type: int = 0


class BoundedCopy:
    """Bound retained bytes/entries and each action's independent traversal.

    Missing or replaced entries are omitted; fingerprints describe the read view.
    Aggregate storage is charged only for retained copies, never unchanged paths.
    """

    def __init__(self) -> None:
        self.storage = _CopyBudget()
        self.observed = _CopyBudget()
        self.skipped: tuple[Skipped, ...] = ()
        self.skipped_truncated = False

    def reset_observation(self) -> None:
        """Start an independent bounded snapshot or sampling pass."""
        self.observed = _CopyBudget()

    def copy_changed(
        self, source: Path, destination: Path, previous: tuple[str, str] | None
    ) -> _CopyResult:
        """Observe first; store only new identities without reserving unchanged bytes.

        A changed path is read again for its stored copy. Its returned fingerprint
        describes that second read, which may differ from the initial observation.
        Both reads consume the same per-sample traversal and byte budget.
        """
        if previous is not None:
            skipped_before, truncated_before = self.skipped, self.skipped_truncated
            probe = self.copy_path(source, None)
            if (probe.kind, probe.sha256) == previous:
                return replace(probe, truncated=False)
            self.skipped, self.skipped_truncated = skipped_before, truncated_before
        return self.copy_path(source, destination)

    def copy_path(self, source: Path, destination: Path | None) -> _CopyResult:
        """Copy and fingerprint an entry, retaining only bytes actually read.

        Entries lost or replaced before reading are recorded as missing. An open
        regular file remains a valid observation even if its name is replaced.
        """
        if self.observed.entries >= MAX_ENTRIES:
            return _CopyResult(truncated=True, kind="truncated")
        self.observed.entries += 1
        entries_before, bytes_before = self.storage.entries, self.storage.bytes
        try:
            return self._copy_path(source, destination)
        except OSError as error:
            if error.errno not in (
                errno.ENOENT,
                errno.ENOTDIR,
                errno.EISDIR,
                errno.ELOOP,
                errno.ENXIO,
                errno.ENODEV,
            ):
                raise
            if destination is not None:
                _remove_copy(destination)
            self.storage.entries, self.storage.bytes = entries_before, bytes_before
            return _CopyResult()

    def _copy_path(self, source: Path, destination: Path | None) -> _CopyResult:
        if _has_symlink_component(source):
            self._record_skip(source, "symlink")
            return _CopyResult(kind="symlink", file_type=stat.S_IFLNK)
        try:
            mode = source.lstat().st_mode
        except FileNotFoundError:
            return _CopyResult()
        if not stat.S_ISREG(mode) and not stat.S_ISDIR(mode):
            self._record_skip(source, "special")
            return _CopyResult(kind="special", file_type=stat.S_IFMT(mode))
        if self.storage.entries >= MAX_ENTRIES:
            destination = None
        if stat.S_ISREG(mode):
            return self._copy_file(source, destination)
        return self._copy_directory(source, destination)

    def _copy_file(self, source: Path, destination: Path | None) -> _CopyResult:
        if self.storage.bytes >= MAX_EVIDENCE_BYTES:
            destination = None
        if destination is not None:
            self.storage.entries += 1
            destination.parent.mkdir(parents=True, exist_ok=True)
        remaining = MAX_EVIDENCE_BYTES - self.observed.bytes
        observed = 0
        written = 0
        digest = hashlib.sha256()
        with (
            os.fdopen(
                os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb"
            ) as input_stream,
            destination.open("wb")
            if destination is not None
            else nullcontext() as output,
        ):
            if not stat.S_ISREG(os.fstat(input_stream.fileno()).st_mode):
                raise IsADirectoryError(errno.EISDIR, "entry changed type")
            while observed < remaining:
                chunk = input_stream.read(min(CHUNK_BYTES, remaining - observed))
                if not chunk:
                    break
                digest.update(chunk)
                observed += len(chunk)
                if output is not None:
                    stored = chunk[: MAX_EVIDENCE_BYTES - self.storage.bytes]
                    output.write(stored)
                    written += len(stored)
                    self.storage.bytes += len(stored)
            incomplete = bool(input_stream.read(1))
        self.observed.bytes += observed
        return _CopyResult(
            int(destination is not None),
            written,
            incomplete or destination is None or written < observed,
            "regular",
            None if incomplete else digest.hexdigest(),
            stat.S_IFREG,
        )

    def _copy_directory(self, source: Path, destination: Path | None) -> _CopyResult:
        if destination is not None:
            self.storage.entries += 1
            destination.mkdir(parents=True, exist_ok=True)
        count = 0
        byte_count = 0
        truncated = destination is None
        incomplete = False
        fingerprints: list[tuple[str, int, str]] = []
        remaining = MAX_ENTRIES - self.observed.entries
        children = list(itertools.islice(source.iterdir(), remaining + 1))
        if len(children) > remaining:
            incomplete = True
            children.pop()
        for child in sorted(children):
            if (
                self.observed.entries >= MAX_ENTRIES
                or self.observed.bytes >= MAX_EVIDENCE_BYTES
            ):
                incomplete = True
                break
            copied = self.copy_path(
                child, destination / child.name if destination is not None else None
            )
            count += copied.entries
            byte_count += copied.bytes
            truncated |= copied.truncated
            incomplete |= copied.kind == "truncated" or (
                copied.kind in ("regular", "directory") and copied.sha256 is None
            )
            if copied.kind != "missing":
                fingerprints.append(
                    (child.name, copied.file_type, copied.sha256 or copied.kind)
                )
        digest = hashlib.sha256(json.dumps(fingerprints).encode()).hexdigest()
        return _CopyResult(
            count,
            byte_count,
            truncated or incomplete,
            "directory",
            None if incomplete else digest,
            stat.S_IFDIR,
        )

    def _record_skip(self, path: Path, kind: Literal["symlink", "special"]) -> None:
        """Keep bounded metadata for entries intentionally left uncopied."""
        skipped = self.skipped
        if len(skipped) >= MAX_SKIPPED or len(str(path)) > MAX_PATH_LENGTH:
            self.skipped_truncated = True
            return
        self.skipped = (*skipped, Skipped(str(path), kind))


def _remove_copy(path: Path) -> None:
    """Discard an interrupted entry without following a planted link."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
