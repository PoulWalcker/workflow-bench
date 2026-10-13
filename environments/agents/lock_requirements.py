"""Print pip requirement lines pinning packages and their dependencies to uv.lock.

Arguments: the lock file, then the root package names.
"""

import sys
import tomllib
from pathlib import Path
from typing import Any

UNCONDITIONAL = ""


def lock_requirements(lock_text: str, roots: list[str]) -> list[str]:
    """Return ``name==version`` lines for the roots and their locked dependencies.

    A dependency reached only through marked edges keeps those edges' markers,
    so pip evaluates them for the image's interpreter. A package locked at
    several versions is ambiguous and raises ``SystemExit``.
    """
    packages: dict[str, list[dict[str, Any]]] = {}
    for package in tomllib.loads(lock_text)["package"]:
        packages.setdefault(package["name"], []).append(package)
    markers: dict[str, set[str]] = {name: {UNCONDITIONAL} for name in roots}
    pending = list(roots)
    while pending:
        name = pending.pop()
        if len(packages[name]) != 1:
            raise SystemExit(f"{name}: locked at several versions")
        for dependency in packages[name][0].get("dependencies", []):
            if dependency["name"] not in markers:
                pending.append(dependency["name"])
            markers.setdefault(dependency["name"], set()).add(
                dependency.get("marker", UNCONDITIONAL)
            )
    return [
        _requirement(name, packages[name][0]["version"], markers[name])
        for name in sorted(markers)
    ]


def _requirement(name: str, version: str, markers: set[str]) -> str:
    if UNCONDITIONAL in markers:
        return f"{name}=={version}"
    condition = " or ".join(f"({marker})" for marker in sorted(markers))
    return f"{name}=={version} ; {condition}"


if __name__ == "__main__":
    lines = lock_requirements(Path(sys.argv[1]).read_text(), sys.argv[2:])
    sys.stdout.write("".join(f"{line}\n" for line in lines))
