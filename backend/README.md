# Kabar Pasar — Backend

FastAPI service for RSS aggregation and news processing.

## Setup

```bash
cd backend

# Create virtual environment
python -m venv .venv

# Activate (Windows PowerShell)
.venv\Scripts\Activate.ps1

# Activate (macOS / Linux)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy env file
cp .env.example .env
```

## Run

```bash
uvicorn main:app --reload --port 8000
```

API docs available at: http://localhost:8000/docs

## Endpoints

| Method | Path      | Description                   |
|--------|-----------|-------------------------------|
| GET    | /health   | Health check                  |
| GET    | /news     | Fetch and return parsed news  |
