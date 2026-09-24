from datetime import datetime, timedelta, timezone
from functools import wraps
import hashlib

import jwt
from flask import g, request

import config
import database




# User ID, session version aur expiry ko signed token mein rakhna.
def create_login_token(user):
    """Create a signed JWT login token for one user."""

    now = datetime.now(timezone.utc)

    expiry_time = now + timedelta(hours=config.JWT_EXPIRY_HOURS)

    details = {
        "sub": str(user["id"]),
        "version": user["auth_version"],
        "iat": now,
        "exp": expiry_time,
    }

    token = jwt.encode(details, config.SECRET_KEY, algorithm='HS256')

    return token


# Signature aur expiry check karni hai; invalid token par None.
def read_login_token(token):
    """Decode and verify a JWT token. Return None if the token is invalid."""

    try:
        details = jwt.decode(
            token,
            config.SECRET_KEY,
            algorithms=["HS256"],
            # Expiry field missing ho tab bhi token reject karna.
            options={"require": ["exp"]},
        )

        return details

    except (
        jwt.InvalidTokenError,
        TypeError,
        ValueError,
    ):
        return None


def get_bearer_token():
    """Read the JWT token from the HTTP Authorization header."""

    header = request.headers.get('Authorization', '')

    if not header.startswith("Bearer "):
        return None

    token = header[7:].strip()

    if not token:
        return None

    return token


# Token aur current session version check karke user ko g mein rakhna.
def login_required(view):
    """Decorator that allows only a valid logged-in user to access a route."""

    @wraps(view)
    def wrapped(*args, **kwargs):

        token = get_bearer_token()

        details = read_login_token(token)

        if not details:
            return ({'error': 'Please sign in first.'}, 401)

        try:
            user_id = int(details['sub'])

            token_version = int(details['version'])

        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            return ({'error': 'Your session is invalid.'}, 401)

        user = database.get_user_by_id(user_id)

        if not user:
            return ({'error': 'Your session has ended. Please sign in again.'}, 401)

        if user["auth_version"] != token_version:
            return ({'error': 'Your session has ended. Please sign in again.'}, 401)

        g.current_user = user

        return view(*args, **kwargs)

    return wrapped


# Login ke baad database wala admin flag bhi check karna.
def admin_required(view):
    """Decorator that allows only logged-in admin users to access a route."""

    @login_required
    @wraps(view)
    def wrapped(*args, **kwargs):

        if not g.current_user["is_admin"]:
            return ({'error': 'Admin access is required.'}, 403)

        return view(*args, **kwargs)

    return wrapped


def rate_key(key):
    value = str(key or 'unknown').casefold()
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def rate_limit_reached(group, key, limit, window_seconds):
    return database.rate_limit_status(group, rate_key(key), limit, window_seconds)


# True ka matlab limit hit; warna isi request ka attempt count hoga.
def take_rate_slot(group, key, limit, window_seconds):
    """Return True when blocked; otherwise count this request atomically."""
    return database.rate_limit_status(group, rate_key(key), limit, window_seconds, record=True)


def record_rate_event(group, key):
    database.rate_limit_status(group, rate_key(key), None, 86400, record=True)


def clear_rate_events(group, key):
    database.clear_stored_rate_events(group, rate_key(key))
