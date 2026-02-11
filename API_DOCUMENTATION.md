# Video Audio Merger API Documentation

A FastAPI server that merges multiple videos and adds an audio track.

## Base URL

```
http://localhost:8000
```

## Authentication

All `POST /merge` and `POST /merge-beat-sync` requests require an API key in the header:

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

# Download result
curl -O "http://localhost:8000/download/merged.mp4"
```

---

## Notes

- **Audio handling:** Audio is automatically trimmed if longer than video, or padded with silence if shorter.
- **Auto-deletion:** Output files are automatically deleted after 120 seconds. Download immediately after merge.
- **Concurrency:** Server supports up to 20 simultaneous merge requests.
- **Supported formats:** MP4, MOV, AVI for video; MP3, WAV, AAC for audio.

## Requirements

The server requires `ffmpeg` installed on the system.
