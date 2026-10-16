"""Assess collected orders independently of the mechanism that produced them."""

import csv
import hashlib
import io
import shutil
from pathlib import Path

from workflow_bench.contracts import Criterion
from workflow_bench.data import DataError, read_bytes
from workflow_bench.evaluation import write_evaluation
from workflow_bench.window import read_window

HEADER = ("order_id", "customer", "sku", "quantity", "unit_price_cents")
ORDERS = Path("/work/output/orders.csv")
EVIDENCE = Path("/window-evidence")
VERIFIER_DIR = Path("/logs/verifier")
Order = tuple[str, ...]


def main() -> None:
    """Write task criteria from final files and independently collected snapshots."""
    batches: list[set[Order]] = []
    expected: set[Order] = set()
    for index in range(1, 4):
        rows, reason = _orders(Path(f"/tests/expected/orders-{index}.csv"))
        if reason != "pass":
            raise DataError("invalid_expected", "orders")
        expected.update(rows)
        batches.append(set(rows))
    final, reason = _orders(ORDERS)
    if reason == "pass" and (set(final) != expected or len(final) != len(expected)):
        reason = "wrong_orders"
    criteria: list[Criterion] = [_criterion("all_orders", reason)]
    try:
        criteria.extend(_window_criteria(batches))
    except (DataError, OSError, ValueError):
        criteria.extend(
            {
                "criterion_id": name,
                "status": "unknown",
                "reason_code": "window_incomplete",
            }
            for name in ("no_duplicates", "latency", "no_collateral_changes")
        )
    if _duplicates(final) != "pass":
        criteria[1].update(status="fail", reason_code="duplicate_orders")
    for entry in VERIFIER_DIR.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    write_evaluation(VERIFIER_DIR, criteria)


def _orders(path: Path) -> tuple[list[Order], str]:
    if any(part.is_symlink() for part in (path, *path.parents)):
        return [], "invalid_orders"
    try:
        content = read_bytes(path, "orders.csv").decode("utf-8")
    except FileNotFoundError:
        return [], "missing_orders"
    except (DataError, OSError, UnicodeError):
        return [], "invalid_orders"
    try:
        records = list(csv.reader(io.StringIO(content, newline=""), strict=True))
    except csv.Error:
        return [], "invalid_orders"
    if not records or tuple(records[0]) != HEADER:
        return [], "invalid_header"
    rows = [tuple(row) for row in records[1:]]
    if any(len(row) != len(HEADER) or not row[0] for row in rows):
        return [], "invalid_orders"
    return rows, "pass"


def _window_criteria(batches: list[set[Order]]) -> list[Criterion]:
    facts = read_window(EVIDENCE)
    if (
        facts.status != "completed"
        or facts.elapsed_sec is None
        or facts.elapsed_sec < 660
        or len(facts.drops) != 3
        or len(facts.snapshots) != 3
    ):
        raise DataError("window_incomplete", "window")
    for index, drop in enumerate(facts.drops):
        planned = (60, 240, 420)[index]
        if (
            drop.planned_offset_sec != planned
            or not planned <= drop.actual_offset_sec <= planned + 5
            or drop.target != f"/work/inbox/orders-{index + 1}.csv"
        ):
            raise DataError("invalid_drop", "window")
    for index, snapshot in enumerate(facts.snapshots):
        planned = (240, 420, 600)[index]
        if (
            snapshot.planned_offset_sec != planned
            or not planned <= snapshot.actual_offset_sec <= planned + 5
            or snapshot.truncated
            or snapshot.actual_offset_sec < facts.drops[index].actual_offset_sec
            or (
                index < 2
                and snapshot.actual_offset_sec
                > facts.drops[index + 1].actual_offset_sec
            )
        ):
            raise DataError("invalid_snapshot", "window")
        for skipped in facts.skipped:
            if Path(skipped.path) in (ORDERS, *ORDERS.parents):
                raise DataError("unavailable_orders", "window")
    expected: set[Order] = set()
    duplicate_reason = "pass"
    latency_reason = "pass"
    all_orders = set().union(*batches)
    for index, snapshot in enumerate(facts.snapshots):
        expected.update(batches[index])
        rows, reason = _orders(EVIDENCE / snapshot.directory / "00-output/orders.csv")
        if _duplicates(rows) != "pass":
            duplicate_reason = "duplicate_orders"
        if set(rows) & (all_orders - expected):
            latency_reason = "processed_before_arrival"
        elif reason != "pass" or set(rows) != expected:
            if latency_reason == "pass":
                latency_reason = "late_orders"
    collateral_reason = "pass"
    for drop in facts.drops:
        path = Path(drop.target)
        try:
            if any(part.is_symlink() for part in (path, *path.parents)):
                raise DataError("unsafe_file", "inbox")
            content = read_bytes(path, "inbox")
            if hashlib.sha256(content).hexdigest() != drop.sha256:
                collateral_reason = "inbox_changed"
        except (DataError, OSError):
            collateral_reason = "inbox_changed"
    return [
        _criterion("no_duplicates", duplicate_reason),
        _criterion("latency", latency_reason),
        _criterion("no_collateral_changes", collateral_reason),
    ]


def _duplicates(rows: list[Order]) -> str:
    identifiers = [row[0] for row in rows]
    return "duplicate_orders" if len(set(identifiers)) != len(identifiers) else "pass"


def _criterion(name: str, reason: str) -> Criterion:
    return {
        "criterion_id": name,
        "status": "pass" if reason == "pass" else "fail",
        "reason_code": reason,
    }


if __name__ == "__main__":
    main()
