"""Checked host-side exchange values; nested JSON trees must not be mutated."""

type JsonValue = (
    None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
)
