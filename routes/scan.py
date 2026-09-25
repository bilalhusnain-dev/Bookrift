import time
import uuid

from flask import Blueprint, g, request

import config
import database
from core.matching import REJECTED
from services import identification
from utils.security import login_required, take_rate_slot
from utils.validation import (
    allowed_image_name,
    delete_upload,
    json_body,
    normalize_isbn,
    valid_isbn,
    validate_image,
)


scan = Blueprint(
    'scan',
    __name__,
    url_prefix='/api'
)


def processing_time(started):
    return max(
        0,
        int(
            (time.monotonic() - started)
            * 1000
        )
    )


def limit_reached(group, limit, seconds):
    user_id = g.current_user['id']

    return take_rate_slot(
        group,
        user_id,
        limit,
        seconds,
    )


# Uploaded image ko temporary random filename se save karna.
def save_uploaded_image():
    uploaded = request.files.get('image')

    if not uploaded or not uploaded.filename:
        return None, 'Choose an image first.'

    if not allowed_image_name(
        uploaded.filename
    ):
        return (
            None,
            'Only JPG, PNG, and WebP images are allowed.'
        )

    extension = (
        uploaded.filename
        .rsplit('.', 1)[1]
        .lower()
    )

    path = (
        config.UPLOAD_FOLDER
        / (
            uuid.uuid4().hex
            + '.'
            + extension
        )
    )

    try:
        uploaded.save(path)

        error = validate_image(
            path,
            uploaded.mimetype,
        )

    except Exception:
        error = (
            'The uploaded file is not '
            'a readable image.'
        )

    if error:
        delete_upload(path)

        return None, error

    return path, ''


# Modal OCR ko call karna.
# Actual PaddleOCR ab Render par nahi chalta.
def run_ocr(path):
    from core.ocr import (
        classify_ocr,
        process_book_cover,
    )

    result = process_book_cover(path)

    status = classify_ocr(result)

    return result, status


# Barcode processing abhi existing local logic use karega.
def run_barcode(path):
    from core.barcode import read_isbn

    return read_isbn(path)


@scan.post('/search-by-title')
@login_required
def manual_search():
    if limit_reached(
        'manual-search',
        15,
        60,
    ):
        return {
            'error': (
                'You have made several searches recently. '
                'Please try again shortly.'
            )
        }, 429

    started = time.monotonic()

    data = json_body()

    title = str(
        data.get('title') or ''
    ).strip()

    author = str(
        data.get('author') or ''
    ).strip()

    isbn = normalize_isbn(
        data.get('isbn')
    )

    if not title and not isbn:
        return {
            'error': 'Enter a book title or ISBN.'
        }, 400

    if (
        len(title) > 240
        or len(author) > 180
    ):
        return {
            'error': 'Title or author is too long.'
        }, 400

    if isbn and not valid_isbn(isbn):
        return {
            'error': (
                'Enter a valid ISBN-10 or ISBN-13.'
            )
        }, 400

    ranked = identification.identify_candidates(
        title,
        author,
        isbn,
    )

    evidence = {
        'query_title': title,
        'query_author': author,
        'query_isbn': isbn,
        'processing_ms': processing_time(
            started
        ),
    }

    return identification.begin_funnel(
        g.current_user['id'],
        evidence,
        ranked,
        'manual',
    )


@scan.post('/scan')
@login_required
def scan_cover():
    if limit_reached(
        'cover-scan',
        10,
        600,
    ):
        return {
            'error': (
                'You have scanned several covers recently. '
                'Please try again shortly.'
            )
        }, 429

    path, error = save_uploaded_image()

    if error:
        return {
            'error': error
        }, 400

    try:
        # identify_cover run_ocr() ko call karega.
        # run_ocr image Modal PaddleOCR service ko bhejega.
        return identification.identify_cover(
            path,
            g.current_user['id'],
            run_ocr,
        )

    finally:
        # Modal response ke baad temporary image delete.
        delete_upload(path)


@scan.post('/barcode')
@login_required
def scan_barcode():
    if limit_reached(
        'barcode-scan',
        10,
        600,
    ):
        return {
            'error': (
                'You have scanned several barcodes recently. '
                'Please try again shortly.'
            )
        }, 429

    path, error = save_uploaded_image()

    if error:
        return {
            'error': error
        }, 400

    started = time.monotonic()

    try:
        isbn = run_barcode(path)

        if isbn:
            ranked = (
                identification.identify_candidates(
                    '',
                    '',
                    isbn,
                )
            )

        else:
            ranked = {
                'decision': REJECTED,
                'candidates': [],
                'error': (
                    'No valid ISBN barcode was found.'
                ),
            }

        evidence = {
            'query_isbn': isbn,
            'processing_ms': processing_time(
                started
            ),
        }

        return identification.begin_funnel(
            g.current_user['id'],
            evidence,
            ranked,
            'barcode',
        )

    finally:
        delete_upload(path)


@scan.post('/identify/confirm')
@login_required
def confirm_identification():
    if limit_reached(
        'confirm-identification',
        20,
        60,
    ):
        return {
            'error': (
                'You are choosing books very quickly. '
                'Please try again shortly.'
            )
        }, 429

    data = json_body()

    try:
        attempt_id = int(
            data.get('attempt_id')
        )

        candidate_id = int(
            data.get('candidate_id')
        )

    except (TypeError, ValueError):
        return {
            'error': (
                'A valid attempt and candidate '
                'are required.'
            )
        }, 400

    return identification.finalize_candidate(
        g.current_user['id'],
        attempt_id,
        candidate_id,
        'user_confirmation',
    )


@scan.post('/identify/reject')
@login_required
def reject_identification():
    try:
        attempt_id = int(
            json_body().get('attempt_id')
        )

    except (TypeError, ValueError):
        return {
            'error': (
                'A valid attempt is required.'
            )
        }, 400

    reason = (
        'None of the suggested books '
        'was the right one.'
    )

    attempt = database.reject_identification(
        attempt_id,
        g.current_user['id'],
        reason,
    )

    if not attempt:
        return {
            'error': (
                'This identification cannot '
                'be changed.'
            )
        }, 404

    return {
        'status': 'rejected',
        'decision': REJECTED,
        'input_method': attempt['input_method'],
        'attempt_id': attempt_id,
        'failure_reason': reason,
        'recovery_query': (
            attempt['query_title']
            or attempt['ocr_title']
        ),
    }