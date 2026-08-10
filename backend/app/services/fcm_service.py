"""
Firebase Cloud Messaging delivery.

Push is treated as a real dependency rather than a best-effort side effect.
When ``FCM_ENABLED`` is true the Admin SDK must initialise; if it cannot, the
reason is logged at error level and reported back to the caller so the
notification pipeline can retry later. Nothing is ever logged as if it had
been sent.

Every send returns a structured result that separates the two failure modes
that matter operationally:

``invalid_tokens``
    The registration token is permanently dead (uninstalled app, cleared site
    data, token rotated, wrong sender). These are retired immediately.
``retryable``
    Network, quota, or Firebase-side errors. The token stays active and the
    notification is re-attempted with backoff.

Send methods never raise — they report. Callers stay in control of retries.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import threading
import time as _time
from typing import Any, Dict, List, Optional, Sequence

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Failure classification ───────────────────────────────────────────

#: Registration token is permanently unusable — retire it.
INVALID_TOKEN = "invalid_token"
#: Temporary condition (network, quota, Firebase outage) — retry later.
TRANSIENT = "transient"
#: Server-side misconfiguration (bad credentials, wrong project, APNs setup).
CONFIGURATION = "configuration"

#: Push is switched off deliberately; retrying will not change the outcome.
REASON_DISABLED = "fcm_disabled"
#: Push is switched on but the SDK could not be initialised.
REASON_UNAVAILABLE = "fcm_unavailable"

# Re-initialisation is retried after this many seconds so a transient
# credential/network problem at boot does not disable push until restart.
_INIT_RETRY_COOLDOWN_SECONDS = 60

_FIREBASE_APP_NAME = "icap-notifications"

_init_lock = threading.Lock()
_firebase_app = None
_last_init_attempt_at: float = 0.0
_last_init_error: Optional[str] = None


def _load_credentials():
    """Build Firebase credentials from inline JSON or a file path.

    ``FIREBASE_CREDENTIALS_JSON`` wins when both are configured so that
    container deployments can override a baked-in path. Raises ``ValueError``
    with an actionable message when nothing usable is configured.
    """
    from firebase_admin import credentials  # type: ignore

    raw = (settings.FIREBASE_CREDENTIALS_JSON or "").strip()
    if raw:
        payload = raw
        if not payload.startswith("{"):
            try:
                payload = base64.b64decode(payload, validate=True).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError) as exc:
                raise ValueError(
                    "FIREBASE_CREDENTIALS_JSON is neither raw JSON nor valid "
                    f"base64: {exc}"
                ) from exc
        try:
            cert = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"FIREBASE_CREDENTIALS_JSON does not contain valid JSON: {exc}"
            ) from exc
        return credentials.Certificate(cert)

    cred_path = (settings.FIREBASE_CREDENTIALS_PATH or "").strip()
    if not cred_path:
        raise ValueError(
            "FCM_ENABLED is true but neither FIREBASE_CREDENTIALS_JSON nor "
            "FIREBASE_CREDENTIALS_PATH is set. See backend/.env.example."
        )
    if not os.path.isfile(cred_path):
        raise ValueError(
            f"Firebase credentials file not found at '{cred_path}'. Set "
            "FIREBASE_CREDENTIALS_PATH to the service-account JSON, or supply "
            "FIREBASE_CREDENTIALS_JSON instead."
        )
    return credentials.Certificate(cred_path)


def _ensure_firebase() -> bool:
    """Initialise the Firebase Admin SDK, retrying after failures.

    Returns ``True`` when the SDK is ready to send. Initialisation errors are
    logged with a stack trace and re-attempted after a cooldown rather than
    disabling push for the lifetime of the process.
    """
    global _firebase_app, _last_init_attempt_at, _last_init_error

    if _firebase_app is not None:
        return True

    if not settings.FCM_ENABLED:
        _last_init_error = REASON_DISABLED
        return False

    with _init_lock:
        if _firebase_app is not None:
            return True

        now = _time.monotonic()
        if _last_init_attempt_at and (
            now - _last_init_attempt_at < _INIT_RETRY_COOLDOWN_SECONDS
        ):
            return False
        _last_init_attempt_at = now

        try:
            import firebase_admin  # type: ignore

            cred = _load_credentials()
            try:
                _firebase_app = firebase_admin.get_app(_FIREBASE_APP_NAME)
            except ValueError:
                _firebase_app = firebase_admin.initialize_app(
                    cred, name=_FIREBASE_APP_NAME
                )
            _last_init_error = None
            logger.info(
                "Firebase Admin SDK initialised — push notifications active."
            )
            return True
        except ImportError:
            _last_init_error = (
                "firebase-admin is not installed; run "
                "'pip install -r requirements.txt'"
            )
            logger.error(
                "FCM_ENABLED is true but firebase-admin is not installed. "
                "Push notifications cannot be delivered.",
                exc_info=True,
            )
            return False
        except Exception as exc:
            _last_init_error = str(exc)
            logger.error(
                "Firebase Admin SDK initialisation failed: %s. Push delivery "
                "will be retried in %ds.",
                exc,
                _INIT_RETRY_COOLDOWN_SECONDS,
                exc_info=True,
            )
            return False


def _classify(exc: BaseException) -> str:
    """Map a Firebase send error to ``INVALID_TOKEN``/``TRANSIENT``/``CONFIGURATION``."""
    try:
        from firebase_admin import exceptions as fb_exceptions  # type: ignore
        from firebase_admin import messaging  # type: ignore
    except ImportError:
        return TRANSIENT

    # The registration token is dead or belongs to a different sender.
    if isinstance(exc, (messaging.UnregisteredError, messaging.SenderIdMismatchError)):
        return INVALID_TOKEN
    if isinstance(exc, fb_exceptions.NotFoundError):
        return INVALID_TOKEN
    # Malformed token strings surface as INVALID_ARGUMENT and never recover.
    if isinstance(exc, fb_exceptions.InvalidArgumentError):
        return INVALID_TOKEN

    # Retry-worthy: Firebase-side or network conditions.
    if isinstance(exc, messaging.QuotaExceededError):
        return TRANSIENT
    if isinstance(
        exc,
        (
            fb_exceptions.UnavailableError,
            fb_exceptions.InternalError,
            fb_exceptions.DeadlineExceededError,
            fb_exceptions.ResourceExhaustedError,
            fb_exceptions.AbortedError,
        ),
    ):
        return TRANSIENT

    # Our credentials/project are wrong — retrying helps only after a fix,
    # but the token itself is innocent so it must not be retired.
    if isinstance(
        exc,
        (
            fb_exceptions.UnauthenticatedError,
            fb_exceptions.PermissionDeniedError,
            messaging.ThirdPartyAuthError,
        ),
    ):
        return CONFIGURATION

    return TRANSIENT


def _mask(token: str) -> str:
    """Render a token for logs without exposing the credential itself."""
    if not token:
        return "<empty>"
    return f"{token[:12]}…{token[-4:]}" if len(token) > 20 else f"{token[:6]}…"


def _unavailable_result(tokens: Sequence[str]) -> Dict[str, Any]:
    """Result for a send attempted while the SDK is not ready.

    The returned ``errors`` carry only the coarse reason code — the underlying
    detail can name credential paths, so it stays in the server log.
    """
    disabled = not settings.FCM_ENABLED
    reason = REASON_DISABLED if disabled else REASON_UNAVAILABLE
    if not disabled:
        logger.error(
            "Dropping push for %d token(s): %s",
            len(tokens),
            _last_init_error or "Firebase Admin SDK is not initialised",
        )
    return {
        "success_count": 0,
        "failure_count": len(tokens),
        "failed_tokens": list(tokens),
        "invalid_tokens": [],
        "retryable": not disabled,
        "unavailable_reason": reason,
        "errors": [reason],
    }


def _webpush_config(title: str, body: str, payload: Dict[str, str]):
    """Web-push overrides for notifications that must not self-dismiss.

    Returned only for payloads flagged ``requires_interaction`` (alarm rings).
    Everything else keeps Firebase's default web display so existing
    notifications are unaffected.
    """
    if str(payload.get("requires_interaction", "")).lower() not in (
        "true",
        "1",
    ):
        return None

    from firebase_admin import messaging  # type: ignore

    # FCM only accepts HTTPS deep links; a local/http frontend falls back to
    # the SDK default (focus the app), where the ring modal still opens.
    link = payload.get("url") or ""
    if not link.startswith("https://"):
        link = ""
    return messaging.WebpushConfig(
        notification=messaging.WebpushNotification(
            title=title,
            body=body,
            icon="/favicon.svg",
            badge="/favicon.svg",
            tag=payload.get("notification_id") or None,
            require_interaction=True,
            renotify=True,
            silent=False,
            vibrate=[400, 200, 400, 200, 400],
        ),
        fcm_options=(
            messaging.WebpushFCMOptions(link=link) if link else None
        ),
    )


class FCMService:
    """Firebase Cloud Messaging delivery layer."""

    @staticmethod
    def is_available() -> bool:
        """Return ``True`` when FCM pushes can actually be sent."""
        return _ensure_firebase()

    @staticmethod
    def unavailable_reason() -> Optional[str]:
        """Return the coarse reason push is unavailable, or ``None`` if ready.

        Deliberately coarse: the underlying detail can include credential
        paths, so it is only ever written to the server log.
        """
        if _firebase_app is not None:
            return None
        return REASON_DISABLED if not settings.FCM_ENABLED else REASON_UNAVAILABLE

    @staticmethod
    def unavailable_detail() -> Optional[str]:
        """Return the full initialisation error, for logs and admin tooling."""
        if _firebase_app is not None:
            return None
        if not settings.FCM_ENABLED:
            return "FCM_ENABLED is false"
        return _last_init_error or "Firebase Admin SDK is not initialised"

    @staticmethod
    def initialize_at_startup() -> bool:
        """Eagerly initialise the SDK so misconfiguration surfaces at boot.

        Returns ``True`` when push is ready. Never raises — a failure here is
        logged and retried on the first real send.
        """
        if not settings.FCM_ENABLED:
            logger.warning(
                "FCM_ENABLED is false — push notifications are switched off. "
                "In-app notifications are unaffected."
            )
            return False
        ready = _ensure_firebase()
        if not ready:
            logger.error(
                "Push notifications are enabled but unavailable at startup: %s",
                _last_init_error,
            )
        return ready

    @staticmethod
    def send_to_device(
        fcm_token: str,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        *,
        image_url: Optional[str] = None,
    ) -> bool:
        """Send a push notification to a single device.

        Returns ``True`` only when Firebase accepted the message. Never raises.
        """
        result = FCMService.send_detailed(
            [fcm_token], title, body, data, image_url=image_url
        )
        return result["success_count"] > 0

    @staticmethod
    def send_to_multiple(
        fcm_tokens: List[str],
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send a push to multiple device tokens.

        Returns ``{"success_count", "failure_count", "failed_tokens",
        "invalid_tokens", "retryable", "errors"}``.
        """
        return FCMService.send_detailed(fcm_tokens, title, body, data)

    @staticmethod
    def send_detailed(
        fcm_tokens: Sequence[str],
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        *,
        image_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Deliver to ``fcm_tokens`` and report per-token outcomes.

        Failures are split into ``invalid_tokens`` (retire) and everything
        else (retry), so callers never retire a token over a network blip.
        """
        tokens = [t for t in fcm_tokens if t]
        if not tokens:
            return {
                "success_count": 0,
                "failure_count": 0,
                "failed_tokens": [],
                "invalid_tokens": [],
                "retryable": False,
                "errors": [],
            }

        if not _ensure_firebase():
            return _unavailable_result(tokens)

        try:
            from firebase_admin import messaging  # type: ignore

            notification = messaging.Notification(
                title=title, body=body, image=image_url
            )
            payload = {k: str(v) for k, v in (data or {}).items()}
            message = messaging.MulticastMessage(
                notification=notification,
                tokens=list(tokens),
                data=payload,
                webpush=_webpush_config(title, body, payload),
            )
            response = messaging.send_each_for_multicast(
                message, app=_firebase_app
            )
        except Exception as exc:
            # The whole batch failed before Firebase could judge any token, so
            # no token may be blamed. Classify once and let the caller retry.
            kind = _classify(exc)
            logger.error(
                "[FCM] Multicast send failed for %d token(s) (%s): %s",
                len(tokens),
                kind,
                exc,
                exc_info=True,
            )
            return {
                "success_count": 0,
                "failure_count": len(tokens),
                "failed_tokens": list(tokens),
                "invalid_tokens": [],
                "retryable": True,
                "errors": [f"{kind}: {exc}"],
            }

        failed_tokens: List[str] = []
        invalid_tokens: List[str] = []
        errors: List[str] = []
        retryable = False

        for idx, send_resp in enumerate(response.responses):
            if send_resp.success:
                continue
            token = tokens[idx]
            exc = send_resp.exception
            kind = _classify(exc) if exc is not None else TRANSIENT
            failed_tokens.append(token)
            if kind == INVALID_TOKEN:
                invalid_tokens.append(token)
                logger.info(
                    "[FCM] Retiring invalid token %s: %s", _mask(token), exc
                )
            else:
                retryable = True
                logger.warning(
                    "[FCM] %s failure for token %s: %s",
                    kind,
                    _mask(token),
                    exc,
                )
            errors.append(f"{kind}: {exc}")

        if response.success_count:
            logger.info(
                "[FCM] Delivered '%s' to %d/%d device(s).",
                title,
                response.success_count,
                len(tokens),
            )

        return {
            "success_count": response.success_count,
            "failure_count": response.failure_count,
            "failed_tokens": failed_tokens,
            "invalid_tokens": invalid_tokens,
            "retryable": retryable,
            "errors": errors,
        }

    @classmethod
    def send_to_user_devices(
        cls,
        db,
        user_id: int,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Send a push to every active device token for a user.

        Retires tokens Firebase reported as permanently invalid and records
        health for the rest. Tokens that fail transiently stay active.
        """
        from app.models.notification import UserDeviceToken

        tokens = (
            db.query(UserDeviceToken)
            .filter(
                UserDeviceToken.user_id == user_id,
                UserDeviceToken.is_active.is_(True),
            )
            .all()
        )

        if not tokens:
            logger.debug("[FCM] No active device tokens for user %d", user_id)
            return {
                "success_count": 0,
                "failure_count": 0,
                "failed_tokens": [],
                "invalid_tokens": [],
                "retryable": False,
                "errors": [],
                "no_devices": True,
            }

        result = cls.send_detailed(
            [t.fcm_token for t in tokens], title, body, data
        )
        result["no_devices"] = False
        result["deactivated_count"] = cls._record_token_health(
            db, tokens, result
        )
        return result

    @staticmethod
    def _record_token_health(
        db,
        token_rows: Sequence[Any],
        result: Dict[str, Any],
    ) -> int:
        """Persist per-token delivery outcomes; return tokens retired."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        invalid = set(result.get("invalid_tokens") or [])
        failed = set(result.get("failed_tokens") or [])
        deactivated = 0

        for row in token_rows:
            if row.fcm_token in invalid:
                row.is_active = False
                row.deactivated_at = now
                row.deactivated_reason = "fcm_invalid_token"
                deactivated += 1
            elif row.fcm_token in failed:
                # Transient failure: keep the token, just note the miss.
                row.failure_count = (row.failure_count or 0) + 1
            else:
                row.failure_count = 0
                row.last_success_at = now

        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.error(
                "[FCM] Failed to persist device-token health for %d token(s).",
                len(token_rows),
                exc_info=True,
            )
            return 0

        if deactivated:
            logger.info(
                "[FCM] Retired %d invalid device token(s).", deactivated
            )
        return deactivated

    @staticmethod
    def cleanup_invalid_tokens(db, *, stale_after_days: int = 270) -> int:
        """Delete device tokens that are retired and long past useful life.

        Firebase itself treats registration tokens untouched for months as
        stale. Rows are only removed once they have been inactive for
        ``stale_after_days``, so recent deactivations stay auditable.
        """
        from datetime import datetime, timedelta, timezone

        from app.models.notification import UserDeviceToken

        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            days=stale_after_days
        )
        removed = (
            db.query(UserDeviceToken)
            .filter(
                UserDeviceToken.is_active.is_(False),
                UserDeviceToken.updated_at < cutoff,
            )
            .delete(synchronize_session=False)
        )
        if removed:
            try:
                db.commit()
                logger.info(
                    "[FCM] Purged %d device token(s) inactive since before %s.",
                    removed,
                    cutoff.date(),
                )
            except Exception:
                db.rollback()
                logger.error(
                    "[FCM] Failed to purge stale device tokens.", exc_info=True
                )
                return 0
        return removed
