"""Validated API list prices and a shared token-cost estimate."""

import math
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import TypedDict, cast

from workflow_bench.data import DataError, read_json

_RATE_FIELDS = ("input_per_million", "cached_input_per_million", "output_per_million")
_PRICE_FIELDS = set(_RATE_FIELDS) | {
    "tier",
    "context_band",
    "source_url",
    "retrieved_on",
}
PRICE_LIMITS = "cache-write tokens and the long-context band are not modelled"


class PriceEntry(TypedDict):
    """Per-million USD rates and provenance for one Harbor model id."""

    input_per_million: float
    cached_input_per_million: float
    output_per_million: float
    tier: str
    context_band: str
    source_url: str
    retrieved_on: str


class PriceEstimateLabel(TypedDict):
    """The provenance and limitations of every estimate in one report."""

    label: str
    source_url: str | None
    limits: str


def read_price_file(path: Path) -> dict[str, PriceEntry]:
    """Read a dated price file, rejecting malformed or ambiguous provenance."""
    document = read_json(path, "prices")
    if not isinstance(document, dict) or set(document) != {"models"}:
        raise DataError("invalid_prices", "prices")
    models = document["models"]
    if not isinstance(models, dict) or not models:
        raise DataError("invalid_prices", "prices")
    entries: dict[str, PriceEntry] = {}
    provenance: tuple[str, str] | None = None
    for model, entry in models.items():
        if not isinstance(model, str) or not model or not isinstance(entry, dict):
            raise DataError("invalid_prices", "prices")
        if set(entry) != _PRICE_FIELDS:
            raise DataError("invalid_prices", "prices")
        _validate_rates(entry)
        if not all(
            isinstance(entry[key], str) and entry[key]
            for key in _PRICE_FIELDS - set(_RATE_FIELDS)
        ):
            raise DataError("invalid_prices", "prices")
        retrieved_on = cast(str, entry["retrieved_on"])
        source_url = cast(str, entry["source_url"])
        try:
            if date.fromisoformat(retrieved_on).isoformat() != retrieved_on:
                raise ValueError("noncanonical date")
        except ValueError:
            raise DataError("invalid_prices", "prices") from None
        if not source_url.startswith("https://"):
            raise DataError("invalid_prices", "prices")
        model_provenance = (retrieved_on, source_url)
        if provenance is not None and model_provenance != provenance:
            raise DataError("invalid_prices", "prices")
        provenance = model_provenance
        entries[model] = cast(PriceEntry, entry)
    return entries


def estimate_cost_usd(
    input_tokens: int | None,
    cached_tokens: int | None,
    output_tokens: int | None,
    rates: Mapping[str, object],
) -> float | None:
    """Estimate USD from total input (including cached), cached and output tokens.

    Return None if a token count is missing, negative or boolean, or if cached
    tokens exceed total input. Invalid or missing rates raise DataError, even
    when a token count is unknown.
    """
    _validate_rates(rates)
    if input_tokens is None or cached_tokens is None or output_tokens is None:
        return None
    if any(
        isinstance(value, bool) or value < 0
        for value in (input_tokens, cached_tokens, output_tokens)
    ):
        return None
    if cached_tokens > input_tokens:
        return None
    input_rate = cast(float, rates["input_per_million"])
    cached_rate = cast(float, rates["cached_input_per_million"])
    output_rate = cast(float, rates["output_per_million"])
    return (
        (input_tokens - cached_tokens) * input_rate
        + cached_tokens * cached_rate
        + output_tokens * output_rate
    ) / 1_000_000


def price_estimate_label(prices: Mapping[str, PriceEntry] | None) -> PriceEstimateLabel:
    """Describe the selected price source, or the unknown estimate without one.

    A supplied mapping must be nonempty, with the same retrieval date and source
    URL for every entry, as enforced by read_price_file.
    """
    if prices is None:
        return {"label": "unknown", "source_url": None, "limits": PRICE_LIMITS}
    entry = next(iter(prices.values()))
    return {
        "label": f"estimate by OpenAI API list price as of {entry['retrieved_on']}",
        "source_url": entry["source_url"],
        "limits": PRICE_LIMITS,
    }


def _validate_rates(rates: Mapping[str, object]) -> None:
    for key in _RATE_FIELDS:
        value = rates.get(key)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise DataError("invalid_prices", "prices")
