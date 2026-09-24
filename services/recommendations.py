import database
from utils.validation import genre_map


# Library se taste lena; genre na mile to selected interests use karne hain.
def reading_profile(user_id, exclude_book_id=None):
    """Get the reader's taste and the books that support each genre."""
    profile_books = database.get_profile_books(user_id, exclude_book_id)
    taste = {}
    titles_by_genre = {}
    for book in profile_books:
        book_genres = genre_map(book["genres"])
        for key, label in book_genres.items():
            if key not in taste:
                taste[key] = label
            if key not in titles_by_genre:
                titles_by_genre[key] = []
            titles_by_genre[key].append(book["title"])
    if not taste:
        user_interests = database.get_user_interests(user_id)
        taste = genre_map(user_interests)
    return taste, titles_by_genre


def shared_genres(book, taste):
    """Find genres shared by the candidate book and the reader's taste."""
    book_genres = genre_map(book["genres"])
    keys = []
    for key in book_genres:
        if key in taste:
            keys.append(key)
    keys.sort()
    labels = []
    for key in keys:
        labels.append(book_genres[key])
    return labels, keys


# Reason mein user ki actual books ke naam dene hain.
def evidence_titles(keys, titles_by_genre, limit=2):
    """Return up to 'limit' real books that support the shared genres."""
    titles = []
    for key in keys:
        genre_titles = titles_by_genre.get(key, [])
        for title in genre_titles:
            if title not in titles and len(titles) < limit:
                titles.append(title)
    return titles


# Zyada shared genres wali book pehle; barabar hon to title ka order.
def rank_books(user_id, books, exclude_owned=False, limit=None):
    """Rank books by how many genres they share with the reader."""
    taste, titles_by_genre = reading_profile(user_id)
    if exclude_owned:
        owned = database.get_library_book_ids(user_id)
    else:
        owned = set()
    ranked = []
    for book in books:
        if book["id"] in owned:
            continue
        labels, keys = shared_genres(book, taste)
        titles = evidence_titles(keys, titles_by_genre)
        ranked_item = (book, labels, titles)
        ranked.append(ranked_item)

    def ranking_key(item):
        book = item[0]
        labels = item[1]
        shared_genre_count = len(labels)
        title = book["title"].casefold()
        return (-shared_genre_count, title)

    # Shared genres barabar hon to title se order rakhna.
    ranked.sort(key=ranking_key)
    if limit is not None:
        ranked = ranked[:limit]
    return ranked


def recommendation_reason(labels, titles):
    """Create a readable reason explaining the recommendation."""
    if len(labels) < 3:
        genres = " and ".join(labels)
    else:
        genres = ", ".join(labels)
    if not titles:
        return f"Matches your interest in {genres}."
    joined_titles = " and ".join(titles)
    return f"Based on {joined_titles} in your library. Shares {genres}."


def fit_state(status, labels=(), titles=()):
    """Create one standard result describing how well a book fits the reader."""
    shared = list(labels)
    because = list(titles)
    result = {'status': status, 'shared_genres': shared, 'because': because}
    return result


# Isi book ko taste banane mein count nahi karna; warna khud se match ho jayegi.
def fit_for_reader(user_id, book):
    """Decide how well one book fits this particular reader."""
    taste, titles_by_genre = reading_profile(user_id, book['id'])
    book_genres = genre_map(book["genres"])
    if not book_genres:
        return fit_state("no_genres")
    if not taste:
        return fit_state("cold_start")
    labels, keys = shared_genres(book, taste)
    if not labels:
        if titles_by_genre:
            status = "different_from_your_books"
        else:
            status = "different_from_your_interests"
        return fit_state(status)
    titles = evidence_titles(keys, titles_by_genre)
    if titles:
        status = "good_match"
    else:
        status = "interest_match"
    return fit_state(status, labels, titles)
