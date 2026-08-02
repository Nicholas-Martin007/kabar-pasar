# Telegram Watchlist Alerts — Setup (free)

Free push alerts to your phone when news breaks for stocks you follow — no
Apple account, no per-message cost. Works while the app is closed.

## How it works
- The backend runs a Telegram bot. Users DM the bot to manage a watchlist.
- Each news refresh cycle, newly-ingested items whose detected tickers match a
  subscriber's watchlist are pushed to that chat.
- The bot's watchlist is **separate** from the app's watchlist (managed via chat
  commands), so this works standalone.

## Setup (≈2 minutes)
1. In Telegram, open **@BotFather** → `/newbot` → follow prompts → copy the
   **bot token** (looks like `123456:ABC-DEF...`).
2. Put it in `backend/.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
   ```
3. Restart the backend:
   ```
   # from the repo root
   backend/.venv/Scripts/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
   ```
   You should see `telegram.poller.started` in the logs (instead of
   `telegram.disabled`).
4. In Telegram, find your bot (by the username you chose) and send:
   - `/start` — register + see help
   - `/watch BBCA` — follow a stock
   - `/list` — show your watchlist
   - `/unwatch BBCA` — stop following
   - `/stop` — unsubscribe entirely

## Receiving alerts
- Alerts fire on the **refresh cycle** (`REFRESH_INTERVAL_MIN`, default 5 min)
  for **newly-ingested** news that has a **detected ticker** matching your
  watchlist. Old/already-cached items don't re-alert.
- Each alert shows: ticker(s), headline, source, and a link. AI `impact` line is
  included if the Anthropic key is set.

## Notes & limits
- Capped at 5 alerts per subscriber per cycle (anti-spam).
- Uses long-polling (`getUpdates`) — no public URL/webhook needed, works from
  localhost.
- Ticker tagging drives matching, so alert coverage improves with the
  `ticker_service` dictionary.
- 100% free (Telegram Bot API has no per-message cost).
