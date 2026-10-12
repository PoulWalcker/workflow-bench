"""Offline validation of sanitized Blindly fixture data; no desktop access."""

import argparse
import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def structure(value: Any, field: str = "") -> Any:
    """Commit hierarchy/types/empty text, excluding personal text and screen origin."""
    if isinstance(value, dict):
        return {key: structure(item, key) for key, item in value.items()}
    if isinstance(value, list):
        return [structure(item, field) for item in value]
    if field in {"description", "title", "value", "identifier"}:
        if isinstance(value, str) and value:
            return "<text>"
    if field in {"pid", "x", "y"}:
        return {"type": type(value).__name__, "field": field}
    return value


def strings(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)
    elif isinstance(value, str):
        yield value


def environment_is_safe(value: Any) -> bool:
    if isinstance(value, dict):
        if "pid" in value and (type(value["pid"]) is not int or value["pid"] != 0):
            return False
        if "identifier" in value and value["identifier"] != "fixture-redacted-id":
            return False
        return all(environment_is_safe(item) for item in value.values())
    if isinstance(value, list):
        return all(environment_is_safe(item) for item in value)
    return True


def layout_matches(
    original: Any, sanitized: Any, translation: dict[str, int], field: str = ""
) -> bool:
    if isinstance(original, dict):
        return all(
            layout_matches(item, sanitized[key], translation, key)
            for key, item in original.items()
        )
    if isinstance(original, list):
        return all(
            layout_matches(item, sanitized[index], translation, field)
            for index, item in enumerate(original)
        )
    if field in {"x", "y"}:
        return sanitized == original + translation.get(field, 0)
    return True


def read_json(root: Path, relative: str) -> Any:
    path = root / relative
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(root):
        raise ValueError("unsafe_reference")
    if path.is_symlink() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("unsafe_reference")
    return json.loads(path.read_text(encoding="utf-8"))


def select(value: Any, pointer: str) -> Any:
    if pointer and not pointer.startswith("/"):
        raise ValueError("invalid_manifest")
    for part in pointer.split("/")[1:]:
        key = part.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def check_package(root: Path, source_root: Path | None = None) -> dict[str, Any]:
    """Check trusted manifest commitments; optional originals never leave memory.

    The manifest is the reviewed baseline, not an adversarial signing authority.
    Structure retains dictionary keys, list order, roles, types, empty strings,
    flags, attributes and actions. Text and environment fields are masked only in
    structural commitments; exact sanitized digests protect their fixture values.
    """
    manifest = read_json(root, "manifest.json")
    if manifest["schema_version"] != 1 or not 0 < len(manifest["files"]) <= 64:
        raise ValueError("invalid_manifest")
    safe_strings = set(manifest["safe_strings"])
    compared = 0
    assets = {}
    for entry in manifest["files"]:
        data = read_json(root, entry["file"])
        assets[entry["id"]] = data
        if any(text and text not in safe_strings for text in strings(data)):
            return {"status": "fail", "code": "privacy_value"}
        if not environment_is_safe(data):
            return {"status": "fail", "code": "privacy_environment"}
        if digest(structure(data)) != entry["structure_sha256"]:
            return {"status": "fail", "code": "structural_drift"}
        if digest(data) != entry["sha256"]:
            return {"status": "fail", "code": "fixture_drift"}
        if source_root is not None:
            source = entry["source"]
            original = select(read_json(source_root, source["file"]), source["pointer"])
            if digest(structure(original)) != entry["structure_sha256"]:
                return {"status": "fail", "code": "source_drift"}
            translation = manifest.get("environment", {}).get(
                "coordinate_translation", {}
            )
            if not layout_matches(original, data, translation):
                return {"status": "fail", "code": "layout_drift"}
            compared += 1
    for template in manifest.get("templates", []):
        fragment = assets[template["id"]]
        if fragment != select(assets[template["tree"]], template["pointer"]):
            return {"status": "fail", "code": "fragment_drift"}
        for slot in template.get("slots", []):
            if select(fragment, slot["pointer"]) != slot["example"]:
                return {"status": "fail", "code": "substitution_drift"}
    return {
        "status": "pass",
        "files": len(manifest["files"]),
        "source_compared": compared,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=Path(__file__).parent)
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    try:
        report = check_package(
            args.fixtures.resolve(),
            args.source_root.resolve() if args.source_root else None,
        )
    except (OSError, ValueError, KeyError, TypeError, IndexError, RecursionError):
        # File/JSON failures can include private values or machine paths.
        report = {"status": "fail", "code": "invalid_input"}
    print(json.dumps(report))
    raise SystemExit(0 if report["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
