import secrets

from flask import Blueprint, current_app, g, request
from werkzeug.security import (
    check_password_hash,
    generate_password_hash,
)

import database

from utils.mail import (
    send_password_reset,
    send_password_change,
    send_verification,
)

from utils.security import (
    clear_rate_events,
    create_login_token,
    login_required,
    rate_limit_reached,
    take_rate_slot,
)

from utils.validation import (
    genre_map,
    genre_names,
    json_body,
    password_error,
    valid_email,
)


auth = Blueprint('auth', __name__, url_prefix='/api')


# Verification/reset codes remain valid for 15 minutes.
CODE_LIFETIME_SECONDS = 15 * 60


# Response mein sirf allowed user fields deni hain, password hash nahi.
def public_user(user):
    """Return only the user fields that are safe to send to the frontend."""

    result = {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "is_admin": user["is_admin"],
        "email_verified": user["email_verified"],
    }

    return result


def new_email_code(user_id, purpose):
    """Create a six-digit verification/reset code, store it in the database and return the code."""

    random_number = secrets.randbelow(1000000)

    code = str(random_number).zfill(6)

    database.create_auth_token(user_id, purpose, code, CODE_LIFETIME_SECONDS)

    return code


def send_email_code(user_id, purpose, email, sender):
    """Keep the previous code if sending the replacement fails."""
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT id FROM users WHERE id=%s FOR UPDATE', (user_id,))
            if not cursor.fetchone():
                return False
        code = new_email_code(user_id, purpose)
        if not sender(email, code):
            connection.rollback()
            return False
    return True


def code_attempt_blocked(group, email):
    """Limit verification/reset code guesses to five attempts per email in fifteen minutes."""

    blocked = take_rate_slot(group, email, 5, 900)

    if blocked:

        return ({'error': 'Too many attempts. Please wait a few minutes and try again.'}, 429)


    return None


def client_ip():
    """Return the client's IP address for public rate limits."""

    ip_address = request.remote_addr

    if not ip_address:
        ip_address = "unknown"

    return ip_address

# REGISTER

@auth.post("/register")
# Input check, password hash, account save, phir verification code.
def register():
    """Create a user account and send a verification code."""

    ip_address = client_ip()

    blocked = rate_limit_reached('register', ip_address, 5, 600)

    if blocked:

        return {
            "error": (
                "You have tried to sign up several times. "
                "Please wait a few minutes and try again."
            )
        }, 429

    # READ INPUT

    data = json_body()

    name = str(data.get('name') or '').strip()

    email = str(data.get('email') or '').strip().lower()

    password = str(data.get('password') or '')

    # VALIDATE INPUT

    if len(name) < 2:

        return ({'error': 'Name must be between 2 and 100 characters.'}, 400)

    if len(name) > 100:

        return ({'error': 'Name must be between 2 and 100 characters.'}, 400)

    if not valid_email(
        email
    ):

        return ({'error': 'Enter a valid email address.'}, 400)

    error = password_error(password)

    if error:

        return ({'error': error}, 400)

    # SECURITY ORDER:
    # Do not move this above validation.
    # Typing mistakes must not consume signup attempts.
    if take_rate_slot('register', ip_address, 5, 600):
        return {'error': 'Too many signup attempts. Please wait a few minutes.'}, 429

    # CREATE USER

    password_hash = generate_password_hash(password)

    user_id = database.create_user(name, email, password_hash)

    # If the address was actually registered,
    # create and send its verification code.
    if user_id:

        send_email_code(user_id, 'verify', email, send_verification)

    # SECURITY:
    # Always return the same message whether the
    # address was actually registered or not.
    return {
        "message": (
            "Check your inbox for a verification code. "
            "If it does not arrive, use Resend code."
        )
    }, 201

# LOGIN

@auth.post("/login")
# Password aur verification check karke login token dena.
def login():
    """Authenticate a verified user and return a JWT token."""

    data = json_body()

    email = str(data.get('email') or '').strip().lower()

    password = str(data.get('password') or '')

    ip_address = client_ip()

    # IP RATE LIMIT

    ip_blocked = take_rate_slot('login-ip', ip_address, 20, 600)

    if ip_blocked:

        return {
            "error": (
                "Too many sign-in attempts. "
                "Please wait a few minutes and try again."
            )
        }, 429

    # EMAIL RATE LIMIT

    email_blocked = rate_limit_reached('login-email', email, 5, 900)

    if email_blocked:

        return {
            "error": (
                "Too many sign-in attempts. "
                "Please wait a few minutes and try again."
            )
        }, 429

    # LOOK UP USER

    user = database.get_user_by_email(email)

    password_correct = False

    if user:

        password_correct = check_password_hash(user['password_hash'], password)

    # WRONG EMAIL / PASSWORD

    if not user or not password_correct:

        # SECURITY ORDER:
        # Email-specific attempts are recorded ONLY
        # when credentials actually fail.
        if take_rate_slot('login-email', email, 5, 900):
            return {'error': 'Too many sign-in attempts. Please try again later.'}, 429

        return ({'error': 'Email or password is incorrect.'}, 401)

    # EMAIL NOT VERIFIED

    if not user["email_verified"]:

        return ({'error': 'Please verify your email before signing in.'}, 403)

    # SUCCESS

    # SECURITY ORDER:
    # Clear failed attempts only after a successful,
    # verified login.
    clear_rate_events('login-email', email)

    token = create_login_token(user)

    safe_user = public_user(user)

    return {'token': token, 'user': safe_user}

# LOGOUT

@auth.post("/logout")
@login_required
# Session version badalni hai taake purane tokens kaam na karein.
def logout():
    """End the current user's existing login sessions."""

    user_id = g.current_user['id']

    database.end_user_sessions(user_id)

    return {'message': 'Signed out successfully.'}

# VERIFY EMAIL

@auth.post("/verify-email")
# Sahi unused OTP par email verified mark karni hai.
def verify_email():
    """Verify an email address using its six-digit code."""

    data = json_body()

    email = str(data.get('email') or '').strip().lower()

    code = str(data.get('code') or '').strip()

    # LIMIT CODE GUESSES

    blocked = code_attempt_blocked('verify-code', email)

    if blocked:
        return blocked

    # FIND USER

    user = database.get_user_by_email(email)

    user_id = None

    if user:

        user_id = database.consume_auth_token(user['id'], code, 'verify')

    # Do not reveal whether the email was wrong,
    # the code was wrong, or the code expired.
    if not user_id:

        return ({'error': 'That code is not correct, or it has expired.'}, 400)

    # SUCCESS

    database.verify_user_email(user_id)

    clear_rate_events('verify-code', email)

    return {'message': 'Email verified. You can now sign in.'}

# RESEND VERIFICATION

@auth.post("/resend-verification")
def resend_verification():
    """Send a new verification code when appropriate."""

    ip_address = client_ip()

    blocked = take_rate_slot('verify-email', ip_address, 5, 900)

    if blocked:

        return {
            "error": (
                "You have asked for several codes. "
                "Please wait a few minutes and try again."
            )
        }, 429


    data = json_body()

    email = str(data.get('email') or '').strip().lower()

    user = database.get_user_by_email(email)

    if user:

        if not user["email_verified"]:

            send_email_code(user['id'], 'verify', email, send_verification)

    # SECURITY:
    # Do not reveal whether this address exists
    # or whether it was already verified.
    return {'message': 'If the account needs verification, a new code has been sent.'}

# FORGOT PASSWORD

@auth.post("/forgot-password")
# Response se yeh reveal nahi karna ke email registered hai ya nahi.
def forgot_password():
    """Send a password reset code when the account exists."""

    ip_address = client_ip()

    blocked = take_rate_slot('password-email', ip_address, 5, 900)

    if blocked:

        return {
            "error": (
                "You have asked for several reset codes. "
                "Please wait a few minutes and try again."
            )
        }, 429


    data = json_body()

    email = str(data.get('email') or '').strip().lower()

    user = database.get_user_by_email(email)

    if user:

        if not send_email_code(user['id'], 'reset', email, send_password_reset):
            current_app.logger.warning('Password reset email could not be sent.')

    # SECURITY:
    # Always use the same response whether the
    # account exists or not.
    return {'message': (
        'If the account exists, a password reset code has been requested. '
        'Check your inbox and spam folder. If no new code arrives, '
        'your previous unexpired code still works. Try again later.'
    )}

# RESET PASSWORD

@auth.post("/reset-password")
# Reset code check karke naya password save karna.
def reset_password():
    """Reset a password using a valid reset code."""

    data = json_body()

    email = str(data.get('email') or '').strip().lower()

    code = str(data.get('code') or '').strip()

    password = str(data.get('password') or '')

    # VALIDATE NEW PASSWORD FIRST

    # SECURITY ORDER:
    # This MUST remain before code_attempt_blocked().
    # A weak password must not consume one of the
    # user's five reset-code attempts.
    error = password_error(password)

    if error:

        return ({'error': error}, 400)

    # COUNT CODE ATTEMPT

    blocked = code_attempt_blocked('reset-code', email)

    if blocked:
        return blocked

    user = database.get_user_by_email(email)
    password_hash = generate_password_hash(password)
    updated = False
    if user:
        updated = database.apply_password_code(user['id'], code, 'reset', password_hash)
    if not updated:
        return {'error': 'That code is not correct, or it has expired.'}, 400

    clear_rate_events('reset-code', email)

    return {'message': 'Password updated. You can now sign in.'}

# PROFILE

@auth.get("/profile")
@login_required
def profile():
    """Return the current user's public profile, interests and library book count."""

    user_id = g.current_user['id']

    user = public_user(g.current_user)

    stored_interests = database.get_user_interests(user_id)

    user['interests'] = genre_names(stored_interests)

    user['book_count'] = database.count_user_books(user_id)

    return {'user': user}

# AVAILABLE INTERESTS

def available_interests():
    """Return the unique genre labels used by Bookrift's catalogue, sorted alphabetically."""

    subjects = {}

    catalogue_values = database.catalogue_subjects()

    for value in catalogue_values:

        genre_dictionary = genre_map(value)

        for key, label in genre_dictionary.items():

            subjects[key] = label

    interests = list(subjects.values())

    interests.sort(key=str.casefold)

    return interests

# GET INTERESTS

@auth.get("/interests")
@login_required
def interests():
    """Return available interests and the user's selections."""

    user_id = g.current_user['id']

    stored_interests = database.get_user_interests(user_id)

    selected = genre_names(stored_interests)

    available = available_interests()

    return {'available': available, 'selected': selected}

# UPDATE INTERESTS

@auth.post("/profile/interests")
@login_required
def update_interests():
    """Replace the user's selected interests."""

    data = json_body()

    chosen = data.get('interests')

    # Must be a JSON list.
    if not isinstance(
        chosen,
        list,
    ):

        return ({'error': 'Interests must be sent as a list.'}, 400)

    # Maximum five interests.
    if len(chosen) > 5:

        return ({'error': 'Choose up to 5 interests.'}, 400)

    # BUILD ALLOWED INTEREST LOOKUP

    allowed = {}

    available = available_interests()

    for item in available:

        key = item.casefold()

        allowed[key] = item

    # VALIDATE CHOSEN INTERESTS

    cleaned = []

    for item in chosen:

        submitted_name = str(item).strip()

        submitted_key = submitted_name.casefold()

        name = allowed.get(submitted_key)

        if not name:

            return ({'error': 'Choose interests from the available list.'}, 400)

        # Avoid duplicates while preserving order.
        if name not in cleaned:

            cleaned.append(name)

    # SAVE

    stored_value = ', '.join(cleaned)

    database.set_user_interests(g.current_user['id'], stored_value)

    return {'interests': cleaned}

# CHANGE PASSWORD

@auth.post("/profile/password/code")
@login_required
def request_password_change_code():
    user = g.current_user
    email = user['email']
    if take_rate_slot('change-password-email', email, 5, 900):
        return {'error': 'Too many requests. Please try again later.'}, 429
    data = json_body()
    password = str(data.get('current_password') or '')
    if not check_password_hash(user['password_hash'], password):
        return {'error': 'Current password is incorrect.'}, 400
    if not send_email_code(user['id'], 'change_password', email, send_password_change):
        return {'error': (
            'Email could not be sent. Your previous unexpired code still works. '
            'Please try again later or contact the administrator.'
        )}, 503
    return {'message': 'A 6-digit code was sent to your account email. It expires in 15 minutes.'}


@auth.post("/profile/password")
@login_required
# Current password aur OTP dono sahi hon to naya password save karna.
def change_password():
    """Require the current password and an emailed OTP before changing it."""
    data = json_body()
    current_password = str(data.get('current_password') or '')
    new_password = str(data.get('new_password') or '')
    code = str(data.get('code') or '').strip()
    user = g.current_user
    error = password_error(new_password)
    if error:
        return {'error': error}, 400
    if len(code) != 6 or not code.isdigit():
        return {'error': 'Enter the 6-digit code sent to your account email.'}, 400
    if take_rate_slot('change-password-current', user['email'], 5, 900):
        return {'error': 'Too many password attempts. Please try again in 15 minutes.'}, 429
    if not check_password_hash(user['password_hash'], current_password):
        return {'error': 'Current password is incorrect.'}, 400
    clear_rate_events('change-password-current', user['email'])
    blocked = code_attempt_blocked('change-password-code', user['email'])
    if blocked:
        return blocked
    password_hash = generate_password_hash(new_password)
    updated = database.apply_password_code(user['id'], code, 'change_password', password_hash)
    if not updated:
        return {'error': 'That code is not correct, or it has expired.'}, 400
    clear_rate_events('change-password-code', user['email'])
    return {'message': 'Password changed. Please sign in again.'}

# DELETE PROFILE

@auth.delete("/profile")
@login_required
# Password confirm karke account hatana; admin account ko yahan nahi hatana.
def delete_profile():
    """Delete the current user's account after verifying their password."""

    # Admin account cannot be removed from this route.
    if g.current_user["is_admin"]:

        return ({'error': 'The admin account cannot be deleted here.'}, 400)

    data = json_body()

    password = str(data.get('password') or '')

    password_correct = check_password_hash(g.current_user['password_hash'], password)

    if not password_correct:

        return ({'error': 'Password is incorrect.'}, 400)

    database.delete_user(g.current_user['id'])

    return {'message': 'Your account has been deleted.'}
