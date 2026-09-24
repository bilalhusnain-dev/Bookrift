import math

import requests

import config
from core.matching import normalize_match_text
from utils.validation import normalize_isbn, valid_isbn


GOOGLE_URL = "https://www.googleapis.com/books/v1/volumes"

OPEN_LIBRARY_URL = "https://openlibrary.org/search.json"

OPEN_LIBRARY_FIELDS = (
    "key,edition_key,title,author_name,first_publish_year,cover_i,"
    "number_of_pages_median,publisher,subject,isbn,ratings_average,"
    "ratings_count,want_to_read_count,currently_reading_count,already_read_count"
)

REQUEST_HEADERS = {'User-Agent': 'Bookrift'}


# API response lena; timeout ya error par None return karna.
def request_json(url, params=None):
    """Send a GET request and return its JSON data."""

    try:
        response = requests.get(url, params=params, headers=REQUEST_HEADERS, timeout=8)

        response.raise_for_status()

        data = response.json()
        if not isinstance(data, dict) or data.get('error'):
            return None
        return data

    except (requests.RequestException, ValueError):
        return None


def number(value, default=0):
    """Safely convert a value to an integer."""

    try:
        if value:
            return int(value)

        return int(default)

    except (TypeError, ValueError, OverflowError):
        return default


def decimal_number(value):
    """Safely convert a value to a decimal/float number."""

    if value is None:
        return None

    try:
        number = float(value)
        if not math.isfinite(number):
            return None
        return number

    except (TypeError, ValueError, OverflowError):
        return None


def list_values(value):
    """Make sure a value is returned as a list."""

    if isinstance(value, list):
        return value

    if value:
        return [value]

    return []


def identifier_values(values):
    """Extract valid ISBN-10 and ISBN-13 values from Google Books identifier records."""

    result = {'isbn_10': None, 'isbn_13': None}

    if not values:
        return result

    for item in values:

        raw_identifier = item.get("identifier")

        identifier = normalize_isbn(raw_identifier)

        identifier_type = item.get("type")

        if identifier_type == "ISBN_10":
            if valid_isbn(identifier):
                result["isbn_10"] = identifier

        if identifier_type == "ISBN_13":
            if valid_isbn(identifier):
                result["isbn_13"] = identifier

    return result


# Google ki fields ko apni book dictionary mein lana.
def google_book(item):
    """Convert one Google Books result into Bookrift's standard book dictionary."""

    info = item.get("volumeInfo")

    if not info:
        info = {}

    identifiers = identifier_values(info.get('industryIdentifiers'))

    images = info.get("imageLinks")

    if not images:
        images = {}

    cover = images.get("thumbnail")

    if not cover:
        cover = images.get("smallThumbnail")

    if not cover:
        cover = ""

    # Prefer HTTPS instead of HTTP.
    if cover.startswith("http://"):
        cover = "https://" + cover[7:]

    authors = list_values(info.get('authors'))

    author_text = ", ".join(authors)

    categories = list_values(info.get('categories'))

    genre_text = ", ".join(categories)

    page_count = number(info.get('pageCount'))

    if page_count < 0:
        page_count = 0

    ratings_count = number(info.get('ratingsCount'))

    if ratings_count < 0:
        ratings_count = 0

    result = {
        "title": str(
            info.get("title") or ""
        ).strip(),

        "author": author_text,

        "isbn_10": identifiers["isbn_10"],

        "isbn_13": identifiers["isbn_13"],

        "google_books_id": str(
            item.get("id") or ""
        ),

        "open_library_edition_id": None,

        "open_library_work_id": None,

        "provider": "google_books",

        "publisher": str(
            info.get("publisher") or ""
        ),

        "published_date": str(
            info.get("publishedDate") or ""
        ),

        "genres": genre_text,

        "description": str(
            info.get("description") or ""
        ),

        "description_source": "Google Books",

        "cover_url": cover,

        "page_count": page_count,

        "rating": decimal_number(
            info.get("averageRating")
        ),

        "ratings_count": ratings_count,

        "on_shelves": 0,
    }

    return result


def first_valid_isbn(values, length):
    """Return the first valid ISBN with the requested length."""

    isbn_values = list_values(values)

    for value in isbn_values:

        isbn = normalize_isbn(value)

        correct_length = len(isbn) == length
        valid = valid_isbn(isbn)

        if correct_length and valid:
            return isbn

    return None


# Open Library ki alag field names ko apne format mein lana.
def open_library_book(document):
    """Convert one Open Library search result into Bookrift's standard book dictionary."""

    cover_id = document.get("cover_i")

    if cover_id:
        cover = f'https://covers.openlibrary.org/b/id/{cover_id}-M.jpg?default=false'
    else:
        cover = ""

    edition_keys = list_values(document.get('edition_key'))

    publishers = list_values(document.get('publisher'))

    work_id = str(document.get('key') or '')

    work_id = work_id.replace('/works/', '')
    if work_id:
        saved_work_id = work_id
    else:
        saved_work_id = None

    shelf_count = 0

    shelf_fields = ('want_to_read_count', 'currently_reading_count', 'already_read_count')

    for field in shelf_fields:

        count = number(document.get(field))

        if count < 0:
            count = 0

        shelf_count += count

    authors = list_values(document.get('author_name'))

    # Keep at most the first three authors.
    authors = authors[:3]

    author_text = ", ".join(authors)

    subjects = list_values(document.get('subject'))

    # Limit the number of subjects/genres.
    subjects = subjects[:25]

    genre_text = ", ".join(subjects)

    if edition_keys:
        edition_id = edition_keys[0]
    else:
        edition_id = None

    if publishers:
        publisher = str(publishers[0])
    else:
        publisher = ""

    page_count = number(document.get('number_of_pages_median'))

    if page_count < 0:
        page_count = 0

    ratings_count = number(document.get('ratings_count'))

    if ratings_count < 0:
        ratings_count = 0

    result = {
        "title": str(
            document.get("title") or ""
        ).strip(),

        "author": author_text,

        "isbn_10": first_valid_isbn(
            document.get("isbn"),
            10,
        ),

        "isbn_13": first_valid_isbn(
            document.get("isbn"),
            13,
        ),

        "google_books_id": None,

        "open_library_edition_id": edition_id,

        "open_library_work_id": saved_work_id,

        "provider": "open_library",

        "publisher": publisher,

        "published_date": str(
            document.get("first_publish_year") or ""
        ),

        "genres": genre_text,

        "description": "",

        "description_source": "Open Library",

        "cover_url": cover,

        "page_count": page_count,

        "rating": decimal_number(
            document.get("ratings_average")
        ),

        "ratings_count": ratings_count,

        "on_shelves": shelf_count,
    }

    return result


# Title, author ya ISBN se provider ki search query banani hai.
def google_query(title="", author="", isbn="", plain=False):
    """Build the query that will be sent to Google Books."""

    if isbn:
        return f"isbn:{isbn}"

    # Plain mode sends only title words.
    # This is useful when OCR produced messy title/author ordering.
    if plain:
        return title

    parts = []

    if title:
        title_part = f'intitle:"{title}"'
        parts.append(title_part)

    if author:
        author_part = f'inauthor:"{author}"'
        parts.append(author_part)

    query = " ".join(parts)

    return query


# Ek kharab provider record ki wajah se saare results nahi rokne.
def parse_provider_record(item, converter):
    """Skip a broken provider record instead of failing the whole search."""
    if not isinstance(item, dict):
        return None
    try:
        return converter(item)
    except (TypeError, ValueError, AttributeError, OverflowError):
        return None


def search_google_books(title="", author="", isbn="", limit=10, plain=False):
    """Search Google Books."""

    if not config.GOOGLE_BOOKS_API_KEY:
        return None

    clean_title = title.strip()
    clean_author = author.strip()
    clean_isbn = normalize_isbn(isbn)

    query = google_query(clean_title, clean_author, clean_isbn, plain)

    if not query:
        return []

    safe_limit = max(limit, 1)

    safe_limit = min(safe_limit, 20)

    params = {
        "q": query,
        "key": config.GOOGLE_BOOKS_API_KEY,
        "maxResults": safe_limit,
        "printType": "books",
        "orderBy": "relevance",
    }

    data = request_json(GOOGLE_URL, params)

    if not isinstance(data, dict) or data.get('error'):
        return None
    items = data.get('items', [])
    if not isinstance(items, list):
        return None
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        info = item.get('volumeInfo')
        if not isinstance(info, dict) or not isinstance(info.get('title'), str):
            continue
        book = parse_provider_record(item, google_book)
        if book and book['title']:
            results.append(book)
    if items and not results:
        return None
    return results


def search_open_library(title="", author="", isbn="", limit=10):
    """Search Open Library."""

    safe_limit = max(limit, 1)

    safe_limit = min(safe_limit, 20)

    params = {'limit': safe_limit, 'fields': OPEN_LIBRARY_FIELDS, 'lang': 'en'}

    isbn = normalize_isbn(isbn)

    if isbn:
        params["isbn"] = isbn

    else:

        clean_title = title.strip()
        clean_author = author.strip()

        if clean_title:
            params["title"] = clean_title

        if clean_author:
            params["author"] = clean_author

    # ISBN was not supplied and title is also empty.
    if not isbn and not title.strip():
        return []

    data = request_json(OPEN_LIBRARY_URL, params)

    if not isinstance(data, dict) or data.get('error'):
        return None
    documents = data.get('docs', [])
    if not isinstance(documents, list):
        return None
    results = []
    for document in documents:
        if not isinstance(document, dict) or not isinstance(document.get('title'), str):
            continue
        book = parse_provider_record(document, open_library_book)
        if book and book['title']:
            results.append(book)
    if documents and not results:
        return None
    return results


def candidate_key(book):
    """Build a deduplication key for one provider book record."""

    identifier = book.get("isbn_13")

    if not identifier:
        identifier = book.get("isbn_10")

    if not identifier:
        identifier = book.get("google_books_id")

    if not identifier:
        identifier = book.get('open_library_edition_id')

    if not identifier:
        author = book.get('author', '')

        identifier = author.casefold()

    normalized_title = normalize_match_text(book.get('title'))

    key = str(identifier) + '|' + normalized_title

    return key


# Dono providers ke results jorna aur duplicate records hatane hain.
def search_books(title="", author="", isbn="", limit=10, plain=False):
    """Search Google Books and Open Library and combine their results."""

    google = search_google_books(title, author, isbn, limit, plain)

    open_library = search_open_library(title, author, isbn, limit)

    # Neither provider could be used/reached.
    if google is None and open_library is None:
        return None

    candidates = []

    if google:
        candidates.extend(google)

    if open_library:
        candidates.extend(open_library)

    unique = []

    seen = set()

    for book in candidates:

        key = candidate_key(book)

        # Ignore records without titles.
        if not book["title"]:
            continue

        # Ignore duplicate provider records.
        if key in seen:
            continue

        seen.add(key)

        unique.append(book)

    return unique


def get_google_volume(volume_id):
    """Fetch one exact Google Books volume by its ID."""

    if not volume_id:
        return None

    params = {}

    if config.GOOGLE_BOOKS_API_KEY:
        params['key'] = config.GOOGLE_BOOKS_API_KEY

    url = GOOGLE_URL + '/' + str(volume_id)

    data = request_json(url, params)

    if not isinstance(data, dict):
        return None
    if isinstance(data.get('volumeInfo'), dict):
        return parse_provider_record(data, google_book)

    return None


def description_text(value):
    """Convert an Open Library description into plain text."""

    if isinstance(value, dict):
        value = value.get("value")

    if not isinstance(value, str):
        return ''
    text = value.strip()

    return text


# Edition ya work se available description leni hai.
def get_open_library_description(book):
    """Get a description from Open Library."""

    edition_id = str(book.get('open_library_edition_id') or '')

    edition_id = edition_id.replace('/books/', '')

    work_id = str(book.get('open_library_work_id') or '')

    work_id = work_id.replace('/works/', '')
    if work_id:
        saved_work_id = work_id
    else:
        saved_work_id = None

    # First try the edition record.

    if edition_id:

        edition_url = 'https://openlibrary.org/books/' + edition_id + '.json'

        edition = request_json(edition_url)

        if not isinstance(edition, dict):
            edition = {}

        description = description_text(edition.get('description'))

        if description:
            return description

        # If we do not already know the work ID,
        # try to get it from the edition.
        if not work_id:

            works = edition.get('works')

            if isinstance(works, list) and works and isinstance(works[0], dict):
                first_work = works[0]

                work_key = str(first_work.get('key') or '')

                work_id = work_key.replace('/works/', '')

    # If edition had no description, try work record.

    if work_id:

        work_url = 'https://openlibrary.org/works/' + work_id + '.json'

        work = request_json(work_url)

        if not isinstance(work, dict):
            work = {}

        description = description_text(work.get('description'))

        return description

    return ""
