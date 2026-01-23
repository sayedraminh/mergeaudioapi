# Video Audio Merger API

A FastAPI server that merges multiple videos and adds an audio track with automatic cleanup.

## Features

- Merge multiple video URLs into a single video
- Add audio track to merged video
- Automatic audio trimming/padding to match video duration
- API key authentication
- Auto-delete output files after 30 seconds
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

### Download Output
```
GET /download/{filename}
```

## Documentation

See [API_DOCUMENTATION.md](API_DOCUMENTATION.md) for full API documentation with code examples.

## License

MIT
