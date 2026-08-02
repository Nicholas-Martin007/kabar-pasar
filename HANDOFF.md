# Kabar Pasar — Handoff

> Context handoff for a fresh Claude Code session. Read this first.

**What it is:** Real-time IDX financial-news + market intelligence app.
React Native / Expo (iOS-first) frontend + Python FastAPI backend.
Repo: `github.com/Nicholas-Martin007/kabar-pasar`.

**Active branch:** `feature/news-price-reaction` — the main working branch,
~40 commits ahead of `main`, contains *everything*. No PRs opened yet
(`gh` not installed). Other branch: `feature/ios-live-activity` = parked native
Live Activity scaffold.

---

## Environment gotchas (important)
- **Windows + PowerShell**, project lives in **OneDrive** → `node_modules`
  corrupts (files silently vanish). Fix with **`npm ci`**, not `npm install`.
- **Run the backend from the `backend/` folder:**
  ```powershell
  cd backend
  python -m uvicorn main:app --host 0.0.0.0 --port 8000
  ```
  venv is `backend/.venv` (activate it, or call `.\.venv\Scripts\python`).
  Only one backend per port 8000 (`Errno 10048` = port already in use).
- A JSON formatter keeps reindenting `app.json`/`package.json` — harmless noise;
  `app.json` may show an uncommitted whitespace diff.
- **`backend/.env`** (git-ignored) holds:
  - `TELEGRAM_BOT_TOKEN` (set by user)
  - `ANTHROPIC_API_KEY` — **intentionally empty; user will NOT pay for AI**
  - `TEST_ALERT_SECONDS`, `QUIET_HOURS` (e.g. `22-6`), `HOURLY_DIGEST_HOURS`,
    `HOURLY_DIGEST_COUNT`, `DIGEST_HOUR_WIB`
- Frontend `.env` (git-ignored): `EXPO_PUBLIC_API_URL=http://10.10.5.224:8000`
  (user's LAN IP; a physical iPhone needs the LAN IP, not localhost).

## Verify workflow (no device builds possible — Windows, no Mac / Apple acct)
- Frontend: `npx tsc --noEmit -p tsconfig.json` + `npx expo export -p ios --output-dir <temp>`.
- Backend: `py_compile` each changed file; unit-test logic with small `asyncio` scripts.
- Emoji in `print()` breaks the Windows cp1252 console — use `.encode('ascii','replace')`.

## What's built
- Frontend↔backend via React Query; **live news + market data** (Yahoo `.JK`,
  `^JKSE`), **mock fallback** when offline.
- Market: quotes, **line + candlestick charts**, **news→price reaction badges**,
  free **Yahoo fundamentals** (day/52w range, volume).
- Persisted **watchlist**, **bookmarks** (+ Saved view), **read-state** (AsyncStorage).
- **12 news sources** (RSS + one scraper): CNBC Indonesia, Detik, Kontan, Bisnis,
  BEI, Bloomberg Technoz, Yahoo Finance (markets/gold/oil), CNBC Global
  (geopolitics), Katadata, Antara, Liputan6, Investor.id (HTML scraper, fragile).
- **Free keyword importance scorer** (high/medium/low, no AI) + ~200-ticker detection.
- **Telegram bot**: `/start` (default all-news), `/watch /unwatch /follow /unfollow
  /mute /unmute /all /important` (high-only), `/news [n] /digest /link` (app
  watchlist sync), `/test /testnews`; **inline buttons** (open/mute), **quiet
  hours** (DND), **hourly + daily digest**. App "Connect Telegram" prefs UI
  (all-news / high-only / mute) synced via `/telegram/prefs`.
- DB **auto-migrates** added columns on startup (`init_db`).

## Hard constraints (from CLAUDE.md + this project)
- **No paid AI** — Anthropic key stays empty; AI summaries disabled by choice.
- **Never scrape aggressively; RSS / official APIs only**; no full-article reproduction.
- **Always work on a feature branch, commit + push, mention a PR is needed.**
  Backward-compatible / non-breaking changes only.
- iOS Live Activities need a Mac or paid Apple Developer account → parked.

## Known limitations / TODO
- AI summaries off (paid). Global (Yahoo/CNBC) headlines are English (no free translate).
- Existing cached news is "medium" importance until the feed re-fetches (scorer
  runs at fetch time). Optional: delete `backend/data/kabar_pasar.db` once to re-score.
- `investor.id` scraper breaks if their HTML changes (logs `scrape.failed`, returns 0).
- IDNFinancials (403 Cloudflare), Kompas (no RSS), investortrust (JS SPA) — not added.

## Good next tasks (all free)
- `/search <keyword>` bot command · story dedup/clustering · app feed search
- Open the PR: `compare/main...feature/news-price-reaction`, then merge to main.
