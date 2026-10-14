"""Count solutions to a private logic-grid encoding and write the unique grid."""

import itertools
import json
import sys
from pathlib import Path

PUZZLE_PATH = Path(__file__).with_name("puzzle.json")
ANSWER_PATH = Path("/work/output/solution.json")


def satisfies(kind: str, left: int, right: int) -> bool:
    """Evaluate one positional clue on zero-based house indices."""
    return {
        "same_house": left == right,
        "not_same_house": left != right,
        "direct_left": left + 1 == right,
        "direct_right": left == right + 1,
        "side_by_side": abs(left - right) == 1,
        "left_of": left < right,
        "right_of": left > right,
        "one_between": abs(left - right) == 2,
        "two_between": abs(left - right) == 3,
    }[kind]


def solutions(
    puzzle: dict, limit: int | None = None
) -> list[dict[str, tuple[int, ...]]]:
    """Enumerate satisfying attribute permutations, optionally stopping at limit."""
    attributes = puzzle["attributes"]
    clues = puzzle["clues"]
    size = len(next(iter(attributes.values())))
    permutations = list(itertools.permutations(range(size)))
    domains: dict[str, list[tuple[int, ...]]] = {}
    for attribute, values in attributes.items():
        unary = [
            clue for clue in clues if clue["a"][0] == attribute and "house" in clue
        ]
        domains[attribute] = [
            positions
            for positions in permutations
            if all(
                (positions[values.index(clue["a"][1])] == clue["house"] - 1)
                == (clue["type"] == "found_at")
                for clue in unary
            )
        ]

    found: list[dict[str, tuple[int, ...]]] = []

    def compatible(
        attribute: str, positions: tuple[int, ...], assigned: dict[str, tuple[int, ...]]
    ) -> bool:
        for clue in clues:
            if "b" not in clue:
                continue
            left_attribute, left_value = clue["a"]
            right_attribute, right_value = clue["b"]
            if left_attribute == attribute and right_attribute in assigned:
                left = positions[attributes[left_attribute].index(left_value)]
                right = assigned[right_attribute][
                    attributes[right_attribute].index(right_value)
                ]
            elif right_attribute == attribute and left_attribute in assigned:
                left = assigned[left_attribute][
                    attributes[left_attribute].index(left_value)
                ]
                right = positions[attributes[right_attribute].index(right_value)]
            elif left_attribute == right_attribute == attribute:
                left = positions[attributes[left_attribute].index(left_value)]
                right = positions[attributes[right_attribute].index(right_value)]
            else:
                continue
            if not satisfies(clue["type"], left, right):
                return False
        return True

    def search(assigned: dict[str, tuple[int, ...]]) -> None:
        if limit is not None and len(found) >= limit:
            return
        if len(assigned) == len(attributes):
            found.append(assigned.copy())
            return
        choices = {
            attribute: [
                positions
                for positions in domain
                if compatible(attribute, positions, assigned)
            ]
            for attribute, domain in domains.items()
            if attribute not in assigned
        }
        attribute = min(choices, key=lambda name: len(choices[name]))
        for positions in choices[attribute]:
            assigned[attribute] = positions
            search(assigned)
            del assigned[attribute]
            if limit is not None and len(found) >= limit:
                return

    search({})
    return found


def grid(
    puzzle: dict, assignment: dict[str, tuple[int, ...]]
) -> dict[str, dict[str, str]]:
    """Render the unique assignment in the public answer shape."""
    size = len(next(iter(puzzle["attributes"].values())))
    houses = {f"House {house}": {} for house in range(1, size + 1)}
    for attribute, values in puzzle["attributes"].items():
        for value, house in zip(values, assignment[attribute], strict=True):
            houses[f"House {house + 1}"][attribute] = value
    return houses


def main() -> None:
    """Reject non-unique clues and write the unique solution."""
    puzzle = json.loads(PUZZLE_PATH.read_text())
    assignments = solutions(puzzle)
    if len(assignments) != 1:
        sys.exit(f"expected one solution, found {len(assignments)}")
    ANSWER_PATH.parent.mkdir(parents=True, exist_ok=True)
    ANSWER_PATH.write_text(json.dumps(grid(puzzle, assignments[0]), indent=2) + "\n")
    sys.stdout.write("solution_count=1\n")


if __name__ == "__main__":
    main()
