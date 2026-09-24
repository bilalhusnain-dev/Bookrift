import re
from threading import Lock

import torch  # Windows par PaddleOCR se pehle torch ki DLLs load karni hain.
import cv2
from paddleocr import PaddleOCR


MAX_OCR_DIMENSION = 1000
MIN_LINE_CONFIDENCE = 0.35
TITLE_HEIGHT_RATIO = 0.5
NOISE_PHRASES = (
    'NEW YORK TIMES', 'BESTSELLER', 'A NOVEL', 'WINNER', 'PRIZE', 'AWARD',
    'MOTION PICTURE', 'EDITION', 'AUTHOR', 'BESTSELLING', 'THE INTERNATIONAL',
    '#1', 'SUNDAY TIMES',
)
NOT_AUTHOR_WORDS = {
    'the', 'a', 'an', 'of', 'and', 'by', 'in', 'on', 'to', 'for', 'from',
    'new', 'no', 'is', 'it', 'all', 'with', 'his', 'her', 'you', 'your',
}
_reader = None
_ocr_lock = Lock()


# Reader ek baar load karna, har photo par dobara nahi.
def get_reader():
    """Load one OCR pipeline and reuse it for later photos."""
    global _reader
    if _reader is None:
        _reader = PaddleOCR(
            use_textline_orientation=True,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            text_detection_model_name='PP-OCRv5_mobile_det',
            text_recognition_model_name='PP-OCRv5_mobile_rec',
            enable_mkldnn=False,
        )
    return _reader


# Image ka ratio same rakh kar OCR ke liye size adjust karna.
def resize_for_ocr(image):
    height, width = image.shape[:2]
    if max(height, width) < 1000:
        image = cv2.resize(image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    longest_edge = max(image.shape[:2])
    if longest_edge > MAX_OCR_DIMENSION:
        scale = MAX_OCR_DIMENSION / longest_edge
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return image


def noise_line(text):
    for phrase in NOISE_PHRASES:
        if phrase in str(text).upper():
            return True
    return False


# Kam confidence aur promotional lines hata kar text ki position rakhni hai.
def text_blocks(result):
    """Put each readable line, its position and confidence together."""
    texts = result.get('rec_texts') or []
    scores = result.get('rec_scores') or []
    polygons = result.get('rec_polys')
    if polygons is None:
        polygons = result.get('dt_polys')
    if polygons is None:
        polygons = []
    blocks = []
    for text, confidence, polygon in zip(texts, scores, polygons):
        text = str(text).strip()
        if float(confidence) < MIN_LINE_CONFIDENCE or noise_line(text):
            continue
        if len(text) < 2 and not text.isalnum():
            continue
        positions = []
        for point in polygon:
            positions.append(float(point[1]))
        if not positions:
            continue
        blocks.append({
            'text': text,
            'height': max(positions) - min(positions),
            'top': min(positions),
            'confidence': float(confidence),
        })
    return blocks


def pick_author(blocks):
    if not blocks:
        return ''
    chosen = blocks[0]
    for block in blocks:
        if block['height'] == chosen['height'] and block['top'] > chosen['top']:
            chosen = block
    return chosen['text']


# Bara text probable title hai; yeh andaza hai, final match nahi.
def split_title_and_author(blocks):
    """Large text suggests the title; smaller text may be the author."""
    threshold = blocks[0]['height'] * TITLE_HEIGHT_RATIO
    title_parts = []
    author_blocks = []
    for block in blocks:
        if block['height'] >= threshold:
            title_parts.append(block['text'])
        elif not block['text'].isdigit():
            author_blocks.append(block)
    return ' '.join(title_parts), pick_author(author_blocks)


def empty_result(error=''):
    return {
        'probable_title': '',
        'probable_author': '',
        'full_text': '',
        'text_lines': [],
        'confidence_score': 0.0,
        'error': error,
    }


def block_height(block):
    return block['height']


# Photo se text nikalna, phir title aur author ka andaza lagana.
def process_book_cover(image_path):
    image = cv2.imread(str(image_path))
    if image is None:
        return empty_result('Could not read the image file.')
    image = resize_for_ocr(image)
    try:
        # Same reader par ek waqt mein ek photo process karni hai.
        with _ocr_lock:
            output = get_reader().predict(image)
    except Exception:
        return empty_result('The cover could not be read.')
    if not output:
        return empty_result('No text was found on the cover.')
    blocks = text_blocks(output[0])
    if not blocks:
        return empty_result('No readable text was found on the cover.')
    original_lines = []
    for block in blocks:
        original_lines.append(block['text'])
    blocks.sort(key=block_height, reverse=True)
    title, author = split_title_and_author(blocks)
    lines = []
    confidences = []
    for block in blocks:
        lines.append(block['text'])
        confidences.append(block['confidence'])
    return {
        'probable_title': title,
        'probable_author': author,
        'full_text': ' '.join(original_lines),
        'text_lines': lines,
        'confidence_score': sum(confidences) / len(confidences),
    }


# OCR ka result usable, weak ya failed hai, yahan decide karna.
def classify_ocr(result):
    title = str(result.get('probable_title') or '').strip()
    if not title:
        return 'OCR_FAILED'
    letters = 0
    for character in result.get('full_text') or '':
        if character.isalpha():
            letters += 1
    if len(result.get('text_lines') or []) <= 2 and letters < 3:
        return 'OCR_NO_BOOK_TEXT'
    if result.get('confidence_score', 0) < 0.55 or len(title) < 3:
        return 'OCR_LOW_CONFIDENCE'
    return 'OCR_SUCCESS'


def usable_ocr_author(value):
    value = str(value or '').strip()
    words = re.findall(r'[A-Za-z]+', value)
    useful = []
    for word in words:
        if len(word) > 2 and word.lower() not in NOT_AUTHOR_WORDS:
            useful.append(word)
    if useful:
        return value
    else:
        return ''
