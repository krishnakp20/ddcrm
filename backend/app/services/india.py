"""Indian business-data validators: GSTIN (with check digit), PAN, mobile, pincode, state codes."""
import re

# GST state codes -> state / UT names
GST_STATES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
    "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
    "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura",
    "17": "Meghalaya", "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh",
    "23": "Madhya Pradesh", "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
}
STATES = sorted(GST_STATES.values())

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

PAN_HOLDER = {
    "P": "Individual", "C": "Company", "H": "HUF", "F": "Firm", "A": "Association of persons",
    "T": "Trust", "B": "Body of individuals", "L": "Local authority", "J": "Artificial juridical person",
    "G": "Government",
}


def gstin_check_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        product = _CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return _CHARS[(36 - total % 36) % 36]


def validate_gstin(value: str) -> str | None:
    """Returns an error message, or None when the GSTIN is valid."""
    if not GSTIN_RE.match(value):
        return "GSTIN must be 15 characters, for example 09AAGCC4479E2ZG"
    if value[:2] not in GST_STATES:
        return "GSTIN starts with an unknown state code"
    if gstin_check_char(value[:14]) != value[14]:
        return "GSTIN check digit is wrong; please re-check the number"
    return None


def validate_pan(value: str) -> str | None:
    if not PAN_RE.match(value):
        return "PAN must look like AAGCC4479E"
    if value[3] not in PAN_HOLDER:
        return "PAN has an unknown holder type"
    return None


def normalize_mobile(value: str) -> str:
    """'+91 98765-43210' -> '9876543210'."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits


def valid_mobile(value: str) -> bool:
    return bool(re.fullmatch(r"[6-9][0-9]{9}", value))


def valid_pincode(value: str) -> bool:
    return bool(re.fullmatch(r"[1-9][0-9]{5}", value))


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
