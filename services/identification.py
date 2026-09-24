import json
import time

from flask import current_app
import config

from thefuzz import fuzz

import database
from core.overview import build_overview
from core.matching import (
    HIGH_CONFIDENCE,
    NEEDS_CONFIRMATION,
    REJECTED,
    normalize_match_text,
    rank_candidates,
    recover_ocr_candidates,
)
from routes.books import book_json
from services import providers
from services.recommendations import fit_for_reader


CANDIDATE_FIELDS = (
    "catalogue_book_id",
    "title",
    "author",
    "isbn_10",
    "isbn_13",
    "google_books_id",
    "open_library_edition_id",
    "open_library_work_id",
    "provider",
    "catalogue_status",
    "publisher",
    "published_date",
    "genres",
    "description",
    "description_source",
    "overview",
    "cover_url",
    "page_count",
    "page_count_source",
    "rating",
    "ratings_count",
    "on_shelves",
    "score",
    "decision",
    "reasons",
    "score_breakdown",
)


def safe_candidate(candidate):
    """Keep allowed fields and convert stored numbers to standard Python types."""
    data = {}
    for field in CANDIDATE_FIELDS:
        data[field] = candidate.get(field)
    if data["rating"] is not None:
        data["rating"] = float(data["rating"])
    data["page_count"] = int(data["page_count"] or 0)
    data["ratings_count"] = int(data["ratings_count"] or 0)
    data["on_shelves"] = int(data["on_shelves"] or 0)
    return data


def candidate_for_user(candidate):
    """Return only the candidate information that should be sent to the user."""
    fields = (
        "candidate_id",
        "title",
        "author",
        "isbn_10",
        "isbn_13",
        "publisher",
        "published_date",
        "genres",
        "cover_url",
        "page_count",
        "page_count_source",
        "rating",
        "ratings_count",
        "provider",
        "score",
        "decision",
        "reasons",
    )
    data = {}
    for field in fields:
        data[field] = candidate.get(field)
    return data


# OCR se query, phir matching, phir final result ya choices.
def identify_cover(path, user_id, read_cover):
    """Read the cover, match its text, and return the identification result."""
    started = time.monotonic()
    try:
        result, status = read_cover(path)
    except Exception:
        current_app.logger.exception('Cover OCR failed')
        result = {'error': (
            'The cover reader could not process this photo. Please try another '
            'photo or manual search.'
        )}
        status = 'OCR_FAILED'
    evidence = ocr_evidence(result, status)
    ranked = {'decision': REJECTED, 'candidates': []}
    if result.get('error'):
        ranked['error'] = result['error']
    elif result.get('full_text') or result.get('probable_title'):
        ranked = identify_candidates(
            evidence['query_title'], evidence['query_author'],
            high_confidence_allowed=status == 'OCR_SUCCESS',
            ocr_text=result.get('full_text') or '',
            text_lines=result.get('text_lines') or [],
        )
    evidence['processing_ms'] = max(0, int((time.monotonic() - started) * 1000))
    return begin_funnel(user_id, evidence, ranked, 'cover')


def identify_candidates(title, author='', isbn='', limit=5, high_confidence_allowed=True,
                        ocr_text='', text_lines=None):
    # Pehle local catalogue try karna, yahan internet call nahi chahiye.
    local = []
    with (config.BASE_DIR / 'catalogue.json').open(encoding='utf-8') as file:
        aliases = {}
        for book in json.load(file):
            title_key = normalize_match_text(book['title'])
            aliases[title_key] = book.get('alternate_titles', [])
    for book in database.list_catalogue('VERIFIED'):
        candidate = dict(book)
        candidate['catalogue_book_id'] = book['id']
        title_key = normalize_match_text(book['title'])
        candidate['alternate_titles'] = aliases.get(title_key, [])
        local.append(candidate)
    ranked = rank_candidates(local, title, author, isbn, limit, high_confidence_allowed)
    if ranked['decision'] == HIGH_CONFIDENCE:
        ranked['tier'] = 'catalogue'
        return ranked
    if ocr_text or text_lines:
        recovered = recover_ocr_candidates(local, title, author, ocr_text, text_lines, limit)
        if recovered['candidates']:
            recovered['tier'] = 'catalogue'
            return recovered
    if ranked['candidates']:
        ranked['tier'] = 'catalogue'
        return ranked
    return external_candidates(title, author, isbn, limit, high_confidence_allowed,
                               ocr_text=ocr_text, text_lines=text_lines)


# Provider results ko bhi score karna; sirf API result milna kaafi nahi.
def external_candidates(title, author='', isbn='', limit=5, high_confidence_allowed=True,
                        ocr_text='', text_lines=None):
    books = providers.search_books(title, author, isbn, limit=10)
    if books is None:
        return {'decision': REJECTED, 'candidates': [], 'tier': 'external',
                'error': (
                    'The book service is not responding right now. Please check your '
                    'internet connection and try again.'
                )}
    ranked = rank_candidates(books, title, author, isbn, limit, high_confidence_allowed)
    if ranked['decision'] == REJECTED and (ocr_text or text_lines):
        ranked = recover_ocr_candidates(books, title, author, ocr_text, text_lines, limit)
    if ranked['decision'] == REJECTED and title:
        retry = providers.search_books(title, '', isbn, limit=10, plain=True)
        if retry is None:
            ranked['error'] = 'The book service is not responding right now. Please try again.'
        else:
            ranked = rank_candidates(retry, title, '', isbn, limit, False)
            if ranked['decision'] == REJECTED and (ocr_text or text_lines):
                ranked = recover_ocr_candidates(retry, title, '', ocr_text, text_lines, limit)
    ranked['tier'] = 'external'
    return ranked


def same_book(first, second):
    if normalize_match_text(first.get('title')) != normalize_match_text(second.get('title')):
        return False
    first_author = normalize_match_text(first.get('author'))
    second_author = normalize_match_text(second.get('author'))
    if first_author == second_author:
        return True
    if not first_author or not second_author:
        return False
    return fuzz.token_set_ratio(first_author, second_author) >= 95


# Same title aur author wali repeated choices kam karni hain.
def collapse_editions(candidates):
    """Remove duplicate candidate editions that represent the same book."""
    collapsed = []
    if not candidates:
        return collapsed
    for candidate in candidates:
        duplicate_found = False
        for kept in collapsed:
            if same_book(candidate, kept):
                duplicate_found = True
                break
        if not duplicate_found:
            collapsed.append(candidate)
    return collapsed


def ocr_evidence(result, status, processing_ms=0):
    """Keep the OCR text and query used for this scan."""
    from core.ocr import usable_ocr_author
    title = str(result.get('probable_title') or '').strip()
    author = str(result.get('probable_author') or '').strip()
    full_text = str(result.get('full_text') or '').strip()
    confidence = float(result.get('confidence_score') or 0)
    usable_author = usable_ocr_author(author)
    processing_ms = max(0, int(processing_ms))
    evidence = {
        "ocr_status": status,
        "ocr_title": title,
        "ocr_author": author,
        "ocr_text": full_text,
        "ocr_confidence": confidence,
        "query_title": title,
        "query_author": usable_author,
        "query_isbn": "",
        "processing_ms": processing_ms,
    }
    return evidence


def response_for_book(user_id, book_id, attempt_id, library_id, confidence, method):
    """Build the final success response after a book has been identified."""
    book = database.get_book(book_id)
    library = database.get_library_item(user_id, book_id)
    if confidence == "high":
        decision = HIGH_CONFIDENCE
    else:
        decision = "USER_CONFIRMED"
    response = {
        "status": "success",
        "decision": decision,
        "confidence": confidence,
        "match_method": method,
        "attempt_id": attempt_id,
        "library_id": library_id,
        "favorite": library["favorite"],
        "reading_status": library["reading_status"],
        "book": book_json(book, full=True),
        "for_you": fit_for_reader(user_id, book),
    }
    return response


# Provider se missing details bharni hain.
def hydrate_external_candidate(candidate):
    """Fill missing provider details without replacing existing values."""
    google_books_id = candidate.get("google_books_id")
    if google_books_id:
        exact = providers.get_google_volume(google_books_id)
        if exact:
            # Copy par kaam karna taake original dictionary na badle.
            filled = dict(candidate)
            for field, value in exact.items():
                # Sirf khaali fields bharni hain.
                if not filled.get(field):
                    filled[field] = value
            candidate = filled
    else:
        open_library_edition_id = candidate.get('open_library_edition_id')
        open_library_work_id = candidate.get('open_library_work_id')
        if open_library_edition_id or open_library_work_id:
            description = providers.get_open_library_description(candidate)
            if description:
                candidate["description"] = description
                candidate["description_source"] = "Open Library"
    return candidate


def selected_candidate_response(user_id, attempt_id, stored, method):
    """Return the previous result when the same choice is confirmed again."""
    book_id = stored['selected_book_id']
    library = database.get_library_item(user_id, book_id)
    if not library:
        return {'error': 'This saved book was removed from your library.'}, 409
    if stored['decision'] == HIGH_CONFIDENCE:
        confidence = 'high'
    else:
        confidence = 'confirmed'
    response = response_for_book(
        user_id, book_id, attempt_id, library['id'], confidence, method,
    )
    response['already_in_library'] = True
    return response, 200


def save_external_candidate(candidate):
    """Save provider details, checking for identifiers shared by different books."""
    candidate = hydrate_external_candidate(candidate)
    overview = build_overview(candidate)
    candidate["overview"] = overview["overview"]
    book_id = database.save_book(candidate)
    if not book_id:
        return None, ({'error': 'The selected book could not be saved.'}, 500)
    stored_book = database.get_book(book_id)
    if stored_book and not same_book(stored_book, candidate):
        error = {
            "error": (
                "This book could not be confirmed because its "
                "identifier already belongs to a different book."
            )
        }
        return None, (error, 409)
    if overview["status"] == "ready":
        description = candidate.get('description') or ''
        description_source = candidate.get('description_source') or ''
        database.update_book_overview(
            book_id, description, description_source, overview["overview"],
        )
    return book_id, None


# Confirmation ke steps saath save hon; error status par rollback.
def finalize_candidate(user_id, attempt_id, candidate_id, method):
    with database.transaction() as connection:
        response, status = finalize_candidate_steps(user_id, attempt_id, candidate_id, method)
        if status >= 400:
            connection.rollback()
        return response, status


# Pehle user ki choice check karni hai, phir book library mein save karni hai.
def finalize_candidate_steps(user_id, attempt_id, candidate_id, method):
    """Validate the choice, find its book, and save it to the reader's library."""
    stored = database.get_candidate_for_user(candidate_id, attempt_id, user_id)
    if not stored:
        return {'error': 'Candidate not found.'}, 404
    if stored["attempt_decision"] == REJECTED:
        return {'error': 'This identification was already rejected.'}, 409
    if stored["decision"] == REJECTED:
        return {'error': 'A rejected candidate cannot be selected.'}, 400
    if stored["selected_book_id"] and not stored["selected"]:
        return {'error': 'This identification was already completed.'}, 409
    if stored['selected_book_id'] and stored['selected']:
        return selected_candidate_response(user_id, attempt_id, stored, method)

    candidate = dict(stored["metadata"])
    catalogue_book_id = candidate.get('catalogue_book_id')
    if catalogue_book_id:
        book = database.get_catalogue_book(catalogue_book_id)
        if not book or book["catalogue_status"] != "VERIFIED":
            return {'error': 'The verified book is no longer available.'}, 409
        book_id = book["id"]
    else:
        book_id, error = save_external_candidate(candidate)
        if error is not None:
            return error

    if stored["decision"] == HIGH_CONFIDENCE:
        decision = HIGH_CONFIDENCE
    else:
        decision = "USER_CONFIRMED"
    # Pehle attempt claim karna taake doosri book saath select na ho.
    claimed = database.complete_identification(attempt_id, candidate_id, book_id, decision)
    if not claimed:
        return {'error': 'This identification was already completed.'}, 409
    existing_library_item = database.get_library_item(user_id, book_id)
    already_saved = existing_library_item is not None
    library_id = database.add_to_library(user_id, book_id, 'identified')
    if decision == HIGH_CONFIDENCE:
        confidence = "high"
    else:
        confidence = "confirmed"
    response = response_for_book(user_id, book_id, attempt_id, library_id, confidence, method)
    response["already_in_library"] = already_saved
    return response, 200


# Attempt record karna, phir auto save, user choice ya retry advice deni hai.
def begin_funnel(user_id, evidence, ranked, input_method):
    """Save the attempt, then return a book, choices, or recovery advice."""
    decision = ranked.get('decision', REJECTED)
    original_candidates = ranked.get('candidates') or []
    candidates = collapse_editions(original_candidates)
    # Candidate hi nahi hai to result reject hoga.
    if not candidates:
        decision = REJECTED
    # Evidence ki copy save karni hai.
    stored_evidence = dict(evidence)
    stored_evidence["decision"] = decision
    if decision == REJECTED:
        failure_reason = ranked.get("error")
        if not failure_reason:
            failure_reason = 'No candidate was strong enough to verify.'
        stored_evidence["failure_reason"] = failure_reason
    attempt_id = database.create_identification_attempt(user_id, input_method, stored_evidence)
    # Candidate ki allowed fields hi store karni hain.
    safe_candidates = []
    for candidate in candidates:
        safe_candidates.append(safe_candidate(candidate))
    candidates = safe_candidates
    database.save_identification_candidates(attempt_id, candidates)
    # Strong match par save karna.
    if decision == HIGH_CONFIDENCE and candidates:
        first_candidate = candidates[0]
        return finalize_candidate(
            user_id,
            attempt_id,
            first_candidate["candidate_id"],
            input_method,
        )
    # Doubt ho to user se choice leni hai.
    if decision == NEEDS_CONFIRMATION and candidates:
        user_candidates = []
        for candidate in candidates:
            user_candidates.append(candidate_for_user(candidate))
        ocr_data = {
            "status": evidence.get("ocr_status", ""),
            "extracted_title": evidence.get("ocr_title", ""),
            "extracted_author": evidence.get("ocr_author", ""),
            "confidence_score": evidence.get("ocr_confidence", 0),
        }
        response = {
            "status": "needs_confirmation",
            "decision": NEEDS_CONFIRMATION,
            "input_method": input_method,
            "attempt_id": attempt_id,
            "candidates": user_candidates,
            "ocr": ocr_data,
            "message": (
                "Please choose the exact book before it is saved."
            ),
        }
        return response, 200
    # Match na mile to retry ka tareeqa dikhana.
    if input_method == "barcode":
        advice = 'Try a clearer photo of the barcode, or search by title instead.'
    else:
        ocr_status = evidence.get('ocr_status')
        if ocr_status in (
            "OCR_FAILED",
            "OCR_NO_BOOK_TEXT",
        ):
            advice = (
                "No text could be read from this photo. "
                "Use a clear, straight photo of the front cover, "
                "or search by title instead."
            )
        else:
            advice = 'Try a clearer cover, the barcode mode, or manual search.'
    recovery_query = evidence.get('query_title')
    if not recovery_query:
        recovery_query = evidence.get('ocr_title', '')
    ocr_data = {
        "status": evidence.get("ocr_status", ""),
        "extracted_title": evidence.get("ocr_title", ""),
        "extracted_author": evidence.get("ocr_author", ""),
        "confidence_score": evidence.get("ocr_confidence", 0),
    }
    response = {
        "status": "rejected",
        "decision": REJECTED,
        "input_method": input_method,
        "attempt_id": attempt_id,
        "book": None,
        "failure_reason": stored_evidence.get("failure_reason", ""),
        "recovery_query": recovery_query,
        "ocr": ocr_data,
        "message": advice,
    }
    return response, 200
