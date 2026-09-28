from __future__ import annotations

import smtplib
from email.message import EmailMessage

from .config import AppConfig


def send_report_email(
    config: AppConfig,
    report_path: str,
    report_text_body: str,
    report_html_body: str,
) -> None:
    msg = EmailMessage()
    msg["Subject"] = "Weekly Music Report"
    msg["From"] = config.email_from
    msg["To"] = config.email_to
    msg.set_content(
        f"Your weekly listening report is ready.\n\nReport file: {report_path}\n\n{report_text_body}"
    )
    msg.add_alternative(report_html_body, subtype="html")

    with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=30) as server:
        server.login(config.smtp_username, config.smtp_password)
        server.send_message(msg)
