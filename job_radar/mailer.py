"""Sends the report through Gmail SMTP using an App Password (stored as a GitHub Secret)."""
from __future__ import annotations

import os
import smtplib
import ssl
from email.message import EmailMessage


def send(subject: str, html: str, text: str) -> None:
    user = os.environ["GMAIL_USER"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    to = os.getenv("MAIL_TO") or user

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"job-radar <{user}>"
    msg["To"] = to
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
