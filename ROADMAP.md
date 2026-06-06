# Kabar Pasar — Roadmap

Real-time financial news intelligence untuk investor ritel (React Native + Expo,
iOS-first; backend FastAPI + Python).

---

## Current Phase — UI MVP + Backend RSS + AI Summary

### Sudah selesai

**Frontend (Expo / React Native)**
- Screen utama: Home, Berita (feed + filter chips), Watchlist (add/remove +
  search), News Detail (ringkasan AI + saham terkait), Stock Detail (chart),
  Profil/Settings (notif prefs + quiet hours)
- Global state: WatchlistContext, SettingsContext
- Theme system konsisten (colors, spacing, typography) mengikuti WCAG
- **Integrasi API**: screen berita kini fetch dari backend via React Query
  (`src/services/api.ts`, `src/hooks/useNews.ts`), dengan fallback ke mock data
  saat offline / backend belum jalan

**Backend (FastAPI)**
- Aggregasi RSS dari 5 sumber: BEI, Bisnis Indonesia, CNBC Indonesia, Detik,
  Kontan (modular per-source di `services/sources/`)
- Deteksi ticker otomatis dari teks berita
- AI summarisation (Anthropic tool-use) — bullet ringkasan + 1-line impact
- Persistensi ke SQLite (async SQLAlchemy); siap migrasi ke Postgres via
  `DATABASE_URL`
- Background scheduler (interval refresh configurable) + endpoint `POST /refresh`
- API: `GET /news` (filter source/importance/ticker), `/news/stats`, `/health`

### Masih in-progress

- **Data pasar riil**: IHSG & harga saham di Home/Stock Detail masih mock —
  perlu integrasi financial data API (Finnhub / Marketaux / Alpha Vantage)
- **Populasi berita live**: butuh `ANTHROPIC_API_KEY` di `backend/.env` lalu
  jalankan `POST /refresh` untuk mengisi DB
- **Push notifications**: FCM belum di-wire; notif berbasis watchlist belum ada
- **Filter watchlist di backend**: saat ini filter ticker per-request, belum ada
  endpoint khusus "berita untuk watchlist saya"
- **Dedup & entity extraction**: dedup dasar ada, perlu diperkuat untuk skala

---

## Future / Backlog
> Catatan eksplorasi, bukan komitmen.

- **iOS Live Activities** — berita/harga saham watchlist tampil di lock screen &
  Dynamic Island, tap untuk buka berita. Butuh dev build + widget extension
  (SwiftUI). Fase 1: update lokal; Fase 2: push via APNs (`liveactivity`).
- **Akumulasi/Distribusi (1W, 1M, 1Y)** — butuh broker flow + foreign flow data,
  kemungkinan dari IDX Data Services atau RTI. Kombinasi dengan news untuk
  penjelasan pergerakan.
- **Tambah sumber berita** — global (Bloomberg, Reuters, CNBC) + IR emiten +
  emitennews.com. Selalu via RSS/API resmi, tanpa scraping agresif.
- **Personalisasi & relevansi** — importance scoring per-user berbasis watchlist,
  smart filtering untuk kurangi noise notifikasi.
- **Skalabilitas pipeline** — antrian ingestion, caching Redis, observabilitas.

---

*Setiap perubahan harus backward-compatible & non-breaking. Prefer kode yang
sederhana, mudah dibaca, dan mudah dirawat.*
