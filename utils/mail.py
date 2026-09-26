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
    mailer_url = getattr(
        config,
        "MAILER_URL",
        "",
    ).strip()

    mailer_secret = getattr(
        config,
        "MAILER_SECRET",
        "",
    ).strip()

    # DEBUG:
    # Secret ki actual value print nahi hogi.
    print(
        "MAILER DEBUG: "
        f"url_set={bool(mailer_url)}, "
        f"secret_set={bool(mailer_secret)}, "
        f"url={mailer_url}",
        flush=True,
    )

    if not mailer_url or not mailer_secret:
        print(
            "MAILER DEBUG: URL or secret missing.",
            flush=True,
        )
        return False

    try:
        print(
            f"MAILER DEBUG: Sending email to Vercel for {email}",
            flush=True,
        )

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

        print(
            "MAILER DEBUG: "
            f"response_status={response.status_code}",
            flush=True,
        )

        if not response.ok:
            print(
                "MAILER DEBUG: "
                f"request failed with status {response.status_code}",
                flush=True,
            )

        return response.ok

    except requests.RequestException as error:
        print(
            "MAILER DEBUG ERROR: "
            f"{type(error).__name__}: {error}",
            flush=True,
        )

        return False


# SMTP fallback se email bhejna.
def send_with_smtp(email, subject, body_text):
    if not config.SMTP_HOST:
        print(
            "MAILER DEBUG: SMTP_HOST is not configured.",
            flush=True,
        )
        return False

    try:
        print(
            "MAILER DEBUG: Using direct SMTP fallback.",
            flush=True,
        )

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

        print(
            "MAILER DEBUG: SMTP email sent successfully.",
            flush=True,
        )

        return True

    except (
        smtplib.SMTPException,
        OSError,
    ) as error:

        print(
            "MAILER DEBUG SMTP ERROR: "
            f"{type(error).__name__}: {error}",
            flush=True,
        )

        return False


# Verification/reset/change-password code bhejna.
def send_code(email, subject, instruction, code):
    """Send a verification/reset code by email."""

    body_text = BODY.format(
        instruction=instruction,
        code=code,
    )

    mailer_url = getattr(
        config,
        "MAILER_URL",
        "",
    ).strip()

    mailer_secret = getattr(
        config,
        "MAILER_SECRET",
        "",
    ).strip()

    # Safe diagnostic.
    # Secret/code ki actual value print nahi karni.
    print(
        "MAILER DEBUG send_code: "
        f"url_set={bool(mailer_url)}, "
        f"secret_set={bool(mailer_secret)}, "
        f"smtp_set={bool(config.SMTP_HOST)}",
        flush=True,
    )

    # Production mein pehle Vercel mailer use hoga.
    if mailer_url and mailer_secret:

        print(
            "MAILER DEBUG: Choosing Vercel mailer.",
            flush=True,
        )

        return send_with_mailer(
            email,
            subject,
            body_text,
        )

    # Agar Vercel mailer configure nahi hai,
    # to old SMTP fallback try karo.
    if config.SMTP_HOST:

        print(
            "MAILER DEBUG: Choosing SMTP fallback.",
            flush=True,
        )

        return send_with_smtp(
            email,
            subject,
            body_text,
        )

    # Local development fallback.
    print(
        "MAILER DEBUG: "
        "No mailer or SMTP configured. "
        "Using local terminal fallback.",
        flush=True,
    )

    print(
        f"{subject} for {email}: {code}",
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
        print(
            "MAILER DEBUG: "
            "Password reset mail service is not ready.",
            flush=True,
        )
        return False

    return send_code(
        email,
        subject,
        instruction,
        code,
    )


# Password OTP ke liye real email service available honi chahiye.
def password_mail_ready():
    mailer_url = getattr(
        config,
        "MAILER_URL",
        "",
    ).strip()

    mailer_secret = getattr(
        config,
        "MAILER_SECRET",
        "",
    ).strip()

    # Vercel mailer configured hai.
    if mailer_url and mailer_secret:
        return True

    # Old SMTP fallback.
    if not config.SMTP_HOST:
        return False

    if config.SMTP_HOST == "smtp.gmail.com":

        if (
            not config.SMTP_USER
            or not config.SMTP_PASSWORD
        ):
            return False

    return True


def send_password_change(email, code):
    """Send password-change verification code."""

    if not password_mail_ready():
        print(
            "MAILER DEBUG: "
            "Password change mail service is not ready.",
            flush=True,
        )
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