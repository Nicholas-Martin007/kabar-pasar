# Kabar Pasar

Real-time financial news intelligence for Indonesian retail investors.
React Native / Expo app (iOS-first) backed by a Python FastAPI pipeline that
aggregates IDX and global market news, scores it, and pushes what matters.

## Repository layout

```
backend/          FastAPI app — routers, SQLAlchemy models/db, shared services
  ├── routers/      /news, /market, /telegram endpoints
  ├── db/           async SQLAlchemy engine, models, repository
  ├── models/       Pydantic contract (News) shared across packages
  └── services/     market_service, scheduler, ticker_service
scrapers/         12 news sources (RSS + HTML) and the fan-out aggregator
ta_engine/        technical indicators + chart rendering  (not yet implemented)
ai_engine/        news summarisation / scoring
telegram_bot/     Telegram delivery (commands, alerts, digests)
static/charts/    generated chart images (git-ignored)
frontend/         Expo / React Native app
docs/             setup guides
```

`backend` is the shared kernel: the other top-level packages import
`backend.models.news`, `backend.db` and `backend.services.ticker_service` from
it. Nothing in `backend/` imports back into them at module scope.

## Run the backend

From the **repository root** (not `backend/`) — the packages above are
top-level, so the root must be on `sys.path`:

```powershell
backend\.venv\Scripts\python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

First-time setup:

```powershell
python -m venv backend\.venv
backend\.venv\Scripts\python -m pip install -r backend\requirements.txt
backend\.venv\Scripts\python -m playwright install chromium
copy backend\.env.example backend\.env
```

API docs: http://localhost:8000/docs

## Run the app

From `frontend/`:

```powershell
cd frontend
npm ci          # NOT npm install — see HANDOFF.md, OneDrive corrupts node_modules
npx expo start
```

Copy `frontend/.env.example` to `frontend/.env` and set `EXPO_PUBLIC_API_URL`.
A physical device needs your machine's LAN IP, not `localhost`.

## Verify a change

```powershell
# backend
backend\.venv\Scripts\python -m compileall -q backend scrapers ai_engine telegram_bot ta_engine

# frontend
cd frontend; npx tsc --noEmit -p tsconfig.json; npx expo export -p ios --output-dir $env:TEMP\exp
```

See [HANDOFF.md](HANDOFF.md) for environment gotchas and current status.
