from flask import (
    Blueprint,
    g,
    send_from_directory,
)

import json
import config
import database

from services.recommendations import (
    fit_for_reader,
    rank_books,
    recommendation_reason,
)

from utils.security import login_required

from utils.validation import (
    genre_map,
    genre_names,
    json_body,
)


books = Blueprint('books', __name__)


READING_STATUSES = {'want_to_read', 'reading', 'finished'}


def known_genres(value):
    """Keep only genre labels that exist in Bookrift's own catalogue."""

    catalogue = {}

    catalogue_rows = database.catalogue_subjects()

    for row in catalogue_rows:

        row_genres = genre_map(row)

        for key, label in row_genres.items():

            catalogue[key] = label

    names = []

    incoming_names = genre_names(value)

    for name in incoming_names:

        key = name.casefold()

        label = catalogue.get(key)

        if not label:
            continue

        if label in names:
            continue

        names.append(label)

    return names


def catalogue_reference(book):
    if book.get('provider') != 'catalogue':
        return {}
    if book.get('catalogue_status') != 'VERIFIED':
        return {'catalogue_note': (
            'This older catalogue record needs review and is not used for '
            'recommendations.'
        )}
    with (config.BASE_DIR / 'catalogue.json').open(encoding='utf-8') as file:
        for entry in json.load(file):
            if (entry['title'] == book['title'] and entry['author'] == book['author']):
                note = (
                    'Title and author checked against the linked source. Genres are '
                    'Bookrift classification labels.'
                )
                edition_agrees = True
                for field in ('isbn_13', 'publisher', 'published_date', 'page_count'):
                    if entry.get(field) != book.get(field):
                        edition_agrees = False
                if entry.get('edition_checked') and edition_agrees:
                    note += (
                        ' Listed ISBN, publisher, date and pages refer to one checked '
                        'reference edition.'
                    )
                else:
                    note += ' Edition details in this record are not covered by this source check.'
                note += ' The cover is representative and may show another printing.'
                return {
                    'catalogue_source_url': entry['source_url'],
                    'catalogue_note': note,
                    'rating_source': entry.get('rating_source', ''),
                    'rating_source_url': entry.get('rating_source_url', ''),
                    'ratings_checked_at': entry.get('ratings_checked_at', ''),
                    'overview_source_url': entry.get('overview_source_url', ''),
                }
    return {'catalogue_note': (
        'Admin-managed catalogue entry; check its sources before relying on '
        'edition details.'
    )}


# Book details ko frontend ke response format mein lana.
def book_json(book, full=False):
    """Convert a database book record into the JSON structure returned by Bookrift's API."""

    if book["catalogue_status"] == "VERIFIED":

        source = "Verified catalogue"

    elif book["provider"] == "catalogue":
        source = "Catalogue — needs review"

    elif book["provider"] == "google_books":

        source = "Google Books"

    elif book["provider"] == "open_library":

        source = "Open Library"

    else:

        source = "Book provider"

    if book["rating"] is not None:

        rating = float(book['rating'])

    else:

        rating = None

    page_count_source = book.get('page_count_source')

    if not page_count_source:
        page_count_source = ""

    result = {
        "id": book["id"],
        "title": book["title"],
        "author": book["author"],
        "isbn_10": book["isbn_10"],
        "isbn_13": book["isbn_13"],
        "publisher": book["publisher"],
        "published_date": book["published_date"],
        "genres": known_genres(
            book["genres"]
        ),
        "cover_url": book["cover_url"],
        "page_count": book["page_count"],
        "page_count_source": page_count_source,
        "rating": rating,
        "ratings_count": book["ratings_count"],
        "on_shelves": book["on_shelves"],
        "source": source,
    }

    if full:
        result.update(catalogue_reference(book))

        overview = book['overview'] or ''

        if overview:

            overview_status = "ready"

        else:

            overview_status = "unavailable"

        result['description'] = book['description']

        result["overview"] = overview

        result['overview_status'] = overview_status

    return result


@books.get("/covers/<int:cover_id>.jpg")
def cover_image(cover_id):
    """Serve a stored catalogue cover image."""

    filename = str(cover_id) + '.jpg'

    cache_seconds = 30 * 24 * 60 * 60

    return send_from_directory(config.COVER_FOLDER, filename, max_age=cache_seconds)


@books.get("/api/catalogue/<int:book_id>")
@login_required
# Catalogue book ki details deni hain.
def catalogue_detail(book_id):
    """Return verified book details with the reader's library and taste information."""

    book = database.get_catalogue_book(book_id)

    if not book:

        return ({'error': 'Book not found.'}, 404)

    if book["catalogue_status"] != "VERIFIED":

        return ({'error': 'Book not found.'}, 404)

    user_id = g.current_user['id']

    library = database.get_library_item(user_id, book_id)

    if library:

        library_id = library['id']

        favorite = library['favorite']

        reading_status = library['reading_status']

    else:

        library_id = None
        favorite = False
        reading_status = "identified"

    reader_fit = fit_for_reader(user_id, book)

    return {
        "book": book_json(
            book,
            full=True,
        ),
        "library_id": library_id,
        "favorite": favorite,
        "reading_status": reading_status,
        "for_you": reader_fit,
    }


@books.post("/api/catalogue/<int:book_id>/read")
@login_required
# Catalogue ki book current user ki library mein add karni hai.
def save_catalogue_book(book_id):
    """Add a verified catalogue book to the current user's library."""

    book = database.get_catalogue_book(book_id)

    if not book:

        return ({'error': 'Book not found.'}, 404)

    if book["catalogue_status"] != "VERIFIED":

        return ({'error': 'Book not found.'}, 404)

    data = json_body()

    status = data.get('reading_status')

    if not status:
        status = "finished"

    status = str(status)

    if status not in READING_STATUSES:

        return ({'error': 'Invalid reading status.'}, 400)

    user_id = g.current_user['id']

    library_id = database.add_to_library(user_id, book_id, status)

    # A status the reader already set is not replaced by this route, so read
    # back what is actually stored. Reporting the requested status instead
    # would tell the reader the book is finished while it is still reading.
    saved = database.get_library_item(user_id, book_id)

    if saved:
        status = saved["reading_status"]

    return {'library_id': library_id, 'book_id': book_id, 'reading_status': status}


@books.get("/api/closest")
@login_required
# Reader ke genres ke hisaab se catalogue suggestions leni hain.
def closest_books():
    """Return up to three catalogue books that best match the current reader's taste."""

    user_id = g.current_user['id']

    rows = database.list_catalogue('VERIFIED')

    ranked = rank_books(user_id, rows, exclude_owned=True, limit=3)

    result = []

    for ranked_item in ranked:

        book = ranked_item[0]
        shared = ranked_item[1]
        evidence = ranked_item[2]

        if not shared:
            continue

        item = book_json(book)

        reason = recommendation_reason(shared, evidence)

        item["reason"] = reason

        result.append(item)

    return {'books': result}


@books.get('/api/books/<int:book_id>')
@login_required
# Verified catalogue book ya apni library ki book ki details deni hain.
def saved_book_detail(book_id):
    book = database.get_book(book_id)
    library = database.get_library_item(g.current_user['id'], book_id)
    if not book or (book['catalogue_status'] != 'VERIFIED' and not library):
        return {'error': 'Book not found.'}, 404
    book_data = book_json(book, full=True)
    if library:
        library_id = library['id']
        favorite = library['favorite']
        reading_status = library['reading_status']
    else:
        library_id = None
        favorite = False
        reading_status = 'identified'
    return {
        'book': book_data,
        'library_id': library_id,
        'favorite': favorite,
        'reading_status': reading_status,
        'for_you': fit_for_reader(g.current_user['id'], book),
    }
