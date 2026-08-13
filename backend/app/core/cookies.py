"""
HttpOnly authentication cookies.

The SPA authenticates with cookies instead of storing JWTs in ``localStorage``,
so injected JavaScript cannot read a session. Cookies are ``HttpOnly``,
``SameSite`` constrained, and ``Secure`` whenever the app runs in production.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Request, Response

from app.core.config import settings


def _cookie_kwargs(max_age: int, path: str) -> dict:
    return {
        "max_age": max_age,
        "expires": max_age,
        "path": path,
        "domain": settings.AUTH_COOKIE_DOMAIN,
        "secure": settings.cookies_secure,
        "httponly": True,
        "samesite": settings.AUTH_COOKIE_SAMESITE,
    }


def set_auth_cookies(
    response: Response, access_token: str, refresh_token: Optional[str] = None
) -> None:
    """Attach the session cookies to an outgoing response."""
    if not settings.AUTH_COOKIE_ENABLED:
        return

    response.set_cookie(
        settings.ACCESS_COOKIE_NAME,
        access_token,
        **_cookie_kwargs(settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60, "/"),
    )
    if refresh_token:
        response.set_cookie(
            settings.REFRESH_COOKIE_NAME,
            refresh_token,
            **_cookie_kwargs(settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400, "/"),
        )


def clear_auth_cookies(response: Response) -> None:
    """Remove the session cookies (logout)."""
    for name in (settings.ACCESS_COOKIE_NAME, settings.REFRESH_COOKIE_NAME):
        response.delete_cookie(
            name,
            path="/",
            domain=settings.AUTH_COOKIE_DOMAIN,
            secure=settings.cookies_secure,
            httponly=True,
            samesite=settings.AUTH_COOKIE_SAMESITE,
        )


def access_cookie(request: Optional[Request]) -> Optional[str]:
    """Read the access token from the request cookies."""
    if request is None or not settings.AUTH_COOKIE_ENABLED:
        return None
    return request.cookies.get(settings.ACCESS_COOKIE_NAME)


def refresh_cookie(request: Optional[Request]) -> Optional[str]:
    """Read the refresh token from the request cookies."""
    if request is None or not settings.AUTH_COOKIE_ENABLED:
        return None
    return request.cookies.get(settings.REFRESH_COOKIE_NAME)
