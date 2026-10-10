# Video Audio Merger API

A FastAPI server that merges multiple videos and adds an audio track with automatic cleanup.

## Features

- Merge multiple video URLs into a single video
- Add audio track to merged video
- Composite a video layer over a base video (`/overlay`)
- Beat-synced alternating merge for exactly 2 videos (`/merge-beat-sync`)
- Extract/cache exact source audio intervals (`/extract-audio`)
- Trim videos (`/trim`)
- Prepare silent grayscale depth guides with source timing (`/prepare-depth`)
- Build masked depth guides for character swaps (`/normalize-video`, `/pitch-audio`, `/composite-masks`)
- Reverse videos (`/reverse`)
- Speed up or slow down videos (`/speed`)
- Extract the 5th frame of a video as a PNG (`/extract-fifth-frame`)
- Automatic audio trimming/padding to match video duration
- API key authentication
- Auto-delete output files after 120 seconds
- Limits media processing to 10 concurrent jobs per server process

## Requirements

The production target is:

- Ubuntu Server 26.04 LTS
- Python 3.14
- FFmpeg 8.x, with both `ffmpeg` and `ffprobe` on `PATH`
- Rubber Band for `/pitch-audio`: either FFmpeg's `rubberband` filter (Ubuntu's
  `ffmpeg` package includes it) or the `rubberband` CLI from `rubberband-cli`
- Writable `temp/` and `output/` directories with enough space for source and rendered media

`requirements.txt` contains the pinned production dependency set. Test tools are
kept in `requirements-dev.txt`.

## Ubuntu installation

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg rubberband-cli

git clone https://github.com/sayedraminh/mergeaudioapi.git
cd mergeaudioapi

python3 --version
ffmpeg -version
ffprobe -version

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

`python3 --version` should report Python 3.14.x. Ubuntu 26.04's `ffmpeg`
package provides both FFmpeg commands used by this API.

## Configuration

Create a `.env` file in the project root:

```
API_KEY=your-secret-api-key
```

Set a non-empty `API_KEY` in production. The API runs without authentication
when this variable is missing.

## Railway deployment

This project includes Railway build config so Railway installs the system FFmpeg package. That package provides both `ffmpeg` and `ffprobe`, which are required by the video endpoints.

- `railpack.json` is used by Railway's default Railpack builder.
- `nixpacks.toml` is kept for services configured to use the legacy Nixpacks builder.

Set `API_KEY` in Railway variables, then redeploy the service. Railway provides the `PORT` environment variable used by the start command.

## Run the server

Start one production process:

```bash
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000
```

Check it from the server:

```bash
curl http://127.0.0.1:8000/health
```

The response should be `{"status":"healthy"}`. Use a service manager such as
systemd to restart the process and start it after reboot. Terminate HTTPS at a
reverse proxy or load balancer. Use `uvicorn main:app --reload` only for local
development.

## Tests

```bash
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q test.py
```

Some merge tests download remote fixture files and need outbound network access.

## API endpoints

### Health check
```
GET /health
```

### Merge videos with optional audio
```
POST /merge
Headers: X-API-Key: your-api-key
Body: {
  "video_urls": ["https://example.com/video1.mp4"],
  "audio_url": "https://example.com/audio.mp3", // optional
  "output_filename": "output.mp4"
}
```
Omit `audio_url` to concatenate videos while preserving each clip's source audio.

### Add a video layer
```
POST /overlay
Headers: X-API-Key: your-api-key
Body: {
  "base_video_url": "https://example.com/original.mp4",
  "overlay_video_url": "https://example.com/layer.webm",
  "x": 0,
  "y": 0,
  "output_filename": "layered.mp4"
}
```

The base video controls the output dimensions, duration, and audio. The layer's
audio is ignored, and transparent layer video formats remain transparent. Position
and size fields are optional. By default, the server scales the full layer canvas
to the base dimensions and places it at the top-left. This keeps a full-frame 9:16
layer aligned across 720p, 1080p, 2K, and 4K base videos. If the layer is shorter
than the base, the base continues normally.

### Beat-synced merge for two alternating clips
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

### Trim video
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

### Reverse video
```
POST /reverse
Headers: X-API-Key: your-api-key
Body: {
  "video_url": "https://example.com/video.mp4",
  "output_filename": "reversed.mp4"
}
```

### Speed or slow video
```
POST /speed
Headers: X-API-Key: your-api-key
Body: {
  "video_url": "https://example.com/video.mp4",
  "speed": 1.3,
  "output_filename": "faster.mp4"
}
```

### Extract the 5th frame
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

### Download output
```
GET /download/{filename}
```

## Documentation

See [MERGE_API_DOCUMENTATION.md](MERGE_API_DOCUMENTATION.md) for full API documentation with code examples.

Client integration handoff:
- [CLIENT_SIDE_IMPLEMENTATION.md](CLIENT_SIDE_IMPLEMENTATION.md)
- [CLIENT_SIDE_VIDEO_OVERLAY.md](CLIENT_SIDE_VIDEO_OVERLAY.md)
- [CLIENT_SIDE_FRAME_EXTRACTION.md](CLIENT_SIDE_FRAME_EXTRACTION.md)
- [next-test-client/README.md](next-test-client/README.md) (manual tester app)

## License

MIT


## Prepare a depth guide

`POST /prepare-depth` accepts an authenticated JSON request:

```json
{
  "video_url": "https://example.com/depth.mp4",
  "source_duration_seconds": 22.782708
}
```

The duration must be finite and positive. FFmpeg retimes the input to the source
clock and removes color and audio in one H.264 encode, at 30 fps and the input
video dimensions. The response includes `grayscale: true`,
`original_duration_seconds`, `duration_seconds`, and `output_path`. Duration is
checked within 0.05 seconds of the target; invalid media returns 422. Conversion
has a 120-second processing timeout and uses the existing concurrency limit.

Download `/download/<output filename>` and persist the bytes in durable storage
before the normal 120-second output expiry. Preparation does not run an AI model.
Output filenames are generated by the server. Deploy this endpoint before callers
start sending preparation requests.

### Extract a source audio reference

`POST /extract-audio` with `X-API-Key` and JSON:

```json
{"video_url":"https://example.com/source.mp4","start_seconds":0,"end_seconds":5}
```

Returns `had_audio`, `duration_seconds`, and an `output_path` for a mono 48 kHz
PCM WAV when audio exists. Download it immediately via `/download/{filename}`
and persist it; outputs expire after 120 seconds. Sources may be videos or
previously extracted audio. Intervals are at most 30 seconds, use source
seconds without speed changes, and pad short audio tracks to the requested
video interval. A silent source returns `had_audio: false` with no output.

## Masked depth guide

Three steps prepare a character-swap guide video: the swap model sees depth
silhouettes where the people were, the real background everywhere else, and
pitch-shifted vocals instead of the original soundtrack. The caller runs the
AI models (depth, SAM 3 masks, vocal separation) between these calls. Every
output expires after 120 seconds, so download each one via
`/download/{filename}` and persist it.

1. `POST /normalize-video` `{"video_url": "...", "start_seconds": 0, "end_seconds": 22.4, "fps": 24, "max_dimension": 1280}`
   returns an H.264 + AAC clip at a constant frame rate with exactly
   `round(duration * fps)` frames (`frames`, `width`, `height`, `has_audio`).
   The video track sets the length: longer audio is cut, shorter audio padded.
   Send this exact clip to depth, SAM and vocal separation so their frames line up.
2. `POST /pitch-audio` `{"audio_url": "...", "semitones": 3}` returns a WAV of the
   same length, pitch-shifted with Rubber Band (`engine` says whether FFmpeg's
   filter or the CLI ran).
3. `POST /composite-masks` with
   `{"video_url": "<normalized clip>", "depth_url": "...", "mask_zips": [{"url": "...", "start_frame": 0}], "audio_url": "<pitched vocals>", "spread_pixels": 0}`
   puts depth pixels inside the SAM masks over the normalized clip. Zips hold
   `mask_NNNNN.png` files (SAM 3 `mask_only` + `return_zip`); `start_frame`
   offsets a zip made from a later section. Frames with no mask file keep the
   original. `spread_pixels` grows each mask by about that many pixels, which
   fills small holes and blurs the original body outline. The depth video is
   resampled to the clip's size and rate. `audio_url` is optional; without it
   the output is silent. Returns `frames` and `masked_frames`; a zip set with no
   masks at all returns 422.
