"""The Verhoeff checksum (Aadhaar's last digit; SPEC §6.6). Detects every single-digit error and
every swap of adjacent digits."""

# Multiplication table of the dihedral group D5, the permutation table and the inverse table.
_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def _checksum(digits: str, offset: int) -> int:
    c = 0
    for i, digit in enumerate(reversed(digits)):
        c = _D[c][_P[(i + offset) % 8][int(digit)]]
    return c


def is_valid(digits: str) -> bool:
    """True if `digits` (ASCII digits only, check digit last) has a valid Verhoeff checksum."""
    if not digits.isascii() or not digits.isdigit():
        return False
    return _checksum(digits, 0) == 0


def check_digit(digits: str) -> str:
    """The check digit to append to `digits` (ASCII digits only)."""
    if not digits.isascii() or not digits.isdigit():
        raise ValueError("Verhoeff works on digits only")
    return str(_INV[_checksum(digits, 1)])
