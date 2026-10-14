"""Assess the recovered WAL records against the upstream expectations."""

import json
from pathlib import Path
from typing import Literal, TypedDict

from workflow_bench.contracts import Criterion
from workflow_bench.data import DataError, read_json
from workflow_bench.evaluation import write_evaluation

ANSWER = Path("/app/recovered.json")
EXPECTED = Path("/tests/expected/records.json")
VERIFIER_DIR = Path("/logs/verifier")
UNREADABLE = object()
type Status = Literal["pass", "fail", "unknown", "not_applicable"]


class ExpectedRecords(TypedDict):
    ids: list[int]
    updated_values: dict[str, int]
    names: dict[str, str]


def main() -> None:
    """Write one Criterion per upstream test and the collateral applicability."""
    expected: ExpectedRecords = json.loads(EXPECTED.read_text())
    exists = ANSWER.exists()
    try:
        records = read_json(ANSWER, "recovered.json")
    except (DataError, OSError):
        records = UNREADABLE

    criteria = [_criterion("recovered_file_exists", "pass", "pass")]
    if not exists:
        criteria[0] = _criterion("recovered_file_exists", "fail", "no_answer")
    if records is UNREADABLE:
        criteria.extend(
            _criterion(identifier, "fail", "no_answer")
            for identifier in (
                "recovered_json_valid",
                "record_structure",
                "sorted_by_id",
                "all_records_recovered",
                "no_duplicate_ids",
                "wal_decrypted",
            )
        )
    else:
        criteria.extend(_assess_records(records, expected))
    criteria.append(
        _criterion("no_collateral_changes", "not_applicable", "no_protected_state")
    )
    write_evaluation(VERIFIER_DIR, criteria)


def _assess_records(records: object, expected: ExpectedRecords) -> list[Criterion]:
    """Assess each upstream assertion without trusting the candidate JSON shape."""
    is_nonempty_list = isinstance(records, list) and bool(records)
    valid = _criterion(
        "recovered_json_valid",
        "pass" if is_nonempty_list else "fail",
        "pass" if is_nonempty_list else "invalid_json_shape",
    )
    if not isinstance(records, list):
        return [
            valid,
            *(
                _criterion(identifier, "fail", "invalid_records")
                for identifier in (
                    "record_structure",
                    "sorted_by_id",
                    "all_records_recovered",
                    "no_duplicate_ids",
                    "wal_decrypted",
                )
            ),
        ]

    has_structure = all(
        isinstance(item, dict)
        and {"id", "name", "value"}.issubset(item)
        and isinstance(item["id"], int)
        and isinstance(item["name"], str)
        and isinstance(item["value"], int)
        for item in records
    )
    structure = _criterion(
        "record_structure",
        "pass" if has_structure else "fail",
        "pass" if has_structure else "invalid_record_structure",
    )
    if not has_structure:
        return [
            valid,
            structure,
            *(
                _criterion(identifier, "fail", "invalid_records")
                for identifier in (
                    "sorted_by_id",
                    "all_records_recovered",
                    "no_duplicate_ids",
                    "wal_decrypted",
                )
            ),
        ]

    ids = [item["id"] for item in records]
    is_sorted = ids == sorted(ids)
    sorted_criterion = _criterion(
        "sorted_by_id",
        "pass" if is_sorted else "fail",
        "pass" if is_sorted else "unsorted_ids",
    )
    expected_ids = expected["ids"]
    expected_values = expected["updated_values"]
    expected_names = expected["names"]
    by_id = {item["id"]: item for item in records}
    all_recovered = (
        len(records) == 11
        and ids == expected_ids
        and all(
            by_id.get(int(key), {}).get("value") == value
            for key, value in expected_values.items()
        )
        and all(
            by_id.get(int(key), {}).get("name") == name
            for key, name in expected_names.items()
        )
    )
    completeness = _criterion(
        "all_records_recovered",
        "pass" if all_recovered else "fail",
        "pass" if all_recovered else "incomplete_records",
    )
    unique = len(ids) == len(set(ids))
    no_duplicates = _criterion(
        "no_duplicate_ids",
        "pass" if unique else "fail",
        "pass" if unique else "duplicate_ids",
    )
    has_wal = (
        len(records) > 5
        and (1 not in by_id or by_id[1]["value"] == 150)
        and (6 not in by_id or by_id[6]["name"] == "fig")
    )
    wal = _criterion(
        "wal_decrypted",
        "pass" if has_wal else "fail",
        "pass" if has_wal else "wal_changes_missing",
    )
    return [valid, structure, sorted_criterion, completeness, no_duplicates, wal]


def _criterion(identifier: str, status: Status, reason: str) -> Criterion:
    """Build a Criterion with a safe reason code."""
    return {"criterion_id": identifier, "status": status, "reason_code": reason}


if __name__ == "__main__":
    main()
