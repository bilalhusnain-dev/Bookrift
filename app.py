from flask import Flask, request
import psycopg2

import config
import database
from routes.admin import admin
from routes.auth import auth
from routes.books import books
from routes.library import library
from routes.pages import pages
from routes.scan import scan


# App ki settings, routes aur database yahan connect karne hain.
def create_app(test_config=None):
    if test_config is None:
        config.validate_config()

    app = Flask(__name__, static_folder=None)
    app.config.update(
        DATABASE_URL=config.DATABASE_URL,
        MAX_CONTENT_LENGTH=config.MAX_UPLOAD_BYTES,
        SECRET_KEY=config.SECRET_KEY,
    )
    if test_config:
        app.config.update(test_config)

    config.UPLOAD_FOLDER.mkdir(exist_ok=True)
    database.init_app(app)
    app.register_blueprint(auth)
    app.register_blueprint(books)
    app.register_blueprint(library)
    app.register_blueprint(admin)
    app.register_blueprint(pages)
    app.register_blueprint(scan)

    @app.after_request
    # Har response par headers; CORS sirf configured frontend ke liye.
    def add_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"

        if request.headers.get("Origin") == config.DEV_FRONTEND_ORIGIN:
            response.headers["Access-Control-Allow-Origin"] = config.DEV_FRONTEND_ORIGIN
            response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PATCH, DELETE, OPTIONS'
            response.headers["Vary"] = "Origin"
        return response

    @app.errorhandler(psycopg2.Error)
    # Database ki internal details user ko nahi bhejni.
    def database_error(error):
        app.logger.error('A database operation failed: %s', type(error).__name__)
        return {'error': (
            'The database is temporarily unavailable. Please try again shortly.'
        )}, 503

    @app.errorhandler(400)
    def bad_request(error):
        return {'error': 'The request could not be read. Check your input and try again.'}, 400

    @app.errorhandler(500)
    def server_error(error):
        return {'error': 'Something went wrong. Please try again.'}, 500

    @app.errorhandler(404)
    def not_found(error):
        return {"error": "Page not found."}, 404

    @app.errorhandler(405)
    def method_not_allowed(error):
        return {"error": "Method not allowed."}, 405

    @app.errorhandler(413)
    def upload_too_large(error):
        return {"error": f"Upload must be smaller than {config.MAX_UPLOAD_MB} MB."}, 413

    @app.cli.command("init-db")
    def init_database_command():
        database.init_db()
        print("Database tables are ready.")

    @app.cli.command("seed-data")
    def seed_data_command():
        from seed import create_admin, load_catalogue

        database.init_db()
        added, total = load_catalogue()
        admin_created = create_admin()
        print(f"Catalogue ready: {total} verified books ({added} added)")
        if admin_created:
            print("Admin created")
        else:
            print("Admin already exists")

    return app


if __name__ == "__main__":
    application = create_app()
    application.run(host=config.HOST, port=config.PORT, debug=config.DEBUG)
