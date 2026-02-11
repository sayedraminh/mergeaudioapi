# Client-Side Implementation Guide: Beat-Sync Merge

This document describes how the client should call the new FastAPI endpoint without affecting existing endpoints.

## Endpoint

- Method: `POST`
- URL: `/merge-beat-sync`
- Header: `X-API-Key: <your-api-key>` (required if server `API_KEY` is set)
- Content-Type: `application/json`

Existing endpoints remain unchanged:
- `POST /merge`
- `GET /download/{filename}`
- `GET /health`

## Request body

```json
{
  "video_urls": [
    "https://example.com/video1.mp4",
    "https://example.com/video2.mp4"
  ],
  "audio_url": "https://example.com/song.mp3",
  "beat_timestamps": [4.2, 7.2, 10.2, 12.26],
  "video_cut_starts": [0.0, 0.0],
  "output_filename": "beat_sync_output.mp4"
}
```

## Field rules

- `video_urls`
  - Must contain **exactly 2** URLs.
- `audio_url`
  - One audio file URL.
- `beat_timestamps`
  - Required.
  - Must be strictly increasing numbers (`> 0`).
  - Represents cumulative timeline from song start.
- `video_cut_starts` (optional)
  - If you send **2 values**, they are reused for video 1 and video 2 every time those clips appear.
  - If you send **N values**, `N` must equal `beat_timestamps.length` and each value applies per segment.
  - All values must be `>= 0`.
- `output_filename` (optional)
  - If omitted, server auto-generates a name.

## How server builds the output

For `beat_timestamps = [4.2, 7.2, 10.2, 12.26]`:
- Segment 1 duration = `4.2 - 0.0 = 4.2s` -> uses video 1
- Segment 2 duration = `7.2 - 4.2 = 3.0s` -> uses video 2
- Segment 3 duration = `10.2 - 7.2 = 3.0s` -> uses video 1
- Segment 4 duration = `12.26 - 10.2 = 2.06s` -> uses video 2

Then server concatenates all segments, adds song audio, and returns `output_path`.

## Response (success)

```json
{
  "success": true,
  "message": "Beat-synced video created successfully. File will be auto-deleted in 120 seconds.",
  "output_path": "/absolute/path/to/output/beat_sync_output.mp4",
  "delete_after_seconds": 120,
  "processing_time_seconds": 8.914,
  "segments_created": 4,
  "total_duration_seconds": 12.26
}
```

## Download flow

1. Read `output_path` from response.
2. Extract filename (`beat_sync_output.mp4`).
3. Download immediately from:
   - `GET /download/beat_sync_output.mp4`

Important: output files auto-delete after `delete_after_seconds` (default 120s).

## Client validation checklist (before request)

- Ensure exactly 2 video URLs.
- Ensure audio URL exists.
- Parse beat timestamps to numbers.
- Ensure beats are strictly increasing.
- Ensure optional cut starts are numeric and valid length (2 or N).

## Example JS call

```js
const payload = {
  video_urls: [video1Url, video2Url],
  audio_url: audioUrl,
  beat_timestamps: [4.2, 7.2, 10.2, 12.26],
  video_cut_starts: [0, 0],
  output_filename: "beat_sync_output.mp4"
};

const response = await fetch("http://localhost:8090/merge-beat-sync", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-API-Key": API_KEY
  },
  body: JSON.stringify(payload)
});

const data = await response.json();
if (!response.ok) {
  throw new Error(data.detail || "Beat-sync merge failed");
}
```

## Testing app included

A basic Next.js tester is included at:

`/Users/sayedrh7/Documents/Developer/ccc/nsstudio/mergeraudiotovid/next-test-client`

Use it for quick manual QA of the new endpoint.
