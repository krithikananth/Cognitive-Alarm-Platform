"""
Standalone validation utilities.

These helpers can be used outside of Pydantic schemas (e.g. in services or
CLI scripts) for quick, reusable input validation.
"""

import re
from datetime import time
from typing import Dict, List

import pytz


def validate_email(email: str) -> bool:
    """
    Check whether *email* looks like a valid email address.

    Uses a pragmatic regex that covers the vast majority of real-world
    addresses without attempting full RFC 5322 compliance.

    Args:
        email: The email string to validate.

    Returns:
        ``True`` if the format is acceptable, ``False`` otherwise.
    """
    pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    return bool(re.match(pattern, email))


def validate_password_strength(password: str) -> Dict[str, object]:
    """
    Evaluate password strength against the platform's complexity rules.

    Rules:
        - Minimum 8 characters
        - At least one uppercase letter
        - At least one lowercase letter
        - At least one digit

    Args:
        password: The plain-text password to evaluate.

    Returns:
        A dictionary with keys:
            ``is_valid`` (bool) – whether all rules pass.
            ``errors`` (List[str]) – human-readable error messages for
            each failed rule.
    """
    errors: List[str] = []

    if len(password) < 8:
        errors.append("Password must be at least 8 characters long")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        errors.append("Password must contain at least one lowercase letter")
    if not re.search(r"\d", password):
        errors.append("Password must contain at least one digit")

    return {"is_valid": len(errors) == 0, "errors": errors}


def validate_time_format(time_str: str) -> bool:
    """
    Check whether *time_str* can be parsed as ``HH:MM`` or ``HH:MM:SS``.

    Args:
        time_str: The time string to validate.

    Returns:
        ``True`` if parseable, ``False`` otherwise.
    """
    patterns = [
        r"^\d{2}:\d{2}$",       # HH:MM
        r"^\d{2}:\d{2}:\d{2}$",  # HH:MM:SS
    ]
    if not any(re.match(p, time_str) for p in patterns):
        return False

    parts = time_str.split(":")
    try:
        hour, minute = int(parts[0]), int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
        time(hour, minute, second)  # raises ValueError on out-of-range
        return True
    except (ValueError, IndexError):
        return False


def validate_timezone(tz: str) -> bool:
    """
    Check whether *tz* is a valid IANA timezone identifier.

    Args:
        tz: Timezone string (e.g. ``America/New_York``).

    Returns:
        ``True`` if recognized by pytz, ``False`` otherwise.
    """
    return tz in pytz.all_timezones
