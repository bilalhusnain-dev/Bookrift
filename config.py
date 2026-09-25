import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent

# Local settings .env se leni hain.
load_dotenv(BASE_DIR / ".env")


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:YOUR_PASSWORD@localhost:5432/bookrift_db"
)

SECRET_KEY = os.getenv("SECRET_KEY", "")

ADMIN_EMAIL = os.getenv(
    "ADMIN_EMAIL",
    "admin@bookrift.local"
).strip().lower()

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")


# External book provider
GOOGLE_BOOKS_API_KEY = os.getenv(
    "GOOGLE_BOOKS_API_KEY",
    ""
)


# Old/direct SMTP settings
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

MAIL_FROM = os.getenv(
    "MAIL_FROM",
    "Bookrift <no-reply@bookrift.local>"
)


# Vercel mailer settings
MAILER_URL = os.getenv(
    "MAILER_URL",
    ""
).strip()

MAILER_SECRET = os.getenv(
    "MAILER_SECRET",
    ""
).strip()


# File folders
UPLOAD_FOLDER = BASE_DIR / "uploads"

COVER_FOLDER = BASE_DIR / "catalogue_covers"

FRONTEND_FOLDER = (
    BASE_DIR
    / "frontend"
    / "dist"
)


# Upload limits
MAX_UPLOAD_MB = int(
    os.getenv(
        "MAX_UPLOAD_MB",
        "10"
    )
)

MAX_UPLOAD_BYTES = (
    MAX_UPLOAD_MB
    * 1024
    * 1024
)

MAX_IMAGE_PIXELS = 24_000_000


# JWT
JWT_EXPIRY_HOURS = 24


# Flask server
HOST = os.getenv(
    "HOST",
    "127.0.0.1"
)

PORT = int(
    os.getenv(
        "PORT",
        "5000"
    )
)

DEBUG = (
    os.getenv(
        "FLASK_DEBUG",
        "0"
    )
    == "1"
)

DEV_FRONTEND_ORIGIN = os.getenv(
    "DEV_FRONTEND_ORIGIN",
    "http://127.0.0.1:8080"
)


# Zaroori settings missing hon to app start nahi karni.
def validate_config():
    missing = []

    if not SECRET_KEY:
        missing.append(
            "SECRET_KEY"
        )

    if not ADMIN_PASSWORD:
        missing.append(
            "ADMIN_PASSWORD"
        )

    if missing:
        names = ", ".join(
            missing
        )

        raise RuntimeError(
            f"Missing required settings: {names}"
        )

    if len(SECRET_KEY) < 32:
        raise RuntimeError(
            "SECRET_KEY must be at least 32 characters."
        )