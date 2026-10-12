"""Exercise the offline fixture checker, without accessing private research."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

CHECKER = Path(__file__).resolve().parents[2] / "simapps/simsapp/fixtures/check.py"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def package(tmp_path):
    original = {"role": "AXGroup", "children": [{"role": "AXButton"}]}
    (tmp_path / "tree.json").write_text(json.dumps(original))
    manifest = {
        "schema_version": 1,
        "safe_strings": ["AXGroup", "AXButton", "AXStaticText"],
        "files": [
            {
                "id": "tree",
                "file": "tree.json",
                "structure_sha256": digest(original),
                "sha256": digest(original),
            }
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return original, manifest


def check(root, *arguments):
    result = subprocess.run(
        [sys.executable, str(CHECKER), "--fixtures", str(root), *arguments],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return result.returncode, json.loads(result.stdout)


def test_checker_rejects_changed_hierarchy_role(tmp_path):
    original, _ = package(tmp_path)
    original["children"][0]["role"] = "AXStaticText"
    (tmp_path / "tree.json").write_text(json.dumps(original))
    status, report = check(tmp_path)
    assert status == 1 and report == {"status": "fail", "code": "structural_drift"}


def test_checker_rejects_undeclared_text_without_echoing_it(tmp_path):
    original, manifest = package(tmp_path)
    original["children"][0]["description"] = (
        "Someone Private at private@example.invalid"
    )
    # Text is deliberately replaceable; shape is committed independently of content.
    masked = {
        "role": "AXGroup",
        "children": [{"role": "AXButton", "description": "<text>"}],
    }
    manifest["files"][0]["structure_sha256"] = digest(masked)
    manifest["files"][0]["sha256"] = digest(original)
    (tmp_path / "tree.json").write_text(json.dumps(original))
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    status, report = check(tmp_path)
    assert status == 1 and report == {"status": "fail", "code": "privacy_value"}


def test_checker_compares_selected_original_and_preserves_actions(tmp_path):
    root = tmp_path / "fixtures"
    source = tmp_path / "private"
    root.mkdir()
    source.mkdir()
    original, manifest = package(root)
    (source / "selected.json").write_text(json.dumps(original))
    manifest["files"][0]["source"] = {"file": "selected.json", "pointer": ""}
    (root / "manifest.json").write_text(json.dumps(manifest))
    status, report = check(root, "--source-root", str(source))
    assert status == 0 and report["source_compared"] == 1
    # A source drift must be detected even though committed fixtures remain unchanged.
    original["children"][0]["actions"] = ["AXPress"]
    (source / "selected.json").write_text(json.dumps(original))
    status, report = check(root, "--source-root", str(source))
    assert status == 1 and report == {"status": "fail", "code": "source_drift"}


def test_checker_rejects_process_identity_even_when_text_is_approved(tmp_path):
    original, manifest = package(tmp_path)
    original["children"][0]["pid"] = 987654
    masked = {
        "role": "AXGroup",
        "children": [{"role": "AXButton", "pid": {"type": "int", "field": "pid"}}],
    }
    manifest["files"][0]["structure_sha256"] = digest(masked)
    manifest["files"][0]["sha256"] = digest(original)
    (tmp_path / "tree.json").write_text(json.dumps(original))
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    status, report = check(tmp_path)
    assert status == 1 and report == {"status": "fail", "code": "privacy_environment"}


def test_checker_rejects_fragment_that_disagrees_with_parent_tree(tmp_path):
    original, manifest = package(tmp_path)
    fragment = {"role": "AXStaticText"}
    (tmp_path / "fragment.json").write_text(json.dumps(fragment))
    manifest["files"].append(
        {
            "id": "fragment",
            "file": "fragment.json",
            "structure_sha256": digest(fragment),
            "sha256": digest(fragment),
        }
    )
    manifest["templates"] = [
        {"id": "fragment", "tree": "tree", "pointer": "/children/0", "slots": []}
    ]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    status, report = check(tmp_path)
    assert status == 1 and report == {"status": "fail", "code": "fragment_drift"}


def test_original_comparison_rejects_layout_change_beyond_translation(tmp_path):
    root = tmp_path / "fixtures"
    source = tmp_path / "private"
    root.mkdir()
    source.mkdir()
    original, manifest = package(root)
    original["children"][0]["position"] = {"x": 10, "y": 20}
    (source / "selected.json").write_text(json.dumps(original))
    # Expected x=110, y=81; the rewritten x incorrectly stretches the layout.
    sanitized = {
        "role": "AXGroup",
        "children": [{"role": "AXButton", "position": {"x": 500, "y": 81}}],
    }
    masked = {
        "role": "AXGroup",
        "children": [
            {
                "role": "AXButton",
                "position": {
                    "x": {"type": "int", "field": "x"},
                    "y": {"type": "int", "field": "y"},
                },
            }
        ],
    }
    manifest["environment"] = {"coordinate_translation": {"x": 100, "y": 61}}
    manifest["files"][0].update(
        source={"file": "selected.json", "pointer": ""},
        structure_sha256=digest(masked),
        sha256=digest(sanitized),
    )
    (root / "tree.json").write_text(json.dumps(sanitized))
    (root / "manifest.json").write_text(json.dumps(manifest))
    status, report = check(root, "--source-root", str(source))
    assert status == 1 and report == {"status": "fail", "code": "layout_drift"}


def test_committed_fixture_package_passes_without_private_sources():
    status, report = check(CHECKER.parent)
    assert status == 0 and report["status"] == "pass" and report["source_compared"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "child_order",
        "actions",
        "attributes",
        "selected",
        "enabled",
        "relation_order",
        "empty_value",
    ],
)
def test_checker_preserves_observed_fields_and_relationship_order(tmp_path, mutation):
    original = {
        "role": "AXGroup",
        "children": [{"role": "AXButton"}, {"role": "AXStaticText"}],
        "actions": ["AXCancel", "AXPress"],
        "attributes": ["AXChildren", "AXParent"],
        "selected": 0,
        "enabled": True,
        "relations": [{"roles": ["AXWindow", "AXMenuBar"]}],
        "value": "",
    }
    manifest = {
        "schema_version": 1,
        "safe_strings": [
            "AXGroup",
            "AXButton",
            "AXStaticText",
            "AXCancel",
            "AXPress",
            "AXChildren",
            "AXParent",
            "AXWindow",
            "AXMenuBar",
            "Alice Morgan",
        ],
        "files": [
            {
                "id": "tree",
                "file": "tree.json",
                "structure_sha256": digest(original),
                "sha256": digest(original),
            }
        ],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    if mutation == "child_order":
        original["children"].reverse()
    elif mutation == "actions":
        original["actions"].pop()
    elif mutation == "attributes":
        original["attributes"].pop()
    elif mutation == "selected":
        original["selected"] = 1
    elif mutation == "enabled":
        original["enabled"] = False
    elif mutation == "relation_order":
        original["relations"][0]["roles"].reverse()
    else:
        original["value"] = "Alice Morgan"
    (tmp_path / "tree.json").write_text(json.dumps(original))
    status, report = check(tmp_path)
    assert status == 1 and report == {"status": "fail", "code": "structural_drift"}


def test_checker_classifies_missing_source_without_exposing_its_path(tmp_path):
    package(tmp_path)
    status, report = check(tmp_path, "--source-root", str(tmp_path / "private"))
    assert status == 1 and report == {"status": "fail", "code": "invalid_input"}
