import os
import re
import mimetypes
from pathlib import Path

import requests


# Modal par deployed PaddleOCR endpoint.
MODAL_OCR_URL = os.getenv(
    "MODAL_OCR_URL",
    "https://bilalhusnain-dev--bookrift-ocr-scan.modal.run"
).strip()


NOT_AUTHOR_WORDS = {
    'the', 'a', 'an', 'of', 'and', 'by', 'in', 'on', 'to', 'for', 'from',
    'new', 'no', 'is', 'it', 'all', 'with', 'his', 'her', 'you', 'your',
}


def empty_result(error=''):
    return {
        'probable_title': '',
        'probable_author': '',
        'full_text': '',
        'text_lines': [],
        'confidence_score': 0.0,
        'error': error,
    }


# Modal se aane wale result ko safe format mein rakhna.
def normalize_ocr_result(data):
    if not isinstance(data, dict):
        return empty_result('Invalid OCR response.')

    try:
        confidence = float(
            data.get('confidence_score') or 0.0
        )
    except (TypeError, ValueError):
        confidence = 0.0

    text_lines = data.get('text_lines')

    if not isinstance(text_lines, list):
        text_lines = []

    return {
        'probable_title': str(
            data.get('probable_title') or ''
        ).strip(),

        'probable_author': str(
            data.get('probable_author') or ''
        ).strip(),

        'full_text': str(
            data.get('full_text') or ''
        ).strip(),

        'text_lines': [
            str(line).strip()
            for line in text_lines
            if str(line).strip()
        ],

        'confidence_score': confidence,

        'error': str(
            data.get('error') or ''
        ).strip(),
    }


# Image Render se Modal OCR service ko bhejna.
def process_book_cover(image_path):
    path = Path(image_path)

    if not path.exists() or not path.is_file():
        return empty_result(
            'Could not read the image file.'
        )

    if not MODAL_OCR_URL:
        return empty_result(
            'OCR service is not configured.'
        )

    content_type = (
        mimetypes.guess_type(path.name)[0]
        or 'application/octet-stream'
    )

    try:
        with path.open('rb') as image_file:

            files = {
                'file': (
                    path.name,
                    image_file,
                    content_type,
                )
            }

            response = requests.post(
                MODAL_OCR_URL,
                files=files,

                # Modal cold start kabhi thora time le sakta hai.
                timeout=(15, 240),
            )

        response.raise_for_status()

    except requests.Timeout:
        return empty_result(
            'OCR service took too long to respond.'
        )

    except requests.RequestException as error:
        print(
            'MODAL OCR REQUEST ERROR:',
            error
        )

        return empty_result(
            'The OCR service is temporarily unavailable.'
        )

    try:
        data = response.json()

    except ValueError:
        return empty_result(
            'Invalid response from OCR service.'
        )

    return normalize_ocr_result(data)


# OCR ka result usable, weak ya failed hai, yahan decide karna.
def classify_ocr(result):
    title = str(
        result.get('probable_title') or ''
    ).strip()

    if not title:
        return 'OCR_FAILED'

    letters = 0

    for character in result.get('full_text') or '':
        if character.isalpha():
            letters += 1

    if (
        len(result.get('text_lines') or []) <= 2
        and letters < 3
    ):
        return 'OCR_NO_BOOK_TEXT'

    if (
        result.get('confidence_score', 0) < 0.55
        or len(title) < 3
    ):
        return 'OCR_LOW_CONFIDENCE'

    return 'OCR_SUCCESS'


def usable_ocr_author(value):
    value = str(value or '').strip()

    words = re.findall(
        r'[A-Za-z]+',
        value
    )

    useful = []

    for word in words:
        if (
            len(word) > 2
            and word.lower() not in NOT_AUTHOR_WORDS
        ):
            useful.append(word)

    if useful:
        return value

    return ''