from datetime import date, datetime
from decimal import Decimal

import psycopg2
from flask import Blueprint, request

import config
import database

from utils.security import admin_required
from utils.validation import (
    genre_names,
    json_body,
    normalize_isbn,
    valid_isbn,
)


admin = Blueprint('admin', __name__, url_prefix='/api/admin')


CATALOGUE_STATUSES = {'PENDING', 'VERIFIED', 'REJECTED', 'NEEDS_REVIEW'}


FIELD_LIMITS = {
    "title": 240,
    "author": 180,
    "isbn_10": 10,
    "isbn_13": 13,
    "google_books_id": 120,
    "open_library_edition_id": 120,
    "open_library_work_id": 120,
    "publisher": 180,
    "published_date": 30,
    "genres": 500,
    "description": 20000,
    "overview": 4000,
    "cover_url": 1000,
}


def json_value(value):
    """Convert database values into JSON-friendly values."""

    if isinstance(
        value,
        (datetime, date),
    ):
        return value.isoformat()

    if isinstance(
        value,
        Decimal,
    ):
        return float(value)

    return value


def row_json(row):
    """Convert one database row into a normal JSON-friendly dictionary."""

    original = dict(row)

    result = {}

    for key, value in original.items():

        result[key] = json_value(value)

    return result


def admin_book_json(book):
    """Convert one catalogue book into the structure shown in the admin interface."""

    data = row_json(book)
    from routes.books import catalogue_reference
    data.update(catalogue_reference(book))

    data['genres'] = genre_names(data['genres'])

    # Internal normalized fields are not exposed
    # in the admin response.
    data.pop('normalized_title', None)

    data.pop('normalized_author', None)

    return data


# Admin form ki values saaf karke database ke liye ready karni hain.
def clean_catalogue_data(data):
    """Clean only the catalogue fields that are allowed to be created or updated."""

    cleaned = {}

    # COPY ALLOWED CATALOGUE FIELDS

    for field in database.CATALOGUE_FIELDS:

        if field not in data:
            continue

        value = data[field]

        # NORMALIZE GENRES

        if field == "genres":

            # Admin may send:
            # ["Fantasy", "Mystery"]
            #
            # or:
            # "Fantasy; Mystery"
            #
            # Store them in one consistent format.
            if isinstance(
                value,
                list,
            ):

                genre_parts = []

                for item in value:

                    genre_parts.append(str(item))

                value = ', '.join(genre_parts)

            cleaned_genres = genre_names(value)

            value = ', '.join(cleaned_genres)

        # TRIM STRING VALUES

        if isinstance(
            value,
            str,
        ):

            value = value.strip()

        cleaned[field] = value

    # NORMALIZE ISBN VALUES

    isbn_fields = ('isbn_10', 'isbn_13')

    for field in isbn_fields:

        value = cleaned.get(field)

        if not value:
            continue

        normalized = normalize_isbn(value)

        # IMPORTANT:
        # If invalid text such as "abcdefghij" normalizes
        # to an empty string, keep the original value here.
        #
        # catalogue_error() must still be able to reject it.
        if normalized:

            cleaned[field] = normalized

        else:

            cleaned[field] = value

    return cleaned


# Galat status, ISBN ya field values save karne se pehle rokni hain.
def catalogue_error(data, creating=False):
    """Validate catalogue data."""

    # TITLE REQUIRED

    should_check_title = creating or 'title' in data

    if should_check_title:

        title = str(data.get('title') or '').strip()

        if not title:

            return "Title is required."

    # FIELD LENGTH LIMITS

    for field, maximum in FIELD_LIMITS.items():

        if field not in data:
            continue

        value = str(data.get(field) or '')

        if len(value) > maximum:

            field_name = field.replace('_', ' ').title()

            return f'{field_name} is too long.'

    # ISBN VALIDATION

    isbn_fields = ('isbn_10', 'isbn_13')

    for field in isbn_fields:

        value = data.get(field)

        if not value:
            continue

        if not valid_isbn(
            value
        ):

            display_name = field.replace('_', '-').upper()

            return f'{display_name} is invalid.'

    # CATALOGUE STATUS VALIDATION

    status = data.get('catalogue_status')

    if 'catalogue_status' in data:

        if not isinstance(status, str):
            return "Invalid catalogue status."

        if status not in CATALOGUE_STATUSES:

            return "Invalid catalogue status."

    return ""

# DASHBOARD STATS

@admin.get("/stats")
@admin_required
# Admin dashboard ke counts aur recent activity leni hai.
def dashboard_stats():
    """Return admin dashboard statistics, recent scans and recent contact messages."""

    raw_stats = database.get_admin_stats()

    stats = {}

    for key, value in raw_stats.items():

        stats[key] = json_value(value)

    # RECENT SCANS

    recent_scan_rows = database.get_recent_scans(10)

    recent_scans = []

    for row in recent_scan_rows:

        recent_scans.append(row_json(row))

    stats["recent_scans"] = recent_scans

    # RECENT CONTACT MESSAGES

    recent_message_rows = database.get_recent_messages(5)

    recent_messages = []

    for row in recent_message_rows:

        recent_messages.append(row_json(row))

    stats["recent_messages"] = recent_messages

    return stats

# ADMIN CATALOGUE LIST

@admin.get("/catalogue")
@admin_required
def admin_catalogue():
    """Return catalogue books for the admin interface."""

    # READ STATUS FILTER

    status = request.args.get('status')

    if not status:
        status = ""

    status = str(status).strip().upper()

    if status:

        if status not in CATALOGUE_STATUSES:

            return ({'error': 'Invalid catalogue status.'}, 400)

    # READ SEARCH QUERY

    search = request.args.get('q')

    if not search:
        search = ""

    search = str(search).strip()

    search = search[:120]

    # GET CATALOGUE

    rows = database.list_catalogue(status, search)

    books = []

    for row in rows:

        books.append(admin_book_json(row))

    return {'total': len(rows), 'books': books}

# CREATE CATALOGUE RECORD

@admin.post("/catalogue")
@admin_required
# Valid admin input se catalogue book banani hai.
def create_catalogue_record():
    """Create one new catalogue record."""

    data = json_body()

    data = clean_catalogue_data(data)

    # VALIDATE

    error = catalogue_error(data, creating=True)

    if error:

        return ({'error': error}, 400)

    # CHECK DUPLICATE IDENTIFIERS

    duplicate = database.find_book_by_identifiers(data)

    if duplicate:

        return ({'error': 'A book with this ISBN or provider ID already exists.'}, 409)

    # CREATE

    book_id = database.create_catalogue_book(data)

    if not book_id:

        return ({'error': 'The catalogue record could not be created.'}, 409)

    return ({'message': 'Catalogue record created.', 'id': book_id}, 201)

# UPDATE CATALOGUE RECORD

@admin.route(
    "/catalogue/<int:book_id>",
    methods=["POST", "PATCH"],
)
@admin_required
# Existing book check karke valid changes save karni hain.
def update_catalogue_record(book_id):
    """Update an existing catalogue record."""

    data = json_body()

    data = clean_catalogue_data(data)

    # VALIDATE

    error = catalogue_error(data)

    if error:

        return ({'error': error}, 400)

    # UPDATE DATABASE

    try:

        updated = database.update_catalogue_book(book_id, data)

    except psycopg2.errors.UniqueViolation:

        # IMPORTANT:
        # PostgreSQL transaction is in an error state
        # after the constraint violation, so rollback
        # must happen before continuing to use it.
        database.get_db().rollback()

        return ({'error': 'A book with this ISBN or provider ID already exists.'}, 409)

    if not updated:

        return ({'error': 'Catalogue record not found.'}, 404)

    return {'message': 'Catalogue record updated.'}

# IDENTIFICATION REVIEW

@admin.get("/identifications")
@admin_required
def identification_review():
    """Return recent identification attempts for admin review."""

    raw_limit = request.args.get('limit', 100)

    try:

        limit = int(raw_limit)

    except ValueError:

        return ({'error': 'Limit must be a number.'}, 400)

    # Minimum = 1
    if limit < 1:
        limit = 1

    # Maximum = 200
    if limit > 200:
        limit = 200

    rows = database.list_identification_attempts(limit)

    attempts = []

    for row in rows:

        attempts.append(row_json(row))

    return {'total': len(rows), 'attempts': attempts}

# SYSTEM STATUS

@admin.get("/system")
@admin_required
def system_status():
    """Return a simple admin-facing system status summary."""

    stats = database.get_admin_stats()

    google_configured = bool(config.GOOGLE_BOOKS_API_KEY)

    return {
        "database": "available",

        "catalogue": {
            "verified": stats[
                "catalogue_verified"
            ],
            "pending": stats[
                "catalogue_pending"
            ],
            "needs_review": stats[
                "catalogue_needs_review"
            ],
            "rejected": stats[
                "catalogue_rejected"
            ],
        },

        "google_books_configured": google_configured,

        "ocr": "single-pass PaddleOCR mobile",

        "barcode": "separate ISBN scanner",

        "overview": "source-based summary",
    }


@admin.delete('/catalogue/<int:book_id>')
@admin_required
# Library mein saved book ko delete nahi karne dena.
def delete_catalogue_record(book_id):
    result = database.delete_catalogue_book(book_id)
    if result == 'missing':
        return {'error': 'Book not found.'}, 404
    if result == 'in_use':
        return {'error': (
            'Readers have saved this book. Mark it as rejected to remove it from '
            'recommendations without deleting their library entries.'
        )}, 409
    return {'message': 'Catalogue book deleted.'}, 200
