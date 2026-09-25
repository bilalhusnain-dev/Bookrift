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


# Sirf valid 13-digit book ISBN chahiye.
def pick_isbn(decoded_values):
    """
    Look through decoded barcode values and return
    the first valid ISBN-13 book barcode.
    """

    # Kabhi OpenCV ek single string return kar sakta hai.
    if isinstance(decoded_values, str):
        decoded_values = [decoded_values]

    # None/empty ho to empty list use karo.
    if not decoded_values:
        decoded_values = []

    for value in decoded_values:

        isbn = normalize_isbn(value)

        # Book barcode 13 digits ka hona chahiye.
        correct_length = len(isbn) == 13

        # ISBN-13 Bookland prefix 978 ya 979 hota hai.
        correct_prefix = isbn.startswith(
            ('978', '979')
        )

        # Checksum bhi valid hona chahiye.
        checksum_valid = valid_isbn(isbn)

        if (
            correct_length
            and correct_prefix
            and checksum_valid
        ):
            return isbn

    return ""


# Barcode detect karne ke liye image ki
# multiple versions try karni hain.
def barcode_images(image):
    """
    Create several versions of the same image
    so barcode detection gets more than one chance.
    """

    images = []

    # Original image.
    images.append(image)

    # Light blur.
    blur_3 = cv2.GaussianBlur(
        image,
        (3, 3),
        0
    )

    images.append(blur_3)

    # Thori zyada blur.
    blur_5 = cv2.GaussianBlur(
        image,
        (5, 5),
        0
    )

    images.append(blur_5)

    width = image.shape[1]

    # Bohat wide image ho to resized versions bhi try karo.
    if width > 1500:

        for factor in (0.5, 0.25):

            smaller = cv2.resize(
                image,
                None,
                fx=factor,
                fy=factor,
                interpolation=cv2.INTER_AREA
            )

            images.append(smaller)

            images.append(
                cv2.GaussianBlur(
                    smaller,
                    (3, 3),
                    0
                )
            )

            images.append(
                cv2.GaussianBlur(
                    smaller,
                    (5, 5),
                    0
                )
            )

        scale = 1000 / width

        smaller = cv2.resize(
            image,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_AREA
        )

        smaller_blurred = cv2.GaussianBlur(
            smaller,
            (3, 3),
            0
        )

        images.append(smaller_blurred)

    return images


# ISBN mil jaye to return,
# warna empty string.
def read_isbn(image_path):
    """
    Return a valid ISBN-13 from the image,
    or an empty string.
    """

    try:

        image = cv2.imread(
            str(image_path)
        )

        if image is None:
            return ""

        detector = get_detector()

        prepared_images = barcode_images(
            image
        )

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

            isbn = pick_isbn(
                decoded_values
            )

            if isbn:
                return isbn

    except Exception as error:
        print(
            "BARCODE ERROR:",
            error
        )

        return ""

    return ""