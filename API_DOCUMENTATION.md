# Video Audio Merger API Documentation

A FastAPI server that merges multiple videos and adds an audio track.

## Base URL

```
http://localhost:8000
```

## Authentication

All `/merge` requests require an API key in the header:

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
  "message": "Video and audio merged successfully. File will be auto-deleted in 30 seconds.",
  "output_path": "/path/to/output/my_output.mp4",
  "delete_after_seconds": 30
}
```

**Error Responses:**
- `401` - Invalid or missing API key
- `400` - Failed to download file
- `422` - Validation error (invalid URL format, missing fields)
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
- **Auto-deletion:** Output files are automatically deleted after 30 seconds. Download immediately after merge.
- **Concurrency:** Server supports up to 20 simultaneous merge requests.
- **Supported formats:** MP4, MOV, AVI for video; MP3, WAV, AAC for audio.

## Requirements

The server requires `ffmpeg` installed on the system.
