import smtplib
from email.message import EmailMessage

import requests

import config


BODY = (
    "{instruction}\n"
    "\n"
    "    {code}\n"
    "\n"
    "The code expires in 15 minutes.\n"
    "If you did not ask for it, you can ignore this email.\n"
)


# Vercel mailer ko email bhejna.
def send_with_mailer(email, subject, body_text):
    mailer_url = getattr(config, "MAILER_URL", "").strip()
    mailer_secret = getattr(config, "MAILER_SECRET", "").strip()

    if not mailer_url or not mailer_secret:
        return False

    try:
        response = requests.post(
            mailer_url,
            headers={
                "x-mailer-secret": mailer_secret,
            },
            json={
                "to": email,
                "subject": subject,
                "text": body_text,
            },
            timeout=15,
        )

        return response.ok

    except requests.RequestException:
        return False


# SMTP fallback se email bhejna.
def send_with_smtp(email, subject, body_text):
    if not config.SMTP_HOST:
        return False

    try:
        message = EmailMessage()

        message["From"] = config.MAIL_FROM
        message["To"] = email
        message["Subject"] = subject

        message.set_content(body_text)

        with smtplib.SMTP(
            config.SMTP_HOST,
            config.SMTP_PORT,
            timeout=10,
        ) as server:

            server.starttls()

            if config.SMTP_USER:
                server.login(
                    config.SMTP_USER,
                    config.SMTP_PASSWORD,
                )

            server.send_message(message)

        return True

    except (
        smtplib.SMTPException,
        OSError,
    ):
        return False


# Verification/reset/change-password code bhejna.
def send_code(email, subject, instruction, code):
    """Send a verification/reset code by email."""

    body_text = BODY.format(
        instruction=instruction,
        code=code,
    )

    # Production mein pehle Vercel mailer use hoga.
    mailer_url = getattr(config, "MAILER_URL", "").strip()
    mailer_secret = getattr(config, "MAILER_SECRET", "").strip()

    if mailer_url and mailer_secret:
        return send_with_mailer(
            email,
            subject,
            body_text,
        )

    # Agar Vercel mailer configure nahi hai,
    # to old SMTP fallback try karo.
    if config.SMTP_HOST:
        return send_with_smtp(
            email,
            subject,
            body_text,
        )

    # Local development fallback.
    print(
        f'{subject} for {email}: {code}',
        flush=True,
    )

    return True


def send_verification(email, code):
    """Send an email verification code."""

    subject = "Your Bookrift verification code"

    instruction = (
        "Enter this code in Bookrift "
        "to verify your email address:"
    )

    return send_code(
        email,
        subject,
        instruction,
        code,
    )


def send_password_reset(email, code):
    """Send a password-reset code."""

    subject = "Your Bookrift password reset code"

    instruction = (
        "Enter this code in Bookrift "
        "to choose a new password:"
    )

    if not password_mail_ready():
        return False

    return send_code(
        email,
        subject,
        instruction,
        code,
    )


# Password OTP ke liye real email service available honi chahiye.
def password_mail_ready():
    mailer_url = getattr(config, "MAILER_URL", "").strip()
    mailer_secret = getattr(config, "MAILER_SECRET", "").strip()

    # Vercel mailer configured hai.
    if mailer_url and mailer_secret:
        return True

    # Old SMTP fallback.
    if not config.SMTP_HOST:
        return False

    if config.SMTP_HOST == "smtp.gmail.com":
        if not config.SMTP_USER or not config.SMTP_PASSWORD:
            return False

    return True


def send_password_change(email, code):
    if not password_mail_ready():
        return False

    return send_code(
        email,
        "Your Bookrift password change code",
        (
            "Enter this code in your Bookrift profile "
            "to change your password:"
        ),
        code,
    )