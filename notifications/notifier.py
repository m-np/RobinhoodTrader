import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from twilio.rest import Client

from config import settings

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self):
        self._twilio = None
        if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
            self._twilio = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

    def send_sms(self, message: str) -> bool:
        if not self._twilio:
            logger.warning("Twilio not configured — SMS skipped")
            return False
        if not settings.TWILIO_FROM_NUMBER or not settings.NOTIFY_TO_NUMBER:
            logger.warning("Twilio phone numbers not configured — SMS skipped")
            return False
        try:
            msg = self._twilio.messages.create(
                body=message,
                from_=settings.TWILIO_FROM_NUMBER,
                to=settings.NOTIFY_TO_NUMBER,
            )
            logger.info("SMS sent: %s", msg.sid)
            return True
        except Exception as e:
            logger.error("SMS send failed: %s", e)
            return False

    def send_email(self, subject: str, body: str, html: bool = False) -> bool:
        if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
            logger.warning("SMTP not configured — email skipped")
            return False
        if not settings.NOTIFY_EMAIL:
            logger.warning("NOTIFY_EMAIL not set — email skipped")
            return False
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = settings.SMTP_USER
            msg["To"] = settings.NOTIFY_EMAIL
            part = MIMEText(body, "html" if html else "plain")
            msg.attach(part)

            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                server.ehlo()
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.SMTP_USER, settings.NOTIFY_EMAIL, msg.as_string())
            logger.info("Email sent to %s", settings.NOTIFY_EMAIL)
            return True
        except Exception as e:
            logger.error("Email send failed: %s", e)
            return False

    def notify(self, subject: str, body: str, html: bool = False) -> None:
        delivery = _get_delivery_setting()
        if delivery in ("email", "both"):
            self.send_email(subject, body, html=html)
        if delivery in ("sms", "both"):
            sms_body = f"{subject}: {body}"[:160]
            self.send_sms(sms_body)

    def notify_approval_request(self, ticker: str, action: str, total_usd: float, reason: str) -> None:
        subject = f"[Trader] Approval needed: {action.upper()} {ticker}"
        body = (
            f"Your trading agent wants to {action} {ticker} for ~${total_usd:.2f}.\n\n"
            f"Reason for review: {reason}\n\n"
            "Log in to your dashboard to approve or reject this trade."
        )
        self.notify(subject, body)


def _get_delivery_setting() -> str:
    from agent.guardrails import get_knob
    return get_knob("report_delivery", "email")


_notifier: Notifier | None = None


def get_notifier() -> Notifier:
    global _notifier
    if _notifier is None:
        _notifier = Notifier()
    return _notifier
