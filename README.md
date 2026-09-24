# Bookrift

## Upload to GitHub (Windows PowerShell)

Open PowerShell in this folder (the folder containing `app.py`). Before committing,
keep real credentials in `.env` only; `.env` is ignored by Git. Review any other
configuration files for passwords or tokens. The checked-in `.env.example` is a
template and must never contain real credentials.

Create a new **empty** GitHub repository (do not add a README or `.gitignore` on
GitHub). Copy its HTTPS URL, then run these commands one at a time:

```powershell
git init
git branch -M main
git add .
git status
git check-ignore .env
git commit -m "Initial Bookrift project"
git remote add origin https://github.com/YOUR_USERNAME/Bookrift.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your GitHub username. If there is no local `.env`,
`git check-ignore .env` can still show the ignore rule; review `git status` before
committing. If Git reports that `origin` already exists, check `git remote -v`
and use `git remote set-url origin YOUR_REPOSITORY_URL` if it points elsewhere.

For Render, this project exposes a Flask factory: the start command is
`gunicorn --workers 1 --bind 0.0.0.0:$PORT 'app:create_app()'` when entered in
Render's Linux-based Start Command field. The PostgreSQL database must be hosted
separately and initialized with `python -m flask --app app seed-data` against its
connection URL. Render Free blocks outbound SMTP ports 25, 465 and 587, so the
current Gmail SMTP verification requires a different mail integration there.

Bookrift is our final year project. It helps readers find a book using a cover
photo, an ISBN barcode, or a title search. Readers can save books, mark favourites,
update their reading status and get suggestions based on their interests.

The project uses Python, Flask, PostgreSQL and PaddleOCR. The frontend uses HTML,
CSS and JavaScript. Book information is also fetched from Google Books and
Open Library.

## Setup on Windows

Install 64-bit Python 3.13 and PostgreSQL with pgAdmin. Open the project folder
in VS Code and run these commands in the terminal:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

For a fresh setup, copy `.env.example` to a new file named `.env`.
Keep an existing `.env` if you have already configured it.

In pgAdmin, create a database named `bookrift_db`. Set `DATABASE_URL` in `.env`
using your PostgreSQL username and password. The format is:

```text
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/bookrift_db
```

Replace `YOUR_PASSWORD` with your database password. Special characters in the
password must be URL encoded, for example `@` becomes `%40`.

Set `ADMIN_EMAIL` and `ADMIN_PASSWORD` for the first admin account.
Generate a secret key with this command and copy the output into `SECRET_KEY`:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"
```

### Email settings

Email verification and password recovery use SMTP. For Gmail, enable 2-Step
Verification and create an App Password at https://myaccount.google.com/apppasswords.
Use that App Password, not your normal Gmail password.

Set these values in `.env`:

```text
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
MAIL_FROM=Bookrift <your-email@gmail.com>
```

You can also set `GOOGLE_BOOKS_API_KEY` in `.env`. External book searches and
email delivery need an internet connection. Keep `.env` private and do not
upload it to GitHub. `.env.example` contains the settings template.

### Prepare the database

Keep PostgreSQL running and run this command during first setup:

```powershell
.\.venv\Scripts\python.exe -m flask --app app seed-data
```

This creates the tables, loads the starter catalogue and creates the admin
account. You do not need to run it each time you start the app.

## Run

```powershell
.\.venv\Scripts\python.exe app.py
```

With `PORT=5001` from `.env.example`, open http://127.0.0.1:5001 in your browser.
Keep the terminal and PostgreSQL running. No frontend build command is needed.

Cover images are in `demo_covers`. A barcode example is at
`demo_covers/isbn-barcode.png`. The first cover scan may take longer while OCR
models download or load. Allow camera access when using the camera option.

Each new laptop needs its own dependencies, `.env` settings and PostgreSQL
database. This repository does not include live user data.

## Main files

| File or folder | Purpose |
| --- | --- |
| `app.py` | Starts the Flask application |
| `config.py` | Reads application settings |
| `routes/` | Handles API requests |
| `services/` | Book identification, providers and recommendations |
| `core/` | OCR, barcode reading, matching and overview processing |
| `utils/` | Authentication, validation and email helpers |
| `database.py` | Database queries |
| `schema.sql` | Database tables and constraints |
| `seed.py` and `catalogue.json` | Initial catalogue and admin setup |
| `frontend/dist/` | HTML, CSS and JavaScript |
| `catalogue_covers/` | Catalogue cover images |
| `demo_covers/` | Sample images for scanning |
