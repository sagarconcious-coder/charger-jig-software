"""Code-letter mappings for charger traceability serial numbers, per the
"AEIDTH Traceability Detail" sheet (F.No. ADT_R&D_F003_V1.0).

Mirrors the server's bms/charger_code_tables.py (aeidthocpp repo) - kept in
sync manually, same as frontend/js/charger_code_tables.js already does for
the Lot page's dropdowns. Used by backend/tools/gen_serial_qr_sheet.py so it
can build a lot's prefix locally (offline, no server round-trip) using the
exact same validation/format rules the server itself enforces.
"""

from typing import Optional

# (code, label) pairs - code is what goes into the serial number, label is
# what's shown in the UI dropdown.
VOLTAGE_AMP_CHOICES = [
    ("5825", "58V25A-5825"),
    ("7325", "73V25A-7325"),
]

VARIANT_CHOICES = [
    ("A", "CAN+IP-A"),
    ("B", "NON CAN+IP-B"),
]

CONNECTOR_CHOICES = [
    ("A", "Anderson SB75-A"),
    ("B", "Anderson SB50-B"),
    ("C", "Chagori-C"),
]

MS_ID_CHOICES = [
    ("A", "SHIGAN-A"),
    ("B", "SBT-B"),
    ("C", "OSRIM-C"),
    ("D", "TADASHI-D"),
    ("E", "IEMS-E"),
    ("G", "IKIO-G"),
]

MONTH_CHOICES = [
    ("A", "Jan"), ("B", "Feb"), ("C", "Mar"), ("D", "Apr"),
    ("E", "May"), ("F", "Jun"), ("G", "Jul"), ("H", "Aug"),
    ("I", "Sep"), ("J", "Oct"), ("K", "Nov"), ("L", "Dec"),
]
MONTH_CODES = [c for c, _ in MONTH_CHOICES]

YEAR_CODE_BASE_YEAR = 2025  # "A" -> 2025, "B" -> 2026, "C" -> 2027, "D" -> 2028, ...

# Defaults per the traceability sheet / the requested default part config.
DEFAULT_VOLTAGE_AMP_CODE = "5825"
DEFAULT_VARIANT_CODE = "B"       # NON CAN+IP-B
DEFAULT_CONNECTOR_CODE = "A"     # Anderson SB75-A
DEFAULT_MS_ID_CODE = "G"         # IKIO-G

PRODUCT_CODE = "CC"  # Charger


def month_code_for(dt) -> str:
    """dt.month is 1-12 -> 'A'..'L'."""
    return MONTH_CODES[dt.month - 1]


def year_code_for(dt) -> str:
    """2025 -> 'A', 2026 -> 'B', ... Grows past 'Z' is not handled - not a
    realistic concern for this product's lifetime, but raises clearly if hit."""
    offset = dt.year - YEAR_CODE_BASE_YEAR
    if offset < 0 or offset > 25:
        raise ValueError(f"Year {dt.year} is out of the supported traceability code range")
    return chr(ord("A") + offset)


def build_prefix(voltage_amp_code, variant_code, connector_code, ms_id_code, month_code, year_code) -> str:
    return f"{PRODUCT_CODE}{voltage_amp_code}{variant_code}{connector_code}{ms_id_code}{month_code}{year_code}"


def _valid_codes(choices):
    return {c for c, _ in choices}


def validate_codes(voltage_amp_code, variant_code, connector_code, ms_id_code, month_code, year_code) -> Optional[str]:
    """Returns an error message if any code is invalid, else None."""
    if voltage_amp_code not in _valid_codes(VOLTAGE_AMP_CHOICES):
        return f"Invalid voltage_amp_code: {voltage_amp_code}"
    if variant_code not in _valid_codes(VARIANT_CHOICES):
        return f"Invalid variant_code: {variant_code}"
    if connector_code not in _valid_codes(CONNECTOR_CHOICES):
        return f"Invalid connector_code: {connector_code}"
    if ms_id_code not in _valid_codes(MS_ID_CHOICES):
        return f"Invalid ms_id_code: {ms_id_code}"
    if month_code not in MONTH_CODES:
        return f"Invalid month_code: {month_code}"
    if not (isinstance(year_code, str) and len(year_code) == 1 and "A" <= year_code <= "Z"):
        return f"Invalid year_code: {year_code}"
    return None
