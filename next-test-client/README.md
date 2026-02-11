# Next Test Client

Minimal Next.js app for testing the FastAPI beat-sync endpoint.

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

- UI form collects `video_urls`, `audio_url`, `beat_timestamps`, `video_cut_starts`, `output_filename`.
- `POST /api/merge-beat-sync` (Next route handler) proxies request to FastAPI `/merge-beat-sync`.
- `GET /api/download/[filename]` proxies file download from FastAPI `/download/{filename}`.

## 4) Notes

- FastAPI output is auto-deleted after 120 seconds, so download quickly.
- `video_cut_starts` can be either:
  - `2` values: one for video 1 and one for video 2.
  - `N` values: one per generated segment (`N = beat_timestamps.length`).
