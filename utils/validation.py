import re
from pathlib import Path

from flask import request
from PIL import Image, UnidentifiedImageError

import config


ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}

ALLOWED_MIMES = {'image/jpeg', 'image/png', 'image/webp'}

EMAIL_PATTERN = re.compile('^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$')

# The users and messages tables both store the address in VARCHAR(200).
MAX_EMAIL_LENGTH = 200


# Genres may arrive separated using commas, semicolons, or slashes.
GENRE_SEPARATORS = re.compile('[,;/]')


GENRE_SYNONYMS = {
    "thrillers": "Thriller",
    "mysteries": "Mystery",
    "classics": "Classic",
    "memoirs": "Memoir",
    "class": "Social class",
    "juvenile": "Children's",
    "juvenile literature": "Children's",
    "juvenile works": "Children's",
    "children's books": "Children's",
    "children's stories": "Children's",
    "science fiction": "Sci-fi",
    "science": "Popular science",
    "action & adventure": "Adventure",
    "action and adventure": "Adventure",
    "high fantasy": "Epic fantasy",
}


# Request se JSON object lena; galat format ho to empty dictionary.
def json_body():
    """Return the JSON object sent with the current request."""

    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return {}

    return data


def valid_email(email):
    """Return True if the email has a basic valid email structure."""

    email = str(email or '').strip()

    # The email column holds 200 characters. Refusing a longer address here
    # keeps the database from raising on the insert and answering with a 500.
    if len(email) > MAX_EMAIL_LENGTH:
        return False

    match = EMAIL_PATTERN.fullmatch(email)

    if match:
        return True

    return False


# Password rules check karne hain; theek ho to empty string.
def password_error(password):
    """Check the password rules."""

    password = str(password or '')

    if len(password) < 8:
        return "Password must be at least 8 characters."

    if len(password) > 128:
        return "Password is too long."

    has_letter = False

    for character in password:
        if character.isalpha():
            has_letter = True
            break

    if not has_letter:
        return "Password must include a letter."

    has_number = False

    for character in password:
        if character.isdigit():
            has_number = True
            break

    if not has_number:
        return "Password must include a number."

    return ""


def normalize_isbn(value):
    """Remove spaces, dashes and other characters from an ISBN. Keep only digits and X."""

    value = str(value or '')

    isbn = re.sub('[^0-9Xx]', '', value)

    isbn = isbn.upper()

    return isbn


# Sirf digits ki length nahi, ISBN ka checksum bhi check karna.
def valid_isbn(value):
    """Check whether a value is a valid ISBN-10 or ISBN-13."""

    isbn = normalize_isbn(value)

    # ISBN-10

    if len(isbn) == 10:

        first_nine = isbn[:9]
        last_character = isbn[9]

        # First 9 characters must all be numbers.
        if not first_nine.isdigit():
            return False

        # Last character may be a digit or X.
        if not (
            last_character.isdigit()
            or last_character == "X"
        ):
            return False

        digits = []

        for character in first_nine:
            digits.append(int(character))

        if last_character == "X":
            final_digit = 10
        else:
            final_digit = int(last_character)

        digits.append(final_digit)

        total = 0

        for index, number in enumerate(digits):

            weight = 10 - index

            total += (
                weight
                * number
            )

        if total % 11 == 0:
            return True

        return False

    # ISBN-13

    if len(isbn) == 13:

        if not isbn.isdigit():
            return False

        total = 0

        for index, character in enumerate(isbn):

            number = int(character)

            if index % 2 == 0:
                weight = 1
            else:
                weight = 3

            total += (
                number
                * weight
            )

        if total % 10 == 0:
            return True

        return False

    # Neither ISBN-10 nor ISBN-13.
    return False


def junk_genre(label):
    """Return True for provider labels that do not look like useful genres."""

    if ":" in label:
        return True

    if "(" in label:
        return True

    if ")" in label:
        return True

    return False


# Genre labels saaf karne aur duplicate/junk labels hatane hain.
def genre_names(value):
    """Convert a raw genre string into a clean list of genre labels."""

    names = []

    seen = set()

    raw_value = str(value or '')

    parts = GENRE_SEPARATORS.split(raw_value)

    for part in parts:

        # Remove extra spaces inside and around the genre.
        words = part.split()

        label = ' '.join(words)

        lower_label = label.casefold()

        # EXACT SYNONYM FIRST

        if lower_label in GENRE_SYNONYMS:

            label = GENRE_SYNONYMS[lower_label]

        else:

            # Example:
            # "Psychological fiction"
            # becomes
            # "Psychological"
            if lower_label.endswith(" fiction"):

                suffix_length = len(' fiction')

                label = label[:-suffix_length].strip()

            # Check synonyms again after removing the suffix.
            lower_label = label.casefold()

            if lower_label in GENRE_SYNONYMS:
                label = GENRE_SYNONYMS[lower_label]

        key = label.casefold()

        # Ignore empty labels.
        if not label:
            continue

        # Ignore provider junk labels.
        if junk_genre(label):
            continue

        # Ignore duplicate genres.
        if key in seen:
            continue

        seen.add(key)

        names.append(label)

    return names


def genre_map(value):
    """Return genre labels in a case-insensitive dictionary."""

    names = genre_names(value)

    result = {}

    for name in names:

        key = name.casefold()

        result[key] = name

    return result


def allowed_image_name(filename):
    """Check whether the filename has an allowed image extension."""

    filename = str(filename or '')

    if "." not in filename:
        return False

    parts = filename.rsplit('.', 1)

    extension = parts[1].lower()

    if extension in ALLOWED_EXTENSIONS:
        return True

    return False


# Extension par bharosa nahi; actual format, size aur pixels bhi check karne hain.
def validate_image(path, declared_mime=""):
    """Check the uploaded image type, size, readability and dimensions."""

    path = Path(path)

    # MIME TYPE CHECK

    if declared_mime:

        declared_mime = declared_mime.lower()

        if declared_mime not in ALLOWED_MIMES:
            return 'Only JPG, PNG, and WebP images are allowed.'

    # FILE SIZE CHECK

    file_size = path.stat().st_size

    if file_size > config.MAX_UPLOAD_BYTES:
        return f'The image must be smaller than {config.MAX_UPLOAD_MB} MB.'

    # ACTUAL IMAGE VALIDATION

    try:

        # First verify that Pillow can parse the file.
        with Image.open(path) as image:
            image.verify()

        # Re-open because verify() leaves the image unusable
        # for normal metadata access.
        with Image.open(path) as image:

            image_format = (image.format or '').upper()

            width, height = image.size

    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        OSError,
        ValueError,
        SyntaxError,
    ):
        return 'The uploaded file is not a readable image.'

    # ACTUAL FORMAT CHECK

    allowed_formats = {'JPEG', 'PNG', 'WEBP'}

    if image_format not in allowed_formats:
        return 'The uploaded file is not a supported image.'

    # MINIMUM DIMENSIONS

    if width < 40:
        return 'The image is too small to read.'

    if height < 40:
        return 'The image is too small to read.'

    # MAXIMUM PIXEL COUNT

    total_pixels = width * height

    if total_pixels > config.MAX_IMAGE_PIXELS:
        return 'The image dimensions are too large.'

    # Empty string means no validation error.
    return ""


# Temporary photo ka kaam khatam ho to file hatani hai.
def delete_upload(path):
    """Delete a temporary uploaded file."""

    try:

        file_path = Path(path)

        file_path.unlink(missing_ok=True)

    except OSError:
        pass
