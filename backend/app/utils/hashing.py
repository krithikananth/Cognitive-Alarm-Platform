"""
Password hashing utilities using passlib with the bcrypt scheme.

All password operations should go through this module to ensure consistent
hashing behaviour across the application.
"""

from passlib.context import CryptContext

# CryptContext configured with bcrypt as the default (and only) scheme.
# ``deprecated="auto"`` ensures older hash formats are transparently
# re-hashed on successful verification.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain-text password against a bcrypt hash.

    Args:
        plain_password: The user-supplied plain-text password.
        hashed_password: The stored bcrypt hash to compare against.

    Returns:
        ``True`` if the password matches, ``False`` otherwise.
    """
    return _pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Generate a bcrypt hash for the given plain-text password.

    Args:
        password: The plain-text password to hash.

    Returns:
        A bcrypt-hashed string suitable for secure storage.
    """
    return _pwd_context.hash(password)
