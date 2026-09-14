from __future__ import annotations


_CUSIP_VALUES = {
    **{str(value): value for value in range(10)},
    **{chr(ord("A") + offset): 10 + offset for offset in range(26)},
    "*": 36,
    "@": 37,
    "#": 38,
}


def normalize_cusip(value: object) -> str:
    return str(value or "").strip().upper()


def is_valid_cusip(value: object) -> bool:
    """Return whether a value is a canonical nine-character CUSIP."""
    cusip = normalize_cusip(value)
    if len(cusip) != 9 or cusip[-1] not in "0123456789":
        return False
    try:
        values = [_CUSIP_VALUES[character] for character in cusip[:8]]
    except KeyError:
        return False
    checksum = 0
    for index, value in enumerate(values):
        weighted = value * (2 if index % 2 else 1)
        checksum += weighted // 10 + weighted % 10
    return (10 - checksum % 10) % 10 == int(cusip[-1])
