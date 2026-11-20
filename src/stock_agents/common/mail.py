"""Application email delivery. Credentials are read only on the server."""

import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlsplit

from stock_agents.common.config import load_settings


class MailDeliveryError(RuntimeError):
    pass


def send_account_email(recipient: str, purpose: str, token: str) -> None:
    settings = load_settings()
    origin = settings.env("FRONTEND_URL", "http://localhost:3001").rstrip("/")
    parsed = urlsplit(origin)
    if (
        not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path
        or (
            parsed.scheme != "https"
            and not (
                parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            )
        )
    ):
        raise MailDeliveryError("Account email settings are incomplete")
    verify = purpose == "verify_email"
    path = "verify-email" if verify else "reset-password"
    title = "Verify your email" if verify else "Reset your password"
    lifetime = "one hour" if verify else "30 minutes"
    # Fragments stay in the browser and avoid putting bearer secrets in HTTP access logs.
    url = f"{origin}/{path}#token={token}"
    message = EmailMessage()
    message["Subject"] = f"Stock Agents — {title}"
    message["To"] = recipient
    message.set_content(
        f"{title} for your Stock Agents account using the link below.\n\n{url}\n\n"
        f"This link expires in {lifetime} and can be used once.\n"
        "If you did not request this email, you can ignore it.\n"
    )
    deliver_message(message)


def deliver_message(message: EmailMessage) -> None:
    settings = load_settings()
    host = settings.env("EMAIL_HOST", "smtp.gmail.com")
    sender = settings.env("EMAIL")
    password = settings.env("EMAIL_PASSWORD")
    if not sender or not password:
        raise MailDeliveryError("Email sender settings are incomplete")
    message["From"] = sender
    try:
        port = int(settings.env("EMAIL_PORT", "587"))
        context = ssl.create_default_context()
        # Gmail displays app passwords in groups separated by spaces.
        secret = password.replace(" ", "") if host == "smtp.gmail.com" else password
        smtp_type = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
        kwargs = {"context": context} if port == 465 else {}
        with smtp_type(host, port, timeout=10, **kwargs) as smtp:
            if port != 465:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(sender, secret)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError, ValueError) as exc:
        raise MailDeliveryError(
            "Email could not be delivered. Please try again later."
        ) from exc
