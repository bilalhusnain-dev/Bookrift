CREATE TABLE IF NOT EXISTS rate_events (
    group_name TEXT NOT NULL,
    key_hash CHAR(64) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS rate_events_lookup
    ON rate_events (group_name, key_hash, occurred_at);

-- Account aur role yahan; password ka hash store karna hai.
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(200) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE,
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    auth_version INTEGER NOT NULL DEFAULT 0,
    interests TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS auth_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose VARCHAR(20) NOT NULL CHECK (purpose IN ('verify', 'reset', 'change_password')),
    token_hash CHAR(64) UNIQUE NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS books (
    id SERIAL PRIMARY KEY,
    title VARCHAR(240) NOT NULL,
    normalized_title VARCHAR(240) NOT NULL,
    author VARCHAR(180) NOT NULL DEFAULT '',
    normalized_author VARCHAR(180) NOT NULL DEFAULT '',
    isbn_10 VARCHAR(10),
    isbn_13 VARCHAR(13),
    google_books_id VARCHAR(120),
    open_library_edition_id VARCHAR(120),
    open_library_work_id VARCHAR(120),
    provider VARCHAR(30) NOT NULL DEFAULT 'catalogue',
    catalogue_status VARCHAR(20)
        CHECK (catalogue_status IN ('PENDING', 'VERIFIED', 'REJECTED', 'NEEDS_REVIEW')),
    publisher VARCHAR(180) NOT NULL DEFAULT '',
    published_date VARCHAR(30) NOT NULL DEFAULT '',
    genres TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    description_source VARCHAR(80) NOT NULL DEFAULT '',
    overview TEXT NOT NULL DEFAULT '',
    cover_url TEXT NOT NULL DEFAULT '',
    page_count INTEGER NOT NULL DEFAULT 0 CHECK (page_count >= 0),
    page_count_source VARCHAR(40) NOT NULL DEFAULT '',
    rating NUMERIC(3, 2),
    ratings_count INTEGER NOT NULL DEFAULT 0 CHECK (ratings_count >= 0),
    on_shelves INTEGER NOT NULL DEFAULT 0 CHECK (on_shelves >= 0),
    facts_checked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE books
    ADD COLUMN IF NOT EXISTS page_count_source VARCHAR(40) NOT NULL DEFAULT '';

CREATE UNIQUE INDEX IF NOT EXISTS books_isbn10_unique
    ON books(isbn_10) WHERE isbn_10 IS NOT NULL AND isbn_10 <> '';
CREATE UNIQUE INDEX IF NOT EXISTS books_isbn13_unique
    ON books(isbn_13) WHERE isbn_13 IS NOT NULL AND isbn_13 <> '';
CREATE UNIQUE INDEX IF NOT EXISTS books_google_id_unique
    ON books(google_books_id)
    WHERE google_books_id IS NOT NULL AND google_books_id <> '';
CREATE UNIQUE INDEX IF NOT EXISTS books_open_library_edition_unique
    ON books(open_library_edition_id)
    WHERE open_library_edition_id IS NOT NULL AND open_library_edition_id <> '';
CREATE INDEX IF NOT EXISTS books_catalogue_status_index ON books(catalogue_status);
CREATE INDEX IF NOT EXISTS books_title_author_index
    ON books(normalized_title, normalized_author);

-- User aur book ka relation; favourite aur reading status bhi yahin.
CREATE TABLE IF NOT EXISTS library (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    favorite BOOLEAN NOT NULL DEFAULT FALSE,
    reading_status VARCHAR(20) NOT NULL DEFAULT 'identified'
        CHECK (reading_status IN ('identified', 'want_to_read', 'reading', 'finished')),
    added_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, book_id)
);

CREATE INDEX IF NOT EXISTS library_user_index ON library(user_id);

-- Har search/scan ka evidence aur final decision rakhna hai.
CREATE TABLE IF NOT EXISTS identification_attempts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    input_method VARCHAR(20) NOT NULL
        CHECK (input_method IN ('cover', 'manual', 'barcode')),
    ocr_status VARCHAR(30) NOT NULL DEFAULT '',
    ocr_title VARCHAR(240) NOT NULL DEFAULT '',
    ocr_author VARCHAR(180) NOT NULL DEFAULT '',
    ocr_text TEXT NOT NULL DEFAULT '',
    ocr_confidence REAL NOT NULL DEFAULT 0,
    query_title VARCHAR(240) NOT NULL DEFAULT '',
    query_author VARCHAR(180) NOT NULL DEFAULT '',
    query_isbn VARCHAR(13) NOT NULL DEFAULT '',
    decision VARCHAR(30) NOT NULL DEFAULT 'PENDING'
        CHECK (decision IN (
            'PENDING', 'HIGH_CONFIDENCE', 'NEEDS_CONFIRMATION',
            'REJECTED', 'USER_CONFIRMED'
        )),
    selected_book_id INTEGER REFERENCES books(id) ON DELETE SET NULL,
    failure_reason VARCHAR(120) NOT NULL DEFAULT '',
    processing_ms INTEGER NOT NULL DEFAULT 0 CHECK (processing_ms >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS attempts_user_index
    ON identification_attempts(user_id);

-- Attempt ki choices rakhni hain taake user baad mein confirm kar sake.
CREATE TABLE IF NOT EXISTS identification_candidates (
    id SERIAL PRIMARY KEY,
    attempt_id INTEGER NOT NULL
        REFERENCES identification_attempts(id) ON DELETE CASCADE,
    rank_position INTEGER NOT NULL CHECK (rank_position > 0),
    provider VARCHAR(30) NOT NULL DEFAULT '',
    score REAL NOT NULL DEFAULT 0,
    decision VARCHAR(30) NOT NULL
        CHECK (decision IN ('HIGH_CONFIDENCE', 'NEEDS_CONFIRMATION', 'REJECTED')),
    metadata JSONB NOT NULL,
    selected BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(attempt_id, rank_position)
);

CREATE INDEX IF NOT EXISTS candidates_attempt_index
    ON identification_candidates(attempt_id);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(200) NOT NULL,
    subject VARCHAR(200) NOT NULL DEFAULT '',
    message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
