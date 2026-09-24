from flask import (
    Blueprint,
    g,
    request,
)

import database

from routes.books import book_json
from utils.security import login_required
from utils.validation import json_body


library = Blueprint('library', __name__, url_prefix='/api/history')


READING_STATUSES = {'identified', 'want_to_read', 'reading', 'finished'}


def library_json(row):
    """Convert one library database row into the JSON structure returned to the frontend."""

    added_at = row["added_at"].isoformat()

    book = book_json(row)

    result = {
        "library_id": row["library_id"],
        "favorite": row["favorite"],
        "reading_status": row["reading_status"],
        "added_at": added_at,
        "book": book,
    }

    return result


@library.get("")
@login_required
# Current user ki library ko filters ke saath dikhana hai.
def list_library():
    """Return the current user's library."""

    # READ SEARCH QUERY

    search = request.args.get('q')

    if not search:
        search = ""

    search = str(search).strip().casefold()

    # Keep the same maximum search length.
    search = search[:120]

    # READ READING STATUS FILTER

    status = request.args.get('reading_status')

    if not status:
        status = ""

    status = str(status).strip().lower()

    # READ FAVORITE FILTER

    favorite = request.args.get('favorite')

    if not favorite:
        favorite = ""

    favorite = str(favorite).strip().lower()

    # VALIDATE READING STATUS

    if status:

        if status not in READING_STATUSES:

            return ({'error': 'Invalid reading status.'}, 400)

    # GET CURRENT USER'S LIBRARY

    user_id = g.current_user['id']

    rows = database.get_library(user_id)

    # SEARCH FILTER

    if search:

        matching_rows = []

        for row in rows:

            isbn_10 = row['isbn_10']

            if not isbn_10:
                isbn_10 = ""

            isbn_13 = row['isbn_13']

            if not isbn_13:
                isbn_13 = ""

            searchable_parts = [row['title'], row['author'], isbn_10, isbn_13]

            searchable_text = ' '.join(searchable_parts)

            searchable_text = searchable_text.casefold()

            if search in searchable_text:

                matching_rows.append(row)

        rows = matching_rows

    # READING STATUS FILTER

    if status:

        matching_rows = []

        for row in rows:

            if row["reading_status"] == status:

                matching_rows.append(row)

        rows = matching_rows

    # FAVORITE FILTER

    favorite_requested = favorite == '1' or favorite == 'true' or favorite == 'yes'

    if favorite_requested:

        matching_rows = []

        for row in rows:

            if row["favorite"]:

                matching_rows.append(row)

        rows = matching_rows

    # CONVERT DATABASE ROWS TO API JSON

    items = []

    for row in rows:

        item = library_json(row)

        items.append(item)

    return {'total': len(rows), 'items': items}


@library.post("/<int:library_id>/favorite")
@login_required
# Favourite badalna, lekin entry isi user ki honi chahiye.
def toggle_library_favorite(library_id):
    """Toggle the favorite state of one library item."""

    user_id = g.current_user['id']

    favorite = database.toggle_favorite(user_id, library_id)

    if favorite is None:

        return ({'error': 'Library item not found.'}, 404)

    return {'favorite': favorite}


@library.patch("/<int:library_id>/reading")
@login_required
# Allowed reading status check karke save karna.
def change_reading_status(library_id):
    """Change the reading status of one library item."""

    data = json_body()

    status = data.get('reading_status')

    if not status:
        status = ""

    status = str(status).strip().lower()

    # VALIDATE STATUS

    if status not in READING_STATUSES:

        return ({'error': 'Invalid reading status.'}, 400)

    # UPDATE DATABASE

    user_id = g.current_user['id']

    updated = database.update_reading_status(user_id, library_id, status)

    if not updated:

        return ({'error': 'Library item not found.'}, 404)

    return {
        "library_id": updated["id"],
        "favorite": updated["favorite"],
        "reading_status": updated["reading_status"],
    }


@library.delete("/<int:library_id>")
@login_required
# Sirf apni library se entry remove karni hai.
def delete_library_item(library_id):
    """Remove one book from the current user's library."""

    user_id = g.current_user['id']

    removed = database.remove_library_item(user_id, library_id)

    if not removed:

        return ({'error': 'Library item not found.'}, 404)

    return {'message': 'Book removed from your library.'}
