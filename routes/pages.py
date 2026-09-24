from pathlib import Path

from flask import (
    Blueprint,
    request,
    send_file,
    send_from_directory,
)

import config
import database
from utils.security import (
    take_rate_slot,
)
from utils.validation import json_body, valid_email


pages = Blueprint('pages', __name__)


# Browser ko frontend ki index.html deni hai.
def frontend_page():
    """Return the frontend index page if it exists."""

    index_file = config.FRONTEND_FOLDER / 'index.html'

    if index_file.is_file():

        return send_file(index_file)

    return {'message': 'Bookrift API is running.', 'frontend_ready': False}


@pages.get("/")
def home():
    """Serve the main Bookrift frontend page."""

    return frontend_page()


@pages.get("/assets/<path:filename>")
def frontend_asset(filename):
    """Serve frontend files from the assets folder."""

    frontend_folder = Path(config.FRONTEND_FOLDER)

    asset_folder = frontend_folder / 'assets'

    return send_from_directory(asset_folder, filename)


@pages.get("/api/health")
# Database tak connection chal raha hai ya nahi, yahan check karna.
def health():
    """Check whether the application and database are available."""

    try:

        connection = database.get_db()

        with connection.cursor() as cursor:

            cursor.execute('SELECT 1')

            cursor.fetchone()

    except Exception:

        return ({'status': 'unavailable', 'database': 'unavailable'}, 503)

    return {'status': 'ok', 'database': 'available'}


@pages.post("/api/contact")
# Contact form validate karke message database mein rakhna.
def contact():
    """Validate and save a contact-form message."""

    # RATE LIMIT

    client_ip = request.remote_addr

    if not client_ip:
        client_ip = "unknown"

    limit_hit = take_rate_slot('contact', client_ip, 5, 60 * 60)

    if limit_hit:

        return ({'error': 'You have sent several messages recently. Please try again later.'}, 429)


    # READ JSON INPUT

    data = json_body()

    name = str(data.get('name') or '').strip()

    email = str(data.get('email') or '').strip().lower()

    subject = str(data.get('subject') or '').strip()

    message = str(data.get('message') or '').strip()

    # VALIDATE NAME

    if len(name) < 2:

        return ({'error': 'Name must be between 2 and 100 characters.'}, 400)

    if len(name) > 100:

        return ({'error': 'Name must be between 2 and 100 characters.'}, 400)

    # VALIDATE EMAIL

    if not valid_email(
        email
    ):

        return ({'error': 'Enter a valid email address.'}, 400)

    # VALIDATE SUBJECT

    if len(subject) > 200:

        return ({'error': 'Subject is too long.'}, 400)

    # VALIDATE MESSAGE

    if len(message) < 10:

        return ({'error': 'Message must be between 10 and 3000 characters.'}, 400)

    if len(message) > 3000:

        return ({'error': 'Message must be between 10 and 3000 characters.'}, 400)

    # SAVE MESSAGE

    database.save_message(name, email, subject, message)

    return ({'message': 'Thanks. Your message has been received.'}, 201)
