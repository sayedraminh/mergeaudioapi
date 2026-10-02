# Video Audio Merger API Documentation

A FastAPI server that merges multiple videos and adds an audio track.

## Base URL

```
http://localhost:8000
```

## Authentication

All `POST /merge`, `POST /overlay`, `POST /merge-beat-sync`, `POST /trim`, `POST /reverse`, `POST /speed`, and `POST /extract-fifth-frame` requests require an API key in the header:

```
X-API-Key: your-api-key
```

## Endpoints

### Health Check

```http
GET /health
```

**Response:**
```json
{
  "status": "healthy"
}
```

---

### Merge Videos with Audio

```http
POST /merge
```

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `X-API-Key` | Yes | Your API key |
| `Content-Type` | Yes | `application/json` |

**Request Body:**
```json
{
  "video_urls": ["https://example.com/video1.mp4", "https://example.com/video2.mp4"],
  "audio_url": "https://example.com/audio.mp3",
  "output_filename": "my_output.mp4"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `video_urls` | array | Yes | List of video URLs to merge |
| `audio_url` | string | No | Optional URL of the replacement audio file. Omit it to preserve each clip's source audio while concatenating. |
| `output_filename` | string | No | Custom output filename (auto-generated if not provided) |

**Success Response (200):**
```json
{
  "success": true,
  "message": "Video and audio merged successfully. File will be auto-deleted in 120 seconds.",
  "output_path": "/path/to/output/my_output.mp4",
  "delete_after_seconds": 120,
  "processing_time_seconds": 7.812
}
```

**Error Responses:**
- `401` - Invalid or missing API key
- `400` - Failed to download file
- `422` - Validation error (invalid URL format, missing fields)
- `500` - Server error

---

### Overlay a Video Layer

```http
POST /overlay
```

Composites one visual video layer over a base video. The base supplies the final
dimensions, duration, and audio. The overlay's audio is ignored, while an overlay
alpha channel is preserved during compositing.

**Request Body:**
```json
{
  "base_video_url": "https://example.com/original.mp4",
  "overlay_video_url": "https://example.com/layer.webm",
  "x": 0,
  "y": 0,
  "output_filename": "layered.mp4"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `base_video_url` | string | Yes | URL of the user's original video |
| `overlay_video_url` | string | Yes | URL of the visual layer; its audio is ignored |
| `x` | integer | No | Horizontal pixel position, default `0` |
| `y` | integer | No | Vertical pixel position, default `0` |
| `overlay_width` | positive integer | No | Rendered layer width; base width by default |
| `overlay_height` | positive integer | No | Rendered layer height; base height by default |
| `output_filename` | string | No | Custom output filename |

Omit both dimensions to scale a full-frame layer to the base canvas. This keeps
the layer aligned across base videos with different resolutions and the same
aspect ratio. Supplying only one dimension preserves the layer's aspect ratio.
Supplying both uses exact pixel dimensions. A shorter layer ends while the base
continues; a longer layer is trimmed to the base duration.

**Success Response (200):**
```json
{
  "success": true,
  "message": "Video layer added successfully. File will be auto-deleted in 120 seconds.",
  "output_path": "/path/to/output/layered.mp4",
  "delete_after_seconds": 120,
  "processing_time_seconds": 2.431,
  "base_duration_seconds": 12.26
}
```

**Error Responses:**
- `400` - Failed to download a file
- `401` - Invalid or missing API key
- `422` - Invalid URL, media, or overlay dimensions
- `500` - Server error

---

### Beat-Synced Alternating Merge

```http
POST /merge-beat-sync
```

Creates a beat-synced output by alternating exactly two source clips across beat intervals.

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `X-API-Key` | Yes | Your API key |
| `Content-Type` | Yes | `application/json` |

**Request Body:**
```json
{
  "video_urls": [
    "https://example.com/clip1.mp4",
    "https://example.com/clip2.mp4"
  ],
  "audio_url": "https://example.com/song.mp3",
  "beat_timestamps": [4.2, 7.2, 10.2, 12.26],
  "video_cut_starts": [0.0, 0.0],
  "output_filename": "beat_sync.mp4"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `video_urls` | array | Yes | Must contain exactly 2 video URLs |
| `audio_url` | string | Yes | URL of the audio file |
| `beat_timestamps` | array<number> | Yes | Strictly increasing timestamps in seconds from song start |
| `video_cut_starts` | array<number> | No | Either 2 values (per source video), or N values (per segment) |
| `output_filename` | string | No | Custom output filename (auto-generated if not provided) |

For beats `[4.2, 7.2, 10.2, 12.26]`, segment durations are:
- Segment 1: `0.0 -> 4.2` (4.2s) uses video 1
- Segment 2: `4.2 -> 7.2` (3.0s) uses video 2
- Segment 3: `7.2 -> 10.2` (3.0s) uses video 1
- Segment 4: `10.2 -> 12.26` (2.06s) uses video 2

**Success Response (200):**
```json
{
  "success": true,
  "message": "Beat-synced video created successfully. File will be auto-deleted in 120 seconds.",
  "output_path": "/path/to/output/beat_sync.mp4",
  "delete_after_seconds": 120,
  "processing_time_seconds": 8.914,
  "segments_created": 4,
  "total_duration_seconds": 12.26
}
```

**Error Responses:**
- `401` - Invalid or missing API key
- `422` - Validation error (bad beats/order/video count/cut list format)
- `400` - Failed to download file
- `500` - Server error

---

### Trim Video

```http
POST /trim
```

Trims a video clip by cutting from the start, from the end, or extracting a specific range.
The trim endpoint re-encodes the output for frame-accurate short clips, so very small cuts such as `1.20` seconds do not drift to keyframe boundaries.

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `X-API-Key` | Yes | Your API key |
| `Content-Type` | Yes | `application/json` |

**Request Body:**
```json
{
  "video_url": "https://example.com/clip.mp4",
  "trim_from": 1.07,
  "trim_to": 10.5,
  "output_filename": "trimmed.mp4"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `video_url` | string | Yes | URL of the video to trim |
| `trim_from` | number | No* | Start point in seconds — everything before this is removed |
| `trim_to` | number | No* | End point in seconds — everything after this is removed |
| `output_filename` | string | No | Custom output filename (auto-generated if not provided) |

\* At least one of `trim_from` or `trim_to` must be provided.

**Trim Modes:**

| Mode | Fields | Behavior |
|------|--------|----------|
| Cut from start | `trim_from` only | Removes the first N seconds, returns the rest |
| Cut from end | `trim_to` only | Keeps the first N seconds, removes the rest |
| Extract range | Both | Extracts the segment between `trim_from` and `trim_to` |

**Examples:**

*Remove the first 1.07 seconds:*
```json
{ "video_url": "https://example.com/clip.mp4", "trim_from": 1.07 }
```

*Keep only the first 10 seconds:*
```json
{ "video_url": "https://example.com/clip.mp4", "trim_to": 10.0 }
```

*Extract from 5s to 15s:*
```json
{ "video_url": "https://example.com/clip.mp4", "trim_from": 5.0, "trim_to": 15.0 }
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "Video trimmed successfully. File will be auto-deleted in 120 seconds.",
  "output_path": "/path/to/output/trimmed.mp4",
  "delete_after_seconds": 120,
  "processing_time_seconds": 1.234,
  "original_duration_seconds": 30.5,
  "trimmed_duration_seconds": 20.0
}
```

**Error Responses:**
- `401` - Invalid or missing API key
- `422` - Validation error (missing both trim fields, trim_from >= trim_to, values exceed duration)
- `400` - Failed to download file
- `500` - Server error

---

### Reverse Video

```http
POST /reverse
```

Reverses the full video timeline. If the source has audio, audio is reversed too.

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `X-API-Key` | Yes | Your API key |
| `Content-Type` | Yes | `application/json` |

**Request Body:**
```json
{
  "video_url": "https://example.com/clip.mp4",
  "output_filename": "reversed.mp4"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `video_url` | string | Yes | URL of the source video |
| `output_filename` | string | No | Custom output filename |

**Success Response (200):**
```json
{
  "success": true,
  "message": "Video reversed successfully. File will be auto-deleted in 120 seconds.",
  "output_path": "/path/to/output/reversed.mp4",
  "delete_after_seconds": 120,
  "processing_time_seconds": 2.219,
  "original_duration_seconds": 12.26,
  "transformed_duration_seconds": 12.26
}
```

**Error Responses:**
- `401` - Invalid or missing API key
- `400` - Failed to download file
- `422` - Validation error (invalid URL format, missing fields)
- `500` - Server error

---

### Speed / Slow Video

```http
POST /speed
```

Changes playback speed using a `speed` factor:
- `> 1.0` speeds up (for example `1.3`)
- `< 1.0` slows down (for example `0.3`)

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `X-API-Key` | Yes | Your API key |
| `Content-Type` | Yes | `application/json` |

**Request Body:**
```json
{
  "video_url": "https://example.com/clip.mp4",
  "speed": 1.3,
  "output_filename": "speed_changed.mp4"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `video_url` | string | Yes | URL of the source video |
| `speed` | number | Yes | Playback factor; must be > 0 |
| `output_filename` | string | No | Custom output filename |

**Success Response (200):**
```json
{
  "success": true,
  "message": "Video speed changed successfully. File will be auto-deleted in 120 seconds.",
  "output_path": "/path/to/output/speed_changed.mp4",
  "delete_after_seconds": 120,
  "processing_time_seconds": 2.108,
  "original_duration_seconds": 12.26,
  "transformed_duration_seconds": 9.431,
  "speed": 1.3
}
```

**Error Responses:**
- `401` - Invalid or missing API key
- `400` - Failed to download file
- `422` - Validation error (`speed <= 0`, invalid payload)
- `500` - Server error

---

### Strip Audio

```http
POST /strip-audio
```

Removes every audio track from a video. The video stream is copied without re-encoding, so quality and frame count are unchanged. A video that already has no audio still returns an output, with `had_audio: false`.

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `X-API-Key` | Yes | Your API key |
| `Content-Type` | Yes | `application/json` |

**Request Body:**
```json
{
  "video_url": "https://example.com/clip.mp4",
  "output_filename": "silent.mp4"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `video_url` | string | Yes | URL of the source video |
| `output_filename` | string | No | Custom output filename |

**Success Response (200):**
```json
{
  "success": true,
  "message": "Audio stripped successfully. File will be auto-deleted in 120 seconds.",
  "output_path": "/path/to/output/silent.mp4",
  "delete_after_seconds": 120,
  "processing_time_seconds": 0.412,
  "duration_seconds": 12.26,
  "had_audio": true
}
```

**Error Responses:**
- `401` - Invalid or missing API key
- `400` - Failed to download file
- `422` - Validation error (invalid URL format, missing fields) or unreadable media
- `500` - Server error

---

### Replace Audio

```http
POST /replace-audio
```

Replaces a video's audio with the first audio track of `audio_source_url`. The source can be an audio file (MP3, WAV, AAC, ...) or a video file, in which case only its audio is used. The video stream is copied without re-encoding; the new audio is encoded as AAC 192k. The output ends at whichever input is shorter.

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `X-API-Key` | Yes | Your API key |
| `Content-Type` | Yes | `application/json` |

**Request Body:**
```json
{
  "video_url": "https://example.com/clip.mp4",
  "audio_source_url": "https://example.com/other-clip.mp4",
  "output_filename": "replaced_audio.mp4"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `video_url` | string | Yes | URL of the video whose picture is kept |
| `audio_source_url` | string | Yes | URL of an audio or video file whose first audio track is used |
| `output_filename` | string | No | Custom output filename |

**Success Response (200):**
```json
{
  "success": true,
  "message": "Audio replaced successfully. File will be auto-deleted in 120 seconds.",
  "output_path": "/path/to/output/replaced_audio.mp4",
  "delete_after_seconds": 120,
  "processing_time_seconds": 0.873,
  "video_duration_seconds": 12.26,
  "audio_duration_seconds": 30.0,
  "output_duration_seconds": 12.26
}
```

**Error Responses:**
- `401` - Invalid or missing API key
- `400` - Failed to download file
- `422` - Validation error (`audio_source_url has no audio track`, invalid payload) or unreadable media
- `500` - Server error

---

### Concatenate Clips

```http
POST /concat
```

Joins clips in order and can lay the soundtrack of another file over the result. Built for one render split into parts: each clip can be cut to a `duration` (seconds kept from its start), so parts that came back padded are trimmed to their source length and the original soundtrack stays in sync. Unlike `/merge`, the output keeps the first clip's own resolution and frame rate instead of a fixed 1080p canvas; other clips are scaled and padded to match. Video is encoded as H.264 (CRF 18); the soundtrack, when given, as AAC 192k.

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `X-API-Key` | Yes | Your API key |
| `Content-Type` | Yes | `application/json` |

**Request Body:**
```json
{
  "clips": [
    { "video_url": "https://example.com/part-1.mp4", "duration": 11.133 },
    { "video_url": "https://example.com/part-2.mp4", "duration": 9.546 }
  ],
  "audio_source_url": "https://example.com/original.mov",
  "output_filename": "joined.mp4"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `clips` | array | Yes | Clips in playback order (at least one) |
| `clips[].video_url` | string | Yes | URL of the clip |
| `clips[].duration` | number | No | Seconds kept from the clip's start; omit to keep it whole |
| `audio_source_url` | string | No | Audio or video file whose first audio track becomes the soundtrack; a file without audio gives a silent output |
| `output_filename` | string | No | Custom output filename |

**Success Response (200):**
```json
{
  "success": true,
  "message": "Clips joined successfully. File will be auto-deleted in 120 seconds.",
  "output_path": "/path/to/output/joined.mp4",
  "delete_after_seconds": 120,
  "processing_time_seconds": 3.42,
  "output_duration_seconds": 20.679,
  "has_audio": true
}
```

**Error Responses:**
- `401` - Invalid or missing API key
- `400` - Failed to download file
- `422` - Validation error (no clips, a duration of 0 or less, invalid payload) or unreadable media
- `500` - Server error

---

### Extract the 5th Frame

```http
POST /extract-fifth-frame
```

Downloads a video or accepts an uploaded file, extracts frame number 5, and streams the PNG back in the same response.

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `X-API-Key` | Yes | Your API key |
| `Content-Type` | Yes | `application/json` |

**Request Body:**
```json
{
  "video_url": "https://example.com/clip.mp4",
  "output_filename": "frame_preview.png"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `video_url` | string | Yes* | URL of the source video |
| `output_filename` | string | No | Preferred download filename; server always returns a `.png` |

Alternative multipart form request for local testing:

```bash
curl -X POST http://localhost:8000/extract-fifth-frame \
  -H "X-API-Key: your-api-key" \
  -F "video_file=@/absolute/path/to/local-video.mp4" \
  -F "output_filename=frame_preview.png" \
  --output frame_preview.png
```

Multipart form fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `video_file` | file | Yes* | Local video file upload |
| `video_url` | string | Yes* | Remote video URL |
| `output_filename` | string | No | Preferred download filename |

\* Provide exactly one of `video_file` or `video_url`.

**Success Response (200):**
- Content-Type: `image/png`
- Body: binary PNG image containing the 5th frame

**Example curl:**
```bash
curl -X POST http://localhost:8000/extract-fifth-frame \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{"video_url":"https://example.com/clip.mp4","output_filename":"frame_preview.png"}' \
  --output frame_preview.png
```

**Error Responses:**
- `401` - Invalid or missing API key
- `400` - Failed to download file
- `422` - Validation error (invalid URL, missing source, both sources provided, fewer than 5 frames)
- `500` - Server error

---

### Download Output File

```http
GET /download/{filename}
```

**Example:**
```
GET /download/my_output.mp4
```

**Response:** Video file download

**Error Response:**
- `404` - File not found

---

## Code Examples

### Python

```python
import requests

API_URL = "http://localhost:8000"
API_KEY = "your-api-key"

headers = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json"
}

payload = {
    "video_urls": [
        "https://example.com/video1.mp4",
        "https://example.com/video2.mp4"
    ],
    "audio_url": "https://example.com/audio.mp3",
    "output_filename": "merged_video.mp4"
}

response = requests.post(f"{API_URL}/merge", json=payload, headers=headers)

if response.status_code == 200:
    data = response.json()
    print(f"Success! Output: {data['output_path']}")
    
    # Download the file
    download_url = f"{API_URL}/download/merged_video.mp4"
    video_response = requests.get(download_url)
    
    with open("downloaded_video.mp4", "wb") as f:
        f.write(video_response.content)
else:
    print(f"Error: {response.json()}")
```

### JavaScript (Node.js)

```javascript
const axios = require('axios');
const fs = require('fs');

const API_URL = 'http://localhost:8000';
const API_KEY = 'your-api-key';

async function mergeVideos() {
  const payload = {
    video_urls: [
      'https://example.com/video1.mp4',
      'https://example.com/video2.mp4'
    ],
    audio_url: 'https://example.com/audio.mp3',
    output_filename: 'merged_video.mp4'
  };

  const response = await axios.post(`${API_URL}/merge`, payload, {
    headers: {
      'X-API-Key': API_KEY,
      'Content-Type': 'application/json'
    }
  });

  console.log('Success:', response.data);

  // Download the file
  const videoResponse = await axios.get(`${API_URL}/download/merged_video.mp4`, {
    responseType: 'stream'
  });

  videoResponse.data.pipe(fs.createWriteStream('downloaded_video.mp4'));
}

mergeVideos().catch(console.error);
```

### cURL

```bash
# Merge videos
curl -X POST "http://localhost:8000/merge" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "video_urls": ["https://example.com/video1.mp4"],
    "audio_url": "https://example.com/audio.mp3",
    "output_filename": "merged.mp4"
  }'

# Trim — remove first 1.07 seconds
curl -X POST "http://localhost:8000/trim" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "video_url": "https://example.com/clip.mp4",
    "trim_from": 1.07
  }'

# Replace audio with the soundtrack of another clip
curl -X POST "http://localhost:8000/replace-audio" \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "video_url": "https://example.com/clip.mp4",
    "audio_source_url": "https://example.com/other-clip.mp4"
  }'

# Download result
curl -O "http://localhost:8000/download/merged.mp4"
```

---

## Notes

- **Audio handling:** Audio is automatically trimmed if longer than video, or padded with silence if shorter.
- **Trim re-encodes:** The `/trim` endpoint re-encodes via `libx264` for frame-accurate cuts. This is slower than stream copy, but the output duration matches the requested trim much more closely.
- **No video re-encode for audio edits:** `/strip-audio` and `/replace-audio` copy the video stream as-is, so they are fast and lossless for the picture.
- **Auto-deletion:** Output files are automatically deleted after 120 seconds. Download immediately after processing.
- **Concurrency:** Server supports up to 20 simultaneous requests.
- **Supported formats:** MP4, MOV, AVI for video; MP3, WAV, AAC for audio.

## Requirements

The server requires `ffmpeg` installed on the system.
