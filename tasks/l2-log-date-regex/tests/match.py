"""Apply one candidate pattern to the private sample log in a bounded process."""

import json
import re
import sys
from pathlib import Path

EXPECTED = Path("/tests/expected")


def main() -> None:
    """Print only whether all matches equal the authored expected dates."""
    pattern = sys.stdin.read()
    sample_log = (EXPECTED / "sample_log.txt").read_text()
    expected_dates = json.loads((EXPECTED / "dates.json").read_text())
    matches = re.findall(pattern, sample_log, re.MULTILINE)
    sys.stdout.write("pass\n" if matches == expected_dates else "mismatch\n")


if __name__ == "__main__":
    main()
