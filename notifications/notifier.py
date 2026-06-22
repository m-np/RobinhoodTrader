import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from twilio.rest import Client

from config import settings

logger = logging.getLogger(__name__)


def _get_notify_email() -> str:
    """Recipient email — DB value overrides .env so users can update it from the dashboard."""
    try:
        from agent.guardrails import get_knob
        db_val = get_knob("notify_email", "")
        if db_val:
            return db_val
    except Exception:
        pass
    return settings.NOTIFY_EMAIL or ""


def _get_notify_phone() -> str:
    """Recipient phone — DB value overrides .env so users can update it from the dashboard."""
    try:
        from agent.guardrails import get_knob
        db_val = get_knob("notify_phone", "")
        if db_val:
            return db_val
    except Exception:
        pass
    return settings.NOTIFY_TO_NUMBER or ""


def _make_html_body(body: str) -> str:
    body_html = body.replace("\n", "<br>")
    return f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f4f4f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px">
  <tr><td align="center">
    <table width="560" cellpadding="0" cellspacing="0"
           style="background:#fff;border-radius:10px;overflow:hidden;max-width:560px">
      <tr><td style="background:#185fa5;padding:18px 24px">
        <span style="color:#fff;font-size:14px;font-weight:600">Agentic Trader</span>
      </td></tr>
      <tr><td style="padding:24px 28px">
        <div style="font-size:14px;color:#4a4a46;line-height:1.75">{body_html}</div>
      </td></tr>
      <tr><td style="padding:14px 24px;background:#f9f9f7;font-size:11px;color:#9e9e99">
        Automated report from your trading agent
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


class Notifier:
    def __init__(self):
        self._twilio = None
        if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
            self._twilio = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

    def send_sms(self, message: str) -> bool:
        if not self._twilio:
            logger.warning("Twilio not configured — SMS skipped")
            return False
        to_number = _get_notify_phone()
        if not settings.TWILIO_FROM_NUMBER or not to_number:
            logger.warning("Twilio phone numbers not configured — SMS skipped")
            return False
        try:
            msg = self._twilio.messages.create(
                body=message,
                from_=settings.TWILIO_FROM_NUMBER,
                to=to_number,
            )
            logger.info("SMS sent: %s", msg.sid)
            return True
        except Exception as e:
            logger.error("SMS send failed: %s", e)
            return False

    def send_email(self, subject: str, body: str) -> bool:
        if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
            logger.warning("SMTP not configured — email skipped")
            return False
        to_email = _get_notify_email()
        if not to_email:
            logger.warning("Notify email not set — email skipped")
            return False
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = settings.SMTP_USER
            msg["To"] = to_email
            msg.attach(MIMEText(body, "plain"))
            msg.attach(MIMEText(_make_html_body(body), "html"))

            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                server.ehlo()
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.SMTP_USER, to_email, msg.as_string())
            logger.info("Email sent to %s", to_email)
            return True
        except Exception as e:
            logger.error("Email send failed: %s", e)
            return False

    def send_test_email(self) -> bool:
        return self.send_email(
            subject="Test — Agentic Trader",
            body="Your email notifications are working correctly.\n\nReport summaries and alerts will be delivered to this address.",
        )

    def send_test_sms(self) -> bool:
        return self.send_sms("Agentic Trader: SMS notifications are working correctly.")

    def notify(self, subject: str, body: str) -> None:
        delivery = _get_delivery_setting()
        if delivery in ("email", "both"):
            self.send_email(subject, body)
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
