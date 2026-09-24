import json

from flask import Flask
from werkzeug.security import generate_password_hash

import config
import database
from utils.validation import genre_names


CATALOGUE_FILE = config.BASE_DIR / "catalogue.json"


# JSON wali books database mein dalni hain; existing book update hogi.
def load_catalogue():
    with CATALOGUE_FILE.open(encoding="utf-8") as file:
        books = json.load(file)

    added = 0
    for book in books:
        # The dataset joins genres with semicolons inside one string, so parse
        # it properly and store the one separator the whole app agrees on.
        book['genres'] = ', '.join(genre_names('; '.join(book.get('genres') or [])))

        # Update an existing book instead of adding it twice.
        existing = database.find_catalogue_identity(book)
        if not existing:
            existing = database.find_book_by_identifiers(book)
        if existing:
            database.update_book_facts(existing["id"], book)
            # Apply the current catalogue text and cover.
            database.update_catalogue_book(existing["id"], book)
            database.update_book_overview(
                existing["id"],
                book.get("description") or "",
                book.get("description_source") or "",
                book.get("overview") or "",
            )
            continue

        if database.save_book(book):
            added += 1

    return added, len(books)


# Email pehle se ho to naya admin nahi banega, role bhi change nahi hoga.
def create_admin(email=None, password=None):
    email = (email or config.ADMIN_EMAIL).strip().lower()
    password = password or config.ADMIN_PASSWORD

    if not password:
        raise RuntimeError("Add ADMIN_PASSWORD to the .env file first.")

    if database.get_user_by_email(email):
        return False

    user_id = database.create_user(
        name="Admin",
        email=email,
        password_hash=generate_password_hash(password),
        is_admin=True,
        email_verified=True,
    )
    return user_id is not None


# Pehli setup ke liye tables, catalogue aur admin ready karne hain.
def run_seed():
    app = Flask(__name__)
    app.config["DATABASE_URL"] = config.DATABASE_URL
    database.init_app(app)

    with app.app_context():
        database.init_db()
        added, total = load_catalogue()
        admin_created = create_admin()

    print(f"Catalogue ready: {total} verified books ({added} added)")
    if admin_created:
        print("Admin account created")
    else:
        print("Admin account already exists")


if __name__ == "__main__":
    run_seed()
