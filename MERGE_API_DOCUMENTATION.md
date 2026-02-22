# Video Audio Merger API Documentation

A FastAPI server that merges multiple videos and adds an audio track.

## Base URL

```
http://localhost:8000
```

## Authentication

All `POST /merge`, `POST /merge-beat-sync`, and `POST /trim` requests require an API key in the header:

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
| `audio_url` | string | Yes | URL of the audio file |
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

# Download result
curl -O "http://localhost:8000/download/merged.mp4"
```

---

## Notes

- **Audio handling:** Audio is automatically trimmed if longer than video, or padded with silence if shorter.
- **Trim uses stream copy:** The `/trim` endpoint uses `-c copy` for near-instant trimming without re-encoding. Cuts may be slightly off from the exact timestamp due to keyframe alignment.
- **Auto-deletion:** Output files are automatically deleted after 120 seconds. Download immediately after processing.
- **Concurrency:** Server supports up to 20 simultaneous requests.
- **Supported formats:** MP4, MOV, AVI for video; MP3, WAV, AAC for audio.

## Requirements

The server requires `ffmpeg` installed on the system.
