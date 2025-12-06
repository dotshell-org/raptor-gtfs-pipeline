"""Compression utilities for time data."""

import logging

logger = logging.getLogger(__name__)


def encode_times(times: list[int]) -> list[int]:
    """
    Delta encode a list of times.

    First value is absolute, subsequent values are deltas from previous.
    """
    if not times:
        return []

    encoded = [times[0]]

    for i in range(1, len(times)):
        delta = times[i] - times[i - 1]
        encoded.append(delta)

    return encoded


def decode_times(encoded: list[int]) -> list[int]:
    """
    Decode delta-encoded times back to absolute values.
    """
    if not encoded:
        return []

    decoded = [encoded[0]]

    for i in range(1, len(encoded)):
        absolute = decoded[-1] + encoded[i]
        decoded.append(absolute)

    return decoded
