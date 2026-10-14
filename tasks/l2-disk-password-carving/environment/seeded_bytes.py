"""Emit stable pseudorandom task input bytes for a named build input."""

import hashlib
import sys


def main() -> None:
    """Write deterministic bytes selected by label and length to stdout."""
    if len(sys.argv) != 3:
        raise SystemExit("usage: seeded_bytes.py LABEL SIZE")
    label = sys.argv[1].encode("utf-8")
    size = int(sys.argv[2])
    if size < 0 or size > 4194304:
        raise SystemExit("invalid size")
    sys.stdout.buffer.write(
        hashlib.shake_256(b"wb-m3-password-recovery\0" + label).digest(size)
    )


if __name__ == "__main__":
    main()
