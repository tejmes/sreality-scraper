import smtplib
from email.mime.text import MIMEText
import os


def send_email(to: list[str], subject: str, text: str):
    """
    Odesílá čistě textový e-mail přes Seznam SMTP (SSL).
    """
    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = os.getenv("EMAIL_FROM")
    msg["To"] = ", ".join(to)

    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")

    # SMTP přes SSL
    with smtplib.SMTP_SSL(host, port) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
