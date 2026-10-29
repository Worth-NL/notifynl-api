import smtplib
from email import policy
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from time import monotonic

from flask import current_app
from notifications_utils.clients.audit.audit_client import AuditCode, Key

from app.clients.email import (
    EmailClient,
    EmailClientException,
    EmailClientNonRetryableException,
)


class SmtpClientException(EmailClientException):
    pass


class SmtpClient(EmailClient):
    """
    SMTP email client.

    This class is not thread-safe
    """

    name = "smtp"

    def __init__(
        self, host, port, username, password, use_tls, envelope_from, email_from, statsd_client=None, audit_client=None
    ):
        super().__init__()
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.envelope_from = envelope_from
        self.email_from = email_from
        self.statsd_client = statsd_client
        self.audit_client = audit_client

    def _audit(self, audit_code, *, items=None):
        if self.audit_client:
            self.audit_client.log(audit_code, items=items)

    def send_email(  # noqa: C901
        self,
        *,
        from_address: str,
        to_address: str,
        subject: str,
        body: str,
        html_body: str,
        reply_to_address: str | None,
        headers: list[dict[str, str]],
    ) -> str:
        start_time = monotonic()

        # Auditlog: start notificatiemail versturen
        self._audit(AuditCode.START_NOTIFICATIEMAIL_VERSTUREN, items={Key.KANAAL: "EMAIL"})

        try:
            # Create message
            msg = MIMEMultipart("alternative", policy=policy.SMTP)
            msg["From"] = self.email_from
            msg["To"] = to_address
            msg["Subject"] = subject

            if reply_to_address:
                msg["Reply-To"] = reply_to_address

            # Add custom headers
            for header in headers:
                for key, value in header.items():
                    msg[key] = value

            # Add text and HTML parts
            text_part = MIMEText(body, "plain")
            html_part = MIMEText(html_body, "html")
            msg.attach(text_part)
            msg.attach(html_part)

            # Connect and send
            with smtplib.SMTP(self.host, self.port) as server:
                if self.use_tls:
                    server.starttls()
                if self.username and self.password:
                    server.login(self.username, self.password)

                message_id = server.send_message(msg, from_addr=self.envelope_from)

        except smtplib.SMTPRecipientsRefused as e:
            if self.statsd_client:
                self.statsd_client.incr("clients.smtp.error")
            self._audit(
                AuditCode.RESULTAAT_NOTIFICATIEMAIL_VERSTUREN_MISLUKT,
                items={Key.KANAAL: "EMAIL", Key.REDEN: "Ontvanger geweigerd door mail-relay"},
            )
            raise EmailClientNonRetryableException(f"Invalid recipient: {str(e)}") from e
        except smtplib.SMTPAuthenticationError as e:
            if self.statsd_client:
                self.statsd_client.incr("clients.smtp.error")
            self._audit(
                AuditCode.RESULTAAT_NOTIFICATIEMAIL_VERSTUREN_MISLUKT,
                items={Key.KANAAL: "EMAIL", Key.REDEN: "Authenticatie bij mail-relay mislukt"},
            )
            raise SmtpClientException(f"Authentication failed: {str(e)}") from e
        except Exception as e:
            if self.statsd_client:
                self.statsd_client.incr("clients.smtp.error")
            self._audit(
                AuditCode.RESULTAAT_NOTIFICATIEMAIL_VERSTUREN_MISLUKT,
                items={Key.KANAAL: "EMAIL", Key.REDEN: type(e).__name__},
            )
            raise SmtpClientException(str(e)) from e
        else:
            elapsed_time = monotonic() - start_time
            current_app.logger.info(
                "SMTP request finished in %.4g seconds",
                elapsed_time,
                extra={
                    "duration": elapsed_time,
                },
            )
            if self.statsd_client:
                self.statsd_client.timing("clients.smtp.request-time", elapsed_time)
                self.statsd_client.incr("clients.smtp.success")

            # Generate a simple message ID if none returned
            message_id = message_id or f"smtp-{int(start_time * 1000000)}"

            self._audit(
                AuditCode.RESULTAAT_NOTIFICATIEMAIL_VERSTUREN_GELUKT,
                items={Key.KANAAL: "EMAIL", Key.BERICHT_ID: str(message_id)},
            )

            return message_id
