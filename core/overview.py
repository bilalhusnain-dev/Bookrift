import html
import re


MIN_WORDS = 15
MAX_WORDS = 90
MAX_SENTENCES = 3


PROMOTIONAL = (
    r"\bbuy (?:now|today)\b",
    r"\border (?:now|today|your copy)\b",
    r"\badd to (?:your )?cart\b",
    r"\bclick here\b",
    r"\bdownload (?:now|today|your copy)\b",
    r"\bpre[ -]?order\b",
    r"\bsubscribe\b",
    r"\bvisit (?:our|the) (?:site|website)\b",
    r"\bperfect for fans\b",
    r"\bmust[ -]?read\b",
    r"\bmasterpiece\b",
    r"\bcritically acclaimed\b",
    r"\baward[ -]?winning\b",
    r"\bbest[ -]?seller\b",
    r"\bpraise for\b",
)


BOOK_DETAILS = (
    r"^isbn(?:-1[03])?\b",
    r"^(?:paperback|hardcover|ebook|kindle edition)\b",
    r"^(?:publisher|publication date|published by|page count|language)\s*:",
    r"^(?:first|originally) published\b",
    r"^this edition\b",
    r"^(?:with a )?(?:foreword|introduction) by\b",
    r"^translated by\b",
)


WRONG_DOCUMENT = (
    r"\b(?:study guide|workbook|reader'?s guide|teacher'?s guide)\b",
    r"\b(?:summary and analysis|chapter summaries|book summary)\b",
    r"\b(?:unofficial|unauthori[sz]ed) companion\b",
)


SPOILERS = (
    r"\bthe ending reveals\b",
    r"\bthe final twist\b",
    r"\bin the end\b.*\b(?:dies|killer|murderer|identity|revealed)\b",
    r"\bthe (?:killer|murderer) is\b",
)


def word_count(text):
    """Count words in a piece of text."""
    words = re.findall("\\b[\\w'-]+\\b", text)
    return len(words)


# Provider ki description se HTML aur extra formatting hatani hai.
def clean_source_text(value):
    """Clean HTML, Markdown and unnecessary formatting from a provider's book description."""
    text = str(value or '')
    text = html.unescape(text)
    text = re.sub('(?is)<(?:script|style).*?>.*?</(?:script|style)>', ' ', text)
    text = re.sub('(?i)<br\\s*/?>|</?p\\b[^>]*>|</?li\\b[^>]*>', ' ', text)
    text = re.sub('<[^>]+>', ' ', text)
    text = re.sub('\\*{1,3}|_{2,3}', '', text)
    text = re.sub('^\\s*(?:description|overview|synopsis)\\s*:\\s*', '', text, flags=re.I)
    text = re.sub('\\s+', ' ', text)
    text = text.strip(' -|\t\r\n')
    return text


# Dr. ya initials ke dot par sentence nahi torna.
def split_sentences(text):
    """Split text into sentences without breaking common abbreviations and initials."""
    protected = text
    abbreviations = ('Mr.', 'Mrs.', 'Ms.', 'Dr.', 'Prof.', 'St.', 'vs.', 'e.g.', 'i.e.')
    for abbreviation in abbreviations:
        protected_abbreviation = abbreviation.replace('.', '<dot>')
        protected = protected.replace(abbreviation, protected_abbreviation)
    protected = re.sub('\\b([A-Z])\\.', '\\1<dot>', protected)
    sentences = re.split('(?<=[.!?])\\s+(?=[A-Z0-9"“‘\\\'])', protected)
    cleaned_sentences = []
    for sentence in sentences:
        sentence = sentence.replace('<dot>', '.')
        sentence = sentence.strip()
        if sentence:
            cleaned_sentences.append(sentence)
    return cleaned_sentences


def matches_any(text, patterns):
    """Return True if text matches at least one regex pattern."""
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            return True
    return False


# Adhoora sentence aur listed promotional/spoiler phrases skip karne hain.
def usable_sentence(sentence):
    """Decide whether a sentence is suitable for a book overview."""
    complete_sentence = re.search('[.!?][\\"\'”’)]?$', sentence)
    if not complete_sentence:
        return False
    if word_count(sentence) < 4:
        return False
    unwanted_patterns = PROMOTIONAL + BOOK_DETAILS + SPOILERS
    if matches_any(sentence, unwanted_patterns):
        return False
    unwanted_heading = re.match(
        r"^(?:about the author|reviews?|contents?|chapter \d+)\b",
        sentence,
        re.I,
    )
    if unwanted_heading:
        return False
    return True


# Source ke sentences select karne hain, naya text generate nahi karna.
def build_overview(book):
    """Build a short reliable overview from the book's existing source description."""
    raw_description = book.get('description')
    description = clean_source_text(raw_description)
    source = book.get('description_source')
    if not source:
        source = book.get('provider')
    source = str(source or '').strip()
    if not description:
        return unavailable(source, 'No source description is available.')
    if matches_any(description, WRONG_DOCUMENT):
        return unavailable(source, 'The source describes a different type of document.')
    selected = []
    total_words = 0
    sentences = split_sentences(description)
    for sentence in sentences:
        if not usable_sentence(sentence):
            continue
        sentence_words = word_count(sentence)
        new_total = total_words + sentence_words
        if new_total > MAX_WORDS:
            break
        selected.append(sentence)
        total_words = new_total
        if len(selected) == MAX_SENTENCES:
            break
    if total_words < MIN_WORDS:
        return unavailable(source, 'The source does not contain enough reliable summary text.')
    overview_text = ' '.join(selected)
    return {
        "status": "ready",
        "overview": overview_text,
        "source": source,
        "method": "source_sentences",
        "reason": "",
    }


def unavailable(source, reason):
    """Build the standard response used when a safe overview cannot be created."""
    return {
        "status": "unavailable",
        "overview": "",
        "source": source,
        "method": "source_sentences",
        "reason": reason,
    }
