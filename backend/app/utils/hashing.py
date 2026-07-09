"""
Password hashing utilities using bcrypt.

All password operations should go through this module to ensure consistent
hashing behaviour across the application.
"""

import bcrypt


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain-text password against a bcrypt hash.

    Args:
        plain_password: The user-supplied plain-text password.
        hashed_password: The stored bcrypt hash to compare against.

    Returns:
        ``True`` if the password matches, ``False`` otherwise.
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8")
    )


def get_password_hash(password: str) -> str:
    """
    Generate a bcrypt hash for the given plain-text password.

    Args:
        password: The plain-text password to hash.

    Returns:
        A bcrypt-hashed string suitable for secure storage.
    """
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")
