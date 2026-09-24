import cv2

from utils.validation import normalize_isbn, valid_isbn


_detector = None


# Ek hi detector dobara use karna.
def get_detector():
    """Load the barcode detector once and reuse it."""

    global _detector

    if _detector is None:
        _detector = cv2.barcode.BarcodeDetector()

    return _detector


# Sirf valid 13-digit book ISBN chahiye, har barcode book ka nahi hota.
def pick_isbn(decoded_values):
    """Look through decoded barcode values and return the first valid ISBN-13 book barcode."""

    # Sometimes OpenCV may return one string instead of a list.
    if isinstance(decoded_values, str):
        decoded_values = [decoded_values]

    # If decoded_values is None/empty, use an empty list.
    if not decoded_values:
        decoded_values = []

    for value in decoded_values:

        isbn = normalize_isbn(value)

        # Book barcodes should be valid ISBN-13 values
        # beginning with the Bookland prefixes 978 or 979.
        correct_length = len(isbn) == 13

        correct_prefix = isbn.startswith(('978', '979'))

        checksum_valid = valid_isbn(isbn)

        if (
            correct_length
            and correct_prefix
            and checksum_valid
        ):
            return isbn

    return ""


# Original, blur aur resized versions se barcode parhne ki koshish karni hai.
def barcode_images(image):
    """Create several versions of the same image so barcode detection gets more than one chance."""

    images = []

    # First try the original image.
    images.append(image)

    # Try a lightly blurred image.
    blur_3 = cv2.GaussianBlur(image, (3, 3), 0)

    images.append(blur_3)

    # Try a little more blur.
    blur_5 = cv2.GaussianBlur(image, (5, 5), 0)

    images.append(blur_5)

    # Very wide images are also reduced in size
    # and tried again.
    width = image.shape[1]

    if width > 1500:

        # Reduce wide bars, then smooth resizing noise as for the original.
        for factor in (0.5, 0.25):
            smaller = cv2.resize(image, None, fx=factor, fy=factor,
                                 interpolation=cv2.INTER_AREA)
            images.append(smaller)
            images.append(cv2.GaussianBlur(smaller, (3, 3), 0))
            images.append(cv2.GaussianBlur(smaller, (5, 5), 0))

        scale = 1000 / width

        smaller = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

        smaller_blurred = cv2.GaussianBlur(smaller, (3, 3), 0)

        images.append(smaller_blurred)

    return images


# ISBN mil jaye to return; na mile ya error ho to empty string.
def read_isbn(image_path):
    """Return a valid ISBN-13 from the image, or an empty string."""

    try:

        image = cv2.imread(str(image_path))

        if image is None:
            return ""

        detector = get_detector()

        prepared_images = barcode_images(image)

        for prepared_image in prepared_images:

            (
                found,
                decoded_values,
                decoded_types,
                corners,
            ) = detector.detectAndDecodeWithType(
                prepared_image
            )

            if not found:
                continue

            isbn = pick_isbn(decoded_values)

            if isbn:
                return isbn

    except Exception:
        return ""

    return ""
