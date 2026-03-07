"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

function extractDownloadFilename(contentDisposition, fallbackName) {
  if (!contentDisposition) {
    return fallbackName;
  }

  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    return decodeURIComponent(utf8Match[1]);
  }

  const basicMatch = contentDisposition.match(/filename="?([^"]+)"?/i);
  if (basicMatch?.[1]) {
    return basicMatch[1];
  }

  return fallbackName;
}

export default function ExtractFifthFramePage() {
  const [sourceMode, setSourceMode] = useState("url");
  const [videoUrl, setVideoUrl] = useState("");
  const [videoFile, setVideoFile] = useState(null);
  const [outputFilename, setOutputFilename] = useState("frame_preview.png");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [previewUrl, setPreviewUrl] = useState("");
  const [downloadName, setDownloadName] = useState("frame_preview.png");
  const [fileSizeKb, setFileSizeKb] = useState(null);

  useEffect(() => {
    return () => {
      if (previewUrl) {
        URL.revokeObjectURL(previewUrl);
      }
    };
  }, [previewUrl]);

  async function handleSubmit(event) {
    event.preventDefault();
    setIsSubmitting(true);
    setErrorMessage("");
    setFileSizeKb(null);

    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      setPreviewUrl("");
    }

    try {
      let response;

      if (sourceMode === "upload") {
        if (!videoFile) {
          throw new Error("Please choose a video file from your computer.");
        }

        const formData = new FormData();
        formData.append("video_file", videoFile);

        if (outputFilename.trim()) {
          formData.append("output_filename", outputFilename.trim());
        }

        response = await fetch("/api/extract-fifth-frame", {
          method: "POST",
          body: formData
        });
      } else {
        if (!videoUrl.trim()) {
          throw new Error("Please enter a video URL.");
        }

        response = await fetch("/api/extract-fifth-frame", {
          method: "POST",
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            video_url: videoUrl.trim(),
            output_filename: outputFilename.trim() || undefined
          })
        });
      }

      if (!response.ok) {
        const data = await response.json();
        const detail = data?.detail || "Unknown error";
        throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
      }

      const blob = await response.blob();
      const nextPreviewUrl = URL.createObjectURL(blob);
      const nextDownloadName = extractDownloadFilename(
        response.headers.get("content-disposition"),
        outputFilename.trim() || "frame_5.png"
      );

      setPreviewUrl(nextPreviewUrl);
      setDownloadName(nextDownloadName);
      setFileSizeKb((blob.size / 1024).toFixed(1));
    } catch (error) {
      setErrorMessage(error.message || "Request failed");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="container">
      <section className="card">
        <nav className="nav-links">
          <Link href="/">Beat Sync Tester</Link>
          <Link href="/merge">Merge Tester</Link>
          <Link href="/trim">Trim Tester</Link>
          <Link href="/reverse">Reverse Tester</Link>
          <Link href="/speed">Speed Tester</Link>
          <span className="nav-active">Frame Tester</span>
        </nav>

        <h1>5th Frame Extractor</h1>
        <p>
          Grab frame number 5 from either a source video URL or a file on your computer.
          This tester calls the Next proxy for the FastAPI
          <code> /extract-fifth-frame </code>
          endpoint and shows the PNG inline.
        </p>

        <form onSubmit={handleSubmit} className="form">
          <label>
            Source Type
            <select
              value={sourceMode}
              onChange={(event) => setSourceMode(event.target.value)}
            >
              <option value="url">Video URL</option>
              <option value="upload">Upload from computer</option>
            </select>
          </label>

          {sourceMode === "url" ? (
            <label>
              Video URL
              <input
                type="url"
                required
                value={videoUrl}
                onChange={(event) => setVideoUrl(event.target.value)}
                placeholder="https://.../video.mp4"
              />
            </label>
          ) : (
            <label>
              Video File
              <input
                type="file"
                accept="video/*,.mp4,.mov,.m4v,.webm,.avi,.mkv"
                onChange={(event) => setVideoFile(event.target.files?.[0] || null)}
              />
              <small>
                Pick a local video file. The tester uploads it to the API and returns the
                extracted PNG.
              </small>
            </label>
          )}

          <label>
            Output Filename (optional)
            <input
              type="text"
              value={outputFilename}
              onChange={(event) => setOutputFilename(event.target.value)}
              placeholder="frame_preview.png"
            />
            <small>The API always returns a PNG, even if you omit the extension.</small>
          </label>

          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Extracting..." : `Extract 5th Frame${sourceMode === "upload" ? " from Upload" : ""}`}
          </button>
        </form>

        {errorMessage ? <p className="error">Error: {errorMessage}</p> : null}

        {previewUrl ? (
          <div className="result">
            <p>Frame extracted successfully.</p>
            <p>Filename: {downloadName}</p>
            <p>Size: {fileSizeKb} KB</p>
            <img
              src={previewUrl}
              alt="Extracted fifth frame preview"
              className="frame-preview"
            />
            <a href={previewUrl} download={downloadName}>
              Download PNG frame
            </a>
          </div>
        ) : null}
      </section>
    </main>
  );
}
