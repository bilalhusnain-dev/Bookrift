import smtplib
from email.message import EmailMessage

import config


BODY = (
    "{instruction}\n"
    "\n"
    "    {code}\n"
    "\n"
    "The code expires in 15 minutes.\n"
    "If you did not ask for it, you can ignore this email.\n"
)


# SMTP se code bhejna; send fail ho to False dena.
def send_code(email, subject, instruction, code):
    """Send a verification/reset code by email."""

    # SMTP na ho to verification code terminal mein aayega.

    if not config.SMTP_HOST:

        print(f'{subject} for {email}: {code}', flush=True)

        return True

    # SMTP configured ho to email bhejni hai.

    try:

        message = EmailMessage()

        message["From"] = config.MAIL_FROM
        message["To"] = email
        message["Subject"] = subject

        body_text = BODY.format(instruction=instruction, code=code)

        message.set_content(body_text)

        # Mail server se connection banana.
        with smtplib.SMTP(
            config.SMTP_HOST,
            config.SMTP_PORT,
            timeout=10,
        ) as server:

            # Connection encrypt karna.
            server.starttls()

            # Username diya ho to SMTP login karna.
            if config.SMTP_USER:

                server.login(config.SMTP_USER, config.SMTP_PASSWORD)

            server.send_message(message)

        return True

    except (
        smtplib.SMTPException,
        OSError,
    ):
        # Email fail ho to caller ko False dena.
        return False


def send_verification(email, code):
    """Send an email verification code."""

    subject = "Your Bookrift verification code"

    instruction = 'Enter this code in Bookrift to verify your email address:'

    return send_code(email, subject, instruction, code)


def send_password_reset(email, code):
    """Send a password-reset code."""

    subject = "Your Bookrift password reset code"

    instruction = 'Enter this code in Bookrift to choose a new password:'

    if not password_mail_ready():
        return False
    return send_code(email, subject, instruction, code)


# Password OTP ke liye mail settings honi chahiye.
def password_mail_ready():
    if not config.SMTP_HOST:
        return False
    if config.SMTP_HOST == 'smtp.gmail.com':
        if not config.SMTP_USER or not config.SMTP_PASSWORD:
            return False
    return True


def send_password_change(email, code):
    if not password_mail_ready():
        return False
    return send_code(
        email,
        'Your Bookrift password change code',
        'Enter this code in your Bookrift profile to change your password:',
        code,
    )
