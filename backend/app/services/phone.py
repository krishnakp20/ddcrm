"""Phone numbers as the dialer sends them: digits only, with the Indian 0 / 91 prefixes removed."""
import re
from typing import Optional


def normalize_phone(raw: Optional[str]) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits


def valid_phone(value: str) -> bool:
    """Mobile numbers have 10 digits, but landlines and short numbers (6 to 15 digits) are accepted too."""
    return 6 <= len(value) <= 15


def mask(value: str) -> str:
    return value[:2] + "X" * max(0, len(value) - 4) + value[-2:] if len(value) > 4 else value
