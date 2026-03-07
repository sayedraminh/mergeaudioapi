# Client-Side Guide: Extract the 5th Frame

This guide shows how to call the new frame extraction endpoint with either a remote URL or a local file upload, and how to handle the PNG response on the client.

## Endpoint

- Method: `POST`
- URL: `/extract-fifth-frame`
- Header: `X-API-Key: <your-api-key>` if the FastAPI server has `API_KEY` configured
- Content-Type: `application/json` or `multipart/form-data`
- Success response: `image/png`

## Request body

JSON request:

```json
{
  "video_url": "https://example.com/video.mp4",
  "output_filename": "frame_preview.png"
}
```

Multipart request:

- `video_file`: local video file
- `output_filename`: optional preferred PNG filename

## Field rules

- `video_url`
  - Required for JSON requests.
  - Must be a public `http` or `https` URL that the API server can download.
- `video_file`
  - Required for multipart upload requests.
  - Use this when the user is picking a file from their computer.
- `output_filename`
  - Optional.
  - The server sanitizes the name and always returns a `.png` file.
  - If omitted, the server generates a filename automatically.
- Provide exactly one source:
  - `video_url`
  - or `video_file`

## What comes back

Unlike the merge and transform endpoints, this route does not return JSON on success.

On success:
- HTTP status: `200`
- Content-Type: `image/png`
- Body: raw PNG bytes for frame 5
- Content-Disposition: includes the filename to save

On failure:
- The server returns JSON with a `detail` field.

## Browser example

```js
async function extractFifthFrame(videoUrl) {
  const response = await fetch("http://localhost:8090/extract-fifth-frame", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY
    },
    body: JSON.stringify({
      video_url: videoUrl,
      output_filename: "frame_preview.png"
    })
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Frame extraction failed");
  }

  const blob = await response.blob();
  const imageUrl = URL.createObjectURL(blob);

  return {
    imageUrl,
    contentType: response.headers.get("content-type"),
    fileName: response.headers.get("content-disposition")
  };
}
```

Usage:

```js
const { imageUrl } = await extractFifthFrame(videoUrl);
document.querySelector("img").src = imageUrl;
```

## Download example in the browser

```js
const response = await fetch("http://localhost:8090/extract-fifth-frame", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-API-Key": API_KEY
  },
  body: JSON.stringify({ video_url: videoUrl })
});

if (!response.ok) {
  const error = await response.json();
  throw new Error(error.detail || "Frame extraction failed");
}

const blob = await response.blob();
const href = URL.createObjectURL(blob);
const anchor = document.createElement("a");
anchor.href = href;
anchor.download = "frame_5.png";
anchor.click();
URL.revokeObjectURL(href);
```

## Local upload example in the browser

```js
async function extractFromLocalFile(file) {
  const formData = new FormData();
  formData.append("video_file", file);
  formData.append("output_filename", "frame_preview.png");

  const response = await fetch("http://localhost:8090/extract-fifth-frame", {
    method: "POST",
    headers: {
      "X-API-Key": API_KEY
    },
    body: formData
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail || "Frame extraction failed");
  }

  return response.blob();
}
```

## Next.js proxy route included in this repo

If you are using the sample Next client in this repository, you can call:

- `POST /api/extract-fifth-frame`

That route proxies either JSON or multipart uploads to the FastAPI server and streams the PNG back unchanged.

## Error handling checklist

- Show API errors from `detail`.
- Treat `422` as a bad input case.
- Treat `400` as an upstream download problem.
- Expect binary data only when `response.ok === true`.

## Example error payload

```json
{
  "detail": "Video must contain at least 5 frames"
}
```
