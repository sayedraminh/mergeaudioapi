# Client-Side Implementation Guide: Video Overlay

Use `POST /overlay` to composite a visual video layer over a user's original
video. The endpoint accepts remote URLs and returns a temporary output path,
matching the existing merge API flow.

## Request

```http
POST /overlay
Content-Type: application/json
X-API-Key: your-api-key
```

```json
{
  "base_video_url": "https://example.com/original.mp4",
  "overlay_video_url": "https://example.com/layer.webm",
  "x": 0,
  "y": 0,
  "overlay_width": 540,
  "overlay_height": 960,
  "output_filename": "layered-video.mp4"
}
```

Only `base_video_url` and `overlay_video_url` are required.

| Field | Type | Default | Description |
|---|---:|---:|---|
| `base_video_url` | URL | required | The user's original video. |
| `overlay_video_url` | URL | required | The visual layer. Its audio is ignored. |
| `x` | integer | `0` | Horizontal layer position in pixels. |
| `y` | integer | `0` | Vertical layer position in pixels. |
| `overlay_width` | positive integer | source width | Optional rendered layer width. |
| `overlay_height` | positive integer | source height | Optional rendered layer height. |
| `output_filename` | string | generated | Output filename; `.mp4` is added when omitted. |

If only one layer dimension is provided, the other is calculated automatically
to preserve the layer's aspect ratio. Negative `x` or `y` values are allowed and
crop that part of the layer beyond the base frame.

The base video determines the final canvas, timeline, and audio. Alpha channels
in formats such as WebM or MOV are composited as transparency. If the layer is
shorter, the original base remains visible for the rest of the video. If it is
longer, it is cut at the end of the base.

## Success response

```json
{
  "success": true,
  "message": "Video layer added successfully. File will be auto-deleted in 120 seconds.",
  "output_path": "/absolute/path/to/output/layered-video.mp4",
  "delete_after_seconds": 120,
  "processing_time_seconds": 2.431,
  "base_duration_seconds": 12.26
}
```

Read the filename from `output_path`, then immediately download it from
`GET /download/{filename}` before `delete_after_seconds` elapses.

## Browser example

```js
const response = await fetch(`${API_BASE_URL}/overlay`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-API-Key": API_KEY
  },
  body: JSON.stringify({
    base_video_url: originalVideoUrl,
    overlay_video_url: layerVideoUrl,
    x: 0,
    y: 0,
    output_filename: "layered-video.mp4"
  })
});

const result = await response.json();
if (!response.ok) {
  throw new Error(result.detail || "Video overlay failed");
}

const filename = result.output_path.split(/[\\/]/).pop();
const downloadUrl = `${API_BASE_URL}/download/${encodeURIComponent(filename)}`;
```
