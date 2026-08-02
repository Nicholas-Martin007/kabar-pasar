# Kabar Pasar — Backend

FastAPI service for RSS aggregation and news processing.

> Scraping lives in `../scrapers/`, summarisation in `../ai_engine/`, and
> Telegram delivery in `../telegram_bot/`. This package holds the HTTP layer,
> the database, and the shared `News` contract those packages import.

## Setup

Run from the **repository root** — `backend` is now an importable package, so
the root must be the working directory.

```bash
# Create virtual environment
python -m venv backend/.venv

# Activate (Windows PowerShell)
backend\.venv\Scripts\Activate.ps1

# Activate (macOS / Linux)
source backend/.venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt

# One-time browser download for the Playwright-based sources
python -m playwright install chromium

# Copy env file
cp backend/.env.example backend/.env
```

## Run

From the repository root:

```bash
uvicorn backend.main:app --reload --port 8000
```

API docs available at: http://localhost:8000/docs

## Endpoints

| Method | Path      | Description                   |
|--------|-----------|-------------------------------|
| GET    | /health   | Health check                  |
| GET    | /news     | Fetch and return parsed news  |
