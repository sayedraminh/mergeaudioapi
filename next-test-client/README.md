# Next Test Client

Minimal Next.js app for testing the FastAPI video endpoints.

## 1) Setup

```bash
cd /Users/sayedrh7/Documents/Developer/ccc/nsstudio/mergeraudiotovid/next-test-client
cp .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`.

## 2) Environment variables

- `MERGE_API_BASE_URL` (default `http://localhost:8090`)
- `MERGE_API_KEY` (must match FastAPI `API_KEY` if auth is enabled)

## 3) What this app does

- `POST /api/merge-beat-sync` proxies to FastAPI `/merge-beat-sync`.
- `POST /api/merge` proxies to FastAPI `/merge`.
- `POST /api/trim` proxies to FastAPI `/trim`.
- `POST /api/reverse` proxies to FastAPI `/reverse`.
- `POST /api/speed` proxies to FastAPI `/speed`.
- `POST /api/extract-fifth-frame` proxies to FastAPI `/extract-fifth-frame` and streams back `image/png`.
- `GET /api/download/[filename]` proxies file download from FastAPI `/download/{filename}`.

Available UI pages:
- `/` beat-sync tester
- `/merge` merge tester
- `/trim` trim tester
- `/reverse` reverse tester
- `/speed` speed/slow tester
- `/extract-fifth-frame` fifth-frame PNG tester with URL and local file upload support

## 4) Notes

- FastAPI output is auto-deleted after 120 seconds, so download quickly.
- `video_cut_starts` can be either:
  - `2` values: one for video 1 and one for video 2.
  - `N` values: one per generated segment (`N = beat_timestamps.length`).
