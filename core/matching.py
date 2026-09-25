import re

import unicodedata



from thefuzz import fuzz



from utils.validation import normalize_isbn





HIGH_CONFIDENCE = "HIGH_CONFIDENCE"

NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"

REJECTED = "REJECTED"



# Final score mein title ka 70% aur author ka 30% hissa.

TITLE_WEIGHT = 0.70

AUTHOR_WEIGHT = 0.30



# Score ki limits; auto accept ke liye neeche wali checks bhi zaroori hain.

AUTOMATIC_SCORE = 90

CONFIRMATION_SCORE = 55



# Pehle aur doosre candidate ke score mein kam az kam itna farq chahiye.

CLEAR_WINNER_GAP = 8



# Cover ke words se title milne par starting score.

RECOVERY_BASE_SCORE = 65

# Jitne title words milein, us hisaab se extra score.

RECOVERY_COVERAGE_WEIGHT = 10

# Author ka word bhi mil jaye to bonus.

RECOVERY_AUTHOR_BONUS = 5

# Useful title words mein se kam az kam 90% milne chahiye.

MIN_RECOVERY_COVERAGE = 0.9

# Single-word title bohat chhota na ho.

MIN_SINGLE_TITLE_LENGTH = 4



TITLE_STOP_WORDS = {'a', 'an', 'the', 'of', 'and', 'in', 'to', 'y', 'la', 'el', 'de'}



# Guide, summary ya collection ko asal book samajhne se bachna.

UNSAFE_EDITION_RE = re.compile(

    r"\b(?:box(?:ed)?\s*set|complete\s+(?:set|collection|series|works)|"

    r"collection\s+of|omnibus|bundle|study\s*guide|summary(?:\s+and\s+analysis)?|"

    r"workbook|teacher(?:'s)?\s+edition|educator\s+edition|companion|"

    r"reader(?:'s)?\s+guide|film\s+adaptation|movie\s+tie[- ]?in|"

    r"screenplay|series\s+guide|e-?books?\s+collection|books?\s+collection|"

    r"novels?\s+collection|adaptation|expert\s+guide|in\s+\d+\s+minutes|"

    r"spark\s*notes|cliffs?\s*notes|critical\s+(?:insights|essays|interpretations)|"

    r"bloom'?s\s+(?:modern\s+)?critical|analysis\s+of)\b",

    re.IGNORECASE,

)





def normalize_match_text(value):

    """Lower case, no punctuation, single spaces. Comparing needs a flat shape."""

    value = unicodedata.normalize('NFKD', str(value or '').casefold())

    characters = []

    for char in value:

        if not unicodedata.combining(char):

            characters.append(char)

    value = ''.join(characters)

    value = re.sub(r"[^\w\s]", " ", value)

    return re.sub(r"\s+", " ", value).strip()





def publication_year(value):

    """The four digit year inside a published_date, for display only."""

    match = re.search(r"\b(1[5-9]\d{2}|20\d{2})\b", str(value or ""))

    if match:

        return match.group(1)

    else:

        return ""





def candidate_identity(book):

    # ID, title aur author mila kar duplicate candidate pehchanna.

    title = normalize_match_text(book.get('title'))

    author = normalize_match_text(book.get('author'))

    for field in ('id', 'google_books_id', 'open_library_edition_id', 'open_library_work_id'):

        if book.get(field):

            return f'{field}:{book[field]}|{title}|{author}'

    isbn = normalize_isbn(book.get('isbn_13')) or normalize_isbn(book.get('isbn_10'))

    return f'{isbn}|{title}|{author}'





def unsafe_edition(book):

    """A study guide, box set or summary wearing the real book's title."""

    values = (

        book.get("title"),

        book.get("genres") or book.get("categories"),

        book.get("publisher"),

        book.get("author"),

    )

    parts = []

    for value in values:

        parts.append(str(value or ""))

    text = " ".join(parts)

    return bool(UNSAFE_EDITION_RE.search(text))





def measure_similarity(book, query_title, query_author="", query_isbn=""):

    """Step 1: how close is this book to what was asked for? Numbers only."""

    title = normalize_match_text(book.get("title"))

    author = normalize_match_text(book.get("author"))

    wanted_title = normalize_match_text(query_title)

    wanted_author = normalize_match_text(query_author)

    wanted_isbn = normalize_isbn(query_isbn)

    candidate_isbns = {normalize_isbn(book.get('isbn_10')), normalize_isbn(book.get('isbn_13'))}

    candidate_isbns.discard("")



    if wanted_title and title:

        title_set = fuzz.token_set_ratio(wanted_title, title)

        title_order = fuzz.ratio(wanted_title, title)

    else:

        title_set = 0

        title_order = 0

    # Title ke andar words aur unka order dono compare karne hain.

    title_similarity = round(title_set * 0.65 + title_order * 0.35, 1)

    if wanted_author and author:

        author_similarity = fuzz.token_set_ratio(wanted_author, author)

    else:

        author_similarity = 0



    return {

        "title": title,

        "wanted_title": wanted_title,

        "wanted_author": wanted_author,

        "title_similarity": title_similarity,

        "author_similarity": author_similarity,

        "exact_isbn": bool(wanted_isbn and wanted_isbn in candidate_isbns),

        "has_isbn": bool(candidate_isbns),

        "unsafe_edition": unsafe_edition(book),

    }





def match_score(measured):

    """Step 2: turn the two similarities into one score out of 100."""

    if measured["exact_isbn"]:

        return 100.0, ["Exact ISBN match"]



    # Author missing ho to uska score zero rahega, title ka weight nahi barhana.

    weighted = (

        measured["title_similarity"] * TITLE_WEIGHT

        + measured["author_similarity"] * AUTHOR_WEIGHT

    )

    score = round(weighted / (TITLE_WEIGHT + AUTHOR_WEIGHT), 1)



    reasons = []

    if measured["title_similarity"] >= 90:

        reasons.append("Title is a very close match")

    elif measured["title_similarity"] >= 70:

        reasons.append("Title is a close match")

    else:

        reasons.append("Title is only partly similar")



    if measured["wanted_author"]:

        if measured["author_similarity"] >= 75:

            reasons.append("Author matches")

        elif measured["author_similarity"] >= 40:

            reasons.append("Author is only partly similar")

        else:

            reasons.append("Author does not match")



    return score, reasons





def confidence_decision(score, measured):

    # Score aur evidence se auto accept, confirmation ya reject choose karna.

    if measured['exact_isbn']:

        return HIGH_CONFIDENCE

    if measured['unsafe_edition']:

        return REJECTED

    # Similar title sequel bhi ho sakta hai; exact title aur strong author match chahiye.

    if (score >= AUTOMATIC_SCORE and measured['title'] == measured['wanted_title']

            and measured['author_similarity'] >= 95):

        return HIGH_CONFIDENCE

    if score >= CONFIRMATION_SCORE:

        return NEEDS_CONFIRMATION

    return REJECTED





def score_candidate(book, query_title, query_author="", query_isbn=""):

    """Is this book the one that was asked for? Measure, score, then decide."""

    measured = measure_similarity(book, query_title, query_author, query_isbn)

    score, reasons = match_score(measured)

    decision = confidence_decision(score, measured)

    if measured["wanted_author"]:

        author_similarity = measured["author_similarity"]

    else:

        author_similarity = None



    return {

        "score": score,

        "decision": decision,

        "reasons": reasons,

        "score_breakdown": {

            "title_similarity": measured["title_similarity"],

            "author_similarity": author_similarity,

            "exact_isbn": measured["exact_isbn"],

            "unsafe_edition": measured["unsafe_edition"],

            "publication_year": publication_year(book.get("published_date")),

        },

    }





def candidate_score(candidate):

    return candidate["score"]





def rank_candidates(

    results, query_title, query_author="", query_isbn="", limit=5,

    high_confidence_allowed=True,

):

    """Score every candidate, drop duplicates, and choose one overall answer."""

    ranked = []

    seen = set()

    for raw in results or []:

        identity = candidate_identity(raw)

        if not identity or identity in seen:

            continue

        seen.add(identity)

        candidate = dict(raw)

        candidate.update(score_candidate(candidate, query_title, query_author, query_isbn))

        ranked.append(candidate)



    ranked.sort(key=candidate_score, reverse=True)

    plausible = []

    for item in ranked:

        if item["decision"] != REJECTED:

            plausible.append(item)

    if not plausible:

        final_decision = REJECTED

    else:

        top = plausible[0]

        if len(plausible) > 1:

            runner_score = plausible[1]["score"]

        else:

            runner_score = 0

        clear_winner = top["score"] - runner_score >= CLEAR_WINNER_GAP

        if top["decision"] == HIGH_CONFIDENCE and clear_winner:

            final_decision = HIGH_CONFIDENCE

        else:

            final_decision = NEEDS_CONFIRMATION

            top["decision"] = NEEDS_CONFIRMATION

            if runner_score and not clear_winner:

                top["reasons"].append("Several candidates have similar scores")



        if final_decision == HIGH_CONFIDENCE and not high_confidence_allowed:

            final_decision = NEEDS_CONFIRMATION

            top["decision"] = NEEDS_CONFIRMATION

            top["reasons"].append("OCR confidence is low; confirmation is required")



    shown = plausible[: max(1, int(limit))]

    return {

        "decision": final_decision,

        "candidates": shown,

        "rejected_count": len(ranked) - len(plausible),

    }





def word_on_cover(word, observed_words):
    """OCR spelling mistakes aur joined words ko handle karna."""
    word = normalize_match_text(word)

    for observed in observed_words:
        observed = normalize_match_text(observed)

        # Normal fuzzy match.
        if fuzz.ratio(word, observed) >= 82:
            return True

        # OCR kabhi do words ko join kar deta hai, jaise POOR DAD -> POORDAD.
        if (
            len(word) >= 3
            and len(observed) > len(word)
            and word in observed
        ):
            return True

    return False


def title_words(title):

    # Title se common words hata kar useful words rakhne hain.

    words = []

    for word in normalize_match_text(title).split():

        if word not in TITLE_STOP_WORDS:

            words.append(word)

    return words





def words_found_on_cover(words, observed):

    hits = 0

    for word in words:

        if word_on_cover(word, observed):

            hits += 1

    return hits





def author_is_on_cover(author, observed):

    # Author ka koi ek useful word cover par milna kaafi hai.

    author_words = []

    for word in normalize_match_text(author).split():

        if len(word) > 2:

            author_words.append(word)

    for word in author_words:

        if word_on_cover(word, observed):

            return True

    return False





def recovery_score(title, author, observed):

    # Title ke zyada words milne chahiye; single-word title ko author bhi chahiye.

    words = title_words(title)

    if not words:

        return 0

    hits = words_found_on_cover(words, observed)

    coverage = hits / len(words)

    author_found = author_is_on_cover(author, observed)

    if coverage < MIN_RECOVERY_COVERAGE:

        return 0

    if len(words) == 1:

        if len(words[0]) < MIN_SINGLE_TITLE_LENGTH or not author_found:

            return 0

    if author_found:

        author_bonus = RECOVERY_AUTHOR_BONUS

    else:

        author_bonus = 0

    return RECOVERY_BASE_SCORE + coverage * RECOVERY_COVERAGE_WEIGHT + author_bonus





def book_recovery_score(book, observed):

    # Main aur alternate titles mein se sabse acha recovery score lena.

    titles = [book.get('title') or '']

    titles.extend(book.get('alternate_titles') or [])

    best = 0

    for title in titles:

        score = recovery_score(title, book.get('author'), observed)

        best = max(best, score)

    return best





def recover_ocr_candidates(

    results, probable_title='', probable_author='', full_text='',

    text_lines=None, limit=5,

):

    """Find title words anywhere on the cover, but always ask for confirmation."""

    # Recovery se mili book auto save nahi hogi, user se confirm karwana hai.

    parts = [probable_title, probable_author, full_text]

    parts.extend(text_lines or [])

    raw = ' '.join(parts)

    observed = normalize_match_text(raw).split()

    if not observed:

        return {'decision': REJECTED, 'candidates': [], 'rejected_count': len(results or [])}

    recovered = []

    for book in results or []:

        if unsafe_edition(book):

            continue

        best = book_recovery_score(book, observed)

        if best:

            candidate = dict(book)

            candidate['score'] = round(best, 1)

            candidate['decision'] = NEEDS_CONFIRMATION

            candidate['reasons'] = ['Title words were found on the cover; please check the book.']

            candidate['score_breakdown'] = {'ocr_recovery': True}

            recovered.append(candidate)

    recovered.sort(key=candidate_score, reverse=True)

    if recovered:

        decision = NEEDS_CONFIRMATION

    else:

        decision = REJECTED

    return {

        'decision': decision,

        'candidates': recovered[:limit],

        'rejected_count': len(results or []) - len(recovered),

    }
