from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

MAX_TORRENT_SIZE_BYTES = 2 * 1024**3

_SIZE_RE = re.compile(
    r"^(?P<amount>(?:\d+(?:\.\d+)?|\.\d+))\s*(?P<unit>[a-zA-Z]+)?$"
)
_SIZE_UNITS = {
    "b": 1,
    "byte": 1,
    "bytes": 1,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
    "tb": 1000**4,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
}


def parse_torrent_size_bytes(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            amount = Decimal(str(value))
        except InvalidOperation:
            return None
        multiplier = 1
    elif isinstance(value, str):
        match = _SIZE_RE.fullmatch(value.strip())
        if match is None:
            return None
        unit = (match.group("unit") or "").casefold()
        multiplier = _SIZE_UNITS.get(unit, 1) if not unit else _SIZE_UNITS.get(unit, 0)
        if not multiplier:
            return None
        try:
            amount = Decimal(match.group("amount"))
        except InvalidOperation:
            return None
    else:
        return None

    if not amount.is_finite() or amount <= 0:
        return None
    size_bytes = amount * multiplier
    if size_bytes != size_bytes.to_integral_value():
        return None
    return int(size_bytes)


def torrent_size_exclusion_reason(value: Any) -> str | None:
    size_bytes = parse_torrent_size_bytes(value)
    if size_bytes is None:
        return "unknown_or_invalid_size"
    if size_bytes > MAX_TORRENT_SIZE_BYTES:
        return "oversized"
    return None


def filter_torrent_records(
    records: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    retained: list[dict[str, Any]] = []
    counts = {
        "retained": 0,
        "excludedOversized": 0,
        "excludedUnknownOrInvalidSize": 0,
    }
    for record in records:
        reason = torrent_size_exclusion_reason(record.get("size"))
        if reason == "oversized":
            counts["excludedOversized"] += 1
        elif reason:
            counts["excludedUnknownOrInvalidSize"] += 1
        else:
            retained.append(record)
            counts["retained"] += 1
    return retained, counts
