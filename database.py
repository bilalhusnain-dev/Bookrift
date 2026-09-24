from contextlib import closing, contextmanager

import hashlib
import re
from datetime import datetime, timedelta, timezone

import psycopg2
from flask import current_app, g
from psycopg2.extras import Json, RealDictCursor

import config

# DATABASE CONNECTION

def open_connection(database_url=None):
    # Connection kholna; result mein column ke naam se value milegi.
    if database_url:
        url = database_url
    else:
        url = config.DATABASE_URL

    return psycopg2.connect(url, cursor_factory=RealDictCursor)


def get_db():
    # Isi request mein pehle se khula connection dobara use karna.
    if "database" not in g:

        database_url = current_app.config.get('DATABASE_URL', config.DATABASE_URL)

        g.database = open_connection(database_url)

    return g.database


def close_db(error=None):
    connection = g.pop('database', None)

    if connection is not None:
        connection.close()


def init_app(app):
    app.teardown_appcontext(close_db)


def init_db():
    # Tables aur constraints schema.sql se banane hain.
    schema_path = config.BASE_DIR / 'schema.sql'

    connection = get_db()

    with schema_path.open(encoding="utf-8") as schema_file:
        sql = schema_file.read()

    with connection.cursor() as cursor:
        cursor.execute(sql)

    commit_db()

# GENERAL HELPERS

def rate_limit_status(group, key_hash, limit, window_seconds, record=False):
    """Check and optionally count a request under one database lock."""
    # Same key ka lock busy ho to wait; transaction khatam ho to lock release.
    url = current_app.config.get('DATABASE_URL', config.DATABASE_URL)
    with closing(open_connection(url)) as connection:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    'SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
                    (group + ':' + key_hash,),
                )
                cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
                cursor.execute(
                    'DELETE FROM rate_events WHERE group_name=%s AND key_hash=%s '
                    'AND occurred_at <= %s',
                    (group, key_hash, cutoff),
                )
                cursor.execute(
                    'SELECT COUNT(*) AS total FROM rate_events '
                    'WHERE group_name=%s AND key_hash=%s',
                    (group, key_hash),
                )
                count = cursor.fetchone()['total']
                if limit is not None and count >= limit:
                    return True
                if record:
                    cursor.execute(
                        'INSERT INTO rate_events (group_name, key_hash, occurred_at) '
                        'VALUES (%s, %s, clock_timestamp())',
                        (group, key_hash),
                    )
    return False


def clear_stored_rate_events(group, key_hash):
    # Sirf is group aur key ke rate-limit attempts reset karne hain.
    # Same key ka lock busy ho to wait; transaction khatam ho to lock release.
    url = current_app.config.get('DATABASE_URL', config.DATABASE_URL)
    with closing(open_connection(url)) as connection:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    'SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
                    (group + ':' + key_hash,),
                )
                cursor.execute(
                    'DELETE FROM rate_events WHERE group_name=%s AND key_hash=%s',
                    (group, key_hash),
                )


def normalize_key(value):
    text = str(value or '').casefold()

    text = re.sub('[^\\w]+', ' ', text)

    words = text.split()

    normalized = ' '.join(words)

    return normalized


def clean_identifier(value):
    value = str(value or '').strip()

    if value:
        return value

    return None

# USERS

def create_user(name, email, password_hash, is_admin=False, email_verified=False):
    # Naya user save karna; duplicate email ho to None aayega.
    connection = get_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO users
                    (name, email, password_hash, is_admin, email_verified)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (name, email, password_hash, is_admin, email_verified),
            )

            row = cursor.fetchone()

            user_id = row['id']

        commit_db()

        return user_id

    except psycopg2.errors.UniqueViolation:
        connection.rollback()

        return None


def get_user_by_email(email):
    # Email se user nikalna; na mile to None aayega.
    with get_db().cursor() as cursor:
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        return cursor.fetchone()


def get_user_by_id(user_id):
    with get_db().cursor() as cursor:
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        return cursor.fetchone()


def verify_user_email(user_id):
    connection = get_db()

    with connection.cursor() as cursor:
        cursor.execute('UPDATE users SET email_verified = TRUE WHERE id = %s', (user_id,))

    commit_db()


def update_user_password(user_id, password_hash):
    connection = get_db()

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (password_hash, user_id),
        )

    commit_db()


def end_user_sessions(user_id):
    # Version barhana taake purane login tokens reject ho jayein.
    connection = get_db()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE users
            SET auth_version = auth_version + 1
            WHERE id = %s
            """,
            (user_id,),
        )

    commit_db()


def get_user_interests(user_id):
    with get_db().cursor() as cursor:
        cursor.execute("SELECT interests FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()

    if row:
        return row["interests"]

    return ""


def set_user_interests(user_id, interests):
    connection = get_db()

    with connection.cursor() as cursor:
        cursor.execute('UPDATE users SET interests = %s WHERE id = %s', (interests, user_id))

    commit_db()


def count_user_books(user_id):
    with get_db().cursor() as cursor:
        cursor.execute('SELECT COUNT(*) AS total FROM library WHERE user_id = %s', (user_id,))

        row = cursor.fetchone()

        return row['total']

# EMAIL VERIFICATION / RESET TOKENS

def token_digest(user_id, token, purpose=''):
    # Same OTP number ho tab bhi user aur purpose se hash alag rahega.
    return hashlib.sha256(f'{user_id}:{purpose}:{token}'.encode('utf-8')).hexdigest()


def create_auth_token(user_id, purpose, token, lifetime_seconds):
    # Isi user aur purpose ka purana OTP hata kar naya hash save karna.
    token_hash = token_digest(user_id, token, purpose)

    now = datetime.now(timezone.utc)

    lifetime = timedelta(seconds=lifetime_seconds)

    expires_at = now + lifetime

    connection = get_db()

    with connection.cursor() as cursor:
        cursor.execute(
            "DELETE FROM auth_tokens WHERE user_id = %s AND purpose = %s",
            (user_id, purpose),
        )
        cursor.execute(
            """
            INSERT INTO auth_tokens (user_id, purpose, token_hash, expires_at)
            VALUES (%s, %s, %s, %s)
            """,
            (user_id, purpose, token_hash, expires_at),
        )

    commit_db()


def consume_auth_token(user_id, token, purpose):
    # OTP expired ya used ho to reject; sahi ho to used mark karna.
    if not user_id:
        return None

    if not token:
        return None

    token_hash = token_digest(user_id, token, purpose)

    connection = get_db()

    try:
        with connection.cursor() as cursor:

            # Code isi user ka ho; row lock se ek OTP saath mein do baar use nahi hoga.
            cursor.execute(
                """
                SELECT id, user_id, expires_at, used_at
                FROM auth_tokens
                WHERE user_id = %s AND token_hash = %s AND purpose = %s
                FOR UPDATE
                """,
                (user_id, token_hash, purpose),
            )

            row = cursor.fetchone()

            now = datetime.now(timezone.utc)

            if not row:
                connection.rollback()
                return None

            if row["used_at"]:
                connection.rollback()
                return None

            if row["expires_at"] <= now:
                connection.rollback()
                return None

            cursor.execute(
                "UPDATE auth_tokens SET used_at = CURRENT_TIMESTAMP WHERE id = %s",
                (row["id"],),
            )

        commit_db()

        return row['user_id']

    except Exception:
        connection.rollback()
        raise


def apply_password_code(user_id, code, purpose, password_hash):
    """Consume the OTP, change the password and revoke sessions together."""
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT id FROM users WHERE id=%s FOR UPDATE', (user_id,))
            if not cursor.fetchone():
                return False
        if not consume_auth_token(user_id, code, purpose):
            return False
        update_user_password(user_id, password_hash)
        end_user_sessions(user_id)
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM auth_tokens WHERE user_id=%s "
                "AND purpose IN ('reset', 'change_password')",
                (user_id,),
            )
    return True


def delete_user(user_id):
    connection = get_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))

        commit_db()

    except Exception:
        connection.rollback()
        raise

# BOOKS AND CATALOGUE

def get_book(book_id):
    with get_db().cursor() as cursor:
        cursor.execute("SELECT * FROM books WHERE id = %s", (book_id,))
        return cursor.fetchone()


def find_book_by_identifiers(book):
    # SQL column names fixed rakhne hain, user input se nahi lene.
    fields = ('isbn_13', 'isbn_10', 'google_books_id', 'open_library_edition_id')

    connection = get_db()

    with connection.cursor() as cursor:

        for field in fields:

            value = clean_identifier(book.get(field))

            if not value:
                continue

            cursor.execute(f"SELECT * FROM books WHERE {field} = %s", (value,))

            row = cursor.fetchone()

            if row:
                return row

    return None


def find_catalogue_identity(book):
    with get_db().cursor() as cursor:
        cursor.execute(
            "SELECT * FROM books WHERE provider='catalogue' "
            "AND normalized_title=%s AND normalized_author=%s ORDER BY id LIMIT 1",
            (normalize_key(book['title']), normalize_key(book['author'])),
        )
        return cursor.fetchone()


def save_book(book):
    # Book pehle se ho to uski ID leni hai, warna nayi save karni hai.
    identifiers = (
        'isbn_10', 'isbn_13', 'google_books_id',
        'open_library_edition_id', 'open_library_work_id',
    )
    has_identifier = False
    for field in identifiers:
        if book.get(field):
            has_identifier = True
            break
    if not has_identifier:
        title_key = normalize_key(book.get('title'))
        author_key = normalize_key(book.get('author'))
        with get_db().cursor() as cursor:
            cursor.execute(
                'SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
                (title_key + '|' + author_key,),
            )
            cursor.execute(
                'SELECT id FROM books WHERE normalized_title=%s '
                'AND normalized_author=%s ORDER BY id LIMIT 1',
                (title_key, author_key),
            )
            existing = cursor.fetchone()
        if existing:
            commit_db()
            return existing['id']
    existing = find_book_by_identifiers(book)

    if existing:
        return existing["id"]

    title = str(book.get('title') or '').strip()

    author = str(book.get('author') or '').strip()

    connection = get_db()

    try:
        with connection.cursor() as cursor:
            cursor.execute('SAVEPOINT book_insert')
            cursor.execute(
                """
                INSERT INTO books (
                    title, normalized_title, author, normalized_author,
                    isbn_10, isbn_13, google_books_id,
                    open_library_edition_id, open_library_work_id,
                    provider, catalogue_status, publisher, published_date,
                    genres, description, description_source,
                    overview, cover_url, page_count,
                    page_count_source,
                    rating, ratings_count, on_shelves, facts_checked_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                RETURNING id
                """,
                (
                    title,
                    normalize_key(title),
                    author,
                    normalize_key(author),
                    clean_identifier(book.get("isbn_10")),
                    clean_identifier(book.get("isbn_13")),
                    clean_identifier(book.get("google_books_id")),
                    clean_identifier(book.get("open_library_edition_id")),
                    clean_identifier(book.get("open_library_work_id")),
                    book.get("provider") or "external",
                    book.get("catalogue_status"),
                    book.get("publisher") or "",
                    book.get("published_date") or "",
                    book.get("genres") or "",
                    book.get("description") or "",
                    book.get("description_source") or "",
                    book.get("overview") or "",
                    book.get("cover_url") or "",
                    max(0, int(book.get("page_count") or 0)),
                    book.get("page_count_source") or "",
                    book.get("rating"),
                    max(0, int(book.get("ratings_count") or 0)),
                    max(0, int(book.get("on_shelves") or 0)),
                    book.get("facts_checked_at"),
                ),
            )

            row = cursor.fetchone()

            book_id = row['id']

        commit_db()

        return book_id

    except psycopg2.errors.UniqueViolation:

        # Duplicate insert par savepoint tak rollback, phir query chala sakte hain.
        with connection.cursor() as cursor:
            cursor.execute('ROLLBACK TO SAVEPOINT book_insert')

        # Ho sakta hai doosri request ne yeh book is dauran save kar di ho.
        existing = find_book_by_identifiers(book)

        if existing:
            return existing["id"]

        return None


def list_catalogue(status="VERIFIED", search=""):
    # Status aur search ke mutabiq catalogue ki books nikalni hain.
    if status:
        sql = "SELECT * FROM books WHERE catalogue_status = %s"
        params = [status]
    else:
        sql = "SELECT * FROM books WHERE catalogue_status IS NOT NULL"
        params = []

    search = str(search or '').strip()

    if search:
        sql += """
            AND (
                title ILIKE %s OR author ILIKE %s
                OR COALESCE(isbn_10, '') = %s
                OR COALESCE(isbn_13, '') = %s
            )
        """

        like = '%' + search + '%'

        params.extend([like, like, search, search])

    sql += " ORDER BY title, author"

    with get_db().cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def get_catalogue_book(book_id):
    with get_db().cursor() as cursor:
        cursor.execute(
            "SELECT * FROM books WHERE id = %s AND catalogue_status IS NOT NULL",
            (book_id,),
        )
        return cursor.fetchone()


def catalogue_subjects():
    with get_db().cursor() as cursor:
        cursor.execute(
            """
            SELECT genres
            FROM books
            WHERE catalogue_status = 'VERIFIED' AND genres <> ''
            """
        )

        rows = cursor.fetchall()

    genres = []

    for row in rows:

        genres.append(row['genres'])

    return genres


def update_book_overview(book_id, description, source, overview):
    connection = get_db()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE books
            SET description = %s,
                description_source = %s,
                overview = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (description, source, overview, book_id),
        )

    commit_db()


def update_book_facts(book_id, facts):
    connection = get_db()

    ratings_count = max(0, int(facts.get('ratings_count') or 0))

    on_shelves = max(0, int(facts.get('on_shelves') or 0))

    page_count = max(0, int(facts.get('page_count') or 0))

    page_count_source = facts.get('page_count_source') or ''

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE books
            SET rating = %s,
                ratings_count = %s,
                on_shelves = %s,
                page_count = %s,
                page_count_source = %s,
                facts_checked_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (
                facts.get("rating"),
                ratings_count,
                on_shelves,
                page_count,
                page_count_source,
                book_id,
            ),
        )

    commit_db()


CATALOGUE_FIELDS = (
    "title",
    "author",
    "isbn_10",
    "isbn_13",
    "google_books_id",
    "open_library_edition_id",
    "open_library_work_id",
    "catalogue_status",
    "publisher",
    "published_date",
    "genres",
    "description",
    "overview",
    "cover_url",
)


def create_catalogue_book(data):
    book = {}

    for field in CATALOGUE_FIELDS:

        book[field] = data.get(field)

    book["provider"] = "catalogue"

    if not book.get(
        "catalogue_status"
    ):
        book["catalogue_status"] = "PENDING"

    return save_book(book)


def update_catalogue_book(book_id, data):
    current = get_catalogue_book(book_id)

    if not current:
        return False

    values = {}

    for field in CATALOGUE_FIELDS:

        if field in data:
            values[field] = data[field]

        else:
            values[field] = current.get(field)

    connection = get_db()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE books SET
                title = %s,
                normalized_title = %s,
                author = %s,
                normalized_author = %s,
                isbn_10 = %s,
                isbn_13 = %s,
                google_books_id = %s,
                open_library_edition_id = %s,
                open_library_work_id = %s,
                catalogue_status = %s,
                publisher = %s,
                published_date = %s,
                genres = %s,
                description = %s,
                overview = %s,
                cover_url = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (
                values["title"],
                normalize_key(values["title"]),
                values["author"] or "",
                normalize_key(values["author"]),
                clean_identifier(values["isbn_10"]),
                clean_identifier(values["isbn_13"]),
                clean_identifier(values["google_books_id"]),
                clean_identifier(values["open_library_edition_id"]),
                clean_identifier(values["open_library_work_id"]),
                values["catalogue_status"],
                values["publisher"] or "",
                values["published_date"] or "",
                values["genres"] or "",
                values["description"] or "",
                values["overview"] or "",
                values["cover_url"] or "",
                book_id,
            ),
        )

    commit_db()

    return True

# LIBRARY

def add_to_library(user_id, book_id, reading_status="identified"):
    # Same book dobara add ho to duplicate entry nahi banani.
    connection = get_db()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO library (user_id, book_id, reading_status)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, book_id)
            DO UPDATE SET reading_status = CASE
                WHEN library.reading_status = 'identified'
                THEN EXCLUDED.reading_status
                ELSE library.reading_status
            END
            RETURNING id
            """,
            (user_id, book_id, reading_status),
        )

        row = cursor.fetchone()

        library_id = row['id']

    commit_db()

    return library_id


def get_library(user_id):
    # Sirf is user ki library, book details ke saath nikalni hai.
    with get_db().cursor() as cursor:
        cursor.execute(
            """
            SELECT
                l.id AS library_id, l.favorite, l.reading_status, l.added_at,
                b.*
            FROM library l
            JOIN books b ON b.id = l.book_id
            WHERE l.user_id = %s
            ORDER BY l.added_at DESC
            """,
            (user_id,),
        )
        return cursor.fetchall()


def get_library_item(user_id, book_id):
    with get_db().cursor() as cursor:
        cursor.execute(
            """
            SELECT * FROM library
            WHERE user_id = %s AND book_id = %s
            """,
            (user_id, book_id),
        )
        return cursor.fetchone()


def get_library_book_ids(user_id):
    """Every book already in this user's library, so recommendations can exclude it."""

    with get_db().cursor() as cursor:
        cursor.execute('SELECT book_id FROM library WHERE user_id = %s', (user_id,))

        rows = cursor.fetchall()

    book_ids = set()

    for row in rows:

        book_ids.add(row['book_id'])

    return book_ids


def get_profile_books(user_id, exclude_book_id=None):
    # Recommendations ke liye favourites aur reading/finished books leni hain.
    sql = """
        SELECT b.id, b.title, b.author, b.genres,
               l.favorite, l.reading_status
        FROM library l
        JOIN books b ON b.id = l.book_id
        WHERE l.user_id = %s
          AND (l.favorite = TRUE OR l.reading_status IN ('reading', 'finished'))
    """

    params = [user_id]

    if exclude_book_id:
        sql += " AND b.id <> %s"

        params.append(exclude_book_id)

    with get_db().cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def toggle_favorite(user_id, library_id):
    # Favourite on/off karna; user_id se ownership bhi check hoti hai.
    connection = get_db()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE library
            SET favorite = NOT favorite
            WHERE id = %s AND user_id = %s
            RETURNING favorite
            """,
            (library_id, user_id),
        )

        row = cursor.fetchone()

    commit_db()

    if row:
        return row['favorite']

    return None


def update_reading_status(user_id, library_id, reading_status):
    connection = get_db()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE library
            SET reading_status = %s
            WHERE id = %s AND user_id = %s
            RETURNING id, favorite, reading_status
            """,
            (reading_status, library_id, user_id),
        )

        row = cursor.fetchone()

    commit_db()

    return row


def remove_library_item(user_id, library_id):
    # Sirf user ki library entry hatani hai, asal book nahi.
    connection = get_db()

    with connection.cursor() as cursor:
        cursor.execute('DELETE FROM library WHERE id = %s AND user_id = %s', (library_id, user_id))

        deleted = cursor.rowcount

    commit_db()

    if deleted > 0:
        return True

    return False

# IDENTIFICATION

def create_identification_attempt(user_id, input_method, evidence):
    connection = get_db()

    ocr_status = evidence.get('ocr_status') or ''

    ocr_title = evidence.get('ocr_title') or ''

    ocr_author = evidence.get('ocr_author') or ''

    ocr_text = evidence.get('ocr_text') or ''

    ocr_confidence = float(evidence.get('ocr_confidence') or 0)

    query_title = evidence.get('query_title') or ''

    query_author = evidence.get('query_author') or ''

    query_isbn = evidence.get('query_isbn') or ''

    decision = evidence.get('decision') or 'PENDING'

    failure_reason = evidence.get('failure_reason') or ''

    processing_ms = max(0, int(evidence.get('processing_ms') or 0))

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO identification_attempts (
                user_id, input_method, ocr_status, ocr_title, ocr_author,
                ocr_text, ocr_confidence, query_title, query_author,
                query_isbn, decision, failure_reason, processing_ms
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                user_id,
                input_method,
                ocr_status,
                ocr_title,
                ocr_author,
                ocr_text,
                ocr_confidence,
                query_title,
                query_author,
                query_isbn,
                decision,
                failure_reason,
                processing_ms,
            ),
        )

        row = cursor.fetchone()

        attempt_id = row['id']

    commit_db()

    return attempt_id


def save_identification_candidates(attempt_id, candidates):
    # Candidates ka order aur details rakhni hain, baad mein confirm karne ke liye.
    connection = get_db()

    with connection.cursor() as cursor:

        position = 1

        for candidate in candidates:

            provider = candidate.get('provider') or ''

            score = float(candidate.get('score') or 0)

            decision = candidate.get('decision') or 'REJECTED'

            cursor.execute(
                """
                INSERT INTO identification_candidates (
                    attempt_id, rank_position, provider, score, decision, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    attempt_id,
                    position,
                    provider,
                    score,
                    decision,
                    Json(candidate),
                ),
            )

            row = cursor.fetchone()

            candidate['candidate_id'] = row['id']

            position += 1

    commit_db()

    return candidates


def get_candidate_for_user(candidate_id, attempt_id, user_id):
    # Candidate isi user aur attempt ka ho; attempt row lock bhi karni hai.
    with get_db().cursor() as cursor:
        cursor.execute(
            """
            SELECT
                c.*, a.user_id, a.decision AS attempt_decision,
                a.query_isbn, a.selected_book_id
            FROM identification_candidates c
            JOIN identification_attempts a ON a.id = c.attempt_id
            WHERE c.id = %s AND c.attempt_id = %s AND a.user_id = %s
            FOR UPDATE OF a
            """,
            (candidate_id, attempt_id, user_id),
        )
        return cursor.fetchone()


def complete_identification(attempt_id, candidate_id, book_id, decision):
    connection = get_db()

    try:
        with connection.cursor() as cursor:

            # Is attempt par doosri book select na ho; wahi book dobara confirm ho sakti hai.
            cursor.execute(
                """
                UPDATE identification_attempts
                SET selected_book_id = %s, decision = %s
                WHERE id = %s
                  AND decision <> 'REJECTED'
                  AND (selected_book_id IS NULL OR selected_book_id = %s)
                RETURNING id
                """,
                (book_id, decision, attempt_id, book_id),
            )

            claimed = cursor.fetchone()

            if not claimed:
                connection.rollback()
                return False

            cursor.execute(
                """
                UPDATE identification_candidates
                SET selected = (id = %s)
                WHERE attempt_id = %s
                """,
                (candidate_id, attempt_id),
            )

        commit_db()

        return True

    except Exception:
        connection.rollback()
        raise


def reject_identification(attempt_id, user_id, reason):
    connection = get_db()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE identification_attempts
            SET decision = 'REJECTED', failure_reason = %s
            WHERE id = %s AND user_id = %s
              AND selected_book_id IS NULL
              AND decision = 'NEEDS_CONFIRMATION'
            RETURNING input_method, query_title, ocr_title
            """,
            (reason, attempt_id, user_id),
        )

        attempt = cursor.fetchone()

    commit_db()

    return attempt


def list_identification_attempts(limit=150):
    with get_db().cursor() as cursor:
        cursor.execute(
            """
            SELECT
                a.*, u.name AS user_name, b.title AS selected_title
            FROM identification_attempts a
            JOIN users u ON u.id = a.user_id
            LEFT JOIN books b ON b.id = a.selected_book_id
            ORDER BY a.created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cursor.fetchall()

# MESSAGES AND ADMIN

def save_message(name, email, subject, message):
    connection = get_db()

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO messages (name, email, subject, message)
            VALUES (%s, %s, %s, %s)
            """,
            (name, email, subject, message),
        )

    commit_db()


def get_recent_messages(limit=5):
    with get_db().cursor() as cursor:
        cursor.execute('SELECT * FROM messages ORDER BY created_at DESC LIMIT %s', (limit,))
        return cursor.fetchall()


def get_recent_scans(limit=10):
    with get_db().cursor() as cursor:
        cursor.execute(
            """
            SELECT
                a.id, a.input_method, a.decision, a.processing_ms,
                a.created_at, u.name AS user_name,
                COALESCE(b.title, a.query_title, a.ocr_title) AS title,
                COALESCE(b.author, a.query_author, a.ocr_author) AS author
            FROM identification_attempts a
            JOIN users u ON u.id = a.user_id
            LEFT JOIN books b ON b.id = a.selected_book_id
            ORDER BY a.created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return cursor.fetchall()


def get_admin_stats():
    with get_db().cursor() as cursor:
        cursor.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM users) AS total_users,
                (SELECT COUNT(*) FROM books) AS total_books,
                (SELECT COUNT(*) FROM library) AS total_library_items,
                (SELECT COUNT(*) FROM messages) AS total_messages,
                (SELECT COUNT(*) FROM identification_attempts) AS total_attempts,
                (SELECT COUNT(*) FROM identification_attempts
                    WHERE decision = 'NEEDS_CONFIRMATION') AS needs_confirmation,
                (SELECT COUNT(*) FROM identification_attempts
                    WHERE decision = 'REJECTED') AS rejected,
                (SELECT ROUND(AVG(processing_ms)) FROM identification_attempts
                    WHERE processing_ms > 0) AS average_processing_ms
            """
        )

        row = cursor.fetchone()

        stats = dict(row)

        cursor.execute(
            """
            SELECT catalogue_status, COUNT(*) AS total
            FROM books
            WHERE catalogue_status IS NOT NULL
            GROUP BY catalogue_status
            """
        )

        rows = cursor.fetchall()

        counts = {}

        for row in rows:

            status = row['catalogue_status'].lower()

            counts[status] = row['total']

    statuses = ('pending', 'verified', 'rejected', 'needs_review')

    for status in statuses:

        key = 'catalogue_' + status

        stats[key] = counts.get(status, 0)

    return stats


def commit_db():
    """Helpers commit normally; confirmation commits all its steps together."""
    if not g.get('book_transaction', False):
        get_db().commit()


@contextmanager
def transaction():
    # Saare steps saath save karne hain; error aaye to rollback.
    connection = get_db()
    g.book_transaction = True
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        g.book_transaction = False


def delete_catalogue_book(book_id):
    # Kisi ki library mein book ho to delete nahi karni.
    with transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT id FROM books WHERE id=%s AND catalogue_status IS NOT NULL FOR UPDATE',
                (book_id,),
            )
            if not cursor.fetchone():
                return 'missing'
            cursor.execute('SELECT 1 FROM library WHERE book_id=%s LIMIT 1', (book_id,))
            if cursor.fetchone():
                return 'in_use'
            cursor.execute('DELETE FROM books WHERE id=%s', (book_id,))
    return 'deleted'
