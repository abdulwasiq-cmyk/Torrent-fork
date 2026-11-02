import pytest

from core.torrent_size import (
    MAX_TORRENT_SIZE_BYTES,
    parse_torrent_size_bytes,
    torrent_size_exclusion_reason,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1024, 1024),
        ("1024", 1024),
        ("1 KB", 1000),
        ("1.5 MB", 1_500_000),
        ("1.5 GB", 1_500_000_000),
        ("2 GB", 2_000_000_000),
        ("2 GiB", MAX_TORRENT_SIZE_BYTES),
        ("1 TB", 1_000_000_000_000),
        ("1 TiB", 1024**4),
    ],
)
def test_torrent_size_parser_converts_units_to_bytes(value, expected):
    assert parse_torrent_size_bytes(value) == expected


@pytest.mark.parametrize(
    "value",
    [None, True, False, 0, -1, float("nan"), "0 B", "-1 GB", "unknown", "1.5 B"],
)
def test_torrent_size_parser_rejects_unknown_or_invalid_sizes(value):
    assert parse_torrent_size_bytes(value) is None


def test_torrent_size_limit_is_inclusive_and_rejects_larger_values():
    assert torrent_size_exclusion_reason(MAX_TORRENT_SIZE_BYTES) is None
    assert torrent_size_exclusion_reason("2 GiB") is None
    assert torrent_size_exclusion_reason(MAX_TORRENT_SIZE_BYTES + 1) == "oversized"
    assert torrent_size_exclusion_reason(None) == "unknown_or_invalid_size"
