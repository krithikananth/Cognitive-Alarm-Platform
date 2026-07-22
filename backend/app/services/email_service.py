"""
Transactional email delivery for auth flows.

When SMTP is configured, messages are sent over the network. Otherwise the
link is logged so local development and automated tests still work end-to-end
without requiring a mail server.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """Send password-reset and email-verification messages."""

    @staticmethod
    def is_configured() -> bool:
        """Return True when outbound SMTP credentials are present."""
        return bool(settings.SMTP_HOST and settings.SMTP_FROM_EMAIL)

    @staticmethod
    def _from_header() -> str:
        name = settings.SMTP_FROM_NAME or "Intelligent Cognitive Alarm"
        address = settings.SMTP_FROM_EMAIL or "noreply@localhost"
        return f"{name} <{address}>"

    @staticmethod
    def send_email(
        *,
        to_email: str,
        subject: str,
        text_body: str,
        html_body: Optional[str] = None,
    ) -> bool:
        """
        Deliver a plain-text (and optional HTML) email.

        Returns ``True`` when the message was accepted by SMTP, ``False`` when
        SMTP is not configured (the body is logged instead). Raises on SMTP
        transport failures so callers can decide whether to surface errors.
        """
        if not EmailService.is_configured():
            logger.info(
                "SMTP not configured — email to %s skipped.\nSubject: %s\n%s",
                to_email,
                subject,
                text_body,
            )
            return False

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = EmailService._from_header()
        message["To"] = to_email
        message.set_content(text_body)
        if html_body:
            message.add_alternative(html_body, subtype="html")

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
            if settings.SMTP_USE_TLS:
                smtp.starttls()
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(message)

        logger.info("Email sent to %s (%s)", to_email, subject)
        return True

    @staticmethod
    def send_password_reset_email(*, to_email: str, reset_url: str) -> bool:
        """Send the password-reset link for ``to_email``."""
        subject = "Reset your password"
        text_body = (
            "You requested a password reset for your Intelligent Cognitive Alarm "
            "account.\n\n"
            f"Open this link to choose a new password (expires soon):\n{reset_url}\n\n"
            "If you did not request this, you can ignore this email."
        )
        html_body = (
            "<p>You requested a password reset for your Intelligent Cognitive "
            "Alarm account.</p>"
            f'<p><a href="{reset_url}">Reset your password</a></p>'
            "<p>If you did not request this, you can ignore this email.</p>"
        )
        return EmailService.send_email(
            to_email=to_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )

    @staticmethod
    def send_verification_email(*, to_email: str, verify_url: str) -> bool:
        """Send the email-verification link for ``to_email``."""
        subject = "Verify your email address"
        text_body = (
            "Welcome to Intelligent Cognitive Alarm!\n\n"
            f"Please verify your email by opening this link:\n{verify_url}\n\n"
            "If you did not create an account, you can ignore this email."
        )
        html_body = (
            "<p>Welcome to Intelligent Cognitive Alarm!</p>"
            f'<p><a href="{verify_url}">Verify your email</a></p>'
            "<p>If you did not create an account, you can ignore this email.</p>"
        )
        return EmailService.send_email(
            to_email=to_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )
