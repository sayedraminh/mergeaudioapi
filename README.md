# Video Audio Merger API

A FastAPI server that merges multiple videos and adds an audio track with automatic cleanup.

## Features

- Merge multiple video URLs into a single video
- Add audio track to merged video
- Beat-synced alternating merge for exactly 2 videos (`/merge-beat-sync`)
- Trim videos (`/trim`)
- Reverse videos (`/reverse`)
- Speed up or slow down videos (`/speed`)
- Extract the 5th frame of a video as a PNG (`/extract-fifth-frame`)
- Automatic audio trimming/padding to match video duration
- API key authentication
- Auto-delete output files after 120 seconds
- Supports 20 concurrent requests

## Requirements

- Python 3.8+
- FFmpeg installed on system

## Installation

```bash
# Clone the repository
git clone https://github.com/sayedraminh/mergeaudioapi.git
cd mergeaudioapi

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project root:

```
API_KEY=your-secret-api-key
```

## Usage

Start the server:

```bash
uvicorn main:app --reload
```

Server runs at `http://localhost:8000`

## API Endpoints

### Health Check
```
GET /health
```

### Merge Videos with Audio
```
POST /merge
Headers: X-API-Key: your-api-key
Body: {
  "video_urls": ["https://example.com/video1.mp4"],
  "audio_url": "https://example.com/audio.mp3",
  "output_filename": "output.mp4"
}
```

### Beat-Synced Merge (Alternating 2 Clips)
```
POST /merge-beat-sync
Headers: X-API-Key: your-api-key
Body: {
  "video_urls": ["https://example.com/clip1.mp4", "https://example.com/clip2.mp4"],
  "audio_url": "https://example.com/song.mp3",
  "beat_timestamps": [4.2, 7.2, 10.2, 12.26],
  "video_cut_starts": [0.0, 0.0],
  "output_filename": "beat_sync.mp4"
}
```

`video_cut_starts` supports:
- `2` values: one start offset for video 1 and video 2 (reused every time that source clip is selected)
- `N` values: one start offset per segment (`N` = number of beat timestamps)

With beats `[4.2, 7.2, 10.2, 12.26]`, segment durations become `[4.2, 3.0, 3.0, 2.06]` and source clips alternate as `1,2,1,2`.

### Trim Video
```
POST /trim
Headers: X-API-Key: your-api-key
Body: {
  "video_url": "https://example.com/video.mp4",
  "trim_from": 1.0,
  "trim_to": 8.0,
  "output_filename": "trimmed.mp4"
}
```

### Reverse Video
```
POST /reverse
Headers: X-API-Key: your-api-key
Body: {
  "video_url": "https://example.com/video.mp4",
  "output_filename": "reversed.mp4"
}
```

### Speed / Slow Video
```
POST /speed
Headers: X-API-Key: your-api-key
Body: {
  "video_url": "https://example.com/video.mp4",
  "speed": 1.3,
  "output_filename": "faster.mp4"
}
```

### Extract the 5th Frame
```
POST /extract-fifth-frame
Headers: X-API-Key: your-api-key
Body: {
  "video_url": "https://example.com/video.mp4",
  "output_filename": "frame_preview.png"
}
```

Returns the 5th frame immediately as an `image/png` response. There is no follow-up `/download` step for this endpoint.
The endpoint now supports either:
- a remote `video_url` in JSON
- or a multipart `video_file` upload for quick local testing

### Download Output
```
GET /download/{filename}
```

## Documentation

See [MERGE_API_DOCUMENTATION.md](MERGE_API_DOCUMENTATION.md) for full API documentation with code examples.

Client integration handoff:
- [CLIENT_SIDE_IMPLEMENTATION.md](CLIENT_SIDE_IMPLEMENTATION.md)
- [CLIENT_SIDE_FRAME_EXTRACTION.md](CLIENT_SIDE_FRAME_EXTRACTION.md)
- [next-test-client/README.md](next-test-client/README.md) (manual tester app)

## License

MIT
