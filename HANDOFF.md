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
  `node_modules` now lives in `frontend/`.
- **Run the backend from the repo ROOT** (changed — it used to be `backend/`):
  ```powershell
  backend\.venv\Scripts\python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
  ```
  `scrapers/`, `ai_engine/`, `telegram_bot/` and `ta_engine/` are top-level
  packages, so the repo root has to be on `sys.path`. venv is still
  `backend/.venv`. Only one backend per port 8000 (`Errno 10048` = in use).
- **Run the app from `frontend/`:** `cd frontend; npx expo start`.
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
- Frontend (from `frontend/`): `npx tsc --noEmit -p tsconfig.json` +
  `npx expo export -p ios --output-dir <temp>`.
- Backend (from root): `python -m compileall -q backend scrapers ai_engine
  telegram_bot ta_engine`, then boot uvicorn on a spare port and curl it.
  **Booting the backend sends real Telegram messages** — `TEST_ALERT_SECONDS`
  pings on an interval and a refresh dispatches alerts. Unset it before
  long-running local tests.
- Emoji in `print()` breaks the Windows cp1252 console — use `.encode('ascii','replace')`.

## Project layout (restructured 2026-08-02)
```
backend/     FastAPI + db + shared News contract   scrapers/   12 sources + aggregator
ai_engine/   summarisation (dormant)               telegram_bot/  delivery
ta_engine/   indicators + charts — EMPTY SKELETON  static/charts/ generated PNGs
frontend/    Expo app                              docs/
```
Other packages import *from* `backend` (`backend.models.news`, `backend.db`,
`backend.services.ticker_service`); `backend` never imports them at module scope.

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

## Live ingestion pipeline (added 2026-08-02)
- **`scrapers/news_scraper.py`** — fast lane over Kontan / CNBC Indonesia /
  Bloomberg Technoz. Conditional GET (ETag/Last-Modified), obeys the
  publisher's `Cache-Control: max-age` as an interval floor, honours
  `Retry-After` on 429/503, exponential backoff + jitter to a 15-min ceiling.
  **Deliberately no user-agent rotation** — one honest UA; rotating identity to
  slip a rate limit is what gets an aggregator's whole IP range blocked.
  Env: `FAST_POLL_SECONDS` (default 30, floor 5), `FAST_POLL_ENABLED=0` to stop.
- **`scrapers/commodity_tracker.py`** — Gold `GC=F`, WTI `CL=F`, Brent `BZ=F`
  are real futures. **Coal and nickel have no free Yahoo futures contract**
  (verified: `MTF=F`, `LFF=F`, `ATW=F`, `NID=F`, `NI=F`, `JJN` all return no
  data), so they are tracked as *equity proxies* — ADRO/PTBA/ITMG and
  INCO/ANTM — flagged `isProxy: true`. **The UI must not render a proxy as a
  spot price**; it is a miner's IDR share price carrying earnings/FX/IDX-hours
  effects. Only writes on an actual price move. Env:
  `COMMODITY_POLL_SECONDS` (default 30), `COMMODITY_POLL_ENABLED=0`.
- **Streaming** — `GET /stream/ws` (WebSocket, primary), `GET /stream/sse`
  (fallback, `curl`-friendly), `GET /stream/status` (subscriber count).
  Envelope: `{type: news|commodity|heartbeat, ts, data}`. Bounded 100-event
  per-client queue with drop-oldest, so a stalled phone cannot backpressure the
  scrapers. **Single-process only** — multiple uvicorn workers each get their
  own bus, so a client on worker A misses events from worker B. Multi-worker
  needs Redis pub/sub.
- **Dedup is unchanged**: `stable_id()` = SHA-1(guid or url)[:12] as the news
  PK. Do *not* switch to MD5-of-URL — it changes every id, so the whole cache
  re-inserts as duplicates and every subscriber gets re-alerted for old news.
- New endpoints: `GET /commodities`, `GET /commodities/{symbol}/history`.

## TA engine (added 2026-08-03)
- **`ta_engine/chart_generator.py`** — `generate_chart("BBCA.JK")` returns a
  `ChartResult` (chart_path, support, resistance, tp1, tp2, sl, rsi, atr,
  ema20/50, risk_per_share, warnings) and writes
  `static/charts/{TICKER}_daily.png`.
- **`ta_engine/indicators.py`** — EMA20/50, RSI14, ATR14, fractal swing
  detection, ATR-scaled level clustering, floor-trader pivots. Pure maths, no
  I/O, unit-tested.
- **Levels are LONG-biased**: SL below entry, targets above. Stop goes below
  the nearest support (buffered 0.5×ATR) because that's what invalidates the
  thesis; falls back to 1.5×ATR when no support exists. TP1 = 2R, TP2 = 3R, so
  the 1:2 minimum holds by construction.
- **`ChartResult.warnings` is not decoration** — it flags resistance sitting
  below TP1, stops wider than 15% of price, missing structure, and levels finer
  than the IDX tick size (fraksi harga). Surface them wherever the numbers go.
- **These are not recommendations.** `ta_engine.DISCLAIMER` is burned into the
  PNG and returned in the payload. Anything user-facing must keep it visible —
  see the compliance note below.
- Gotchas handled: `yf.download()` returns MultiIndex columns even for one
  ticker (we use `Ticker().history()`); `ta`'s ATR emits **0.0** during warm-up
  where RSI emits NaN (masked to NaN — a 0 ATR would collapse risk to nothing);
  matplotlib forced to `Agg` and rendering serialised behind a lock because
  pyplot's global state is not thread-safe under `asyncio.to_thread`.

## Compliance note (TP/SL output)
Showing TP/SL to Indonesian retail investors is closer to a trading signal than
to news. Before this ships user-facing: keep the disclaimer visible, never word
it as "buy/sell", and check OJK rules on investment advice plus App Store
Guideline 3.2.1 (financial services). Not legal advice — worth a real check.

## Known limitations / TODO
- **`ta_engine` is not wired to anything yet** — no API route calls
  `generate_chart`, and `telegram_bot` still has no `sendPhoto`, so charts are
  generated on demand from Python but not delivered anywhere.
- **`static/charts/` is never pruned** — one PNG per ticker, overwritten each
  run, but nothing deletes stale tickers.
- **`commodity_price` grows unbounded** — no retention/pruning job yet. Only
  price *changes* are stored, which bounds it a lot, but a busy day still adds
  thousands of rows. Add a pruning job before this runs for weeks.
- **The frontend does not consume the stream yet** — `/stream/ws` is live and
  verified server-side, but no React Native client subscribes to it. The app
  still polls via React Query.
- **EmitenNews not added** — site has no RSS feed (all common paths 500, none
  advertised in HTML); would need an HTML scraper.
- Several pre-existing sources are failing and predate this work:
  Detik (empty error), Bisnis Indonesia (403), BEI/IDX (403 on both the API and
  the HTML fallback).
- **`playwright` + chromium installed but unused** — no scraper uses it; the
  two HTML sources still use httpx + BeautifulSoup.
- **`groq` / `ollama` installed but unwired** — `ai_engine` still targets
  Anthropic only, and that key is intentionally empty, so every refresh logs
  `ai.call_failed ... ANTHROPIC_API_KEY is not set`. Switching to Groq/Ollama
  would make summaries work for free.
- **`python-telegram-bot` installed but unused** — the bot still talks to the
  raw Bot API over httpx. Migration is optional, not started.
- **Bot token leaks into logs**: httpx logs the full request URL at INFO,
  which embeds `TELEGRAM_BOT_TOKEN`. Silence with
  `logging.getLogger("httpx").setLevel(logging.WARNING)`.
- AI summaries off (paid). Global (Yahoo/CNBC) headlines are English (no free translate).
- Existing cached news is "medium" importance until the feed re-fetches (scorer
  runs at fetch time). Optional: delete `backend/data/kabar_pasar.db` once to re-score.
- `investor.id` scraper breaks if their HTML changes (logs `scrape.failed`, returns 0).
- IDNFinancials (403 Cloudflare), Kompas (no RSS), investortrust (JS SPA) — not added.

## Good next tasks (all free)
- `/search <keyword>` bot command · story dedup/clustering · app feed search
- Open the PR: `compare/main...feature/news-price-reaction`, then merge to main.
